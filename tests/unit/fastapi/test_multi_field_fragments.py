"""Tests for fragment spreads and inline fragments in multi-field GraphQL queries.

Tests that fragment spreads (...FragmentName) and inline fragments (... on Type)
are properly expanded at the root level of multi-field queries.
"""

import json
from typing import Any

import pytest
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    OperationDefinitionNode,
)

from fraiseql.core.ast_parser import extract_field_paths_from_info
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


# ---------------------------------------------------------------------------
# Issue #554: resolvers that read info.fragments, as db.find() does
# ---------------------------------------------------------------------------


def _product_schema(seen: dict[str, Any]) -> GraphQLSchema:
    """Build a schema whose list resolvers read their selection the way db.find() does.

    Each resolver records the field paths extract_field_paths_from_info() returns, which
    raises "Fragment 'X' not found" when info.fragments lacks a spread fragment.
    """
    supplier_type = GraphQLObjectType(
        "Supplier",
        {"id": GraphQLField(GraphQLInt), "name": GraphQLField(GraphQLString)},
    )
    product_type = GraphQLObjectType(
        "Product",
        {
            "id": GraphQLField(GraphQLInt),
            "name": GraphQLField(GraphQLString),
            "price": GraphQLField(GraphQLInt),
            "supplier": GraphQLField(supplier_type),
        },
    )
    rows = [
        {"id": 1, "name": "Widget", "price": 10, "supplier": {"id": 7, "name": "Acme"}},
        {"id": 2, "name": "Gadget", "price": 20, "supplier": {"id": 7, "name": "Acme"}},
    ]

    def list_resolver(key: str):
        async def resolve(root, info, limit=None):
            paths = extract_field_paths_from_info(info)
            seen[key] = sorted(".".join(p.path) for p in paths or [])
            return rows[:limit]

        return resolve

    async def resolve_count(root, info):
        return len(rows)

    query_type = GraphQLObjectType(
        "Query",
        {
            "products": GraphQLField(
                GraphQLList(product_type),
                args={"limit": GraphQLArgument(GraphQLInt)},
                resolve=list_resolver("products"),
            ),
            "featuredProducts": GraphQLField(
                GraphQLList(product_type), resolve=list_resolver("featuredProducts")
            ),
            "productsCount": GraphQLField(GraphQLInt, resolve=resolve_count),
        },
    )
    return GraphQLSchema(query=query_type)


async def _run(query: str, seen: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    result = await execute_multi_field_query(_product_schema(seen), query, None, {}, **kwargs)
    return json.loads(bytes(result))


@pytest.mark.asyncio
async def test_issue_554_fragment_spread_with_scalar_sibling(init_schema_registry_fixture):
    """The reporter's query: a named spread in a list root, next to a count root."""
    seen: dict[str, Any] = {}
    body = await _run(
        """
        query { products(limit: 2) { ...ProductFields } productsCount }
        fragment ProductFields on Product { id name }
        """,
        seen,
    )

    assert "errors" not in body, body
    assert seen["products"] == ["id", "name"]
    assert [p["name"] for p in body["data"]["products"]] == ["Widget", "Gadget"]
    assert body["data"]["productsCount"] == 2


@pytest.mark.asyncio
async def test_issue_554_nested_fragment_spread(init_schema_registry_fixture):
    """A fragment that spreads another fragment."""
    seen: dict[str, Any] = {}
    body = await _run(
        """
        query { products { ...ProductFields } productsCount }
        fragment ProductFields on Product { id ...ProductPrice }
        fragment ProductPrice on Product { price }
        """,
        seen,
    )

    assert "errors" not in body, body
    assert seen["products"] == ["id", "price"]
    assert [p["price"] for p in body["data"]["products"]] == [10, 20]


@pytest.mark.asyncio
async def test_issue_554_fragment_spread_in_sub_object(init_schema_registry_fixture):
    """A spread inside a nested object selection."""
    seen: dict[str, Any] = {}
    body = await _run(
        """
        query { products { id supplier { ...SupplierFields } } productsCount }
        fragment SupplierFields on Supplier { id name }
        """,
        seen,
    )

    assert "errors" not in body, body
    assert seen["products"] == ["id", "supplier.id", "supplier.name"]
    assert body["data"]["products"][0]["supplier"]["name"] == "Acme"


@pytest.mark.asyncio
async def test_issue_554_fragment_shared_by_both_roots(init_schema_registry_fixture):
    """The same fragment spread in two root fields."""
    seen: dict[str, Any] = {}
    body = await _run(
        """
        query { products { ...ProductFields } featuredProducts { ...ProductFields } }
        fragment ProductFields on Product { id name }
        """,
        seen,
    )

    assert "errors" not in body, body
    assert seen == {"products": ["id", "name"], "featuredProducts": ["id", "name"]}
    assert len(body["data"]["featuredProducts"]) == 2


# ---------------------------------------------------------------------------
# Issue #554 follow-up: the rest of the resolve info the multi-field path builds
# ---------------------------------------------------------------------------


def _info_capturing_schema(captured: dict[str, Any]) -> GraphQLSchema:
    async def resolve_a(root, info):
        captured["a"] = info
        return 1

    async def resolve_b(root, info):
        captured["b"] = info
        return 2

    query_type = GraphQLObjectType(
        "Query",
        {
            "a": GraphQLField(GraphQLInt, resolve=resolve_a),
            "b": GraphQLField(GraphQLInt, resolve=resolve_b),
        },
    )
    return GraphQLSchema(query=query_type)


@pytest.mark.asyncio
async def test_info_carries_operation_and_path(init_schema_registry_fixture):
    """info.operation is the executed operation; info.path is a graphql-core Path."""
    captured: dict[str, Any] = {}
    result = await execute_multi_field_query(
        _info_capturing_schema(captured), "query Pair { a aliasB: b }", None, {}
    )

    assert json.loads(bytes(result))["data"] == {"a": 1, "aliasB": 2}
    for info in captured.values():
        assert isinstance(info.operation, OperationDefinitionNode)
        assert info.operation.name.value == "Pair"
    assert captured["a"].path.as_list() == ["a"]
    assert captured["b"].path.as_list() == ["aliasB"]
    assert captured["b"].path.typename == "Query"


@pytest.mark.asyncio
async def test_operation_name_selects_operation(init_schema_registry_fixture):
    """With several operations in one document, operationName picks the one to run."""
    captured: dict[str, Any] = {}
    query = """
        query First($skipB: Boolean = true) { a b @skip(if: $skipB) }
        query Second($skipB: Boolean = false) { a b @skip(if: $skipB) }
    """
    result = await execute_multi_field_query(
        _info_capturing_schema(captured), query, None, {}, operation_name="Second"
    )

    assert json.loads(bytes(result))["data"] == {"a": 1, "b": 2}
    assert captured["a"].operation.name.value == "Second"
    assert captured["a"].variable_values == {"skipB": False}
