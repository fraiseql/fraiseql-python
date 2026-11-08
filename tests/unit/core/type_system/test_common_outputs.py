"""Tests for common GraphQL output types and mutation result handling."""

import typing
import uuid
from dataclasses import fields

import pytest

from fraiseql.types.common_outputs import MUTATION_STATUS_MAP, MutationResultRow


class TestMutationResultRow:
    """Test MutationResultRow dataclass functionality."""

    def test_mutation_result_row_creation(self) -> None:
        """Test basic MutationResultRow creation."""
        test_id = uuid.uuid4()
        result = MutationResultRow(
            id=test_id,
            status="ok",
            updated_fields=["name", "email"],
            message="Operation successful",
            object_data={"name": "John", "email": "john@example.com"},
            extra_metadata={"timestamp": "2023-01-01T00:00:00Z"},
        )

        assert result.id == test_id
        assert result.status == "ok"
        assert result.updated_fields == ["name", "email"]
        assert result.message == "Operation successful"
        assert result.object_data == {"name": "John", "email": "john@example.com"}
        assert result.extra_metadata == {"timestamp": "2023-01-01T00:00:00Z"}

    def test_mutation_result_row_fields(self) -> None:
        """Test MutationResultRow field definitions."""
        field_names = [f.name for f in fields(MutationResultRow)]
        expected_fields = {
            "id",
            "status",
            "updated_fields",
            "message",
            "object_data",
            "extra_metadata",
        }
        assert set(field_names) == expected_fields

    def test_mutation_result_row_field_types(self) -> None:
        """Test MutationResultRow field type annotations."""
        annotations = MutationResultRow.__annotations__
        assert annotations["id"] == uuid.UUID
        assert annotations["status"] is str
        assert annotations["updated_fields"] == list[str]
        assert annotations["message"] is str
        assert annotations["object_data"] == dict[str, typing.Any]
        assert annotations["extra_metadata"] == dict[str, typing.Any]

    def test_mutation_result_row_empty_collections(self) -> None:
        """Test MutationResultRow with empty collections."""
        test_id = uuid.uuid4()
        result = MutationResultRow(
            id=test_id,
            status="noop",
            updated_fields=[],  # Empty list
            message="No changes made",
            object_data={},  # Empty dict
            extra_metadata={},  # Empty dict
        )

        assert result.updated_fields == []
        assert result.object_data == {}
        assert result.extra_metadata == {}

    def test_mutation_result_row_repr(self) -> None:
        """Test MutationResultRow string representation."""
        test_id = uuid.uuid4()
        result = MutationResultRow(
            id=test_id,
            status="updated",
            updated_fields=["name"],
            message="Updated successfully",
            object_data={"name": "Jane"},
            extra_metadata={},
        )

        repr_str = repr(result)
        assert "MutationResultRow" in repr_str
        assert str(test_id) in repr_str
        assert "updated" in repr_str

    def test_mutation_result_row_equality(self) -> None:
        """Test MutationResultRow equality comparison."""
        test_id = uuid.uuid4()

        result1 = MutationResultRow(
            id=test_id,
            status="ok",
            updated_fields=["name"],
            message="Success",
            object_data={"name": "John"},
            extra_metadata={},
        )

        result2 = MutationResultRow(
            id=test_id,
            status="ok",
            updated_fields=["name"],
            message="Success",
            object_data={"name": "John"},
            extra_metadata={},
        )

        result3 = MutationResultRow(
            id=test_id,
            status="failed",  # Different status
            updated_fields=["name"],
            message="Success",
            object_data={"name": "John"},
            extra_metadata={},
        )

        assert result1 == result2
        assert result1 != result3


