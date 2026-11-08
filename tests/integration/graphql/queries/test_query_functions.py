"""Test query functions registration and schema building."""

from uuid import UUID

import pytest
from graphql import graphql

import fraiseql
from fraiseql.gql.schema_builder import SchemaRegistry, build_fraiseql_schema
from fraiseql.types import ID

pytestmark = pytest.mark.integration


# Sample types
@fraiseql.type
class User:
    id: UUID
    name: str
    email: str


@fraiseql.type
class Post:
    id: UUID
    title: str
    content: str
    author_id: UUID


# Sample query functions (like in the blog example)
async def get_user(info, id: ID) -> User | None:
    """Get a user by ID."""
    # Mock implementation
    # IDScalar parses the id to uuid.UUID, so compare as string
    if str(id) == "123e4567-e89b-12d3-a456-426614174000":
        return User(
            id=id if isinstance(id, UUID) else UUID(id), name="John Doe", email="john@example.com"
        )
    return None


async def get_post(info, id: ID) -> Post | None:
    """Get a post by ID."""
    # Mock implementation
    # IDScalar parses the id to uuid.UUID, so compare as string
    if str(id) == "123e4567-e89b-12d3-a456-426614174001":
        return Post(
            id=id if isinstance(id, UUID) else UUID(id),
            title="Hello World",
            content="This is a test post",
            author_id=UUID("123e4567-e89b-12d3-a456-426614174000"),
        )
    return None


async def get_posts(info, limit: int = 10) -> list[Post]:
    """Get a list of posts."""
    # Mock implementation
    return [
        Post(
            id=UUID("123e4567-e89b-12d3-a456-426614174001"),
            title="Hello World",
            content="This is a test post",
            author_id=UUID("123e4567-e89b-12d3-a456-426614174000"),
        )
    ]


# Debug: Check type hints
def test_debug_type_hints() -> None:
    """Debug type hints for get_posts."""
    import typing

    typing.get_type_hints(get_posts)


@pytest.fixture(autouse=True)
def clear_registry() -> None:
    """Clear the registry before each test."""
    registry = SchemaRegistry.get_instance()
    registry.clear()
    yield
    registry.clear()


def test_query_functions_registration() -> None:
    """Test that query functions can be registered and schema built."""
    # Build schema with query functions
    schema = build_fraiseql_schema(query_types=[get_user, get_post, get_posts])

    # Verify schema has Query type
    assert schema.query_type is not None
    assert schema.query_type.name == "Query"

    # Verify query fields exist
    query_fields = schema.query_type.fields
    assert "getUser" in query_fields
    assert "getPost" in query_fields
    assert "getPosts" in query_fields

    # Verify field types
    # Handle both nullable and non-nullable types
    user_type = query_fields["getUser"].type
    if hasattr(user_type, "of_type"):
        assert user_type.of_type.name == "User"
    else:
        assert user_type.name == "User"

    post_type = query_fields["getPost"].type
    if hasattr(post_type, "of_type"):
        assert post_type.of_type.name == "Post"
    else:
        assert post_type.name == "Post"

    # List type for get_posts
    from graphql import GraphQLList

    posts_type = query_fields["getPosts"].type
    # The type should be a GraphQLList
    assert isinstance(posts_type, GraphQLList)
    assert posts_type.of_type.name == "Post"

    # Verify arguments
    assert "id" in query_fields["getUser"].args
    assert "id" in query_fields["getPost"].args
    assert "limit" in query_fields["getPosts"].args


@pytest.mark.asyncio
async def test_query_execution() -> None:
    """Test that query functions can be executed."""
    # Build schema with query functions
    schema = build_fraiseql_schema(query_types=[get_user, get_post, get_posts])

    # Execute a query
    query = """
        query GetUser($id: ID!) {
            getUser(id: $id) {
                id
                name
                email
            }
        }
    """
    result = await graphql(
        schema,
        query,
        variable_values={"id": "123e4567-e89b-12d3-a456-426614174000"},
        context_value={},
    )

    assert result.errors is None
    assert result.data == {
        "getUser": {
            "id": "123e4567-e89b-12d3-a456-426614174000",
            "name": "John Doe",
            "email": "john@example.com",
        }
    }


@pytest.mark.asyncio
async def test_mixed_queries_and_types() -> None:
    """Test that both query functions and QueryRoot types can be used together."""

    # Define a QueryRoot type for legacy support
    @fraiseql.type
    class QueryRoot:
        version: str = "1.0.0"

        def resolve_version(self, root, info) -> str:
            return self.version

    # Build schema with both query functions and QueryRoot
    schema = build_fraiseql_schema(query_types=[QueryRoot, get_user, get_posts])

    # Verify all fields exist
    query_fields = schema.query_type.fields
    assert "version" in query_fields  # From QueryRoot
    assert "getUser" in query_fields  # From function
    assert "getPosts" in query_fields  # From function

    # Execute a query for version
    query = """
        query {
            version
            getPosts(limit: 1) {
                title
            }
        }
    """
    result = await graphql(schema, query, context_value={})

    assert result.errors is None
    assert result.data == {"version": "1.0.0", "getPosts": [{"title": "Hello World"}]}
