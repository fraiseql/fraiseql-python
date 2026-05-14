"""Tests for multi-field GraphQL field arguments support.

Tests that root fields can accept arguments for filtering, pagination, and other parameters.
"""

import json

import pytest

from fraiseql.fastapi.routers import execute_multi_field_query


@pytest.mark.asyncio
async def test_field_with_literal_argument(init_schema_registry_fixture):
    """Test root field with a literal argument value."""
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
        # Resolver receives 'limit' argument
        users = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Charlie"},
        ]
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
        {
            users(limit: 2) { id name }
        }
    """

    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    # Should only return 2 users
    assert len(result_json["data"]["users"]) == 2
    assert result_json["data"]["users"][0]["name"] == "Alice"
    assert result_json["data"]["users"][1]["name"] == "Bob"


@pytest.mark.asyncio
async def test_field_with_variable_argument(init_schema_registry_fixture):
    """Test root field argument using a query variable."""
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

    async def resolve_users(root, info, status=None):
        users = [
            {"id": 1, "name": "Alice", "status": "active"},
            {"id": 2, "name": "Bob", "status": "inactive"},
            {"id": 3, "name": "Charlie", "status": "active"},
        ]

        if status:
            users = [u for u in users if u["status"] == status]

        return users

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(
                GraphQLList(user_type),
                args={"status": GraphQLArgument(GraphQLString)},
                resolve=resolve_users,
            ),
        },
    )

    schema = GraphQLSchema(query=query_type)

    query = """
        query GetUsers($userStatus: String!) {
            users(status: $userStatus) { id name status }
        }
    """

    variables = {"userStatus": "active"}

    result = await execute_multi_field_query(schema, query, variables, {})
    result_json = json.loads(bytes(result))

    # Should only return active users
    assert len(result_json["data"]["users"]) == 2
    assert all(u["status"] == "active" for u in result_json["data"]["users"])


@pytest.mark.asyncio
async def test_multi_field_with_different_arguments(init_schema_registry_fixture):
    """Test multiple root fields each with their own arguments."""
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

    post_type = GraphQLObjectType(
        "Post",
        lambda: {
            "id": GraphQLField(GraphQLInt),
            "title": GraphQLField(GraphQLString),
            "author_id": GraphQLField(GraphQLInt),
        },
    )

    async def resolve_users(root, info, limit=10):
        users = [{"id": i, "name": f"User{i}"} for i in range(1, 21)]
        return users[:limit]

    async def resolve_posts(root, info, author_id=None):
        posts = [
            {"id": 1, "title": "Post 1", "author_id": 1},
            {"id": 2, "title": "Post 2", "author_id": 2},
            {"id": 3, "title": "Post 3", "author_id": 1},
        ]

        if author_id:
            posts = [p for p in posts if p["author_id"] == author_id]

        return posts

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(
                GraphQLList(user_type),
                args={"limit": GraphQLArgument(GraphQLInt)},
                resolve=resolve_users,
            ),
            "posts": GraphQLField(
                GraphQLList(post_type),
                args={"author_id": GraphQLArgument(GraphQLInt)},
                resolve=resolve_posts,
            ),
        },
    )

    schema = GraphQLSchema(query=query_type)

    query = """
        query GetData($userId: Int!) {
            users(limit: 5) { id name }
            posts(author_id: $userId) { id title }
        }
    """

    variables = {"userId": 1}

    result = await execute_multi_field_query(schema, query, variables, {})
    result_json = json.loads(bytes(result))

    # Verify users limited to 5
    assert len(result_json["data"]["users"]) == 5

    # Verify posts filtered by author_id
    assert len(result_json["data"]["posts"]) == 2
    # Note: author_id is used for filtering but not selected in the query
    # We expect posts with IDs 1 and 3 (both have author_id=1)
    post_ids = [p["id"] for p in result_json["data"]["posts"]]
    assert 1 in post_ids and 3 in post_ids


@pytest.mark.asyncio
async def test_field_with_complex_arguments(init_schema_registry_fixture):
    """Test field arguments with lists and objects."""
    from graphql import (
        GraphQLArgument,
        GraphQLField,
        GraphQLInputField,
        GraphQLInputObjectType,
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

    # Input object type for filtering
    filter_input = GraphQLInputObjectType(
        "UserFilter",
        {
            "ids": GraphQLInputField(GraphQLList(GraphQLInt)),
            "name_contains": GraphQLInputField(GraphQLString),
        },
    )

    async def resolve_users(root, info, ids=None, filter=None):
        users = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Charlie"},
        ]

        # Filter by IDs list
        if ids:
            users = [u for u in users if u["id"] in ids]

        # Filter by object
        if filter:
            if filter.get("ids"):
                users = [u for u in users if u["id"] in filter["ids"]]
            if filter.get("name_contains"):
                pattern = filter["name_contains"]
                users = [u for u in users if pattern in u["name"]]

        return users

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(
                GraphQLList(user_type),
                args={
                    "ids": GraphQLArgument(GraphQLList(GraphQLInt)),
                    "filter": GraphQLArgument(filter_input),
                },
                resolve=resolve_users,
            ),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Test with list argument
    query1 = """
        {
            users(ids: [1, 3]) { id name }
        }
    """

    result = await execute_multi_field_query(schema, query1, None, {})
    result_json = json.loads(bytes(result))

    assert len(result_json["data"]["users"]) == 2
    assert result_json["data"]["users"][0]["id"] == 1
    assert result_json["data"]["users"][1]["id"] == 3

    # Test with object argument
    query2 = """
        {
            users(filter: {name_contains: "li"}) { id name }
        }
    """

    result = await execute_multi_field_query(schema, query2, None, {})
    result_json = json.loads(bytes(result))

    # Should match "Alice" and "Charlie"
    assert len(result_json["data"]["users"]) == 2


@pytest.fixture
def init_schema_registry_fixture():
    """Initialize schema registry for multi-field argument tests."""
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
