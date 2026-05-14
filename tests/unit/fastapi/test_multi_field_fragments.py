"""Tests for fragment spreads and inline fragments in multi-field GraphQL queries.

Tests that fragment spreads (...FragmentName) and inline fragments (... on Type)
are properly expanded at the root level of multi-field queries.
"""

import json

import pytest

from fraiseql.fastapi.routers import execute_multi_field_query


@pytest.mark.asyncio
async def test_fragment_spread_at_root(init_schema_registry_fixture):
    """Test that named fragment spreads are expanded at root level."""
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

    post_type = GraphQLObjectType(
        "Post",
        lambda: {
            "id": GraphQLField(GraphQLInt),
            "title": GraphQLField(GraphQLString),
        },
    )

    async def resolve_users(root, info):
        return [{"id": 1, "name": "Alice"}]

    async def resolve_posts(root, info):
        return [{"id": 101, "title": "Post 1"}]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type), resolve=resolve_users),
            "posts": GraphQLField(GraphQLList(post_type), resolve=resolve_posts),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Query with fragment spread
    query = """
        fragment UserData on Query {
            users { id name }
        }

        query {
            ...UserData
            posts { id title }
        }
    """

    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    # Both fields should be present
    assert "users" in result_json["data"]
    assert "posts" in result_json["data"]

    assert len(result_json["data"]["users"]) == 1
    assert len(result_json["data"]["posts"]) == 1


@pytest.mark.asyncio
async def test_inline_fragment_at_root(init_schema_registry_fixture):
    """Test that inline fragments work at root level."""
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
        return [{"id": 1, "name": "Alice"}]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type), resolve=resolve_users),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Query with inline fragment
    query = """
        query {
            ... on Query {
                users { id name }
            }
        }
    """

    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    assert "users" in result_json["data"]
    assert len(result_json["data"]["users"]) == 1


@pytest.mark.asyncio
async def test_fragment_with_directive(init_schema_registry_fixture):
    """Test that directives work on fragment spreads."""
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

    async def resolve_posts(root, info):
        return [{"id": 101}]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type), resolve=resolve_users),
            "posts": GraphQLField(GraphQLList(user_type), resolve=resolve_posts),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Fragment spread with @skip directive
    query = """
        fragment UserData on Query {
            users { id }
        }

        query {
            ...UserData @skip(if: true)
            posts { id }
        }
    """

    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    # users should be skipped, only posts
    assert "users" not in result_json["data"]
    assert "posts" in result_json["data"]


@pytest.mark.asyncio
async def test_nested_fragment_spread(init_schema_registry_fixture):
    """Test that fragment spreads work within nested selections."""
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
            "email": GraphQLField(GraphQLString),
        },
    )

    async def resolve_users(root, info):
        return [{"id": 1, "name": "Alice", "email": "alice@example.com"}]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type), resolve=resolve_users),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Query with nested fragment spread
    query = """
        fragment UserFields on User {
            id
            name
        }

        query {
            users {
                ...UserFields
                email
            }
        }
    """

    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    # users should be present with all fields from fragment + additional field
    assert "users" in result_json["data"]
    assert len(result_json["data"]["users"]) == 1

    user = result_json["data"]["users"][0]
    assert "id" in user
    assert "name" in user
    assert "email" in user  # Additional field not in fragment
    assert user["id"] == 1
    assert user["name"] == "Alice"
    assert user["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_deeply_nested_fragments(init_schema_registry_fixture):
    """Test fragment spreads at multiple nesting levels."""
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
            "website": GraphQLField(GraphQLString),
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
        return [{"id": 1, "name": "Alice", "profile": {"bio": "Developer", "website": "alice.dev"}}]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type), resolve=resolve_users),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Query with deeply nested fragment
    query = """
        fragment ProfileFields on Profile {
            bio
        }

        query {
            users {
                id
                name
                profile {
                    ...ProfileFields
                    website
                }
            }
        }
    """

    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    assert "users" in result_json["data"]
    user = result_json["data"]["users"][0]
    assert user["id"] == 1
    assert user["name"] == "Alice"
    assert "profile" in user

    profile = user["profile"]
    assert "bio" in profile  # From fragment
    assert "website" in profile  # Additional field
    assert profile["bio"] == "Developer"
    assert profile["website"] == "alice.dev"


