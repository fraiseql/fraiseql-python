"""Test the @query and @field decorators."""

from uuid import UUID

import pytest
from graphql import graphql

import fraiseql
from fraiseql.gql.schema_builder import SchemaRegistry, build_fraiseql_schema
from fraiseql.types import ID


# Define types
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


# Use @query decorator
@fraiseql.query
async def getUser(info, id: ID) -> User | None:
    """Get a user by ID."""
    # IDScalar parses the id to uuid.UUID, so compare as string
    if str(id) == "123e4567-e89b-12d3-a456-426614174000":
        return User(
            id=id if isinstance(id, UUID) else UUID(id), name="John Doe", email="john@example.com"
        )
    return None


@fraiseql.query
async def get_all_users(info) -> list[User]:
    """Get all users."""
    return [
        User(
            id=UUID("123e4567-e89b-12d3-a456-426614174000"),
            name="John Doe",
            email="john@example.com",
        ),
        User(
            id=UUID("223e4567-e89b-12d3-a456-426614174001"),
            name="Jane Smith",
            email="jane@example.com",
        ),
    ]


# Use @field decorator with QueryRoot
@fraiseql.type
class QueryRoot:
    """Root query type with field decorators."""

    @fraiseql.field(description="API version")
    def version(self, root, info) -> str:
        """Get API version."""
        return "2.0.0"

    @fraiseql.field
    async def post_count(self, root, info) -> int:
        """Get total number of posts."""
        # In real app, would query database
        return 42


@pytest.fixture(autouse=True)
def clear_registry() -> None:
    """Clear the registry before each test."""
    registry = SchemaRegistry.get_instance()
    registry.clear()

    # Re-register the queries after clearing
    # This is needed because decorators run at import time
    registry.register_query(getUser)
    registry.register_query(get_all_users)  # This function is still snake_case
    registry.register_type(QueryRoot)

    yield
    registry.clear()


def test_query_decorator_registration() -> None:
    """Test that @query decorator registers functions."""
    # Functions should already be registered via decorator
    SchemaRegistry.get_instance()

    # Build schema without passing queries
    schema = build_fraiseql_schema(query_types=[QueryRoot])  # Only need to pass types

    # Check that decorated queries are in the schema
    query_fields = schema.query_type.fields
    assert "getUser" in query_fields
    assert "getAllUsers" in query_fields
    assert "version" in query_fields  # From QueryRoot
    assert "postCount" in query_fields  # From QueryRoot


@pytest.mark.asyncio
async def test_query_decorator_execution() -> None:
    """Test that decorated queries can be executed."""
    # Since queries are registered via decorator, we need to include them in build_fraiseql_schema
    registry = SchemaRegistry.get_instance()
    schema = registry.build_schema()

    # Test get_user query
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
async def test_field_decorator_execution() -> None:
    """Test that @field decorated methods work."""
    registry = SchemaRegistry.get_instance()
    schema = registry.build_schema()

    query = """
        query {
            version
            postCount
        }
    """
    result = await graphql(schema, query, context_value={})

    assert result.errors is None
    assert result.data == {"version": "2.0.0", "postCount": 42}


def test_query_decorator_with_empty_parentheses() -> None:
    """Test that @query(): with parentheses works."""

    @fraiseql.query()
    async def getPosts(info) -> list[Post]:
        return [
            Post(
                id=UUID("323e4567-e89b-12d3-a456-426614174002"),
                title="Hello World",
                content="Test content",
            )
        ]

    schema = build_fraiseql_schema()

    query_fields = schema.query_type.fields
    assert "getPosts" in query_fields


def test_mixed_decorators_and_explicit_queries() -> None:
    """Test mixing @query decorator with explicit query list."""

    # Define a non-decorated query
    async def getPost(info, id: ID) -> Post | None:
        # IDScalar parses the id to uuid.UUID, so compare as string
        if str(id) == "323e4567-e89b-12d3-a456-426614174002":
            return Post(
                id=id if isinstance(id, UUID) else UUID(id),
                title="Test Post",
                content="Test content",
            )
        return None

    # Build schema with both decorated and explicit queries
    schema = build_fraiseql_schema(query_types=[QueryRoot, getPost])  # Mix types and functions

    query_fields = schema.query_type.fields
    # Should have all queries
    assert "getUser" in query_fields  # From @query decorator
    assert "getAllUsers" in query_fields  # From @query decorator
    assert "getPost" in query_fields  # From explicit list
    assert "version" in query_fields  # From QueryRoot @field
    assert "postCount" in query_fields  # From QueryRoot @field


def test_no_queries_error() -> None:
    """Test that schema building fails without any queries."""
    # Clear all registered queries and types
    registry = SchemaRegistry.get_instance()
    registry.clear()  # Clear everything

    with pytest.raises(TypeError, match="Type Query must define one or more fields"):
        registry.build_schema()
