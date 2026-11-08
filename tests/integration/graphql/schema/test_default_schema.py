"""Tests for default schema configuration in FraiseQLConfig."""

import pytest

from fraiseql import mutation
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.schema_builder import SchemaRegistry
from fraiseql.mutations.mutation_decorator import MutationDefinition

pytestmark = pytest.mark.integration


@pytest.fixture
def reset_registry() -> None:
    """Reset the schema registry before each test."""
    registry = SchemaRegistry.get_instance()
    registry.queries.clear()
    registry.mutations.clear()
    registry.config = None
    yield
    registry.queries.clear()
    registry.mutations.clear()
    registry.config = None


class TestDefaultSchemaConfig:
    """Test default schema configuration in FraiseQLConfig."""

    def test_config_has_default_schema_fields(self) -> None:
        """Test that FraiseQLConfig includes default schema fields."""
        config = FraiseQLConfig(database_url="postgresql://test@localhost/test")

        # These fields should exist with default values
        assert hasattr(config, "default_mutation_schema")
        assert hasattr(config, "default_query_schema")
        assert config.default_mutation_schema == "public"
        assert config.default_query_schema == "public"

    def test_config_allows_custom_default_schemas(self) -> None:
        """Test that custom default schemas can be set (default_query_schema does nothing)."""
        with pytest.warns(DeprecationWarning, match="default_query_schema has no effect"):
            config = FraiseQLConfig(
                database_url="postgresql://test@localhost/test",
                default_mutation_schema="app",
                default_query_schema="queries",
            )

        assert config.default_mutation_schema == "app"
        assert config.default_query_schema == "queries"


class TestMutationDefaultSchema:
    """Test that mutations use default schema when not specified."""

    def test_mutation_uses_default_schema_when_not_specified(self, reset_registry) -> None:
        """Test that mutations use default_mutation_schema when schema is not provided."""
        # Set up config with default schema
        config = FraiseQLConfig(
            database_url="postgresql://test@localhost/test", default_mutation_schema="app"
        )
        registry = SchemaRegistry.get_instance()
        registry.config = config

        # Create a mutation without specifying schema
        @mutation(function="create_user")
        class CreateUser:
            input: dict
            success: dict
            error: dict

        # Check that the mutation uses the default schema
        definition = CreateUser.__fraiseql_mutation__
        assert isinstance(definition, MutationDefinition)
        assert definition.schema == "app"

    def test_mutation_explicit_schema_overrides_default(self, reset_registry) -> None:
        """Test that explicit schema parameter overrides default."""
        # Set up config with default schema
        config = FraiseQLConfig(
            database_url="postgresql://test@localhost/test", default_mutation_schema="app"
        )
        registry = SchemaRegistry.get_instance()
        registry.config = config

        # Create a mutation with explicit schema
        @mutation(function="create_user", schema="custom")
        class CreateUser:
            input: dict
            success: dict
            error: dict

        # Check that the mutation uses the explicit schema
        definition = CreateUser.__fraiseql_mutation__
        assert isinstance(definition, MutationDefinition)
        assert definition.schema == "custom"

    def test_mutation_fallback_when_no_config(self, reset_registry) -> None:
        """Test that mutations fall back to 'public' when no config is set."""
        registry = SchemaRegistry.get_instance()
        registry.config = None

        # Create a mutation without specifying schema and no config
        @mutation(function="create_user")
        class CreateUser:
            input: dict
            success: dict
            error: dict

        # Check that the mutation uses the fallback schema
        definition = CreateUser.__fraiseql_mutation__
        assert isinstance(definition, MutationDefinition)
        assert definition.schema == "public"


class TestBackwardCompatibility:
    """Test backward compatibility with existing code."""

    def test_existing_mutations_still_work(self, reset_registry) -> None:
        """Test that existing mutations with explicit schema still work."""

        # This should work exactly as before
        @mutation(function="create_user", schema="app")
        class CreateUser:
            input: dict
            success: dict
            error: dict

        definition = CreateUser.__fraiseql_mutation__
        assert isinstance(definition, MutationDefinition)
        assert definition.schema == "app"

    def test_default_behavior_unchanged_when_no_default_set(self, reset_registry) -> None:
        """Test that behavior uses public schema when no custom default is set."""
        config = FraiseQLConfig(database_url="postgresql://test@localhost/test")
        registry = SchemaRegistry.get_instance()
        registry.config = config

        # Create mutation without schema - should use config's default_mutation_schema
        @mutation(function="create_user")
        class CreateUser:
            input: dict
            success: dict
            error: dict

        definition = CreateUser.__fraiseql_mutation__
        # Should use the default_mutation_schema from config, which is "public"
        assert definition.schema == "public"
