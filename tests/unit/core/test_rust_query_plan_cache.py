"""The query plan cache keys plans by argument values and keeps their parameters (#580).

Its signature hashed argument names, not values, so ``users(where: {id: {eq: 1}})``
and ``... {eq: 2}`` shared one plan, and a cache hit returned no parameters.
"""

import pytest

from fraiseql.core.graphql_parser import RustGraphQLParser
from fraiseql.core.query_builder import RustQueryBuilder

_SCHEMA = {
    "tables": {
        "users": {
            "view_name": "v_users",
            "sql_columns": ["id", "email"],
            "jsonb_column": "data",
            "fk_mappings": {},
            "has_jsonb_data": True,
        },
    },
    "types": {},
}


@pytest.fixture
def builder() -> RustQueryBuilder:
    RustQueryBuilder.clear_cache()
    yield RustQueryBuilder()
    RustQueryBuilder.clear_cache()


async def _build(builder: RustQueryBuilder, query: str):
    return builder.build_cached(await RustGraphQLParser().parse(query), _SCHEMA)


async def test_different_argument_values_get_their_own_plan(builder: RustQueryBuilder) -> None:
    first = await _build(builder, 'query { users(where: {email: {eq: "a@x"}}) { id } }')
    second = await _build(builder, 'query { users(where: {email: {eq: "b@x"}}) { id } }')

    assert first.parameters != second.parameters
    assert RustQueryBuilder.get_stats()["hits"] == 0


async def test_cache_hit_returns_the_parameters(builder: RustQueryBuilder) -> None:
    query = 'query { users(where: {email: {eq: "a@x"}}) { id } }'
    miss = await _build(builder, query)
    hit = await _build(builder, query)

    assert RustQueryBuilder.get_stats()["hits"] == 1
    assert hit.sql == miss.sql
    assert hit.parameters == miss.parameters
    assert miss.parameters
