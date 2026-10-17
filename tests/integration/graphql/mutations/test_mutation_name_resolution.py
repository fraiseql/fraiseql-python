"""Tests for mutation name collision fix.

This test verifies that mutations with similar names (like create_item and create_item_component)
don't interfere with each other's parameter validation.

Addresses the bug report where createItemComponent was incorrectly requiring
item_serial_number (from CreateItemInput) instead of its own input fields.
"""

import uuid
from typing import Optional

import pytest

import fraiseql
from fraiseql.gql.builders.registry import SchemaRegistry

pytestmark = pytest.mark.integration


# Define input types that highlight the issue
@fraiseql.input
class CreateItemInput:
    """Input for creating an item - has item_serial_number field."""

    item_serial_number: str
    description: Optional[str] = None


@fraiseql.input
class CreateItemComponentInput:
    """Input for creating an item component - has item_id field, NOT item_serial_number."""

    item_id: uuid.UUID
    component_type: str
    description: Optional[str] = None


# Define success types
@fraiseql.success
class CreateItemSuccess:
    message: str
    item_id: uuid.UUID


@fraiseql.success
class CreateItemComponentSuccess:
    message: str
    component_id: uuid.UUID


# Define failure types
@fraiseql.error
class CreateItemError:
    message: str
    code: str


@fraiseql.error
class CreateItemComponentError:
    message: str
    code: str


# The problematic mutations that caused the collision
@fraiseql.mutation(function="create_item")
class CreateItem:
    """Create a new item."""

    input: CreateItemInput
    success: CreateItemSuccess
    error: CreateItemError


@fraiseql.mutation(function="create_item_component")
class CreateItemComponent:
    """Create a new item component."""

    input: CreateItemComponentInput
    success: CreateItemComponentSuccess
    error: CreateItemComponentError


class TestMutationNameResolution:
    """Test the fix for mutation name collisions."""

    def test_resolver_names_use_function_names(self) -> None:
        """Test that resolver names are based on the PostgreSQL function name."""
        create_item_resolver = CreateItem.__fraiseql_resolver__
        create_item_component_resolver = CreateItemComponent.__fraiseql_resolver__

        # Resolver names should be the function names, not derived from class names
        assert create_item_resolver.__name__ == "create_item"
        assert create_item_component_resolver.__name__ == "create_item_component"

        # They should be different
        assert create_item_resolver.__name__ != create_item_component_resolver.__name__

    def test_input_types_are_correctly_assigned(self) -> None:
        """Test that each resolver has the correct input type annotation."""
        create_item_resolver = CreateItem.__fraiseql_resolver__
        create_item_component_resolver = CreateItemComponent.__fraiseql_resolver__

        # Each should have its own specific input type
        assert create_item_resolver.__annotations__["input"] is CreateItemInput
        assert create_item_component_resolver.__annotations__["input"] is CreateItemComponentInput

        # They should be different input types
        assert (
            create_item_resolver.__annotations__["input"]
            != create_item_component_resolver.__annotations__["input"]
        )

    def test_mutations_are_separately_registered(self) -> None:
        """Test that both mutations are registered with unique keys in the registry."""
        # Clear the registry to start fresh
        registry = SchemaRegistry.get_instance()
        registry.clear()

        # Register our mutations
        registry.register_mutation(CreateItem)
        registry.register_mutation(CreateItemComponent)

        # Both should be registered under their function names
        assert "create_item" in registry.mutations
        assert "create_item_component" in registry.mutations

        # They should be different resolver objects
        create_item_fn = registry.mutations["create_item"]
        create_item_component_fn = registry.mutations["create_item_component"]

        assert create_item_fn is not create_item_component_fn

        # Each should have the correct input type
        assert create_item_fn.__annotations__["input"] is CreateItemInput
        assert create_item_component_fn.__annotations__["input"] is CreateItemComponentInput

    def test_mutation_definitions_are_independent(self) -> None:
        """Test that each mutation class has its own independent definition object."""
        create_item_def = CreateItem.__fraiseql_mutation__
        create_item_component_def = CreateItemComponent.__fraiseql_mutation__

        # They should be separate definition objects
        assert create_item_def is not create_item_component_def

        # Each should have the correct configuration
        assert create_item_def.input_type is CreateItemInput
        assert create_item_component_def.input_type is CreateItemComponentInput

        assert create_item_def.function_name == "create_item"
        assert create_item_component_def.function_name == "create_item_component"

        assert create_item_def.name == "CreateItem"
        assert create_item_component_def.name == "CreateItemComponent"

    def test_input_field_requirements_are_different(self) -> None:
        """Test that the input types have different field requirements."""
        # CreateItemInput should require item_serial_number
        create_item_hints = CreateItemInput.__annotations__
        assert "item_serial_number" in create_item_hints
        assert "item_id" not in create_item_hints

        # CreateItemComponentInput should require item_id and component_type, NOT item_serial_number
        create_item_component_hints = CreateItemComponentInput.__annotations__
        assert "item_id" in create_item_component_hints
        assert "component_type" in create_item_component_hints
        assert "item_serial_number" not in create_item_component_hints

    def test_no_shared_annotation_objects(self) -> None:
        """Test that resolver annotations are not shared between mutations."""
        create_item_resolver = CreateItem.__fraiseql_resolver__
        create_item_component_resolver = CreateItemComponent.__fraiseql_resolver__

        # The annotations dict objects should be different instances
        assert (
            create_item_resolver.__annotations__
            is not create_item_component_resolver.__annotations__
        )

        # Even though they have the same keys, they should have different values
        assert (
            create_item_resolver.__annotations__["input"]
            != create_item_component_resolver.__annotations__["input"]
        )

    @pytest.mark.parametrize(
        ("mutation_class", "expected_resolver_name", "expected_input_type"),
        [
            (CreateItem, "create_item", CreateItemInput),
            (CreateItemComponent, "create_item_component", CreateItemComponentInput),
        ],
    )
    def test_each_mutation_has_correct_metadata(
        self, mutation_class, expected_resolver_name, expected_input_type
    ):
        """Test that each mutation has the correct metadata individually."""
        resolver = mutation_class.__fraiseql_resolver__
        definition = mutation_class.__fraiseql_mutation__

        assert resolver.__name__ == expected_resolver_name
        assert resolver.__annotations__["input"] is expected_input_type
        assert definition.input_type is expected_input_type
        assert definition.function_name == expected_resolver_name
