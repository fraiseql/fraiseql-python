import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clear_registry")]

"""Test schema introspection security enforcement.

This module tests that GraphQL schema introspection is properly controlled
based on environment and configuration settings.
"""

from fastapi.testclient import TestClient
from graphql import GraphQLResolveInfo

from fraiseql import query
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

# Define query outside of any test function to avoid pytest confusion


@pytest.mark.security
@query
async def simple_test_query(info: GraphQLResolveInfo) -> str:
    """Simple test query for introspection tests."""
    return "test data"


class TestSchemaIntrospectionSecurity:
    """Test that schema introspection is properly secured."""

    def test_current_introspection_behavior_in_development(self) -> None:
        """Document current introspection behavior in development - baseline for TDD."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="development",
            introspection_policy="public",
        )

        app = create_fraiseql_app(config=config, queries=[simple_test_query], production=False)

        with TestClient(app) as client:
            # Basic introspection query
            response = client.post(
                "/graphql", json={"query": "{ __schema { queryType { name } } }"}
            )

            # This should work in development
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert "__schema" in data["data"]
            assert data["data"]["__schema"]["queryType"]["name"] == "Query"

    def test_current_introspection_behavior_in_production(self) -> None:
        """Document current introspection behavior in production - baseline for TDD."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="production",
            # Note: enable_introspection should be False due to validator
        )

        app = create_fraiseql_app(config=config, queries=[simple_test_query], production=True)

        with TestClient(app) as client:
            # Basic introspection query
            client.post("/graphql", json={"query": "{ __schema { queryType { name } } }"})

            # This should be blocked in production, but currently isn't
            # This is the bug we need to fix

            # TODO: This should fail (return error), but currently passes
            # This demonstrates the security issue

    def test_introspection_disabled_in_production(self) -> None:
        """RED: Introspection should be blocked in production mode."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="production",
        )

        app = create_fraiseql_app(
            config=config,
            queries=[simple_test_query],
            production=True,
        )

        with TestClient(app) as client:
            # Introspection query should be blocked
            response = client.post(
                "/graphql", json={"query": "{ __schema { queryType { name } } }"}
            )

            # Should return an error, not the schema
            assert response.status_code == 200  # GraphQL always returns 200
            data = response.json()
            assert "errors" in data
            assert "data" not in data or data["data"] is None
            assert any(
                "introspection" in error.get("message", "").lower() for error in data["errors"]
            )

    def test_introspection_enabled_in_development(self) -> None:
        """RED: Introspection should work in development mode."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="development",
            introspection_policy="public",
        )

        app = create_fraiseql_app(
            config=config,
            queries=[simple_test_query],
            production=False,
        )

        with TestClient(app) as client:
            # Introspection query should work
            response = client.post(
                "/graphql", json={"query": "{ __schema { queryType { name } } }"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "errors" not in data
            assert "data" in data
            assert data["data"]["__schema"]["queryType"]["name"] == "Query"

    def test_introspection_configurable_override(self) -> None:
        """RED: Introspection should be configurable via explicit setting."""
        # Explicitly enable introspection in production (override default)
        from fraiseql.fastapi.config import IntrospectionPolicy

        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="production",
        )
        # Override the validator by setting it after creation
        config.introspection_policy = IntrospectionPolicy.PUBLIC

        app = create_fraiseql_app(
            config=config,
            queries=[simple_test_query],
            production=True,
        )

        with TestClient(app) as client:
            # Should work when explicitly enabled
            response = client.post(
                "/graphql", json={"query": "{ __schema { queryType { name } } }"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "errors" not in data
            assert "data" in data

    def test_introspection_type_queries_blocked(self) -> None:
        """RED: Type introspection queries should also be blocked in production."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="production",
        )

        app = create_fraiseql_app(
            config=config,
            queries=[simple_test_query],
            production=True,
        )

        with TestClient(app) as client:
            # Type introspection query
            response = client.post(
                "/graphql", json={"query": '{ __type(name: "Query") { name fields { name } } }'}
            )

            assert response.status_code == 200
            data = response.json()
            assert "errors" in data
            assert any(
                "introspection" in error.get("message", "").lower() for error in data["errors"]
            )

    def test_mixed_introspection_and_normal_query(self) -> None:
        """RED: Mixed queries with introspection should be blocked in production."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="production",
        )

        app = create_fraiseql_app(
            config=config,
            queries=[simple_test_query],
            production=True,
        )

        with TestClient(app) as client:
            # Query that mixes normal query with introspection
            response = client.post(
                "/graphql",
                json={
                    "query": """
                {
                    testQuery
                    __schema { queryType { name } }
                }
                """
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "errors" in data
            assert any(
                "introspection" in error.get("message", "").lower() for error in data["errors"]
            )

    def test_regular_queries_work_in_production(self) -> None:
        """Regular queries should still work in production when introspection is disabled."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="production",
        )

        app = create_fraiseql_app(
            config=config,
            queries=[simple_test_query],
            production=True,
        )

        with TestClient(app) as client:
            # Regular query should work
            response = client.post("/graphql", json={"query": "{ simpleTestQuery }"})

            assert response.status_code == 200
            data = response.json()
            assert "errors" not in data
            assert "data" in data
            assert data["data"]["simpleTestQuery"] == "test data"

    def test_introspection_error_message_is_clear(self) -> None:
        """Error message for blocked introspection should be clear and informative."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="production",
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
            assert len(data["errors"]) > 0

            error_message = data["errors"][0]["message"]

            # Should mention introspection is disabled/not allowed
            assert "introspection" in error_message.lower()
            assert "disabled" in error_message.lower() or "not allowed" in error_message.lower()
            # Should be informative but not overly technical
            expected_message = "GraphQL introspection has been disabled, but the requested query contained the field '__schema'."
            assert error_message == expected_message
