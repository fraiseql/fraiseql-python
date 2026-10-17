"""Test to reproduce the first query returning null issue."""

import uuid
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from graphql import GraphQLResolveInfo

from fraiseql import query
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import fraise_type

# The test builds a schema from the global SchemaRegistry, which other tests in the
# same process leave types in; start it from an empty registry.
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clear_registry")]

# Define the User type


@pytest.mark.unit
@fraise_type
class User:
    id: uuid.UUID
    name: str
    email: str


# Mock users data
MOCK_USERS = {
    uuid.UUID("11111111-1111-1111-1111-111111111111"): {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "name": "Alice",
        "email": "alice@example.com",
        "tenant_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
    },
    uuid.UUID("33333333-3333-3333-3333-333333333333"): {
        "id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "name": "Bob",
        "email": "bob@example.com",
        "tenant_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
    },
}


# Define query resolver
@query
async def user(info: GraphQLResolveInfo, id: uuid.UUID) -> Optional[User]:
    """Get a user by ID."""
    # Convert to UUID if string
    if isinstance(id, str):
        id = uuid.UUID(id)

    # Mock database lookup
    user_data = MOCK_USERS.get(id)

    if user_data:
        return User(id=user_data["id"], name=user_data["name"], email=user_data["email"])
    return None


@query
async def users(info: GraphQLResolveInfo, limit: int = 10) -> list[User]:
    """Get list of users."""
    # Return mock users
    result = []
    for user_data in list(MOCK_USERS.values())[:limit]:
        result.append(User(id=user_data["id"], name=user_data["name"], email=user_data["email"]))

    return result


def test_first_query_returns_null_simple() -> None:
    """Test that demonstrates the first query returning null issue using simple mocked queries."""
    # Create the app without database
    app = create_fraiseql_app(
        database_url="postgresql://test/test",  # Dummy URL since we're mocking
        types=[User],
        queries=[user, users],  # Include the query resolvers
        production=False,
    )

    # Use TestClient for simpler testing
    with TestClient(app) as client:
        # Query 1: Get user by ID (FIRST QUERY - might return null)
        query1 = {
            "query": """
                query GetUser {
                    user(id: "11111111-1111-1111-1111-111111111111") {
                        id
                        name
                        email
                    }
                }
            """
        }

        response1 = client.post("/graphql", json=query1)
        result1 = response1.json()

        # Query 2: Same query again (should work)

        response2 = client.post("/graphql", json=query1)
        result2 = response2.json()

        # Query 3: List query
        query3 = {
            "query": """
                query GetUsers {
                    users(limit: 5) {
                        id
                        name
                        email
                    }
                }
            """
        }

        response3 = client.post("/graphql", json=query3)
        result3 = response3.json()

        # Assertions
        first_query_user = result1.get("data", {}).get("user")
        second_query_user = result2.get("data", {}).get("user")
        result3.get("data", {}).get("users", [])

        # The bug: first query returns null, second query works
        if first_query_user is None and second_query_user is not None:
            # Make test fail to highlight the issue
            pytest.fail(
                "First query returned null while second query worked - initialization bug confirmed"
            )
        elif first_query_user is not None:
            pass
            # This would mean the bug is fixed or not present
        else:
            pytest.fail("Both queries returned null - this is a different issue")
