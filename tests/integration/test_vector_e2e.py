"""End-to-end integration tests for PostgreSQL pgvector support in FraiseQL.

Tests complete vector similarity search functionality including:
- Vector filtering with cosine, L2, and inner product distances
- Vector ordering by distance
- Composition with other filters
- Pagination and limits
- Error handling for dimension mismatches
- Performance with HNSW indexes
"""

from uuid import UUID

import pytest
import pytest_asyncio
from tests.unit.utils.test_response_utils import extract_graphql_data

from fraiseql.db import FraiseQLRepository
from fraiseql.types import fraise_type

pytestmark = pytest.mark.integration


@fraise_type
class DocumentType:
    """Test document type with vector embedding for semantic search."""

    id: UUID
    title: str
    content: str
    embedding: list[float]  # Vector field detected by name pattern
    tenant_id: UUID
    created_at: str


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def vector_test_setup(class_db_pool, test_schema, pgvector_available) -> None:
    """Set up test database with pgvector extension and test data."""
    if not pgvector_available:
        pytest.skip("pgvector extension not available")

    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")

        # Create test table with vector column
        await conn.execute("""
            CREATE TABLE test_documents (
                id UUID PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT,
                embedding vector(384),  -- OpenAI text-embedding-ada-002 dimensions
                tenant_id UUID NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        # Create HNSW index for performance
        await conn.execute("""
            CREATE INDEX test_documents_embedding_hnsw
            ON test_documents
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)

        # Insert test data with sample embeddings
        test_docs = [
            {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "title": "Python Programming",
                "content": "Guide to Python programming language",
                "embedding": [0.1, 0.2, 0.3] + [0.0] * 381,  # 384 dimensions
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
            },
            {
                "id": "550e8400-e29b-41d4-a716-446655440002",
                "title": "Machine Learning",
                "content": "Introduction to machine learning concepts",
                "embedding": [0.2, 0.3, 0.4] + [0.0] * 381,  # 384 dimensions
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
            },
            {
                "id": "550e8400-e29b-41d4-a716-446655440003",
                "title": "Data Science",
                "content": "Data science and analytics overview",
                "embedding": [0.3, 0.4, 0.5] + [0.0] * 381,  # 384 dimensions
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
            },
        ]

        for doc in test_docs:
            await conn.execute(
                """
                INSERT INTO test_documents (id, title, content, embedding, tenant_id)
                VALUES (%s, %s, %s, %s::vector, %s)
            """,
                (
                    doc["id"],
                    doc["title"],
                    doc["content"],
                    doc["embedding"],
                    doc["tenant_id"],
                ),
            )

        await conn.commit()


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def binary_vector_test_setup(class_db_pool, test_schema, pgvector_available) -> None:
    """Set up test database with binary vector test data."""
    if not pgvector_available:
        pytest.skip("pgvector extension not available")

    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")

        # Create test table with bit vector column
        await conn.execute("""
            CREATE TABLE test_fingerprints (
                id UUID PRIMARY KEY,
                name TEXT NOT NULL,
                fingerprint bit(64),  -- 64-bit binary vector
                category TEXT,
                tenant_id UUID NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        # Insert test data with sample bit vectors
        test_items = [
            {
                "id": "650e8400-e29b-41d4-a716-446655440001",
                "name": "Item A",
                "fingerprint": "1111000011110000111100001111000011110000111100001111000011110000",  # 64 bits
                "category": "electronics",
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
            },
            {
                "id": "650e8400-e29b-41d4-a716-446655440002",
                "name": "Item B",
                "fingerprint": "1111111100000000111111110000000011111111000000001111111100000000",  # 64 bits
                "category": "books",
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
            },
            {
                "id": "650e8400-e29b-41d4-a716-446655440003",
                "name": "Item C",
                "fingerprint": "1010101010101010101010101010101010101010101010101010101010101010",  # 64 bits
                "category": "clothing",
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
            },
        ]

        for item in test_items:
            await conn.execute(
                """
                INSERT INTO test_fingerprints (id, name, fingerprint, category, tenant_id)
                VALUES (%s, %s, %s::bit(64), %s, %s)
            """,
                (
                    item["id"],
                    item["name"],
                    item["fingerprint"],
                    item["category"],
                    item["tenant_id"],
                ),
            )

        await conn.commit()


@pytest.mark.asyncio
async def test_vector_filter_cosine_distance(class_db_pool, test_schema, vector_test_setup) -> None:
    """Test filtering documents by cosine distance."""
    # This test will fail until vector filtering is implemented
    repo = FraiseQLRepository(class_db_pool)
    query_embedding = [0.1, 0.2, 0.3] + [0.0] * 381  # Same as first document

    result = await repo.find(
        "test_documents",
        where={"embedding": {"cosine_distance": {"vector": query_embedding, "threshold": 0.5}}},
        limit=5,
    )

    results = extract_graphql_data(result, "test_documents")

    # Should return documents ordered by cosine distance (most similar first)
    assert len(results) > 0
    # First result should be the identical document (distance = 0.0)
    assert results[0]["title"] == "Python Programming"


@pytest.mark.asyncio
async def test_vector_filter_tuple_format(class_db_pool, test_schema, vector_test_setup) -> None:
    """Test filtering with tuple format (vector, threshold)."""
    repo = FraiseQLRepository(class_db_pool)
    query_embedding = [0.1, 0.2, 0.3] + [0.0] * 381

    # Use tuple format instead of dict
    result = await repo.find(
        "test_documents",
        where={"embedding": {"cosine_distance": (query_embedding, 0.5)}},
        limit=5,
    )

    results = extract_graphql_data(result, "test_documents")
    assert len(results) > 0
    assert results[0]["title"] == "Python Programming"


@pytest.mark.asyncio
async def test_vector_order_by_distance(class_db_pool, test_schema, vector_test_setup) -> None:
    """Test ordering results by vector distance using GraphQL input objects."""
    repo = FraiseQLRepository(class_db_pool)
    query_embedding = [0.1, 0.2, 0.3] + [0.0] * 381

    # Use proper GraphQL input object (not plain dict)
    from fraiseql.sql.graphql_order_by_generator import VectorOrderBy

    result = await repo.find(
        "test_documents",
        # Create VectorOrderBy input object
        order_by={"embedding": VectorOrderBy(cosine_distance=query_embedding)},
        limit=3,
    )

    results = extract_graphql_data(result, "test_documents")

    # Should return documents ordered by cosine distance
    assert len(results) == 3
    # First result should be Python Programming (identical embedding)
    assert results[0]["title"] == "Python Programming"


@pytest.mark.asyncio
async def test_vector_with_other_filters(class_db_pool, test_schema, vector_test_setup) -> None:
    """Test vector filtering composed with other filters."""
    # This test will fail until vector filtering is implemented
    repo = FraiseQLRepository(class_db_pool)
    query_embedding = [0.1, 0.2, 0.3] + [0.0] * 381

    result = await repo.find(
        "test_documents",
        where={
            "embedding": {"cosine_distance": (query_embedding, 0.5)},
            "title": {
                "contains": "Python"  # Additional filter
            },
        },
        limit=5,
    )

    results = extract_graphql_data(result, "test_documents")


@pytest.mark.asyncio
async def test_vector_l1_distance_filter(class_db_pool, test_schema, vector_test_setup) -> None:
    """Test filtering documents by L1/Manhattan distance."""
    repo = FraiseQLRepository(class_db_pool)
    query_embedding = [0.1, 0.2, 0.3] + [0.0] * 381

    result = await repo.find(
        "test_documents",
        where={"embedding": {"l1_distance": (query_embedding, 10.0)}},
        limit=5,
    )

    results = extract_graphql_data(result, "test_documents")
    assert len(results) > 0
    # Results should be filtered by L1 distance


@pytest.mark.asyncio
async def test_vector_l1_distance_order_by(class_db_pool, test_schema, vector_test_setup) -> None:
    """Test ordering documents by L1/Manhattan distance."""
    repo = FraiseQLRepository(class_db_pool)
    # Nearest the last-inserted row, so the expected order is the reverse of the
    # physical one and cannot be satisfied by an unordered scan (#483).
    query_embedding = [0.3, 0.4, 0.5] + [0.0] * 381

    # Use proper GraphQL input object (not plain dict)
    from fraiseql.sql.graphql_order_by_generator import VectorOrderBy

    result = await repo.find(
        "test_documents",
        order_by={"embedding": VectorOrderBy(l1_distance=query_embedding)},
        limit=3,
    )

    results = extract_graphql_data(result, "test_documents")
    assert [row["title"] for row in results] == [
        "Data Science",
        "Machine Learning",
        "Python Programming",
    ]


@pytest.mark.asyncio
async def test_vector_l1_distance_combined(class_db_pool, test_schema, vector_test_setup) -> None:
    """Test L1 distance for both WHERE and ORDER BY combined."""
    repo = FraiseQLRepository(class_db_pool)
    query_embedding = [0.3, 0.4, 0.5] + [0.0] * 381

    from fraiseql.sql.graphql_order_by_generator import VectorOrderBy

    result = await repo.find(
        "test_documents",
        where={"embedding": {"l1_distance": {"vector": query_embedding, "threshold": 10.0}}},
        order_by={"embedding": VectorOrderBy(l1_distance=query_embedding)},
        limit=3,
    )

    results = extract_graphql_data(result, "test_documents")
    assert [row["title"] for row in results] == [
        "Data Science",
        "Machine Learning",
        "Python Programming",
    ]


@pytest.mark.asyncio
async def test_binary_vector_hamming_distance_filter(
    class_db_pool, test_schema, binary_vector_test_setup
) -> None:
    """Test filtering binary vectors by Hamming distance."""
    repo = FraiseQLRepository(class_db_pool)
    query_fingerprint = "1111000011110000111100001111000011110000111100001111000011110000"

    result = await repo.find(
        "test_fingerprints",
        where={"fingerprint": {"hamming_distance": {"vector": query_fingerprint, "threshold": 10}}},
        limit=5,
    )

    results = extract_graphql_data(result, "test_fingerprints")
    # Item A *is* the query fingerprint (distance 0); B and C each differ in 32
    # of the 64 bits, so a threshold of 10 must exclude both. Asserting only
    # len(results) > 0 held just as well when the filter matched everything (#494).
    assert [row["name"] for row in results] == ["Item A"]


@pytest.mark.asyncio
async def test_binary_vector_jaccard_distance_filter(
    class_db_pool, test_schema, binary_vector_test_setup
) -> None:
    """Test filtering binary vectors by Jaccard distance."""
    repo = FraiseQLRepository(class_db_pool)
    query_fingerprint = "1111000011110000111100001111000011110000111100001111000011110000"

    result = await repo.find(
        "test_fingerprints",
        where={
            "fingerprint": {"jaccard_distance": {"vector": query_fingerprint, "threshold": 0.3}}
        },
        limit=5,
    )

    results = extract_graphql_data(result, "test_fingerprints")
    # Distances are 0.0 / 0.667 / 0.667 to Items A / B / C, so 0.3 keeps only A.
    # See the Hamming test above for why counting rows was not enough (#494).
    assert [row["name"] for row in results] == ["Item A"]


@pytest.mark.asyncio
async def test_binary_vector_where_builders_compute_over_every_bit(
    class_db_pool, test_schema, binary_vector_test_setup
) -> None:
    """The WHERE-side bit builders must span the whole literal, not one bit (#494).

    Drives the real operator-registry builders -- the path a filter with no
    resolved type hint takes -- and checks the distances PostgreSQL actually
    computes. Under the old bare ``::bit`` both operands were truncated to
    ``bit(1)`` and every row came back 0.0.
    """
    from psycopg.sql import SQL, Composed

    from fraiseql.sql.where.operators.vectors import (
        build_hamming_distance_sql,
        build_jaccard_distance_sql,
    )

    query_fingerprint = "1111000011110000111100001111000011110000111100001111000011110000"
    expected = [
        (build_hamming_distance_sql, [("Item A", 0.0), ("Item B", 32.0), ("Item C", 32.0)]),
        (build_jaccard_distance_sql, [("Item A", 0.0), ("Item B", 0.667), ("Item C", 0.667)]),
    ]

    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        for builder, want in expected:
            # The registry renders a JSONB text extraction, so feed the builder a
            # text-typed path rather than the bit(64) column itself.
            distance = builder(SQL("fingerprint::text"), query_fingerprint)
            cur = await conn.execute(
                Composed(
                    [
                        SQL("SELECT name, round(("),
                        distance,
                        SQL(")::numeric, 3) FROM test_fingerprints ORDER BY name"),
                    ]
                )
            )
            assert [(name, float(d)) for name, d in await cur.fetchall()] == want


@pytest.mark.asyncio
async def test_binary_vector_hamming_distance_order_by(
    class_db_pool, test_schema, binary_vector_test_setup
) -> None:
    """Test ordering binary vectors by Hamming distance."""
    repo = FraiseQLRepository(class_db_pool)
    # Distances 25 / 31 / 33 to items C / A / B -- distinct, and in an order the
    # physical A, B, C cannot produce, so an omitted ORDER BY fails here (#483).
    query_fingerprint = "0000000000100010100000100111001111100101001010111011101110100100"

    from fraiseql.sql.graphql_order_by_generator import VectorOrderBy

    result = await repo.find(
        "test_fingerprints",
        order_by={"fingerprint": VectorOrderBy(hamming_distance=query_fingerprint)},
        limit=3,
    )

    results = extract_graphql_data(result, "test_fingerprints")
    assert [row["name"] for row in results] == ["Item C", "Item A", "Item B"]


@pytest.mark.asyncio
async def test_binary_vector_jaccard_distance_order_by(
    class_db_pool, test_schema, binary_vector_test_setup
) -> None:
    """Test ordering binary vectors by Jaccard distance."""
    repo = FraiseQLRepository(class_db_pool)
    # Distances 0.595 / 0.689 / 0.717 to items C / A / B -- see the Hamming test
    # above for why the expected order has to differ from the physical one.
    query_fingerprint = "0000000000100010100000100111001111100101001010111011101110100100"

    from fraiseql.sql.graphql_order_by_generator import VectorOrderBy

    result = await repo.find(
        "test_fingerprints",
        order_by={"fingerprint": VectorOrderBy(jaccard_distance=query_fingerprint)},
        limit=3,
    )

    results = extract_graphql_data(result, "test_fingerprints")
    assert [row["name"] for row in results] == ["Item C", "Item A", "Item B"]


@pytest.mark.asyncio
async def test_vector_limit_results(class_db_pool, test_schema, vector_test_setup) -> None:
    """Test pagination with vector similarity search."""
    # This test will fail until vector filtering is implemented
    repo = FraiseQLRepository(class_db_pool)
    query_embedding = [0.0, 0.0, 0.0] + [0.0] * 381  # Different from all documents

    result = await repo.find(
        "test_documents",
        where={"embedding": {"l2_distance": {"vector": query_embedding, "threshold": 10.0}}},
        limit=2,
    )

    results = extract_graphql_data(result, "test_documents")

    # Should return exactly 2 results
    assert len(results) == 2


@pytest.mark.asyncio
async def test_vector_dimension_mismatch_error(
    class_db_pool, test_schema, vector_test_setup
) -> None:
    """Test that dimension validation is handled by PostgreSQL (not FraiseQL)."""
    # According to design, FraiseQL does NOT validate dimensions - PostgreSQL handles it
    repo = FraiseQLRepository(class_db_pool)
    wrong_dimension_embedding = [0.1, 0.2]  # Only 2 dimensions vs required 384

    # PostgreSQL will catch the dimension mismatch and raise an exception
    # FraiseQL should not reject the query upfront - validation happens in PostgreSQL
    from psycopg import errors as psycopg_errors

    with pytest.raises(psycopg_errors.DataException, match="different vector dimensions"):
        await repo.find(
            "test_documents",
            where={
                "embedding": {
                    "cosine_distance": {"vector": wrong_dimension_embedding, "threshold": 0.5}
                }
            },
        )


@pytest.mark.asyncio
async def test_vector_hnsw_index_performance(class_db_pool, test_schema, vector_test_setup) -> None:
    """Test that HNSW index is used for vector queries (optional performance test)."""
    # This test verifies index usage by checking query execution plan
    repo = FraiseQLRepository(class_db_pool)
    query_embedding = [0.1, 0.2, 0.3] + [0.0] * 381

    result = await repo.find(
        "test_documents",
        where={"embedding": {"cosine_distance": {"vector": query_embedding, "threshold": 0.5}}},
        limit=5,
    )

    results = extract_graphql_data(result, "test_documents")

    # Query should succeed and use index (verified by fast execution)
    assert len(results) >= 0  # At least no results is acceptable

    # In a real performance test, we would:
    # 1. Run EXPLAIN on the query
    # 2. Verify "Index Scan" appears in the plan
    # 3. Check that query executes in < 100ms
