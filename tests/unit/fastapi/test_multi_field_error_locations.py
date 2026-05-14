"""Tests for multi-field GraphQL error location reporting.

Tests that errors include line and column numbers for better debugging.
"""

import json

import pytest

from fraiseql.fastapi.routers import execute_multi_field_query


@pytest.mark.asyncio
async def test_error_includes_location(init_schema_registry_fixture):
    """Test that errors include line and column location."""
    from graphql import (
        GraphQLField,
        GraphQLInt,
        GraphQLList,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
    )

    user_type = GraphQLObjectType(
        "User",
        lambda: {
            "id": GraphQLField(GraphQLInt),
            "name": GraphQLField(GraphQLString),
        },
    )

    async def resolve_users(root, info):
        raise RuntimeError("Resolver failed")

    async def resolve_posts(root, info):
        return [{"id": 1, "title": "Post 1"}]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type), resolve=resolve_users),
            "posts": GraphQLField(GraphQLList(user_type), resolve=resolve_posts),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Multi-line query where 'users' starts at line 3
    query = """
        {
            users { id name }
            posts { id title }
        }
    """

    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    # Verify error has location
    assert len(result_json["errors"]) == 1
    error = result_json["errors"][0]

    assert "locations" in error
    assert len(error["locations"]) == 1

    location = error["locations"][0]
    assert "line" in location
    assert "column" in location

    # 'users' should be at line 3 (after opening brace and newline)
    assert location["line"] == 3
    assert location["column"] > 0


@pytest.mark.asyncio
async def test_multiple_errors_with_locations(init_schema_registry_fixture):
    """Test that each error has its own location."""
    from graphql import (
        GraphQLField,
        GraphQLInt,
        GraphQLList,
        GraphQLObjectType,
        GraphQLSchema,
    )

    user_type = GraphQLObjectType(
        "User",
        lambda: {
            "id": GraphQLField(GraphQLInt),
        },
    )

    async def resolve_users(root, info):
        raise RuntimeError("Users failed")

    async def resolve_posts(root, info):
        raise RuntimeError("Posts failed")

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type), resolve=resolve_users),
            "posts": GraphQLField(GraphQLList(user_type), resolve=resolve_posts),
        },
    )

    schema = GraphQLSchema(query=query_type)

    query = """
        {
            users { id }
            posts { id }
        }
    """

    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    assert len(result_json["errors"]) == 2

    # Both errors should have locations
    for error in result_json["errors"]:
        assert "locations" in error
        assert len(error["locations"]) == 1
        assert "line" in error["locations"][0]
        assert "column" in error["locations"][0]

    # Errors should have different line numbers
    lines = [e["locations"][0]["line"] for e in result_json["errors"]]
    assert lines[0] != lines[1]


@pytest.mark.asyncio
async def test_success_no_error_locations(init_schema_registry_fixture):
    """Test that successful queries don't have errors or locations."""
    from graphql import (
        GraphQLField,
        GraphQLInt,
        GraphQLList,
        GraphQLObjectType,
        GraphQLSchema,
    )

    user_type = GraphQLObjectType(
        "User",
        lambda: {
            "id": GraphQLField(GraphQLInt),
        },
    )

    async def resolve_users(root, info):
        return [{"id": 1}]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type), resolve=resolve_users),
        },
    )

    schema = GraphQLSchema(query=query_type)

    query = """
        {
            users { id }
        }
    """

    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    # No errors key at all
    assert "errors" not in result_json
    assert "data" in result_json


@pytest.fixture
def init_schema_registry_fixture():
    """Initialize schema registry for multi-field error location tests."""
    import fraiseql._fraiseql_rs as fraiseql_rs

    # Reset the schema registry to allow re-initialization
    fraiseql_rs.reset_schema_registry_for_testing()

    # Minimal schema IR for testing
    schema_ir = {
        "version": "1.0",
        "features": ["type_resolution"],
        "types": {},
    }

    fraiseql_rs.initialize_schema_registry(json.dumps(schema_ir))
