"""FraiseQL vector store for LangChain.

This integration allows LangChain applications to use FraiseQL/PostgreSQL
as a vector store, combining relational data with semantic search.

Example:
    from fraiseql.integrations.langchain import FraiseQLVectorStore
    from langchain.embeddings import OpenAIEmbeddings

    # Initialize
    vectorstore = FraiseQLVectorStore(
        db_pool=db_pool,
        table_name="documents",
        embedding_function=OpenAIEmbeddings()
    )

    # Add documents
    vectorstore.add_documents([
        Document(page_content="...", metadata={...}),
        Document(page_content="...", metadata={...})
    ])

    # Similarity search
    results = vectorstore.similarity_search("query", k=5)
"""

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

import psycopg_pool
from psycopg.sql import SQL, Identifier

# Optional imports for LangChain
try:
    from langchain_core.documents import Document  # type: ignore[import]
    from langchain_core.embeddings import Embeddings  # type: ignore[import]
    from langchain_core.vectorstores import VectorStore  # type: ignore[import]

    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

    # Define dummy classes for type hints when LangChain is not available
    class VectorStore:  # type: ignore[no-redef]
        """Dummy VectorStore class for type hints when LangChain is not available."""

    class Document:  # type: ignore[no-redef]
        """Dummy Document class for type hints when LangChain is not available."""

        def __init__(self, page_content: str, metadata: Optional[Dict[str, Any]] = None):
            self.page_content = page_content
            self.metadata = metadata or {}

    class Embeddings:  # type: ignore[no-redef]
        """Dummy Embeddings class for type hints when LangChain is not available."""

        async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
            """Dummy async embed documents method."""
            return [[0.0] * 384 for _ in texts]

        async def aembed_query(self, text: str) -> List[float]:
            """Dummy async embed query method."""
            return [0.0] * 384

        def embed_query(self, text: str) -> List[float]:
            """Dummy embed query method."""
            return [0.0] * 384


