"""FraiseQL integration for LlamaIndex.

This integration allows LlamaIndex applications to use FraiseQL/PostgreSQL
as a vector store and data source, combining relational data with semantic search.

Example:
    from fraiseql.integrations.llamaindex import FraiseQLVectorStore, FraiseQLReader
    from llama_index.core import VectorStoreIndex

    # Initialize
    vector_store = FraiseQLVectorStore(
        db_pool=db_pool,
        table_name="documents"
    )

    # Create index
    index = VectorStoreIndex.from_vector_store(vector_store)

    # Query
    query_engine = index.as_query_engine()
    response = query_engine.query("What is machine learning?")
"""

import asyncio
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from psycopg.types.json import Json

if TYPE_CHECKING:
    from llama_index.core.schema import BaseNode  # type: ignore[import-untyped]


def _parse_vector(vec: Any) -> Optional[List[float]]:
    """Parse a vector from PostgreSQL format to list of floats.

    Args:
        vec: Vector from PostgreSQL (could be string, list, or None)

    Returns:
        List of floats or None
    """
    if vec is None:
        return None
    if isinstance(vec, list):
        return vec
    if isinstance(vec, str):
        # Parse string format: "[0.1,0.2,0.3]"
        vec = vec.strip()
        if vec.startswith("[") and vec.endswith("]"):
            vec = vec[1:-1]
        return [float(x) for x in vec.split(",")]
    return None


# Optional imports for LlamaIndex
try:
    from llama_index.core.readers.base import BaseReader  # type: ignore[import-untyped]
    from llama_index.core.schema import Document as LlamaDocument  # type: ignore[import-untyped]
    from llama_index.core.vector_stores.types import (  # type: ignore[import-untyped]
        BasePydanticVectorStore,
        MetadataFilter,
        MetadataFilters,
        VectorStoreQuery,
        VectorStoreQueryResult,
    )
    from llama_index.core.vector_stores.utils import (  # type: ignore[import-untyped]
        node_to_metadata_dict,
    )

    LLAMAINDEX_AVAILABLE = True
except ImportError:
    LLAMAINDEX_AVAILABLE = False

    # Define dummy classes for type hints when LlamaIndex is not available
    class BaseReader:  # type: ignore[no-redef]
        """Dummy BaseReader class for type hints when LlamaIndex is not available."""

    class LlamaDocument:  # type: ignore[no-redef]
        """Dummy Document class for type hints when LlamaIndex is not available."""

        def __init__(self, text: str, metadata: Optional[Dict[str, Any]] = None):
            self.text = text
            self.metadata = metadata or {}

    class BasePydanticVectorStore:  # type: ignore[no-redef]
        """Dummy BasePydanticVectorStore class for type hints when LlamaIndex is not available."""

    class VectorStoreQuery:  # type: ignore[no-redef]
        """Dummy VectorStoreQuery class for type hints when LlamaIndex is not available."""

        def __init__(self):
            self.query_embedding = None
            self.similarity_top_k = 10
            self.filters = None

    class VectorStoreQueryResult:  # type: ignore[no-redef]
        """Dummy VectorStoreQueryResult class for type hints when LlamaIndex is not available."""

        def __init__(
            self,
            nodes: Optional[List[Any]] = None,
            similarities: Optional[List[float]] = None,
            ids: Optional[List[str]] = None,
        ) -> None:
            self.nodes = nodes or []
            self.similarities = similarities or []
            self.ids = ids or []

    class MetadataFilters:  # type: ignore[no-redef]
        """Dummy MetadataFilters class for type hints when LlamaIndex is not available."""

        def __init__(self):
            self.filters = []

    class MetadataFilter:  # type: ignore[no-redef]
        """Dummy MetadataFilter class for type hints when LlamaIndex is not available."""

        def __init__(self):
            self.key = ""
            self.value = None

    # Dummy functions
    def node_to_metadata_dict(node: Any) -> Dict[str, Any]:  # type: ignore[no-untyped-def]
        """Convert a node to metadata dictionary."""
        return getattr(node, "metadata", {})


import psycopg_pool


