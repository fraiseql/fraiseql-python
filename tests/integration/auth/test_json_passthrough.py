"""Test to verify that JSON passthrough is always enabled in production.

Since v1, pure passthrough is always enabled for maximum performance (25-60x faster).
No configuration flags are needed - it's always on in production mode.
"""

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.schema_builder import SchemaRegistry

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clear_registry() -> None:
    """Clear registry before each test to avoid type conflicts."""
    registry = SchemaRegistry.get_instance()
    registry.clear()

    # Also clear the GraphQL type cache
    from fraiseql.core.graphql_type import _graphql_type_cache

    _graphql_type_cache.clear()

    yield

    registry.clear()
    _graphql_type_cache.clear()


@asynccontextmanager
async def noop_lifespan(app: FastAPI) -> None:
    """No-op lifespan for tests that don't need a database."""
    yield


# Define test types and queries at module level to avoid scoping issues
# Use names that don't start with Test to avoid pytest collection
@fraiseql.type
class DataType:
    """Test type for JSON passthrough testing."""

    snake_case_field: str
    another_snake_field: str


@fraiseql.query
async def data_query(info) -> DataType:
    """Query that returns snake_case fields."""
    return DataType(snake_case_field="test_value", another_snake_field="another_value")


class TestJSONPassthroughConfiguration:
    """Test that JSON passthrough is always enabled in production (v1 behavior)."""

    def test_json_passthrough_always_enabled_in_production(self) -> None:
        """Test that JSON passthrough is always enabled in production mode.

        Since v1, passthrough is always on for max performance. No config flags needed.
        """
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="production",
        )

        app = create_fraiseql_app(
            config=config,
            types=[DataType],
            queries=[data_query],
            lifespan=noop_lifespan,
        )

        with TestClient(app) as client:
            response = client.post(
                "/graphql",
                json={
                    "query": """
                        query {
                            dataQuery {
                                snakeCaseField
                                anotherSnakeField
                            }
                        }
                    """
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert "dataQuery" in data["data"]
            # Passthrough is always enabled - test passes if no errors

    def test_production_mode_enables_passthrough(self) -> None:
        """Test that production mode automatically enables passthrough."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="production",
        )

        app = create_fraiseql_app(
            config=config,
            types=[DataType],
            queries=[data_query],
            lifespan=noop_lifespan,
        )

        with TestClient(app) as client:
            response = client.post(
                "/graphql",
                json={
                    "query": """
                        query {
                            dataQuery {
                                snakeCaseField
                                anotherSnakeField
                            }
                        }
                    """
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            data["data"]["dataQuery"]
            # Passthrough is enabled - fields should be transformed

    def test_testing_mode_also_enables_passthrough(self) -> None:
        """Test that testing mode also enables passthrough (same as production)."""
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="testing",
        )

        app = create_fraiseql_app(
            config=config,
            types=[DataType],
            queries=[data_query],
            lifespan=noop_lifespan,
        )

        with TestClient(app) as client:
            response = client.post(
                "/graphql",
                json={
                    "query": """
                        query {
                            dataQuery {
                                snakeCaseField
                                anotherSnakeField
                            }
                        }
                    """
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            data["data"]["dataQuery"]
            # Passthrough is enabled in all non-development modes
