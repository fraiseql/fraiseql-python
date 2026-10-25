"""End-to-end tests for default schema configuration."""

import pytest

from fraiseql import fraise_input, fraise_type, mutation, query
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.gql.builders.registry import SchemaRegistry

pytestmark = pytest.mark.integration


@pytest.fixture
def clean_registry() -> None:
    """Clean the schema registry before and after each test."""
    # Clear before test
    from fraiseql.gql.builders.registry import SchemaRegistry
    from fraiseql.mutations.decorators import clear_mutation_registries

    registry = SchemaRegistry.get_instance()
    registry.clear()
    clear_mutation_registries()

    yield

    # Clear after test
    registry.clear()
    clear_mutation_registries()


@fraise_input
class E2EInput:
    """Test input type."""

    name: str
    value: int


@fraise_type
class E2ESuccess:
    """Test success type."""

    message: str
    result: str


@fraise_type
class E2EError:
    """Test error type."""

    code: str
    message: str


# Dummy query to satisfy GraphQL schema requirements
@query
async def health_check(info) -> str:
    """Health check query."""
    return "OK"


@pytest.mark.asyncio
class TestDefaultSchemaE2E:
    """End-to-end tests for default schema configuration."""

    async def test_app_with_custom_default_mutation_schema(self, clean_registry) -> None:
        """Test that creating an app with custom default schema works."""
        # Create config with custom default schema
        config = FraiseQLConfig(
            database_url="postgresql://test@localhost/test",
            default_mutation_schema="custom_app",
        )

        # Set config in registry BEFORE creating mutations
        from fraiseql.fastapi.dependencies import set_fraiseql_config

        set_fraiseql_config(config)

        # Create mutations without specifying schema
        @mutation(function="test_mutation")
        class TestMutation:
            input: E2EInput
            success: E2ESuccess
            error: E2EError

        create_fraiseql_app(
            config=config,
            mutations=[TestMutation],
            queries=[health_check],
            types=[E2ESuccess, E2EError],
        )

        # Verify the mutation uses the custom default schema
        assert TestMutation.__fraiseql_mutation__.schema == "custom_app"

    @pytest.mark.asyncio
    async def test_multiple_apps_with_different_defaults(self, clean_registry) -> None:
        """Test that multiple apps can have different default schemas."""
        # Create first app with one default
        config1 = FraiseQLConfig(
            database_url="postgresql://test@localhost/test", default_mutation_schema="app1"
        )

        # Set config in registry BEFORE creating mutations
        from fraiseql.fastapi.dependencies import set_fraiseql_config

        set_fraiseql_config(config1)

        @mutation(function="mutation1")
        class Mutation1:
            input: E2EInput
            success: E2ESuccess
            error: E2EError

        create_fraiseql_app(
            config=config1,
            mutations=[Mutation1],
            queries=[health_check],
            types=[E2ESuccess, E2EError],
        )

        # Verify first mutation uses app1 schema
        assert Mutation1.__fraiseql_mutation__.schema == "app1"

        # Clean registry for second app
        from fraiseql.mutations.decorators import clear_mutation_registries

        registry = SchemaRegistry.get_instance()
        registry.clear()
        clear_mutation_registries()

        # Create second app with different default
        config2 = FraiseQLConfig(
            database_url="postgresql://test@localhost/test", default_mutation_schema="app2"
        )

        # Set new config
        set_fraiseql_config(config2)

        @mutation(function="mutation2")
        class Mutation2:
            input: E2EInput
            success: E2ESuccess
            error: E2EError

        create_fraiseql_app(
            config=config2,
            mutations=[Mutation2],
            queries=[health_check],
            types=[E2ESuccess, E2EError],
        )

        # Verify second mutation uses app2 schema
        assert Mutation2.__fraiseql_mutation__.schema == "app2"

    @pytest.mark.asyncio
    async def test_override_still_works_with_defaults(self, clean_registry) -> None:
        """Test that explicit schema override still works when defaults are set."""
        # Create app with default schema
        config = FraiseQLConfig(
            database_url="postgresql://test@localhost/test",
            default_mutation_schema="default_schema",
        )

        # Set config in registry BEFORE creating mutations
        from fraiseql.fastapi.dependencies import set_fraiseql_config

        set_fraiseql_config(config)

        # Mutation with explicit schema override
        @mutation(function="override_mutation", schema="explicit_schema")
        class OverrideMutation3:
            input: E2EInput
            success: E2ESuccess
            error: E2EError

        # Mutation using default
        @mutation(function="default_mutation")
        class DefaultMutation3:
            input: E2EInput
            success: E2ESuccess
            error: E2EError

        # Verify schemas
        assert OverrideMutation3.__fraiseql_mutation__.schema == "explicit_schema"
        assert DefaultMutation3.__fraiseql_mutation__.schema == "default_schema"