@pytest.mark.asyncio
async def test_nested_fragment_with_alias(init_schema_registry_fixture):
    """Test that fragment spreads work correctly with field aliases in nested selections."""
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
            "email": GraphQLField(GraphQLString),
        },
    )

    async def resolve_users(root, info):
        return [{"id": 1, "name": "Alice", "email": "alice@example.com"}]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type), resolve=resolve_users),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Query with alias and nested fragment
    query = """
        fragment UserFields on User {
            id
            name
        }

        query {
            allUsers: users {
                ...UserFields
                contactEmail: email
            }
        }
    """

    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    # Check that alias works and fragment fields are included
    assert "allUsers" in result_json["data"]
    user = result_json["data"]["allUsers"][0]
    assert "id" in user  # From fragment
    assert "name" in user  # From fragment
    assert "contactEmail" in user  # Aliased field
    assert user["contactEmail"] == "alice@example.com"


@pytest.mark.asyncio
async def test_fragment_cycle_detection(init_schema_registry_fixture):
    """Test that circular fragment references are detected and rejected."""
    from graphql import GraphQLField, GraphQLList, GraphQLObjectType, GraphQLSchema, GraphQLString

    user_type = GraphQLObjectType(
        "User",
        lambda: {
            "id": GraphQLField(GraphQLString),
        },
    )

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type)),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Query with circular fragment references
    query = """
        fragment A on User {
            id
            ...B
        }

        fragment B on User {
            ...A
        }

        query {
            users {
                ...A
            }
        }
    """

    # Should raise ValueError due to circular reference
    with pytest.raises(ValueError, match="Circular fragment reference"):
        await execute_multi_field_query(schema, query, None, {})


@pytest.mark.asyncio
async def test_fragment_self_reference_cycle(init_schema_registry_fixture):
    """Test that self-referencing fragments are detected."""
    from graphql import GraphQLField, GraphQLList, GraphQLObjectType, GraphQLSchema, GraphQLString

    user_type = GraphQLObjectType(
        "User",
        lambda: {
            "id": GraphQLField(GraphQLString),
        },
    )

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type)),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Query with self-referencing fragment
    query = """
        fragment SelfRef on User {
            id
            ...SelfRef
        }

        query {
            users {
                ...SelfRef
            }
        }
    """

    # Should raise ValueError due to self-reference
    with pytest.raises(ValueError, match="Circular fragment reference"):
        await execute_multi_field_query(schema, query, None, {})


@pytest.mark.asyncio
async def test_deep_fragment_cycle(init_schema_registry_fixture):
    """Test cycle detection in deeply nested fragment chains."""
    from graphql import GraphQLField, GraphQLList, GraphQLObjectType, GraphQLSchema, GraphQLString

    user_type = GraphQLObjectType(
        "User",
        lambda: {
            "id": GraphQLField(GraphQLString),
        },
    )

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type)),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Query with A -> B -> C -> A cycle
    query = """
        fragment A on User {
            id
            ...B
        }

        fragment B on User {
            ...C
        }

        fragment C on User {
            ...A
        }

        query {
            users {
                ...A
            }
        }
    """

    # Should raise ValueError due to circular reference
    with pytest.raises(ValueError, match="Circular fragment reference"):
        await execute_multi_field_query(schema, query, None, {})


@pytest.mark.asyncio
async def test_valid_fragment_no_cycle(init_schema_registry_fixture):
    """Test that valid fragments without cycles work correctly."""
    from graphql import GraphQLField, GraphQLList, GraphQLObjectType, GraphQLSchema, GraphQLString

    user_type = GraphQLObjectType(
        "User",
        lambda: {
            "id": GraphQLField(GraphQLString),
            "name": GraphQLField(GraphQLString),
            "email": GraphQLField(GraphQLString),
        },
    )

    async def resolve_users(root, info):
        return [{"id": "1", "name": "Alice", "email": "alice@example.com"}]

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "users": GraphQLField(GraphQLList(user_type), resolve=resolve_users),
        },
    )

    schema = GraphQLSchema(query=query_type)

    # Valid query with fragments that don't cycle
    query = """
        fragment UserBasic on User {
            id
            name
        }

        fragment UserContact on User {
            email
        }

        query {
            users {
                ...UserBasic
                ...UserContact
            }
        }
    """

    result = await execute_multi_field_query(schema, query, None, {})
    result_json = json.loads(bytes(result))

    # Should work without errors
    assert "users" in result_json["data"]
    assert len(result_json["data"]["users"]) == 1
    user = result_json["data"]["users"][0]
    assert "id" in user
    assert "name" in user
    assert "email" in user


@pytest.fixture
def init_schema_registry_fixture():
    """Initialize schema registry for fragment tests."""
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
