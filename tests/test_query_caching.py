"""Tests for query plan caching."""

import pytest

from fraiseql.core.graphql_parser import RustGraphQLParser
from fraiseql.core.query_builder import RustQueryBuilder


@pytest.fixture
def parser():
    return RustGraphQLParser()


@pytest.fixture
def builder():
    RustQueryBuilder.clear_cache()  # Clean slate
    return RustQueryBuilder()


@pytest.fixture
def test_schema():
    return {
        "tables": {
            "users": {  # GraphQL field name as key
                "view_name": "v_users",  # SQL view name
                "sql_columns": ["id", "email"],
                "jsonb_column": "data",
                "fk_mappings": {},
                "has_jsonb_data": True,
            },
            "posts": {
                "view_name": "v_post",
                "sql_columns": ["id", "title"],
                "jsonb_column": "data",
                "fk_mappings": {},
                "has_jsonb_data": True,
            }
        },
        "types": {},
    }


@pytest.mark.asyncio
async def test_cache_hit(parser, builder, test_schema):
    """Test that identical queries hit cache."""
    query = "query { users { id } }"

    # First query - cache miss
    parsed1 = await parser.parse(query)
    result1 = builder.build_cached(parsed1, test_schema)

    stats_after_first = RustQueryBuilder.get_stats()
    assert stats_after_first["misses"] == 1  # First query is a miss
    assert stats_after_first["hits"] == 0

    # Second identical query - cache hit
    parsed2 = await parser.parse(query)
    result2 = builder.build_cached(parsed2, test_schema)

    stats_after_second = RustQueryBuilder.get_stats()

    # Verify cache hit
    assert stats_after_second["misses"] == 1  # Still only 1 miss
    assert stats_after_second["hits"] == 1  # Now we have 1 hit
    assert result1.sql == result2.sql


@pytest.mark.asyncio
async def test_cache_miss_different_query(parser, builder, test_schema):
    """Test that different queries are not cached together."""
    query1 = "query { users { id } }"
    query2 = "query { posts { id } }"

    parsed1 = await parser.parse(query1)
    result1 = builder.build_cached(parsed1, test_schema)

    parsed2 = await parser.parse(query2)
    result2 = builder.build_cached(parsed2, test_schema)

    # Different queries should generate different SQL
    assert result1.sql != result2.sql


@pytest.mark.asyncio
async def test_cache_clear(parser, builder, test_schema):
    """Test cache invalidation."""
    query = "query { users { id } }"
    parsed = await parser.parse(query)

    # Build and cache
    builder.build_cached(parsed, test_schema)

    stats_before = RustQueryBuilder.get_stats()
    initial_cached = stats_before["cached_plans"]

    # Clear cache
    RustQueryBuilder.clear_cache()

    stats_after = RustQueryBuilder.get_stats()

    assert stats_after["cached_plans"] == 0
    assert stats_after["hits"] == 0


@pytest.mark.asyncio
async def test_cache_stats(parser, builder, test_schema):
    """Test cache statistics."""
    query = "query { users { id } }"

    for _ in range(5):
        parsed = await parser.parse(query)
        builder.build_cached(parsed, test_schema)

    stats = RustQueryBuilder.get_stats()

    assert stats["hits"] == 4  # 5 queries - 1 first miss
    assert stats["misses"] == 1
    assert stats["hit_rate"] > 0.7
    assert stats["cached_plans"] >= 1


@pytest.mark.asyncio
async def test_cache_with_parameters(parser, builder, test_schema):
    """Test caching with parameterized queries."""
    query1 = 'query { users(where: {status: "active"}) { id } }'
    query2 = 'query { users(where: {status: "inactive"}) { id } }'

    # Different parameter values should still cache (same structure)
    parsed1 = await parser.parse(query1)
    result1 = builder.build_cached(parsed1, test_schema)

    parsed2 = await parser.parse(query2)
    result2 = builder.build_cached(parsed2, test_schema)

    # Same SQL structure, different parameters
    assert result1.sql == result2.sql
