"""Unit tests for connection pool configuration in create_fraiseql_app.

Tests that connection pool parameters are correctly applied and that
environment-based defaults work as expected (WP-027).
"""

import uuid
from unittest.mock import patch

import pytest

from fraiseql import fraise_type, query
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

pytestmark = pytest.mark.unit


@pytest.fixture
def clean_registries():
    """Clean all registries before and after each test."""
    from fraiseql.gql.builders.registry import SchemaRegistry
    from fraiseql.mutations.decorators import clear_mutation_registries

    registry = SchemaRegistry.get_instance()
    registry.clear()
    clear_mutation_registries()

    yield

    # Clear after test
    registry.clear()
    clear_mutation_registries()


class TestConnectionPoolDefaults:
    """Tests for default connection pool parameter values."""

    def test_production_defaults_to_20_connections(self, clean_registries):
        """Test that production mode defaults to pool_size=20."""

        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        # Mock schema registry to avoid initialization
        with patch("fraiseql._fraiseql_rs.initialize_schema_registry"):
            create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[User],
                queries=[users],
                production=True,  # Production mode
            )

            # Check config was set correctly
            from fraiseql.fastapi.dependencies import get_fraiseql_config

            config = get_fraiseql_config()
            assert config.database_pool_size == 20, "Production should default to 20 connections"

    def test_development_defaults_to_10_connections(self, clean_registries):
        """Test that development mode defaults to pool_size=10."""

        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        with patch("fraiseql._fraiseql_rs.initialize_schema_registry"):
            create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[User],
                queries=[users],
                production=False,  # Development mode
            )

            from fraiseql.fastapi.dependencies import get_fraiseql_config

            config = get_fraiseql_config()
            assert config.database_pool_size == 10, "Development should default to 10 connections"


class TestConnectionPoolCustomParameters:
    """Tests for custom connection pool parameters."""

    def test_custom_pool_size(self, clean_registries):
        """Test that custom pool_size is applied."""

        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        with patch("fraiseql._fraiseql_rs.initialize_schema_registry"):
            create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[User],
                queries=[users],
                connection_pool_size=30,  # Custom size
            )

            from fraiseql.fastapi.dependencies import get_fraiseql_config

            config = get_fraiseql_config()
            assert config.database_pool_size == 30

    def test_custom_max_overflow(self, clean_registries):
        """Test that custom max_overflow is applied."""

        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        with patch("fraiseql._fraiseql_rs.initialize_schema_registry"):
            create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[User],
                queries=[users],
                connection_pool_max_overflow=20,  # Custom overflow
            )

            from fraiseql.fastapi.dependencies import get_fraiseql_config

            config = get_fraiseql_config()
            assert config.database_max_overflow == 20

    def test_custom_timeout(self, clean_registries):
        """Test that custom timeout is applied."""

        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        with patch("fraiseql._fraiseql_rs.initialize_schema_registry"):
            create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[User],
                queries=[users],
                connection_pool_timeout=60.0,  # Custom timeout
            )

            from fraiseql.fastapi.dependencies import get_fraiseql_config

            config = get_fraiseql_config()
            assert config.database_pool_timeout == 60

    def test_custom_recycle(self, clean_registries):
        """Test that custom recycle time is applied."""

        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        with patch("fraiseql._fraiseql_rs.initialize_schema_registry"):
            create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[User],
                queries=[users],
                connection_pool_recycle=7200,  # Custom recycle (2 hours)
            )

            from fraiseql.fastapi.dependencies import get_fraiseql_config

            config = get_fraiseql_config()
            assert config.database_pool_recycle == 7200

    def test_all_custom_parameters(self, clean_registries):
        """Test that all custom pool parameters can be set together."""

        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        with patch("fraiseql._fraiseql_rs.initialize_schema_registry"):
            create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[User],
                queries=[users],
                connection_pool_size=50,
                connection_pool_max_overflow=30,
                connection_pool_timeout=90.0,
                connection_pool_recycle=1800,
            )

            from fraiseql.fastapi.dependencies import get_fraiseql_config

            config = get_fraiseql_config()
            assert config.database_pool_size == 50
            assert config.database_max_overflow == 30
            assert config.database_pool_timeout == 90
            assert config.database_pool_recycle == 1800


class TestConnectionPoolWithConfig:
    """Tests for connection pool parameters when FraiseQLConfig is provided."""

    def test_parameters_override_config(self, clean_registries):
        """Test that explicit parameters override config values."""

        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        # Create config with initial values
        config = FraiseQLConfig(
            database_url="postgresql://test@localhost/test",
            database_pool_size=15,
            database_max_overflow=5,
        )

        with patch("fraiseql._fraiseql_rs.initialize_schema_registry"):
            create_fraiseql_app(
                types=[User],
                queries=[users],
                config=config,
                connection_pool_size=25,  # Override
                connection_pool_max_overflow=15,  # Override
            )

            # Config should be updated with overrides
            assert config.database_pool_size == 25
            assert config.database_max_overflow == 15


class TestBackwardCompatibility:
    """Tests for backward compatibility - ensure existing code still works."""

    def test_app_creation_without_pool_parameters(self, clean_registries):
        """Test that app can be created without any pool parameters."""

        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        with patch("fraiseql._fraiseql_rs.initialize_schema_registry"):
            # This should work exactly as before WP-027
            create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[User],
                queries=[users],
            )

            # Should use default values
            from fraiseql.fastapi.dependencies import get_fraiseql_config

            config = get_fraiseql_config()
            assert config.database_pool_size == 10  # Development default


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