class FraiseQLReader(BaseReader if LLAMAINDEX_AVAILABLE else object):  # type: ignore[misc]  # ty: ignore[unsupported-base]
    """FraiseQL reader for LlamaIndex.

    Reads data from FraiseQL tables and converts them to LlamaIndex documents.
    Supports filtering and pagination for large datasets.
    """

    def __init__(
        self,
        db_pool: psycopg_pool.AsyncConnectionPool,
        table_name: str,
        content_column: str = "content",
        metadata_columns: Optional[List[str]] = None,
        id_column: str = "id",
        metadata_column: Optional[str] = "metadata",
    ):
        """Initialize FraiseQL reader.

        Args:
            db_pool: PostgreSQL connection pool
            table_name: Table name to read from
            content_column: Column containing the main text content
            metadata_columns: Additional columns to include in metadata
            id_column: Column containing unique IDs
            metadata_column: JSONB column containing metadata (default: "metadata")
        """
        self.db_pool = db_pool
        self.table_name = table_name
        self.content_column = content_column
        self.metadata_columns = metadata_columns or []
        self.id_column = id_column
        self.metadata_column = metadata_column

    async def aload_data(
        self,
        where_clause: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[LlamaDocument]:
        """Load data from FraiseQL table asynchronously.

        Args:
            where_clause: Optional WHERE conditions as dict
            limit: Maximum number of documents to load
            offset: Number of documents to skip

        Returns:
            List of LlamaIndex documents
        """
        # Build query
        select_columns = [self.id_column, self.content_column]
        if self.metadata_column:
            select_columns.append(self.metadata_column)
        select_columns.extend(self.metadata_columns)

        query = f"""
        SELECT {", ".join(select_columns)}
        FROM {self.table_name}
        """

        params = []
        if where_clause:
            conditions = []
            for key, value in where_clause.items():
                # Support both direct column access and JSONB field access
                if self.metadata_column and key not in [
                    self.id_column,
                    self.content_column,
                    *self.metadata_columns,
                ]:
                    # Assume it's a JSONB field
                    condition = f"{self.metadata_column}->>'{{key}}' = %s"
                    conditions.append(condition.replace("{key}", key))
                else:
                    conditions.append(f"{key} = %s")
                params.append(value)
            if conditions:
                query += f" WHERE {' AND '.join(conditions)}"

        if limit:
            query += " LIMIT %s"
            params.append(limit)

        if offset:
            query += " OFFSET %s"
            params.append(offset)

        # Execute query
        async with self.db_pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(query, params)  # type: ignore[arg-type]
            rows = await cursor.fetchall()

        # Convert to LlamaIndex documents
        documents = []
        for row in rows:
            row_dict = dict(zip(select_columns, row, strict=False))
            content = row_dict[self.content_column]

            # Build metadata from JSONB column if present
            metadata = {}
            if self.metadata_column and self.metadata_column in row_dict:
                jsonb_metadata = row_dict[self.metadata_column]
                if jsonb_metadata:
                    metadata.update(jsonb_metadata)

            # Add metadata from additional columns
            for col in self.metadata_columns:
                if col in row_dict:
                    metadata[col] = row_dict[col]

            # Add ID to metadata
            metadata["id"] = row_dict[self.id_column]

            documents.append(LlamaDocument(text=content, metadata=metadata))  # type: ignore[call-arg]

        return documents

    def load_data(
        self,
        where_clause: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[LlamaDocument]:
        """Load data from FraiseQL table synchronously."""
        return asyncio.run(self.aload_data(where_clause, limit, offset))


class FraiseQLVectorStore(BasePydanticVectorStore if LLAMAINDEX_AVAILABLE else object):  # type: ignore[misc,name-defined]  # ty: ignore[unsupported-base]
    """FraiseQL vector store for LlamaIndex.

    Stores documents in PostgreSQL with pgvector for semantic search,
    integrating with LlamaIndex's vector store interface.
    """

    stores_text: bool = True
    stores_node_embeddings: bool = True

    # Pydantic fields required by BasePydanticVectorStore
    db_pool: Any = None
    table_name: str = ""
    embedding_dimension: int = 384
    embedding_column: str = "embedding"
    content_column: str = "content"
    metadata_column: str = "metadata"
    id_column: str = "id"
    distance_metric: str = "cosine"

    def __init__(
        self,
        db_pool: psycopg_pool.AsyncConnectionPool,
        table_name: str,
        embedding_dimension: int = 1536,  # OpenAI ada-002 default
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
            embedding_dimension: Dimension of embedding vectors
            embedding_column: Column name for embeddings
            content_column: Column name for text content
            metadata_column: Column name for metadata (JSONB)
            id_column: Column name for document IDs
            distance_metric: "cosine", "l2", or "inner_product"
        """
        super().__init__()
        self.db_pool = db_pool
        self.table_name = table_name
        self.embedding_dimension = embedding_dimension
        self.embedding_column = embedding_column
        self.content_column = content_column
        self.metadata_column = metadata_column
        self.id_column = id_column
        self.distance_metric = distance_metric

    @property
    def client(self) -> Any:
        """Return the database client (required by BasePydanticVectorStore)."""
        return self.db_pool

    async def aadd(
        self,
        nodes: List["BaseNode"],  # type: ignore[name-defined]
        **kwargs: Any,
    ) -> List[str]:
        """Add nodes to the vector store asynchronously."""
        ids = []

        for node in nodes:
            # Generate ID if not present
            node_id = getattr(node, "id_", None) or str(uuid.uuid4())
            ids.append(node_id)

            # Prepare data
            embedding = getattr(node, "embedding", None)
            if embedding is None:
                raise ValueError(f"Node {node_id} does not have an embedding")

            content = getattr(node, "text", "") or getattr(node, "content", "")

            # Convert metadata
            metadata = node_to_metadata_dict(node) if LLAMAINDEX_AVAILABLE else {}

            # Insert into database
            async with self.db_pool.connection() as conn:
                insert_query = f"""
                    INSERT INTO {self.table_name}
                    ({self.id_column}, {self.content_column},
                     {self.embedding_column}, {self.metadata_column})
                    VALUES (%s, %s, %s::vector, %s)
                    ON CONFLICT ({self.id_column}) DO UPDATE SET
                        {self.content_column} = EXCLUDED.{self.content_column},
                        {self.embedding_column} = EXCLUDED.{self.embedding_column},
                        {self.metadata_column} = EXCLUDED.{self.metadata_column}
                """
                await conn.execute(
                    insert_query,  # type: ignore[arg-type]
                    (node_id, content, embedding, Json(metadata)),
                )

        return ids

    async def aget(
        self,
        doc_ids: List[str],
        **kwargs: Any,
    ) -> List["BaseNode"]:  # type: ignore[name-defined]
        """Get nodes by IDs asynchronously."""
        if not doc_ids:
            return []

        # Build query
        placeholders = ", ".join(["%s"] * len(doc_ids))
        query = f"""
        SELECT {self.id_column}, {self.content_column},
               {self.embedding_column}, {self.metadata_column}
        FROM {self.table_name}
        WHERE {self.id_column} IN ({placeholders})
        """

        async with self.db_pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(query, doc_ids)  # type: ignore[arg-type]
            rows = await cursor.fetchall()

        # Convert to nodes
        nodes = []
        for row in rows:
            node_id, content, embedding, metadata = row

            # Parse embedding from PostgreSQL format
            embedding_list = _parse_vector(embedding)

            # Create node from data
            if LLAMAINDEX_AVAILABLE:
                from llama_index.core.schema import TextNode  # type: ignore[import-untyped]

                node = TextNode(
                    id_=node_id, text=content, embedding=embedding_list, metadata=metadata or {}
                )
            else:
                # Fallback for when LlamaIndex is not available
                node = type(
                    "MockNode",
                    (),
                    {
                        "id_": node_id,
                        "text": content,
                        "embedding": embedding,
                        "metadata": metadata or {},
                    },
                )()

            nodes.append(node)

        return nodes

    async def adelete(
        self,
        doc_ids: List[str],
        **kwargs: Any,
    ) -> None:
        """Delete nodes by IDs asynchronously."""
        if not doc_ids:
            return

        placeholders = ", ".join(["%s"] * len(doc_ids))
        query = f"DELETE FROM {self.table_name} WHERE {self.id_column} IN ({placeholders})"

        async with self.db_pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(query, doc_ids)  # type: ignore[arg-type]

    async def aquery(
        self,
        query: VectorStoreQuery,
        **kwargs: Any,
    ) -> VectorStoreQueryResult:
        """Query the vector store asynchronously."""
        # Extract query parameters
        query_embedding = query.query_embedding
        similarity_top_k = query.similarity_top_k or 10

        # Build metadata filters
        metadata_filter_sql = ""
        metadata_params = []

        if query.filters and LLAMAINDEX_AVAILABLE:
            conditions = []
            for filter_item in query.filters.filters:
                if isinstance(filter_item, MetadataFilter):
                    conditions.append(f"{self.metadata_column} ->> %s = %s")
                    metadata_params.extend([filter_item.key, filter_item.value])
            if conditions:
                metadata_filter_sql = " AND " + " AND ".join(conditions)

        # Build similarity search query
        distance_op = {"cosine": "<=>", "l2": "<->", "inner_product": "<#>"}.get(
            self.distance_metric, "<=>"
        )

        sql_query = f"""
        SELECT {self.id_column}, {self.content_column},
               {self.embedding_column}, {self.metadata_column}
        FROM {self.table_name}
        WHERE 1=1{metadata_filter_sql}
        ORDER BY {self.embedding_column} {distance_op} %s::vector
        LIMIT %s
        """

        all_params = [*metadata_params, query_embedding, similarity_top_k]

        async with self.db_pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(sql_query, all_params)  # type: ignore[arg-type]
            rows = await cursor.fetchall()

        # Convert results
        nodes = []
        similarities = []
        ids = []

        for row in rows:
            node_id, content, embedding, metadata = row
            ids.append(node_id)

            # Parse embedding from PostgreSQL format
            embedding_list = _parse_vector(embedding)

            # Create node
            if LLAMAINDEX_AVAILABLE:
                from llama_index.core.schema import TextNode  # type: ignore[import-untyped]

                node = TextNode(
                    id_=node_id, text=content, embedding=embedding_list, metadata=metadata or {}
                )
            else:
                node = type(
                    "MockNode",
                    (),
                    {
                        "id_": node_id,
                        "text": content,
                        "embedding": embedding,
                        "metadata": metadata or {},
                    },
                )()

            nodes.append(node)
            similarities.append(0.0)  # Placeholder similarity score

        return VectorStoreQueryResult(  # type: ignore[call-arg]
            nodes=nodes, similarities=similarities, ids=ids
        )

    # Synchronous methods (wrappers around async methods)
    def add(self, nodes: List["BaseNode"], **kwargs: Any) -> List[str]:  # type: ignore[name-defined]
        """Add nodes to the vector store synchronously."""
        return asyncio.run(self.aadd(nodes, **kwargs))

    def get(self, doc_ids: List[str], **kwargs: Any) -> List["BaseNode"]:  # type: ignore[name-defined]
        """Get nodes by IDs synchronously."""
        return asyncio.run(self.aget(doc_ids, **kwargs))

    def delete(self, doc_ids: List[str], **kwargs: Any) -> None:
        """Delete nodes by IDs synchronously."""
        asyncio.run(self.adelete(doc_ids, **kwargs))

    def query(self, query: VectorStoreQuery, **kwargs: Any) -> VectorStoreQueryResult:
        """Query the vector store synchronously."""
        return asyncio.run(self.aquery(query, **kwargs))

    # Required abstract methods from BasePydanticVectorStore
    def delete_nodes(
        self,
        node_ids: List[str],
        delete_from_docstore: bool = False,
        **kwargs: Any,
    ) -> None:
        """Delete nodes from the vector store."""
        self.delete(node_ids, **kwargs)

    async def adelete_nodes(
        self,
        node_ids: List[str],
        delete_from_docstore: bool = False,
        **kwargs: Any,
    ) -> None:
        """Delete nodes from the vector store asynchronously."""
        await self.adelete(node_ids, **kwargs)