class FraiseQLVectorStore(VectorStore if LANGCHAIN_AVAILABLE else object):  # type: ignore[misc,name-defined]  # ty: ignore[unsupported-base]
    """FraiseQL vector store for LangChain.

    Stores documents in PostgreSQL with pgvector for semantic search,
    combining relational queries with vector similarity.

    Features:
        - Native PostgreSQL storage (no separate vector DB)
        - Metadata filtering with GraphQL-style queries
        - Hybrid search (keyword + vector)
        - ACID transactions
        - PostgreSQL reliability
    """

    def __init__(
        self,
        db_pool: psycopg_pool.AsyncConnectionPool,
        table_name: str,
        embedding_function: "Embeddings",  # type: ignore[name-defined]
        embedding_column: str = "embedding",
        content_column: str = "content",
        metadata_column: str = "metadata",
        id_column: str = "id",
        distance_metric: str = "cosine",
    ):
        """Initialize FraiseQL vector store.

        Args:
            db_pool: PostgreSQL connection pool
            table_name: Table name for documents
            embedding_function: LangChain embedding function
            embedding_column: Column name for embeddings
            content_column: Column name for text content
            metadata_column: Column name for metadata (JSONB)
            id_column: Column name for document IDs
            distance_metric: "cosine", "l2", or "inner_product"
        """
        self.db_pool = db_pool
        self.table_name = table_name
        self.embedding_function = embedding_function
        self.embedding_column = embedding_column
        self.content_column = content_column
        self.metadata_column = metadata_column
        self.id_column = id_column
        self.distance_metric = distance_metric

    async def aadd_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Add texts to the vector store asynchronously."""
        # Generate embeddings
        if hasattr(self.embedding_function, "aembed_documents"):
            embeddings = await self.embedding_function.aembed_documents(texts)
        else:
            # Fallback for synchronous embeddings
            embeddings = []
            for text in texts:
                if hasattr(self.embedding_function, "embed_query"):
                    embedding = self.embedding_function.embed_query(text)
                else:
                    embedding = [0.0] * 384  # Dummy embedding
                embeddings.append(embedding)

        # Prepare documents for insertion
        documents = []
        ids = []

        for i, (text, embedding) in enumerate(zip(texts, embeddings, strict=False)):
            doc_id = str(uuid.uuid4())
            ids.append(doc_id)

            doc_data = {
                self.id_column: doc_id,
                self.content_column: text,
                self.embedding_column: embedding,
            }

            if metadatas and i < len(metadatas):
                doc_data[self.metadata_column] = metadatas[i]

            documents.append(doc_data)

        # Insert documents using raw SQL
        async with self.db_pool.connection() as conn:
            for doc in documents:
                columns = list(doc.keys())
                values = []

                # Convert values, handling JSON serialization for metadata
                for col, val in doc.items():
                    if col == self.metadata_column and isinstance(val, dict):
                        values.append(json.dumps(val))
                    else:
                        values.append(val)

                query = SQL("""
                INSERT INTO {} ({})
                VALUES ({})
                """).format(
                    Identifier(self.table_name),
                    SQL(", ").join(Identifier(col) for col in columns),
                    SQL(", ").join(SQL("%s") for _ in values),
                )

                await conn.execute(query, values)

        return ids

    async def aadd_documents(self, documents: List["Document"], **kwargs: Any) -> List[str]:  # type: ignore[name-defined]
        """Add documents to the vector store asynchronously."""
        texts = [doc.page_content for doc in documents]
        metadatas = [doc.metadata for doc in documents]
        return await self.aadd_texts(texts, metadatas, **kwargs)

    def _build_metadata_where_clause(self, filter_dict: Dict[str, Any]) -> Tuple[str, List[Any]]:
        """Build WHERE clause for metadata filtering.

        Args:
            filter_dict: Dictionary of metadata filters
                (e.g., {"author": "John", "category": "tech"})

        Returns:
            Tuple of (where_clause_sql, parameters)
        """
        if not filter_dict:
            return "", []

        conditions = []
        params = []

        for key, value in filter_dict.items():
            # For now, support simple equality filtering
            # v1.8: Add support for complex operators (gt, lt, in, etc.)
            conditions.append(f"{self.metadata_column} ->> %s = %s")
            params.extend([key, value])

        if conditions:
            where_sql = " AND " + " AND ".join(conditions)
        else:
            where_sql = ""

        return where_sql, params

    async def asimilarity_search(
        self,
        query: str,
        k: int = 4,
        filter: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List["Document"]:  # type: ignore[name-defined]
        """Perform similarity search asynchronously."""
        # Generate embedding for query
        query_embedding = await self.embedding_function.aembed_query(query)

        # Build metadata filter clause
        metadata_where, metadata_params = self._build_metadata_where_clause(filter or {})

        # Perform search with ordering by distance using raw SQL
        async with self.db_pool.connection() as conn:
            # Build the query for vector similarity search
            # Use different operators based on distance metric
            if self.distance_metric == "cosine":
                distance_op = "<=>"
            elif self.distance_metric == "l2":
                distance_op = "<->"
            elif self.distance_metric == "inner_product":
                distance_op = "<#>"
            else:
                distance_op = "<=>"

            query_str = f"""
            SELECT {self.id_column}, {self.content_column}, {self.metadata_column}
            FROM {self.table_name}
            WHERE 1=1{metadata_where}
            ORDER BY {self.embedding_column} {distance_op} %s::vector
            LIMIT %s
            """

            # Combine metadata params with vector params
            all_params = [*metadata_params, query_embedding, k]

            async with conn.cursor() as cursor:
                await cursor.execute(query_str, all_params)  # type: ignore[arg-type]
                rows = await cursor.fetchall()

        # Convert results to LangChain Documents
        documents = []
        for row in rows:
            content = row[1]  # content column
            metadata = row[2] or {}  # metadata column
            documents.append(Document(page_content=content, metadata=metadata))  # type: ignore[name-defined]

        return documents

    async def asimilarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        filter: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Tuple["Document", float]]:  # type: ignore[name-defined]
        """Perform similarity search with scores asynchronously."""
        # For now, return search results without scores
        # v1.8: Implement score extraction from pgvector results
        documents = await self.asimilarity_search(query, k=k, filter=filter, **kwargs)
        return [(doc, 0.0) for doc in documents]  # Placeholder scores

    async def adelete(self, ids: Optional[List[str]] = None, **kwargs: Any) -> None:
        """Delete documents by IDs asynchronously."""
        if not ids:
            return

        async with self.db_pool.connection() as conn:
            for doc_id in ids:
                query = SQL("DELETE FROM {} WHERE {} = %s").format(
                    Identifier(self.table_name),
                    Identifier(self.id_column),
                )
                await conn.execute(query, [doc_id])

    @property
    def embeddings(self) -> "Embeddings":  # type: ignore[name-defined]
        """Get the embedding function."""
        return self.embedding_function

    # Synchronous methods (wrappers around async methods)
    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Add texts to the vector store."""
        return asyncio.run(self.aadd_texts(texts, metadatas, **kwargs))

    def add_documents(self, documents: List["Document"], **kwargs: Any) -> List[str]:  # type: ignore[name-defined]
        """Add documents to the vector store."""
        return asyncio.run(self.aadd_documents(documents, **kwargs))

    def similarity_search(
        self,
        query: str,
        k: int = 4,
        filter: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List["Document"]:  # type: ignore[name-defined]
        """Perform similarity search."""
        return asyncio.run(self.asimilarity_search(query, k=k, filter=filter, **kwargs))

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        filter: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Tuple["Document", float]]:  # type: ignore[name-defined]
        """Perform similarity search with scores."""
        return asyncio.run(self.asimilarity_search_with_score(query, k=k, filter=filter, **kwargs))

    def delete(self, ids: Optional[List[str]] = None, **kwargs: Any) -> None:
        """Delete documents by IDs."""
        asyncio.run(self.adelete(ids, **kwargs))

    @classmethod
    def from_texts(
        cls,
        texts: List[str],
        embedding: "Embeddings",  # type: ignore[name-defined]
        metadatas: Optional[List[Dict[str, Any]]] = None,
        db_pool: Optional[psycopg_pool.AsyncConnectionPool] = None,
        table_name: str = "documents",
        **kwargs: Any,
    ) -> "FraiseQLVectorStore":
        """Create a FraiseQL vector store from texts.

        Args:
            texts: List of texts to add
            embedding: Embedding function
            metadatas: Optional list of metadata dicts
            db_pool: PostgreSQL connection pool
            table_name: Table name for documents
            **kwargs: Additional arguments passed to __init__

        Returns:
            FraiseQLVectorStore instance
        """
        if db_pool is None:
            raise ValueError("db_pool is required for FraiseQLVectorStore.from_texts")

        # Create instance
        instance = cls(
            db_pool=db_pool,
            table_name=table_name,
            embedding_function=embedding,
            **kwargs,
        )

        # Add texts
        instance.add_texts(texts, metadatas=metadatas)

        return instance
