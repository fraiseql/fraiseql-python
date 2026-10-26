"""FraiseQL LlamaIndex Integration Tests

Tests complete LlamaIndex VectorStore functionality including:
- Document storage and retrieval
- Vector similarity search
- Metadata filtering
- Error handling and edge cases
- Performance with real database operations
"""

import uuid
from typing import List
from unittest.mock import Mock

import pytest
import pytest_asyncio
from psycopg.types.json import Json

pytestmark = pytest.mark.integration

# Check if LlamaIndex is available
try:
    from llama_index.core.schema import Document as LlamaDocument  # type: ignore[import-untyped]
    from llama_index.core.schema import TextNode  # type: ignore[import-untyped]

    LLAMAINDEX_AVAILABLE = True
except ImportError:
    LLAMAINDEX_AVAILABLE = False
    LlamaDocument = Mock  # type: ignore
    TextNode = Mock  # type: ignore

from fraiseql.integrations.llamaindex import FraiseQLReader, FraiseQLVectorStore


# Mock embedding function for testing
class MockEmbeddings:
    """Mock embeddings class for testing."""

    def __init__(self, dimension: int = 384):
        self.dimension = dimension

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """Mock async embed documents."""
        return [[0.1] * self.dimension for _ in texts]

    async def aembed_query(self, text: str) -> List[float]:
        """Mock async embed query."""
        return [0.1] * self.dimension

    def embed_query(self, text: str) -> List[float]:
        """Mock sync embed query."""
        return [0.1] * self.dimension


@pytest_asyncio.fixture
async def vectorstore_table(class_db_pool, test_schema, pgvector_available):
    """Create a test table for vectorstore integration tests."""
    if not pgvector_available:
        pytest.skip("pgvector extension not available")

    table_name = f"test_llamaindex_docs_{uuid.uuid4().hex[:8]}"

    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")

        # Create test table with vector support
        await conn.execute(f"""
            CREATE TABLE {table_name} (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                embedding vector(384),
                metadata JSONB
            );
        """)

        # Create vector index for performance
        try:
            await conn.execute(f"""
                CREATE INDEX {table_name}_embedding_idx
                ON {table_name} USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100);
            """)
        except Exception:
            # Index creation might fail in some test environments, continue anyway
            pass

    yield table_name


@pytest.fixture
def mock_embeddings() -> MockEmbeddings:
    """Mock embeddings for testing."""
    return MockEmbeddings(dimension=384)


@pytest_asyncio.fixture
async def vectorstore(
    class_db_pool, vectorstore_table: str, pgvector_available
) -> FraiseQLVectorStore:
    """Create a FraiseQLVectorStore instance for testing."""
    if not pgvector_available:
        pytest.skip("pgvector extension not available")

    return FraiseQLVectorStore(
        db_pool=class_db_pool,
        table_name=vectorstore_table,
        embedding_dimension=384,
    )


@pytest_asyncio.fixture
async def reader(class_db_pool, vectorstore_table: str) -> FraiseQLReader:
    """Create a FraiseQLReader instance for testing."""
    return FraiseQLReader(
        db_pool=class_db_pool,
        table_name=vectorstore_table,
    )


