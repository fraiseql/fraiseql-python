import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clear_registry")]

"""Test that authentication is properly enforced when configured."""

from typing import Optional

from fastapi.testclient import TestClient
from graphql import GraphQLResolveInfo

from fraiseql import fraise_type, query
from fraiseql.auth.base import AuthProvider, UserContext
from fraiseql.fastapi import create_fraiseql_app


@fraise_type
class UserInfo:
    """User information object for GraphQL."""

    id: Optional[str] = None
    email: Optional[str] = None
    authenticated: bool = False


@fraise_type
class ContextInfo:
    """Context information object for GraphQL."""

    has_user: bool = False
    authenticated: bool = False
    user_id: Optional[str] = None


@pytest.mark.security
class TestAuthProvider(AuthProvider):
    """Test auth provider with known tokens."""

    async def validate_token(self, token: str) -> dict:
        if token == "valid-token":
            return {"sub": "user-123", "email": "test@example.com"}
        raise ValueError("Invalid token")

    async def get_user_from_token(self, token: str) -> Optional[UserContext]:
        if token == "valid-token":
            return UserContext(user_id="user-123", email="test@example.com")
        return None


# Define test queries
@query
async def public_data(info: GraphQLResolveInfo) -> str:
    """Query that should be accessible without auth when auth is disabled."""
    return "Public information"


@query
async def sensitive_data(info: GraphQLResolveInfo) -> str:
    """Query that should require auth when auth is enabled."""
    return "Sensitive information"


@query
async def user_info(info: GraphQLResolveInfo) -> UserInfo:
    """Query that returns current user info."""
    user = info.context.get("user")
    if not user:
        return UserInfo(id=None, email=None, authenticated=False)
    return UserInfo(
        id=user.user_id if hasattr(user, "user_id") else user.get("id"),
        email=user.email if hasattr(user, "email") else user.get("email"),
        authenticated=True,
    )


class TestAuthenticationEnforcement:
    """Test that authentication is properly enforced."""

    def test_auth_disabled_allows_anonymous(self) -> None:
        """When auth is not configured, anonymous requests should succeed."""
        # When no auth provider is passed, auth is disabled
        app = create_fraiseql_app(
            database_url="sqlite:///:memory:",
            queries=[public_data, sensitive_data, user_info],
            production=False,
            # No auth parameter = auth disabled
        )

        with TestClient(app) as client:
            # Without auth header - should succeed
            response = client.post("/graphql", json={"query": "{ publicData }"})
            assert response.status_code == 200
            assert response.json()["data"]["publicData"] == "Public information"

            # Sensitive data also accessible without auth when auth is disabled
            response = client.post("/graphql", json={"query": "{ sensitiveData }"})
            assert response.status_code == 200
            assert response.json()["data"]["sensitiveData"] == "Sensitive information"

    def test_auth_enabled_blocks_anonymous(self) -> None:
        """When auth is configured, anonymous requests should be blocked."""
        # When auth provider is passed, auth is enabled
        app = create_fraiseql_app(
            database_url="sqlite:///:memory:",
            queries=[public_data, sensitive_data, user_info],
            auth=TestAuthProvider(),  # This enables auth
            production=True,
        )

        with TestClient(app) as client:
            # Without auth header - should be blocked
            response = client.post("/graphql", json={"query": "{ sensitiveData }"})
            assert response.status_code == 401
            assert "Authentication required" in response.json()["detail"]

            # Public data also requires auth when auth is enabled
            response = client.post("/graphql", json={"query": "{ publicData }"})
            assert response.status_code == 401

    def test_auth_enabled_accepts_valid_token(self) -> None:
        """When auth is configured, valid tokens should work."""
        app = create_fraiseql_app(
            database_url="sqlite:///:memory:",
            queries=[public_data, sensitive_data, user_info],
            auth=TestAuthProvider(),
            production=False,
        )

        with TestClient(app) as client:
            # With valid token - should succeed
            response = client.post(
                "/graphql",
                json={"query": "{ sensitiveData }"},
                headers={"Authorization": "Bearer valid-token"},
            )
            assert response.status_code == 200
            assert response.json()["data"]["sensitiveData"] == "Sensitive information"

            # User info should show authenticated user
            response = client.post(
                "/graphql",
                json={"query": "{ userInfo { id email authenticated } }"},
                headers={"Authorization": "Bearer valid-token"},
            )
            assert response.status_code == 200
            data = response.json()["data"]["userInfo"]
            assert data["id"] == "user-123"
            assert data["email"] == "test@example.com"
            assert data["authenticated"] is True

    def test_auth_enabled_rejects_invalid_token(self) -> None:
        """Invalid tokens should be rejected."""
        app = create_fraiseql_app(
            database_url="sqlite:///:memory:",
            queries=[sensitive_data],
            auth=TestAuthProvider(),
            production=False,
        )

        with TestClient(app) as client:
            # With invalid token - should fail
            response = client.post(
                "/graphql",
                json={"query": "{ sensitiveData }"},
                headers={"Authorization": "Bearer invalid-token"},
            )
            assert response.status_code == 401

    def test_introspection_allowed_in_dev_without_auth(self) -> None:
        """Introspection should be allowed in development even without auth."""
        app = create_fraiseql_app(
            database_url="sqlite:///:memory:",
            queries=[sensitive_data],
            auth=TestAuthProvider(),
            production=False,  # Development mode
        )

        with TestClient(app) as client:
            # Introspection query without auth - should work in dev
            response = client.post(
                "/graphql", json={"query": "{ __schema { queryType { name } } }"}
            )
            assert response.status_code == 200
            assert response.json()["data"]["__schema"]["queryType"]["name"] == "Query"

    def test_introspection_blocked_in_production_without_auth(self) -> None:
        """Introspection should be blocked in production without auth."""
        app = create_fraiseql_app(
            database_url="sqlite:///:memory:",
            queries=[sensitive_data],
            auth=TestAuthProvider(),
            production=True,  # Production mode
        )

        with TestClient(app) as client:
            # Introspection query without auth - should be blocked in production
            response = client.post(
                "/graphql", json={"query": "{ __schema { queryType { name } } }"}
            )
            assert response.status_code == 401
            assert "Authentication required" in response.json()["detail"]

    def test_auth_provider_passed_enables_auth(self) -> None:
        """Passing an auth provider should automatically enable authentication."""
        # Don't explicitly set auth_enabled, just pass auth provider
        app = create_fraiseql_app(
            database_url="sqlite:///:memory:",
            queries=[sensitive_data],
            auth=TestAuthProvider(),  # This should enable auth
            production=False,
        )

        with TestClient(app) as client:
            # Without auth - should be blocked
            response = client.post("/graphql", json={"query": "{ sensitiveData }"})
            assert response.status_code == 401

            # With valid auth - should work
            response = client.post(
                "/graphql",
                json={"query": "{ sensitiveData }"},
                headers={"Authorization": "Bearer valid-token"},
            )
            assert response.status_code == 200


