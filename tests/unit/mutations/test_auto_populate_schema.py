"""Test that auto-populated fields appear in GraphQL schema."""

from fraiseql.mutations.decorators import error, success
from fraiseql.types import fraise_type


@fraise_type
class Machine:
    id: str
    name: str


def test_success_decorator_adds_fields_to_gql_fields():
    """Auto-populated fields should be in __gql_fields__ for schema generation."""

    @success
    class CreateMachineSuccess:
        machine: Machine

    gql_fields = getattr(CreateMachineSuccess, "__gql_fields__", {})

    # All auto-populated fields must be present
    assert "machine" in gql_fields, "Original field should be present"
    assert "status" in gql_fields, "Auto-injected status missing"
    assert "message" in gql_fields, "Auto-injected message missing"
    assert "errors" not in gql_fields, "Success types should NOT have errors field (v1.8.1)"
    assert "updated_fields" in gql_fields, "Auto-injected updatedFields missing"
    assert "id" in gql_fields, "Auto-injected id missing (entity detected)"

    # Verify field types
    assert gql_fields["status"].field_type is str
    assert gql_fields["message"].field_type == str | None


def test_failure_decorator_adds_fields():
    """Failure types should also get auto-populated fields."""

    @error
    class CreateMachineError:
        error_code: str

    gql_fields = getattr(CreateMachineError, "__gql_fields__", {})

    assert "status" in gql_fields
    assert "message" in gql_fields
    assert "errors" in gql_fields
    assert "code" in gql_fields  # Auto-injected in v1.8.1
    assert "updated_fields" not in gql_fields  # Errors don't update entities (v1.8.1)
    assert "id" not in gql_fields  # Errors don't create entities (v1.8.1)

    # Verify field types
    assert gql_fields["code"].field_type is int  # Error code is integer


def test_no_entity_field_no_id():
    """ID should not be added when no entity field present."""

    @success
    class DeleteSuccess:
        """Deletion confirmation without entity."""

    gql_fields = getattr(DeleteSuccess, "__gql_fields__", {})

    # Standard fields should be present
    assert "status" in gql_fields
    assert "message" in gql_fields
    assert "errors" not in gql_fields  # Success types don't have errors (v1.8.1)
    assert "updated_fields" in gql_fields

    # But NOT id (no entity field detected)
    assert "id" not in gql_fields


def test_user_defined_fields_not_overridden():
    """User's explicit field definitions should be preserved."""

    @success
    class CreateMachineSuccess:
        machine: Machine
        status: str = "custom_success"

    gql_fields = getattr(CreateMachineSuccess, "__gql_fields__", {})

    # User-defined status should be preserved
    assert "status" in gql_fields
    # But auto-injected fields should still be added
    assert "message" in gql_fields
    assert "errors" not in gql_fields  # Success types don't have errors (v1.8.1)
    assert "updated_fields" in gql_fields  # Auto-injected for success types
    assert "id" in gql_fields  # Auto-injected when entity field present