@pytest.mark.skipif(not LLAMAINDEX_AVAILABLE, reason="LlamaIndex not available")
class TestFraiseQLReader:
    """Test FraiseQLReader functionality."""

    @pytest.mark.asyncio
    async def test_load_data_basic(self, reader: FraiseQLReader, class_db_pool, test_schema):
        """Test basic data loading from FraiseQL table."""
        # Insert test data
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute(
                f"INSERT INTO {reader.table_name} (id, content, metadata) VALUES (%s, %s, %s)",
                ("test1", "This is test content", Json({"author": "test", "category": "test"})),
            )

        # Load data
        documents = await reader.aload_data()

        assert len(documents) == 1
        assert documents[0].text == "This is test content"
        assert documents[0].metadata["author"] == "test"
        assert documents[0].metadata["category"] == "test"
        assert documents[0].metadata["id"] == "test1"

    @pytest.mark.asyncio
    async def test_load_data_with_filters(self, reader: FraiseQLReader, class_db_pool, test_schema):
        """Test data loading with WHERE filters."""
        # Insert test data
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute(
                f"INSERT INTO {reader.table_name} (id, content, metadata) VALUES (%s, %s, %s)",
                ("test1", "Content 1", Json({"category": "A"})),
            )
            await conn.execute(
                f"INSERT INTO {reader.table_name} (id, content, metadata) VALUES (%s, %s, %s)",
                ("test2", "Content 2", Json({"category": "B"})),
            )

        # Load data with filter
        documents = await reader.aload_data(where_clause={"category": "A"})

        assert len(documents) == 1
        assert documents[0].text == "Content 1"
        assert documents[0].metadata["category"] == "A"

    @pytest.mark.asyncio
    async def test_load_data_with_limit(self, reader: FraiseQLReader, class_db_pool, test_schema):
        """Test data loading with LIMIT."""
        # Insert test data
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            for i in range(5):
                await conn.execute(
                    f"INSERT INTO {reader.table_name} (id, content, metadata) VALUES (%s, %s, %s)",
                    (f"test{i}", f"Content {i}", Json({"index": i})),
                )

        # Load data with limit
        documents = await reader.aload_data(limit=2)

        assert len(documents) == 2

    @pytest.mark.asyncio
    async def test_load_data_filter_key_is_not_sql(
        self, reader: FraiseQLReader, class_db_pool, test_schema
    ):
        """A where_clause key is a JSON key or a column name, never SQL."""
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            for doc_id, category in (("q1", "A"), ("q2", "B")):
                await conn.execute(
                    f"INSERT INTO {reader.table_name} (id, content, metadata) VALUES (%s, %s, %s)",
                    (doc_id, f"Content {doc_id}", Json({"it's": category, "100%": category})),
                )

        # The quote and the percent sign are part of the JSON key
        documents = await reader.aload_data(where_clause={"it's": "A"})
        assert [d.metadata["id"] for d in documents] == ["q1"]
        documents = await reader.aload_data(where_clause={"100%": "B"})
        assert [d.metadata["id"] for d in documents] == ["q2"]

        # Used to end the quoted key and match every row
        injected = "x' IS NULL OR metadata->>'x"
        assert await reader.aload_data(where_clause={injected: "zzz"}) == []

        # A column key is quoted as an identifier
        documents = await reader.aload_data(where_clause={"id": "q2"})
        assert [d.metadata["id"] for d in documents] == ["q2"]

    def test_load_data_sync(self, reader: FraiseQLReader):
        """Test synchronous data loading."""
        # This should work without errors (even if no data)
        documents = reader.load_data()
        assert isinstance(documents, list)


