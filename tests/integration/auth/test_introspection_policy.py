import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clear_registry")]

"""Test the redesigned introspection policy system.

This module tests the new enum-based introspection policy that replaces
the old boolean-based system for cleaner configuration.
"""

from typing import Optional

from fastapi.testclient import TestClient
from graphql import GraphQLResolveInfo

from fraiseql import query
from fraiseql.auth.base import AuthProvider, UserContext
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app


@pytest.mark.security
@query
async def simple_test_query(info: GraphQLResolveInfo) -> str:
    """Simple test query for introspection tests."""
    return "test data"


class TestAuthProvider(AuthProvider):
    """Test auth provider with known tokens for introspection tests."""

    async def validate_token(self, token: str) -> dict:
        if token == "valid-token":
            return {"sub": "user-123", "email": "test@example.com"}
        raise Exception("Invalid token")

    async def get_user_from_token(self, token: str) -> Optional[UserContext]:
        if token == "valid-token":
            return UserContext(user_id="user-123", email="test@example.com")
        return None


class TestIntrospectionPolicyEnum:
    """Test the IntrospectionPolicy enum and its integration."""

    def test_introspection_policy_enum_exists(self) -> None:
        """RED: IntrospectionPolicy enum should exist with correct values."""
        from fraiseql.fastapi.config import IntrospectionPolicy

        # Test enum values
        assert IntrospectionPolicy.DISABLED == "disabled"
        assert IntrospectionPolicy.PUBLIC == "public"
        assert IntrospectionPolicy.AUTHENTICATED == "authenticated"

    def test_config_has_introspection_policy_field(self) -> None:
        """RED: FraiseQLConfig should have introspection_policy field."""
        from fraiseql.fastapi.config import IntrospectionPolicy

        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            introspection_policy=IntrospectionPolicy.AUTHENTICATED,
        )

        assert hasattr(config, "introspection_policy")
        assert config.introspection_policy == IntrospectionPolicy.AUTHENTICATED

    def test_introspection_policy_default_public(self) -> None:
        """RED: introspection_policy should default to PUBLIC for backward compatibility."""
        from fraiseql.fastapi.config import IntrospectionPolicy

        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
        )

        assert config.introspection_policy == IntrospectionPolicy.PUBLIC

    def test_introspection_policy_string_values(self) -> None:
        """RED: IntrospectionPolicy should accept string values."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            introspection_policy="authenticated",
        )

        assert config.introspection_policy == "authenticated"

    def test_introspection_policy_environment_variable(self) -> None:
        """RED: introspection_policy should be configurable via environment variable."""
        import os

        # Set environment variable
        os.environ["FRAISEQL_INTROSPECTION_POLICY"] = "disabled"

        try:
            config = FraiseQLConfig(
                database_url="postgresql://test:test@localhost/test",
            )
            assert config.introspection_policy == "disabled"
        finally:
            # Clean up environment variable
            if "FRAISEQL_INTROSPECTION_POLICY" in os.environ:
                del os.environ["FRAISEQL_INTROSPECTION_POLICY"]

    def test_introspection_policy_production_default(self) -> None:
        """RED: introspection_policy should default to DISABLED in production."""
        from fraiseql.fastapi.config import IntrospectionPolicy

        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="production",
        )

        assert config.introspection_policy == IntrospectionPolicy.DISABLED


class TestIntrospectionPolicyBehavior:
    """Test the actual behavior of different introspection policies."""

    def test_disabled_policy_blocks_all_introspection(self) -> None:
        """RED: DISABLED policy should block introspection for everyone."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            introspection_policy="disabled",
        )

        app = create_fraiseql_app(
            config=config,
            queries=[simple_test_query],
            production=True,
        )

        with TestClient(app) as client:
            response = client.post(
                "/graphql", json={"query": "{ __schema { queryType { name } } }"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "errors" in data
            assert any(
                "introspection" in error.get("message", "").lower() for error in data["errors"]
            )

    def test_public_policy_allows_all_introspection(self) -> None:
        """RED: PUBLIC policy should allow introspection for everyone."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            introspection_policy="public",
        )

        app = create_fraiseql_app(
            config=config,
            queries=[simple_test_query],
            production=False,
        )

        with TestClient(app) as client:
            response = client.post(
                "/graphql", json={"query": "{ __schema { queryType { name } } }"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "errors" not in data
            assert "data" in data
            assert data["data"]["__schema"]["queryType"]["name"] == "Query"

    def test_authenticated_policy_blocks_unauthenticated_users(self) -> None:
        """RED: AUTHENTICATED policy should block introspection for unauthenticated users."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            introspection_policy="authenticated",
        )

        app = create_fraiseql_app(
            config=config,
            queries=[simple_test_query],
            production=False,
        )

        with TestClient(app) as client:
            # No authentication headers
            response = client.post(
                "/graphql", json={"query": "{ __schema { queryType { name } } }"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "errors" in data
            assert any(
                "authentication" in error.get("message", "").lower()
                or "introspection" in error.get("message", "").lower()
                for error in data["errors"]
            )

    def test_authenticated_policy_allows_authenticated_users(self) -> None:
        """RED: AUTHENTICATED policy should allow introspection for authenticated users."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            introspection_policy="authenticated",
            auth_enabled=True,
        )

        app = create_fraiseql_app(
            config=config,
            queries=[simple_test_query],
            auth=TestAuthProvider(),
            production=False,
        )

        with TestClient(app) as client:
            # Mock authentication - this should work when user is authenticated
            response = client.post(
                "/graphql",
                json={"query": "{ __schema { queryType { name } } }"},
                headers={"Authorization": "Bearer valid-token"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "errors" not in data, f"Unexpected errors: {data.get('errors', [])}"
            assert "data" in data
            assert data["data"]["__schema"]["queryType"]["name"] == "Query"

    def test_authenticated_policy_with_invalid_token_blocks_introspection(self) -> None:
        """RED: AUTHENTICATED policy should block introspection for users with invalid tokens."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            introspection_policy="authenticated",
            auth_enabled=True,
        )

        app = create_fraiseql_app(
            config=config,
            queries=[simple_test_query],
            auth=TestAuthProvider(),
            production=False,
        )

        with TestClient(app) as client:
            # Invalid token should be blocked
            response = client.post(
                "/graphql",
                json={"query": "{ __schema { queryType { name } } }"},
                headers={"Authorization": "Bearer invalid-token"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "errors" in data
            assert any(
                "authentication" in error.get("message", "").lower()
                or "introspection" in error.get("message", "").lower()
                for error in data["errors"]
            )

    def test_regular_queries_work_with_all_policies(self) -> None:
        """Regular queries should work regardless of introspection policy."""
        for policy in ["disabled", "public", "authenticated"]:
            config = FraiseQLConfig(
                database_url="postgresql://test:test@localhost/test",
                introspection_policy=policy,
            )

            app = create_fraiseql_app(
                config=config,
                queries=[simple_test_query],
                production=False,
            )

            with TestClient(app) as client:
                response = client.post("/graphql", json={"query": "{ simpleTestQuery }"})

                assert response.status_code == 200, f"Failed for policy: {policy}"
                data = response.json()
                assert "errors" not in data, f"Errors for policy: {policy}: {data}"
                assert "data" in data
                assert data["data"]["simpleTestQuery"] == "test data"
