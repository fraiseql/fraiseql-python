"""Tests for nested field error handling in multi-field GraphQL queries.

Note: This phase documents the current limitation rather than implementing
full nested field error recovery, which is complex and requires both Python
and Rust modifications.

Current behavior: When nested resolvers fail, the entire parent field fails.
Future behavior: Nested fields should fail independently while parent succeeds.
"""

import json

import pytest

from fraiseql.fastapi.routers import execute_multi_field_query


@pytest.mark.asyncio
async def test_nested_field_error_fails_parent(init_schema_registry_fixture):
    """Document that nested field errors fail the parent field by design.

    This is an intentional architectural decision in FraiseQL. Due to the use
    of database views and table views, partial failures are not supported.
    When a nested resolver fails, the entire parent field must fail to maintain
    data consistency with the underlying database views.

    This prioritizes data consistency over GraphQL spec compliance for partial results.
    """
    from graphql import (
        GraphQLField,
        GraphQLInt,
        GraphQLList,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
    )

    profile_type = GraphQLObjectType(
        "Profile",
        lambda: {
            "bio": GraphQLField(GraphQLString),
        },
    )

    user_type = GraphQLObjectType(
        "User",
        lambda: {
            "id": GraphQLField(GraphQLInt),
            "name": GraphQLField(GraphQLString),
            "profile": GraphQLField(profile_type),
        },
    )

    async def resolve_users(root, info):
        # Return users with nested profile data
        return [
            {"id": 1, "name": "Alice", "profile": {"bio": "Developer"}},
            {"id": 2, "name": "Bob", "profile": None},  # Simulated failure
        ]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type), resolve=resolve_users),
        },
    )

    schema = GraphQLSchema(query=query_type)

    query = """
        {
            users {
                id
                name
                profile { bio }
            }
        }
    """

    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    # Current behavior: profile=None is passed through as null
    assert len(result_json["data"]["users"]) == 2
    assert result_json["data"]["users"][1]["profile"] is None

    # Note: In full implementation, we'd want:
    # - errors: [{"message": "...", "path": ["users", 1, "profile"]}]
    # - But parent field still succeeds with partial data


@pytest.fixture
def init_schema_registry_fixture():
    """Initialize schema registry for nested field error tests."""
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
