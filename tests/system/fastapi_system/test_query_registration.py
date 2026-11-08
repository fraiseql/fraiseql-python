"""Test query registration patterns in create_fraiseql_app."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.gql.schema_builder import SchemaRegistry
from fraiseql.types import ID

pytestmark = pytest.mark.integration

# Define test types


@pytest.mark.unit
@fraiseql.type
class User:
    id: UUID
    name: str
    email: str


@fraiseql.type
class Post:
    id: UUID
    title: str
    authorId: UUID


# Define queries using @query decorator
@fraiseql.query
async def getUser(info, id: ID) -> User:
    """Get user by ID."""
    # IDScalar parses the id to uuid.UUID, so use it directly or convert if string
    return User(
        id=id if isinstance(id, UUID) else UUID(id), name="Test User", email="test@example.com"
    )


@fraiseql.query
async def listUsers(info) -> list[User]:
    """List all users."""
    return [
        User(
            id=UUID("123e4567-e89b-12d3-a456-426614174000"),
            name="User 1",
            email="user1@example.com",
        ),
        User(
            id=UUID("223e4567-e89b-12d3-a456-426614174001"),
            name="User 2",
            email="user2@example.com",
        ),
    ]


# Define a query without decorator for explicit registration
async def getPost(info, id: ID) -> Post:
    """Get post by ID."""
    # IDScalar parses the id to uuid.UUID, so use it directly or convert if string
    return Post(
        id=id if isinstance(id, UUID) else UUID(id),
        title="Test Post",
        authorId=UUID("123e4567-e89b-12d3-a456-426614174000"),
    )


# Define queries using QueryRoot pattern with @field
@fraiseql.type
class QueryRoot:
    """Root query type."""

    @fraiseql.field
    def api_version(self, root, info) -> str:
        """Get API version."""
        return "1.0.0"

    @fraiseql.field
    async def postCount(self, root, info) -> int:
        """Get total post count."""
        return 42


@pytest.fixture(autouse=True)
def clear_registry() -> None:
    """Clear registry before each test."""
    registry = SchemaRegistry.get_instance()
    registry.clear()

    # Re-register the decorated queries after clearing
    # This simulates what happens at import time
    registry.register_query(getUser)
    registry.register_query(listUsers)
    registry.register_type(QueryRoot)

    yield
    registry.clear()


def test_query_decorator_auto_registration() -> None:
    """Test that @query decorated functions are automatically included."""
    # Create app without explicitly passing queries
    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[User, Post],  # Only pass types, not queries
    )

    with TestClient(app) as client:
        # Test decorated query is available
        response = client.post(
            "/graphql",
            json={
                "query": """
                    query GetUser($id: ID!) {
                        getUser(id: $id) {
                            id
                            name
                            email
                        }
                    }
                """,
                "variables": {"id": "123e4567-e89b-12d3-a456-426614174000"},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["getUser"]["name"] == "Test User"

        # Test list query
        response = client.post(
            "/graphql",
            json={
                "query": """
                    query {
                        listUsers {
                            id
                            name
                        }
                    }
                """
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]["listUsers"]) == 2


def test_explicit_query_registration() -> None:
    """Test explicit query registration still works."""
    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[User, Post],
        queries=[getPost],  # Explicitly pass non-decorated function
    )

    with TestClient(app) as client:
        # Test explicitly registered query
        response = client.post(
            "/graphql",
            json={
                "query": """
                    query GetPost($id: ID!) {
                        getPost(id: $id) {
                            id
                            title
                            authorId
                        }
                    }
                """,
                "variables": {"id": "323e4567-e89b-12d3-a456-426614174002"},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["getPost"]["title"] == "Test Post"

        # Decorated queries should also be available
        response = client.post("/graphql", json={"query": "{ listUsers { id } }"})

        assert response.status_code == 200
        assert "listUsers" in response.json()["data"]


def test_query_root_with_field_decorator() -> None:
    """Test QueryRoot pattern with @field decorator."""
    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[User, Post, QueryRoot],  # Pass QueryRoot as a type
    )

    with TestClient(app) as client:
        # Test @field decorated methods
        response = client.post(
            "/graphql",
            json={
                "query": """
                    query {
                        apiVersion
                        postCount
                    }
                """
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Debug print
        if "errors" in data:
            pass
        assert data["data"]["apiVersion"] == "1.0.0"
        assert data["data"]["postCount"] == 42

        # Auto-registered queries should also work
        response = client.post("/graphql", json={"query": "{ listUsers { name } }"})

        assert response.status_code == 200
        assert "listUsers" in response.json()["data"]


def test_mixed_registration_patterns() -> None:
    """Test mixing all registration patterns together."""
    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[User, Post, QueryRoot],  # QueryRoot with @field
        queries=[getPost],  # Explicit function
        # @query decorated functions are auto-registered
    )

    with TestClient(app) as client:
        # Test all query types are available
        response = client.post(
            "/graphql",
            json={
                "query": """
                    query {
                        __schema {
                            queryType {
                                fields {
                                    name
                                }
                            }
                        }
                    }
                """
            },
        )

        assert response.status_code == 200
        data = response.json()
        field_names = [f["name"] for f in data["data"]["__schema"]["queryType"]["fields"]]

        # Should have all queries
        assert "getUser" in field_names  # @query decorator
        assert "listUsers" in field_names  # @query decorator
        assert "getPost" in field_names  # Explicit registration
        assert "apiVersion" in field_names  # @field decorator
        assert "postCount" in field_names  # @field decorator


def test_empty_queries_uses_auto_registered() -> None:
    """Test that empty queries list still includes auto-registered queries."""
    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[User, Post],
        queries=[],  # Explicitly empty
    )

    with TestClient(app) as client:
        # Auto-registered queries should still work
        response = client.post("/graphql", json={"query": "{ listUsers { id name } }"})

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]["listUsers"]) == 2


def test_no_queries_parameter_uses_auto_registered() -> None:
    """Test that omitting queries parameter includes auto-registered queries."""
    # This is the pattern shown in the blog - it should just work
    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[User, Post],
        # No queries parameter at all
    )

    with TestClient(app) as client:
        # Should be able to query auto-registered functions
        response = client.post(
            "/graphql",
            json={
                "query": """
                    query {
                        getUser(id: "123e4567-e89b-12d3-a456-426614174000") {
                            name
                            email
                        }
                    }
                """
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["getUser"]["name"] == "Test User"
