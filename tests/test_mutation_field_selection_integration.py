"""Integration tests for mutation field selection (Python + Rust)."""

import json

from fraiseql.mutations.decorators import error, success
from tests.unit.mutations.selection_document import legacy_document


def test_decorator_adds_fields_to_gql_fields():
    """Verify Python decorator adds auto-populated fields to __gql_fields__."""

    @success
    class TestSuccess:
        entity: dict

    gql_fields = getattr(TestSuccess, "__gql_fields__", {})

    # All expected fields should be present
    assert "entity" in gql_fields, "Original field should be present"
    assert "status" in gql_fields, "status field missing"
    assert "message" in gql_fields, "message field missing"
    assert "updated_fields" in gql_fields, "updated_fields field missing"
    assert "id" in gql_fields, "id field missing (entity detected)"

    # Success types should NOT have errors field (v1.9.0+)
    assert "errors" not in gql_fields, "Success types don't have errors field (v1.9.0+)"

    print(f"✅ Python decorator: All fields present: {sorted(gql_fields.keys())}")


def test_failure_decorator_adds_fields():
    """Verify @error decorator adds auto-populated fields (v1.8.1)."""

    @error
    class TestError:
        error_code: str

    gql_fields = getattr(TestError, "__gql_fields__", {})

    # Fields that SHOULD be present on Error types
    assert "error_code" in gql_fields
    assert "status" in gql_fields
    assert "message" in gql_fields
    assert "errors" in gql_fields
    assert "code" in gql_fields, "code field missing (auto-injected in v1.8.1)"

    # Fields that should NOT be present on Error types (semantically incorrect)
    assert "updated_fields" not in gql_fields, "updated_fields should not be on Error types"
    assert "id" not in gql_fields, "id should not be on Error types"

    print(f"✅ Failure decorator: Fields present: {sorted(gql_fields.keys())}")


def test_rust_field_filtering():
    """Verify Rust filters fields based on selection."""
    from fraiseql import _get_fraiseql_rs

    fraiseql_rs = _get_fraiseql_rs()

    # Create test result
    result_dict = {
        "status": "success",
        "message": "Test message",
        "entity_id": "test-123",
        "entity_type": "TestEntity",
        "entity": {"id": "test-123", "name": "Test"},
        "updated_fields": ["name"],
        "cascade": None,
        "metadata": None,
        "is_simple_format": False,
    }

    # Test 1: Only select 'entity' field
    selected_fields = ["entity"]

    response = fraiseql_rs.build_mutation_response(
        json.dumps(result_dict),  # mutation_json (string)
        "testMutation",  # field_name
        "TestSuccess",  # success_type
        "TestError",  # error_type
        "entity",  # entity_field_name
        "TestEntity",  # entity_type
        None,  # cascade_selections
        True,
        None,
        None,
        legacy_document(selected_fields, None, "entity", None),
    )

    response_json = json.loads(response)
    data = response_json["data"]["testMutation"]

    # Should have __typename and entity
    assert "__typename" in data
    assert "entity" in data

    # Should NOT have unrequested fields
    assert "id" not in data, (
        f"id should not be present (not requested), got keys: {list(data.keys())}"
    )
    assert "message" not in data, "message should not be present"
    assert "status" not in data, "status should not be present"
    assert "errors" not in data, "errors should not be present"
    assert "updatedFields" not in data, "updatedFields should not be present"

    print(f"✅ Rust filtering: Only requested fields present: {list(data.keys())}")


def test_rust_no_selection_returns_all():
    """Verify backward compatibility - no selection returns all fields."""
    from fraiseql import _get_fraiseql_rs

    fraiseql_rs = _get_fraiseql_rs()

    result_dict = {
        "status": "success",
        "message": "Test message",
        "entity_id": "test-123",
        "entity_type": "TestEntity",
        "entity": {"id": "test-123", "name": "Test"},
        "updated_fields": ["name"],
        "cascade": None,
        "metadata": None,
        "is_simple_format": False,
    }

    # No field selection (None)
    response = fraiseql_rs.build_mutation_response(
        json.dumps(result_dict),
        "testMutation",
        "TestSuccess",
        "TestError",
        "entity",
        "TestEntity",
        None,
        True,
        None,
        None,
        legacy_document(None, None, "entity", None),
    )

    response_json = json.loads(response)
    data = response_json["data"]["testMutation"]

    # All Success-type fields should be present
    assert "id" in data, "id should be present (no selection)"
    assert "message" in data, "message should be present"
    assert "status" in data, "status should be present"
    assert "entity" in data, "entity should be present"
    assert "updatedFields" in data, "updatedFields should be present"

    # Success types should NOT have errors field
    assert "errors" not in data, "Success types don't have errors (v1.9.0+)"

    print(f"✅ Backward compat: All fields present with None selection: {list(data.keys())}")


def test_partial_field_selection():
    """Verify partial field selection works correctly."""
    from fraiseql import _get_fraiseql_rs

    fraiseql_rs = _get_fraiseql_rs()

    result_dict = {
        "status": "success",
        "message": "Test message",
        "entity_id": "test-123",
        "entity_type": "TestEntity",
        "entity": {"id": "test-123", "name": "Test"},
        "updated_fields": ["name"],
        "cascade": None,
        "metadata": None,
        "is_simple_format": False,
    }

    # Select status, message, and entity
    selected_fields = ["status", "message", "entity"]

    response = fraiseql_rs.build_mutation_response(
        json.dumps(result_dict),
        "testMutation",
        "TestSuccess",
        "TestError",
        "entity",
        "TestEntity",
        None,
        True,
        None,
        None,
        legacy_document(selected_fields, None, "entity", None),
    )

    response_json = json.loads(response)
    data = response_json["data"]["testMutation"]

    # Requested fields should be present
    assert "status" in data
    assert "message" in data
    assert "entity" in data

    # Unrequested fields should NOT be present
    assert "id" not in data, "id not requested"
    assert "updatedFields" not in data, "updatedFields not requested"

    # Success types don't have errors field
    assert "errors" not in data, "Success types don't have errors"

    print(f"✅ Partial selection: {list(data.keys())}")


if __name__ == "__main__":
    # Run tests manually
    print("Running integration tests...")
    print()

    test_decorator_adds_fields_to_gql_fields()
    test_failure_decorator_adds_fields()
    test_rust_field_filtering()
    test_rust_no_selection_returns_all()
    test_partial_field_selection()

    print()
    print("✅ All integration tests passed!")