class TestMutationStatusMap:
    """Test mutation status mapping functionality."""

    def test_status_map_structure(self) -> None:
        """Test that MUTATION_STATUS_MAP has correct structure."""
        assert isinstance(MUTATION_STATUS_MAP, dict)

        # Each value should be a tuple of (error_code, http_status)
        for status, (error_code, http_status) in MUTATION_STATUS_MAP.items():
            assert isinstance(status, str)
            assert error_code is None or isinstance(error_code, str)
            assert isinstance(http_status, int)
            assert 200 <= http_status <= 599  # Valid HTTP status range

    def test_success_statuses(self) -> None:
        """Test success status mappings."""
        success_statuses = ["ok", "updated", "deleted"]

        for status in success_statuses:
            assert status in MUTATION_STATUS_MAP
            error_code, http_status = MUTATION_STATUS_MAP[status]
            assert error_code is None
            assert http_status == 200

    def test_noop_statuses(self) -> None:
        """Test no-operation status mappings."""
        noop_statuses = ["""noop""", """noop:already_exists""", """noop:not_found"""]

        for status in noop_statuses:
            assert status in MUTATION_STATUS_MAP
            error_code, http_status = MUTATION_STATUS_MAP[status]

            if status == "noop":
                assert error_code == "generic_noop"
                assert http_status == 422
            elif status == "noop:already_exists":
                assert error_code == "already_exists"
                assert http_status == 422
            elif status == "noop:not_found":
                assert error_code == "not_found"
                assert http_status == 404

    def test_blocked_statuses(self) -> None:
        """Test blocked operation status mappings."""
        blocked_statuses = [
            "blocked:children",
            "blocked:allocations",
            "blocked:children_and_allocations",
        ]

        for status in blocked_statuses:
            assert status in MUTATION_STATUS_MAP
            error_code, http_status = MUTATION_STATUS_MAP[status]
            assert error_code is not None
            assert http_status == 422

    def test_validation_failure_status(self) -> None:
        """Test validation failure status mapping."""
        status = "failed:validation"
        assert status in MUTATION_STATUS_MAP

        error_code, http_status = MUTATION_STATUS_MAP[status]
        assert error_code == "invalid_input"
        assert http_status == 422

    def test_technical_failure_status(self) -> None:
        """Test technical failure status mapping."""
        status = "failed:exception"
        assert status in MUTATION_STATUS_MAP

        error_code, http_status = MUTATION_STATUS_MAP[status]
        assert error_code == "error_internal"
        assert http_status == 500

    def test_status_map_completeness(self) -> None:
        """Test that all expected status categories are covered."""
        all_statuses = set(MUTATION_STATUS_MAP.keys())

        # Success statuses
        assert "ok" in all_statuses
        assert "updated" in all_statuses
        assert "deleted" in all_statuses

        # Noop statuses
        assert "noop" in all_statuses
        assert "noop:already_exists" in all_statuses
        assert "noop:not_found" in all_statuses

        # Blocked statuses
        assert "blocked:children" in all_statuses
        assert "blocked:allocations" in all_statuses
        assert "blocked:children_and_allocations" in all_statuses

        # Failure statuses
        assert "failed:validation" in all_statuses
        assert "failed:exception" in all_statuses

    @pytest.mark.parametrize(
        ("status", "expected_http"),
        [
            ("ok", 200),
            ("updated", 200),
            ("deleted", 200),
            ("noop", 422),
            ("noop:not_found", 404),
            ("failed:exception", 500),
        ],
    )
    def test_status_http_codes(self, status, expected_http) -> None:
        """Test specific status to HTTP code mappings."""
        _error_code, http_status = MUTATION_STATUS_MAP[status]
        assert http_status == expected_http

    def test_status_map_usage_example(self) -> None:
        """Test typical usage pattern of status map."""
        # Simulate processing a mutation result
        mutation_status = "blocked:children"

        if mutation_status in MUTATION_STATUS_MAP:
            error_code, http_status = MUTATION_STATUS_MAP[mutation_status]

            # Should provide proper error handling info
            assert error_code == "delete_blocked_child_units"
            assert http_status == 422

            # Could be used to construct error response
            is_error = http_status >= 400
            assert is_error is True

    def test_jsontype_alias(self) -> None:
        """Test JSONType alias definition."""
        from fraiseql.types.common_outputs import JSONType

        # Should be a type alias for dict[str, object]
        assert JSONType == dict[str, object]

        # Should be usable in type annotations
        def process_json(data: JSONType) -> str:
            return str(data)

        # Test with valid data
        test_data = {"key": "value", "number": 42}
        result = process_json(test_data)
        assert "key" in result
        assert "42" in result
