"""Integration tests for default schema configuration."""

import pytest

from fraiseql import fraise_input, fraise_type, mutation
from fraiseql.fastapi import FraiseQLConfig
from fraiseql.gql.builders.registry import SchemaRegistry
from fraiseql.mutations.mutation_decorator import MutationDefinition

pytestmark = pytest.mark.integration


@pytest.fixture
def clean_registry() -> None:
    """Clean the schema registry before and after each test."""
    registry = SchemaRegistry.get_instance()
    registry.clear()
    yield
    registry.clear()


@fraise_input
class CreateTestInput:
    """Test input type."""

    name: str
    value: int


@fraise_type
class SuccessType:
    """Test success type."""

    message: str
    id: str


@fraise_type
class ErrorType:
    """Test error type."""

    code: str
    message: str


class TestDefaultSchemaIntegration:
    """Integration tests for default schema configuration."""

    def test_mutation_with_custom_default_schema(self, clean_registry) -> None:
        """Test that mutations use custom default schema from config."""
        # Create config with custom default schema
        config = FraiseQLConfig(
            database_url="postgresql://test@localhost/test",
            default_mutation_schema="app",
        )

        # Set config in registry
        registry = SchemaRegistry.get_instance()
        registry.config = config

        # Create a mutation without specifying schema
        @mutation(function="create_test")
        class CreateTest:
            input: CreateTestInput
            success: SuccessType
            error: ErrorType

        # Verify the mutation uses the default schema
        definition = CreateTest.__fraiseql_mutation__
        assert isinstance(definition, MutationDefinition)
        assert definition.schema == "app"
        assert definition.function_name == "create_test"

    def test_multiple_mutations_with_different_schemas(self, clean_registry) -> None:
        """Test multiple mutations with different schema configurations."""
        # Set up config with default schema
        config = FraiseQLConfig(
            database_url="postgresql://test@localhost/test", default_mutation_schema="app"
        )
        registry = SchemaRegistry.get_instance()
        registry.config = config

        # Mutation using default schema
        @mutation(function="create_default")
        class CreateDefault:
            input: CreateTestInput
            success: SuccessType
            error: ErrorType

        # Mutation with explicit schema override
        @mutation(function="create_custom", schema="custom")
        class CreateCustom:
            input: CreateTestInput
            success: SuccessType
            error: ErrorType

        # Mutation with explicit public schema
        @mutation(function="create_public", schema="public")
        class CreatePublic:
            input: CreateTestInput
            success: SuccessType
            error: ErrorType

        # Verify each mutation uses the correct schema
        assert CreateDefault.__fraiseql_mutation__.schema == "app"
        assert CreateCustom.__fraiseql_mutation__.schema == "custom"
        assert CreatePublic.__fraiseql_mutation__.schema == "public"

    def test_schema_resolution_without_config(self, clean_registry) -> None:
        """Test schema resolution when no config is set."""
        # Ensure no config is set
        registry = SchemaRegistry.get_instance()
        registry.config = None

        # Create mutation without schema parameter
        @mutation(function="test_default")
        class TestDefault:
            input: CreateTestInput
            success: SuccessType
            error: ErrorType

        # Should fall back to "public"
        assert TestDefault.__fraiseql_mutation__.schema == "public"

    def test_changing_config_affects_new_mutations(self, clean_registry) -> None:
        """Test that changing config affects newly created mutations."""
        registry = SchemaRegistry.get_instance()

        # Create first mutation with no config
        registry.config = None

        @mutation(function="first_mutation")
        class FirstMutation:
            input: CreateTestInput
            success: SuccessType
            error: ErrorType

        assert FirstMutation.__fraiseql_mutation__.schema == "public"

        # Set config with custom default
        config = FraiseQLConfig(
            database_url="postgresql://test@localhost/test", default_mutation_schema="custom_schema"
        )
        registry.config = config

        # Create second mutation
        @mutation(function="second_mutation")
        class SecondMutation:
            input: CreateTestInput
            success: SuccessType
            error: ErrorType

        assert SecondMutation.__fraiseql_mutation__.schema == "custom_schema"

        # First mutation should still have its original schema
        assert FirstMutation.__fraiseql_mutation__.schema == "public"
