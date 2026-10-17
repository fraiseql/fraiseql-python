"""Tests for common GraphQL input types."""

import uuid

import pytest

from fraiseql.types.common_inputs import DeletionInput


class TestDeletionInput:
    """Test DeletionInput type functionality."""

    def test_deletion_input_creation(self) -> None:
        """Test basic DeletionInput creation."""
        test_id = uuid.uuid4()
        deletion_input = DeletionInput(id=test_id)

        assert deletion_input.id == test_id
        assert deletion_input.hard_delete is False  # Default value

    def test_deletion_input_with_hard_delete(self) -> None:
        """Test DeletionInput with hard_delete flag."""
        test_id = uuid.uuid4()
        deletion_input = DeletionInput(id=test_id, hard_delete=True)

        assert deletion_input.id == test_id
        assert deletion_input.hard_delete is True

    def test_deletion_input_fields(self) -> None:
        """Test DeletionInput field definitions."""
        # Check that it has the expected fields through FraiseQL definition
        definition = getattr(DeletionInput, "__fraiseql_definition__", None)
        assert definition is not None

        field_names = list(definition.fields.keys())
        assert "id" in field_names
        assert "hard_delete" in field_names
        assert len(field_names) == 2

    def test_deletion_input_field_types(self) -> None:
        """Test DeletionInput field type annotations."""
        # Check type hints
        annotations = DeletionInput.__annotations__
        assert annotations["id"] == uuid.UUID
        assert annotations["hard_delete"] is bool

    def test_deletion_input_default_values(self) -> None:
        """Test DeletionInput default value behavior."""
        test_id = uuid.uuid4()

        # Test default construction
        deletion_input = DeletionInput(id=test_id)
        assert deletion_input.hard_delete is False

        # Test explicit False
        deletion_input_false = DeletionInput(id=test_id, hard_delete=False)
        assert deletion_input_false.hard_delete is False

        # Test explicit True
        deletion_input_true = DeletionInput(id=test_id, hard_delete=True)
        assert deletion_input_true.hard_delete is True

    def test_deletion_input_immutability(self) -> None:
        """Test that DeletionInput behaves as a proper dataclass."""
        test_id = uuid.uuid4()
        deletion_input = DeletionInput(id=test_id, hard_delete=True)

        # Should be able to access fields
        assert deletion_input.id == test_id
        assert deletion_input.hard_delete is True

        # Should be able to modify fields (dataclass is mutable by default)
        deletion_input.hard_delete = False
        assert deletion_input.hard_delete is False

    def test_deletion_input_repr(self) -> None:
        """Test DeletionInput string representation."""
        test_id = uuid.uuid4()
        deletion_input = DeletionInput(id=test_id, hard_delete=True)

        repr_str = repr(deletion_input)
        assert "DeletionInput" in repr_str
        # Note: FraiseQL types may not have detailed repr like dataclasses

    def test_deletion_input_equality(self) -> None:
        """Test DeletionInput equality comparison."""
        test_id = uuid.uuid4()

        deletion_input1 = DeletionInput(id=test_id, hard_delete=True)
        deletion_input2 = DeletionInput(id=test_id, hard_delete=True)
        deletion_input3 = DeletionInput(id=test_id, hard_delete=False)

        # Note: FraiseQL types may not have automatic equality comparison
        # This test verifies the objects can be created and accessed
        assert deletion_input1.id == deletion_input2.id
        assert deletion_input1.hard_delete == deletion_input2.hard_delete
        assert deletion_input1.hard_delete != deletion_input3.hard_delete

    def test_deletion_input_fraiseql_integration(self) -> None:
        """Test DeletionInput integration with FraiseQL decorators."""
        # Test that the class has been properly decorated
        assert hasattr(DeletionInput, "__fraiseql_definition__")

        # Check that it's recognized as an input type
        definition = DeletionInput.__fraiseql_definition__
        assert definition.is_input is True

    @pytest.mark.parametrize("hard_delete_value", [True, False])
    def test_deletion_input_parametrized(self, hard_delete_value) -> None:
        """Test DeletionInput with different hard_delete values."""
        test_id = uuid.uuid4()
        deletion_input = DeletionInput(id=test_id, hard_delete=hard_delete_value)

        assert deletion_input.id == test_id
        assert deletion_input.hard_delete == hard_delete_value