@pytest.mark.skipif(not LLAMAINDEX_AVAILABLE, reason="LlamaIndex not available")
class TestFraiseQLVectorStore:
    """Test FraiseQLVectorStore functionality."""

    @pytest.mark.asyncio
    async def test_add_and_get_nodes(self, vectorstore: FraiseQLVectorStore):
        """Test adding and retrieving nodes."""
        # Create TextNode objects
        nodes = []
        for i in range(3):
            node = TextNode(
                id_=f"node_{i}", text=f"Content {i}", embedding=[0.1] * 384, metadata={"index": i}
            )
            nodes.append(node)

        # Add nodes
        ids = await vectorstore.aadd(nodes)
        assert len(ids) == 3
        assert all(isinstance(id_val, str) for id_val in ids)

        # Get nodes back
        retrieved_nodes = await vectorstore.aget(ids)
        assert len(retrieved_nodes) == 3
        assert retrieved_nodes[0].id_ == "node_0"
        assert retrieved_nodes[0].text == "Content 0"

    @pytest.mark.asyncio
    async def test_delete_nodes(self, vectorstore: FraiseQLVectorStore):
        """Test deleting nodes."""
        # Add a node first
        node = TextNode(
            id_="delete_test", text="Content to delete", embedding=[0.1] * 384, metadata={}
        )

        ids = await vectorstore.aadd([node])
        assert len(ids) == 1

        # Verify it exists
        retrieved = await vectorstore.aget(ids)
        assert len(retrieved) == 1

        # Delete it
        await vectorstore.adelete(ids)

        # Verify it's gone
        retrieved_after = await vectorstore.aget(ids)
        assert len(retrieved_after) == 0

    @pytest.mark.asyncio
    async def test_similarity_search(self, vectorstore: FraiseQLVectorStore):
        """Test vector similarity search."""
        # Add test nodes with different embeddings
        nodes = []
        for i in range(5):
            node = TextNode(
                id_=f"search_{i}",
                text=f"Search content {i}",
                # Create slightly different embeddings
                embedding=[0.1 + i * 0.01] * 384,
                metadata={"score": i},
            )
            nodes.append(node)

        await vectorstore.aadd(nodes)

        # Create a query
        from llama_index.core.vector_stores.types import VectorStoreQuery

        query = VectorStoreQuery(
            query_embedding=[0.1] * 384,  # Similar to first node
            similarity_top_k=3,
            filters=None,
        )

        # Search
        results = await vectorstore.aquery(query)

        assert len(results.nodes) <= 3
        assert len(results.similarities) == len(results.nodes)
        assert len(results.ids) == len(results.nodes)

    @pytest.mark.asyncio
    async def test_metadata_filtering(self, vectorstore: FraiseQLVectorStore):
        """Test metadata filtering in queries."""
        # Add nodes with different metadata
        nodes = []
        for category in ["A", "B", "A"]:
            node = TextNode(
                id_=f"filter_{category}_{len(nodes)}",
                text=f"Content for {category}",
                embedding=[0.1] * 384,
                metadata={"category": category},
            )
            nodes.append(node)

        await vectorstore.aadd(nodes)

        # Create query with metadata filter
        from llama_index.core.vector_stores.types import (
            MetadataFilter,
            MetadataFilters,
            VectorStoreQuery,
        )

        query = VectorStoreQuery(
            query_embedding=[0.1] * 384,
            similarity_top_k=10,
            filters=MetadataFilters(filters=[MetadataFilter(key="category", value="A")]),
        )

        # Search with filter
        results = await vectorstore.aquery(query)

        # Should only return nodes with category "A"
        for node in results.nodes:
            assert node.metadata.get("category") == "A"

    def test_sync_methods(self, vectorstore: FraiseQLVectorStore):
        """Test that sync methods work (even if they do nothing)."""
        # These should not raise errors
        from llama_index.core.vector_stores.types import VectorStoreQuery

        vectorstore.add([])
        vectorstore.get([])
        vectorstore.delete([])
        vectorstore.query(VectorStoreQuery(query_embedding=[0.1] * 384, similarity_top_k=3))

    @pytest.mark.asyncio
    async def test_error_handling(self, vectorstore: FraiseQLVectorStore):
        """Test error handling for invalid operations."""
        # Try to get non-existent nodes
        result = await vectorstore.aget(["nonexistent"])
        assert result == []

        # Try to delete non-existent nodes
        await vectorstore.adelete(["nonexistent"])  # Should not raise

        # Try to add node without embedding
        node = Mock()
        node.id_ = "no_embedding"
        node.text = "Content"
        node.embedding = None
        node.metadata = {}

        with pytest.raises(ValueError, match="does not have an embedding"):
            await vectorstore.aadd([node])


@pytest.mark.skipif(not LLAMAINDEX_AVAILABLE, reason="LlamaIndex not available")
class TestIntegration:
    """Test integration between Reader and VectorStore."""

    @pytest.mark.asyncio
    async def test_reader_vectorstore_workflow(
        self, reader: FraiseQLReader, vectorstore: FraiseQLVectorStore, class_db_pool, test_schema
    ):
        """Test a complete workflow from reading to vector storage."""
        # Insert data via SQL
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute(
                f"INSERT INTO {reader.table_name} (id, content, metadata) VALUES (%s, %s, %s)",
                ("workflow_test", "Workflow test content", Json({"source": "test"})),
            )

        # Read data with reader
        documents = await reader.aload_data()
        assert len(documents) == 1

        # Convert document to node for vectorstore
        # (In real usage, this would be done by LlamaIndex's ingestion pipeline)
        node = TextNode(
            id_=documents[0].metadata["id"],
            text=documents[0].text,
            embedding=[0.1] * 384,
            metadata=documents[0].metadata,
        )

        # Store in vectorstore
        ids = await vectorstore.aadd([node])
        assert len(ids) == 1

        # Verify storage
        retrieved = await vectorstore.aget(ids)
        assert len(retrieved) == 1
        assert retrieved[0].text == "Workflow test content"
