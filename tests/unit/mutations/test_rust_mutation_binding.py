"""Test Rust mutation binding exists and works."""

import pytest

from tests.unit.mutations.selection_document import UNFILTERED

# Import Rust extension for tests
try:
    from fraiseql import _fraiseql_rs
except ImportError:
    _fraiseql_rs = None

requires_rust = pytest.mark.skipif(_fraiseql_rs is None, reason="Rust extension not available")


@requires_rust
def test_rust_binding_exists():
    """Test that build_mutation_response is exposed to Python."""
    assert hasattr(_fraiseql_rs, "build_mutation_response")


@requires_rust
def test_rust_binding_simple_format():
    """Test simple format (just entity JSONB) transformation."""
    import json

    # Simple format: just entity data, no status wrapper
    mutation_json = json.dumps({"id": "123", "first_name": "John", "email": "john@example.com"})

    response_bytes = _fraiseql_rs.build_mutation_response(
        mutation_json,
        "createUser",  # GraphQL field name
        "CreateUserSuccess",  # Success type name
        "CreateUserError",  # Error type name
        "user",  # entity_field_name
        "User",  # entity_type for __typename
        None,  # cascade_selections,
        entity_selections=UNFILTERED,
    )

    response = json.loads(response_bytes)
    assert response["data"]["createUser"]["__typename"] == "CreateUserSuccess"
    assert response["data"]["createUser"]["user"]["__typename"] == "User"
    assert response["data"]["createUser"]["user"]["firstName"] == "John"


@requires_rust
def test_rust_binding_v2_success():
    """Test v2 format (full mutation_result) transformation."""
    import json

    mutation_json = json.dumps(
        {
            "status": "created",
            "message": "User created",
            "entity_id": "123",
            "entity_type": "User",
            "entity": {"id": "123", "first_name": "John"},
            "updated_fields": None,
            "cascade": None,
            "metadata": None,
        }
    )

    response_bytes = _fraiseql_rs.build_mutation_response(
        mutation_json,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        "user",  # entity_field_name
        None,  # entity_type (comes from JSON in v2)
        None,  # cascade_selections,
        entity_selections=UNFILTERED,
    )

    response = json.loads(response_bytes)
    assert response["data"]["createUser"]["__typename"] == "CreateUserSuccess"
    assert response["data"]["createUser"]["user"]["firstName"] == "John"


@requires_rust
def test_rust_binding_error():
    """Test error mutation transformation with validation error."""
    import json

    mutation_json = json.dumps(
        {
            "status": "validation:invalid_email",
            "message": "Invalid email",
            "entity_id": None,
            "entity_type": None,
            "entity": None,
            "updated_fields": None,
            "cascade": None,
            "metadata": None,
        }
    )

    response_bytes = _fraiseql_rs.build_mutation_response(
        mutation_json,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        "user",  # entity_field_name
        None,  # entity_type
        None,  # cascade_selections,
        entity_selections=UNFILTERED,
    )

    response = json.loads(response_bytes)
    assert response["data"]["createUser"]["__typename"] == "CreateUserError"
    assert response["data"]["createUser"]["code"] == 422  # Validation errors map to 422


@requires_rust
def test_rust_binding_invalid_json():
    """Test error handling for invalid JSON."""
    with pytest.raises(ValueError, match="Invalid JSON"):
        _fraiseql_rs.build_mutation_response(
            "not valid json",
            "createUser",
            "CreateUserSuccess",
            "CreateUserError",
            "user",
            None,
            entity_selections=UNFILTERED,
        )