class TestAuthContextPropagation:
    """Test that auth context is properly propagated."""

    def test_context_contains_user_when_authenticated(self) -> None:
        """Context should contain user info when authenticated."""

        @query
        async def context_check(info: GraphQLResolveInfo) -> ContextInfo:
            """Check what's in the context."""
            user = info.context.get("user")
            return ContextInfo(
                has_user="user" in info.context,
                authenticated=info.context.get("authenticated", False),
                user_id=getattr(user, "user_id", None) if user else None,
            )

        app = create_fraiseql_app(
            database_url="sqlite:///:memory:",
            queries=[context_check],
            auth=TestAuthProvider(),
            production=False,
        )

        with TestClient(app) as client:
            # With valid token
            response = client.post(
                "/graphql",
                json={"query": "{ contextCheck { hasUser authenticated userId } }"},
                headers={"Authorization": "Bearer valid-token"},
            )
            assert response.status_code == 200
            data = response.json()["data"]["contextCheck"]
            assert data["hasUser"] is True
            assert data["authenticated"] is True
            assert data["userId"] == "user-123"

    def test_context_shows_unauthenticated(self) -> None:
        """Context should show unauthenticated when auth is optional."""

        @query
        async def context_check(info: GraphQLResolveInfo) -> ContextInfo:
            """Check what's in the context."""
            return ContextInfo(
                has_user="user" in info.context,
                authenticated=info.context.get("authenticated", False),
                user_id=None,
            )

        # Create app without auth provider (auth optional)
        app = create_fraiseql_app(
            database_url="sqlite:///:memory:",
            queries=[context_check],
            production=False,
        )

        with TestClient(app) as client:
            # Without auth header
            response = client.post(
                "/graphql", json={"query": "{ contextCheck { hasUser authenticated userId } }"}
            )
            assert response.status_code == 200
            data = response.json()["data"]["contextCheck"]
            assert data["hasUser"] is True  # user is there but None
            assert data["authenticated"] is False
            assert data["userId"] is None
