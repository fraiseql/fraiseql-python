"""Tests for multi-field query execution with GraphQL variables.

Tests that multi-field queries properly handle variables in field arguments.
"""

import json

import pytest

from fraiseql.fastapi.routers import execute_multi_field_query


@pytest.mark.asyncio
async def test_multi_field_query_with_variables(init_schema_registry_fixture):
    """Test multi-field query with variables in field arguments."""
    from graphql import (
        GraphQLArgument,
        GraphQLField,
        GraphQLInt,
        GraphQLList,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
    )

    # Create test types
    user_type = GraphQLObjectType(
        "User",
        lambda: {
            "id": GraphQLField(GraphQLInt),
            "name": GraphQLField(GraphQLString),
            "age": GraphQLField(GraphQLInt),
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

    # Create resolvers that use variables via field arguments
    async def resolve_users(info):
        # Access variable through field arguments
        min_age = None
        if info.field_nodes and info.field_nodes[0].arguments:
            for arg in info.field_nodes[0].arguments:
                if arg.name.value == "minAge":
                    # Extract variable value
                    if hasattr(arg.value, "name"):
                        # Variable reference like $minAge
                        var_name = arg.value.name.value
                        min_age = info.variable_values.get(var_name)
                    else:
                        # Literal value
                        min_age = arg.value.value

        # Return filtered users
        users = [
            {"id": 1, "name": "Alice", "age": 25},
            {"id": 2, "name": "Bob", "age": 30},
            {"id": 3, "name": "Charlie", "age": 20},
        ]

        if min_age is not None:
            users = [u for u in users if u["age"] >= min_age]

        return users

    async def resolve_posts(info):
        # Access variable for author_id filter
        author_id = None
        if info.field_nodes and info.field_nodes[0].arguments:
            for arg in info.field_nodes[0].arguments:
                if arg.name.value == "authorId":
                    if hasattr(arg.value, "name"):
                        var_name = arg.value.name.value
                        author_id = info.variable_values.get(var_name)
                    else:
                        author_id = arg.value.value

        posts = [
            {"id": 101, "title": "First Post", "author_id": 1},
            {"id": 102, "title": "Second Post", "author_id": 2},
            {"id": 103, "title": "Third Post", "author_id": 1},
        ]

        if author_id is not None:
            posts = [p for p in posts if p["author_id"] == author_id]

        return posts

    # Create schema with arguments
    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(
                GraphQLList(user_type),
                args={"minAge": GraphQLArgument(GraphQLInt)},
                resolve=resolve_users,
            ),
            "posts": GraphQLField(
                GraphQLList(post_type),
                args={"authorId": GraphQLArgument(GraphQLInt)},
                resolve=resolve_posts,
            ),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Test query with variables
    query = """
        query GetUsersAndPosts($minAge: Int!, $authorId: Int!) {
            users(minAge: $minAge) {
                id
                name
                age
            }
            posts(authorId: $authorId) {
                id
                title
            }
        }
    """

    variables = {"minAge": 25, "authorId": 1}

    context = {}

    # Execute multi-field query
    result = await execute_multi_field_query(schema, query, variables, context)

    # Parse result
    result_json = json.loads(bytes(result))

    # Verify structure
    assert "data" in result_json
    assert "users" in result_json["data"]
    assert "posts" in result_json["data"]

    # Verify users filtered by minAge >= 25
    users = result_json["data"]["users"]
    assert len(users) == 2  # Alice (25) and Bob (30), not Charlie (20)
    assert users[0]["name"] == "Alice"
    assert users[0]["age"] == 25
    assert users[1]["name"] == "Bob"
    assert users[1]["age"] == 30

    # Verify posts filtered by authorId == 1
    posts = result_json["data"]["posts"]
    assert len(posts) == 2  # Post 101 and 103 by author 1
    assert posts[0]["id"] == 101
    assert posts[1]["id"] == 103


@pytest.mark.asyncio
async def test_multi_field_query_with_optional_variables(init_schema_registry_fixture):
    """Test multi-field query with optional variables (some fields use them, some don't)."""
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
        },
    )

    async def resolve_users(info):
        # Uses variable
        limit = 10  # default
        if info.field_nodes and info.field_nodes[0].arguments:
            for arg in info.field_nodes[0].arguments:
                if arg.name.value == "limit":
                    if hasattr(arg.value, "name"):
                        var_name = arg.value.name.value
                        limit = info.variable_values.get(var_name, limit)
                    else:
                        limit = arg.value.value

        users = [{"id": i, "name": f"User{i}"} for i in range(1, 11)]
        return users[:limit]

    async def resolve_posts(info):
        # No variables - returns all posts
        return [
            {"id": 101, "title": "Post 1"},
            {"id": 102, "title": "Post 2"},
        ]

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
                resolve=resolve_posts,
            ),
        },
    )

    schema = GraphQLSchema(query=query_type)

    query = """
        query GetData($userLimit: Int) {
            users(limit: $userLimit) {
                id
                name
            }
            posts {
                id
                title
            }
        }
    """

    variables = {"userLimit": 3}
    context = {}

    result = await execute_multi_field_query(schema, query, variables, context)
    result_json = json.loads(bytes(result))

    # Verify users limited to 3
    assert len(result_json["data"]["users"]) == 3

    # Verify posts returns all (not affected by variables)
    assert len(result_json["data"]["posts"]) == 2


@pytest.mark.asyncio
async def test_multi_field_query_with_no_variables(init_schema_registry_fixture):
    """Test multi-field query with no variables at all."""
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

    async def resolve_users(info):
        return [{"id": 1, "name": "Alice"}]

    async def resolve_posts(info):
        return [{"id": 101, "title": "Post 1"}]

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
            users { id name }
            posts { id title }
        }
    """

    # No variables
    variables = None
    context = {}

    result = await execute_multi_field_query(schema, query, variables, context)
    result_json = json.loads(bytes(result))

    assert "data" in result_json
    assert len(result_json["data"]["users"]) == 1
    assert len(result_json["data"]["posts"]) == 1


@pytest.fixture(scope="module", autouse=True)
def init_schema_registry_fixture():
    """Initialize schema registry for multi-field variable tests."""
    import fraiseql._fraiseql_rs as fraiseql_rs

    # Reset the schema registry
    fraiseql_rs.reset_schema_registry_for_testing()

    # Schema IR with types for testing
    schema_ir = {
        "version": "1.0",
        "features": ["type_resolution"],
        "types": {
            "User": {
                "fields": {
                    "id": {"type_name": "Int", "is_nested_object": False, "is_list": False},
                    "name": {"type_name": "String", "is_nested_object": False, "is_list": False},
                    "age": {"type_name": "Int", "is_nested_object": False, "is_list": False},
                }
            },
            "Post": {
                "fields": {
                    "id": {"type_name": "Int", "is_nested_object": False, "is_list": False},
                    "title": {"type_name": "String", "is_nested_object": False, "is_list": False},
                    "author_id": {
                        "type_name": "Int",
                        "is_nested_object": False,
                        "is_list": False,
                    },
                }
            },
        },
    }

    fraiseql_rs.initialize_schema_registry(json.dumps(schema_ir))

    yield

    fraiseql_rs.reset_schema_registry_for_testing()
