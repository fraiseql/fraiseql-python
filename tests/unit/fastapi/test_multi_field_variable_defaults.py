"""Tests for multi-field GraphQL default variable values.

Tests that default values in variable declarations are properly applied
when variables are not provided or partially provided.
"""

import json

import pytest

from fraiseql.fastapi.routers import execute_multi_field_query


@pytest.mark.asyncio
async def test_variable_with_default_value(init_schema_registry_fixture):
    """Test that default variable values are applied when variable not provided."""
    from graphql import (
        GraphQLArgument,
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

    async def resolve_users(root, info, limit=100):
        users = [{"id": i, "name": f"User{i}"} for i in range(1, 21)]
        return users[:limit]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(
                GraphQLList(user_type),
                args={"limit": GraphQLArgument(GraphQLInt)},
                resolve=resolve_users,
            ),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Query with default value
    query = """
        query GetUsers($limit: Int = 5) {
            users(limit: $limit) { id name }
        }
    """

    # Don't provide $limit variable - should use default
    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    # Should use default limit of 5
    assert len(result_json["data"]["users"]) == 5


@pytest.mark.asyncio
async def test_variable_overrides_default(init_schema_registry_fixture):
    """Test that provided variable overrides the default."""
    from graphql import (
        GraphQLArgument,
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

    async def resolve_users(root, info, limit=100):
        users = [{"id": i, "name": f"User{i}"} for i in range(1, 21)]
        return users[:limit]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(
                GraphQLList(user_type),
                args={"limit": GraphQLArgument(GraphQLInt)},
                resolve=resolve_users,
            ),
        },
    )

    schema = GraphQLSchema(query=query_type)

    query = """
        query GetUsers($limit: Int = 5) {
            users(limit: $limit) { id name }
        }
    """

    # Provide explicit value - should override default
    variables = {"limit": 3}

    result = await execute_multi_field_query(schema, query, variables, {})
    result_json = json.loads(bytes(result))

    # Should use provided limit of 3, not default 5
    assert len(result_json["data"]["users"]) == 3


@pytest.mark.asyncio
async def test_multiple_variable_defaults(init_schema_registry_fixture):
    """Test multiple variables with different defaults."""
    from graphql import (
        GraphQLArgument,
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
            "status": GraphQLField(GraphQLString),
        },
    )

    async def resolve_users(root, info, limit=100, status=None):
        users = [
            {"id": 1, "name": "Alice", "status": "active"},
            {"id": 2, "name": "Bob", "status": "inactive"},
            {"id": 3, "name": "Charlie", "status": "active"},
        ]

        if status:
            users = [u for u in users if u["status"] == status]

        return users[:limit]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(
                GraphQLList(user_type),
                args={
                    "limit": GraphQLArgument(GraphQLInt),
                    "status": GraphQLArgument(GraphQLString),
                },
                resolve=resolve_users,
            ),
        },
    )

    schema = GraphQLSchema(query=query_type)

    query = """
        query GetUsers($limit: Int = 10, $status: String = "active") {
            users(limit: $limit, status: $status) { id name status }
        }
    """

    # Don't provide any variables - both should use defaults
    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    # Should filter to active users only (default status)
    assert all(u["status"] == "active" for u in result_json["data"]["users"])
    assert len(result_json["data"]["users"]) == 2


@pytest.fixture
def init_schema_registry_fixture():
    """Initialize schema registry for multi-field variable defaults tests."""
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
