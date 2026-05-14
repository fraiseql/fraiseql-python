"""Tests for Rust SQL query builder."""

import pytest

from fraiseql.core.graphql_parser import RustGraphQLParser
from fraiseql.core.query_builder import RustQueryBuilder


@pytest.fixture
def parser():
    return RustGraphQLParser()


@pytest.fixture
def builder():
    return RustQueryBuilder()


@pytest.fixture
def test_schema():
    return {
        "tables": {
            "users": {  # GraphQL field name as key
                "view_name": "v_users",  # SQL view name
                "sql_columns": ["id", "email", "status"],
                "jsonb_column": "data",
                "fk_mappings": {"machine": "machine_id"},
                "has_jsonb_data": True,
            }
        },
        "types": {},
    }


@pytest.mark.asyncio
async def test_build_simple_query(parser, builder, test_schema):
    """Test building simple SELECT query."""
    query = "query { users { id name } }"
    parsed = await parser.parse(query)

    result = builder.build(parsed, test_schema)

    assert "SELECT" in result.sql
    assert "v_users" in result.sql
    assert "FROM" in result.sql


@pytest.mark.asyncio
async def test_build_query_with_where(parser, builder, test_schema):
    """Test building query with WHERE clause."""
    query = """
        query {
            users(where: {status: "active"}) {
                id
            }
        }
    """
    parsed = await parser.parse(query)
    result = builder.build(parsed, test_schema)

    assert "WHERE" in result.sql
    assert "status" in result.sql


@pytest.mark.asyncio
async def test_build_query_with_limit(parser, builder, test_schema):
    """Test building query with LIMIT."""
    query = "query { users(limit: 10) { id } }"
    parsed = await parser.parse(query)
    result = builder.build(parsed, test_schema)

    assert "LIMIT 10" in result.sql


@pytest.mark.asyncio
async def test_build_query_with_offset(parser, builder, test_schema):
    """Test building query with pagination."""
    query = "query { users(limit: 10, offset: 20) { id } }"
    parsed = await parser.parse(query)
    result = builder.build(parsed, test_schema)

    assert "LIMIT 10" in result.sql
    assert "OFFSET 20" in result.sql


@pytest.mark.asyncio
async def test_build_query_with_complex_where(parser, builder, test_schema):
    """Test building query with complex WHERE clause."""
    query = """
        query {
            users(where: {
                AND: [
                    {status: "active"},
                    {email: {like: "test"}}
                ]
            }) {
                id
            }
        }
    """
    parsed = await parser.parse(query)
    result = builder.build(parsed, test_schema)

    assert "WHERE" in result.sql
    assert "status" in result.sql
    assert "email" in result.sql
    assert "AND" in result.sql


@pytest.mark.asyncio
async def test_parameters_are_collected(parser, builder, test_schema):
    """Test that parameters are properly collected."""
    query = """
        query {
            users(where: {status: "active", email: {like: "test"}}) {
                id
            }
        }
    """
    parsed = await parser.parse(query)
    result = builder.build(parsed, test_schema)

    # Should have parameters for the WHERE values
    assert len(result.parameters) > 0
    param_names = [name for name, _ in result.parameters]
    assert any("param_" in name for name in param_names)
