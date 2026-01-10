"""Performance tests for mutation field selection.

These tests measure and validate performance characteristics of field selection.
They don't use pytest-benchmark fixture to avoid collection issues, but use
timeit for reliable measurements instead.
"""

import json
import timeit
from typing import Any

import pytest

from fraiseql import _get_fraiseql_rs


class TestResponseSizePerformance:
    """Test response size impact of field selection."""

    def test_response_size_comparison(self) -> None:
        """Verify response size reduction with field selection."""
        fraiseql_rs = _get_fraiseql_rs()

        sample_result = {
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

        # Baseline: no selection
        response_full = fraiseql_rs.build_mutation_response(
            json.dumps(sample_result),
            "testMutation",
            "TestSuccess",
            "TestError",
            "entity",
            "TestEntity",
            None,
            True,
            None,  # No selection - all fields
        )
        size_full = len(response_full)

        # With selection: only entity field
        response_filtered = fraiseql_rs.build_mutation_response(
            json.dumps(sample_result),
            "testMutation",
            "TestSuccess",
            "TestError",
            "entity",
            "TestEntity",
            None,
            True,
            ["entity"],  # Only entity field
        )
        size_filtered = len(response_filtered)

        # Verify we have meaningful sizes
        assert size_full > 0, "Full response should have content"
        assert size_filtered > 0, "Filtered response should have content"

        # Calculate reduction percentage
        if size_full > 0:
            reduction_pct = ((size_full - size_filtered) / size_full) * 100
            print(
                f"\nResponse size reduction: {reduction_pct:.1f}%"
                f"\n  Full: {size_full} bytes"
                f"\n  Filtered: {size_filtered} bytes"
            )

            # Response should be smaller with filtering
            assert size_filtered <= size_full, "Filtered response should be smaller or equal"

    def test_multiple_field_selection_size(self) -> None:
        """Test response size with multiple fields selected."""
        fraiseql_rs = _get_fraiseql_rs()

        sample_result = {
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

        # Full response
        response_full = fraiseql_rs.build_mutation_response(
            json.dumps(sample_result),
            "testMutation",
            "TestSuccess",
            "TestError",
            "entity",
            "TestEntity",
            None,
            True,
            None,
        )

        # Partial selection
        response_partial = fraiseql_rs.build_mutation_response(
            json.dumps(sample_result),
            "testMutation",
            "TestSuccess",
            "TestError",
            "entity",
            "TestEntity",
            None,
            True,
            ["status", "message", "entity"],
        )

        size_full = len(response_full)
        size_partial = len(response_partial)

        print(f"\nPartial selection result: {size_partial} bytes (full: {size_full})")
        assert size_partial <= size_full, "Partial selection should reduce or maintain size"


class TestResponseTimePerformance:
    """Test response time impact of field selection."""

    def test_response_time_overhead(self) -> None:
        """Measure response time overhead from field selection."""
        fraiseql_rs = _get_fraiseql_rs()

        sample_result = {
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

        def measure_no_selection() -> None:
            fraiseql_rs.build_mutation_response(
                json.dumps(sample_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "TestEntity",
                None,
                True,
                None,
            )

        def measure_with_selection() -> None:
            fraiseql_rs.build_mutation_response(
                json.dumps(sample_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "TestEntity",
                None,
                True,
                ["entity"],
            )

        # Measure time (using timeit for reliability)
        num_iterations = 100
        time_no_selection = timeit.timeit(measure_no_selection, number=num_iterations)
        time_with_selection = timeit.timeit(measure_with_selection, number=num_iterations)

        # Calculate overhead
        overhead_pct = ((time_with_selection - time_no_selection) / time_no_selection) * 100

        print(
            f"\nResponse time overhead: {overhead_pct:.2f}%"
            f"\n  No selection: {time_no_selection * 1000:.2f}ms"
            f"\n  With selection: {time_with_selection * 1000:.2f}ms"
            f"\n  Per call overhead: {(time_with_selection - time_no_selection) / num_iterations * 1000:.3f}ms"
        )

        # Verify overhead is acceptable (< 10% is good)
        assert overhead_pct < 10, f"Response time overhead should be < 10%, got {overhead_pct:.2f}%"


class TestFieldExtractionPerformance:
    """Test Python field extraction performance."""

    def test_field_extraction_simple(self) -> None:
        """Test extraction performance with simple field count."""
        from fraiseql.mutations.mutation_resolver import convert_selections_to_json

        selections_simple = {f"field_{i}": True for i in range(10)}

        def measure() -> None:
            convert_selections_to_json(selections_simple)

        num_iterations = 1000
        elapsed = timeit.timeit(measure, number=num_iterations)
        per_call = elapsed / num_iterations

        print(f"\nField extraction (10 fields): {per_call * 1000000:.3f}µs per call")
        assert per_call < 0.001, "Field extraction should be < 1ms"

    def test_field_extraction_large(self) -> None:
        """Test extraction performance with large field count."""
        from fraiseql.mutations.mutation_resolver import convert_selections_to_json

        selections_large = {f"field_{i}": True for i in range(100)}

        def measure() -> None:
            convert_selections_to_json(selections_large)

        num_iterations = 1000
        elapsed = timeit.timeit(measure, number=num_iterations)
        per_call = elapsed / num_iterations

        print(f"\nField extraction (100 fields): {per_call * 1000000:.3f}µs per call")
        assert per_call < 0.01, "Field extraction should be < 10ms even for 100 fields"

    def test_field_extraction_very_large(self) -> None:
        """Test extraction performance with very large field count."""
        from fraiseql.mutations.mutation_resolver import convert_selections_to_json

        selections_very_large = {f"field_{i}": True for i in range(1000)}

        def measure() -> None:
            convert_selections_to_json(selections_very_large)

        num_iterations = 100
        elapsed = timeit.timeit(measure, number=num_iterations)
        per_call = elapsed / num_iterations

        print(f"\nField extraction (1000 fields): {per_call * 1000000:.3f}µs per call")
        # 1000 fields might take longer, but should still be reasonable
        assert per_call < 0.1, "Field extraction should be < 100ms for 1000 fields"


class TestScalingCharacteristics:
    """Test scaling behavior of field selection."""

    def test_scaling_with_field_count(self) -> None:
        """Verify performance scales linearly with field count."""
        fraiseql_rs = _get_fraiseql_rs()

        sample_result = {
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

        measurements = []

        for field_count in [10, 50, 100, 500, 1000]:
            fields = [f"field_{i}" for i in range(field_count)]

            def measure() -> None:
                fraiseql_rs.build_mutation_response(
                    json.dumps(sample_result),
                    "testMutation",
                    "TestSuccess",
                    "TestError",
                    "entity",
                    "TestEntity",
                    None,
                    True,
                    fields,
                )

            num_iterations = 10
            elapsed = timeit.timeit(measure, number=num_iterations)
            per_call = elapsed / num_iterations

            measurements.append((field_count, per_call))
            print(f"  {field_count:4d} fields: {per_call * 1000:.3f}ms per call")

        # Check for linear scaling (each doubling shouldn't cause 10x slowdown)
        # This is a basic sanity check
        for i in range(len(measurements) - 1):
            field_ratio = measurements[i + 1][0] / measurements[i][0]
            time_ratio = measurements[i + 1][1] / measurements[i][1]

            # Allow up to 5x the ratio (should be closer to 2x for linear scaling)
            assert time_ratio < field_ratio * 2, (
                f"Performance should scale roughly linearly. "
                f"Field count ratio: {field_ratio:.1f}x, Time ratio: {time_ratio:.1f}x"
            )


class TestBackwardCompatibility:
    """Test backward compatibility of field selection."""

    def test_no_selection_returns_all_fields(self) -> None:
        """Verify that no selection returns all fields (backward compat)."""
        fraiseql_rs = _get_fraiseql_rs()

        sample_result = {
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

        response = fraiseql_rs.build_mutation_response(
            json.dumps(sample_result),
            "testMutation",
            "TestSuccess",
            "TestError",
            "entity",
            "TestEntity",
            None,
            True,
            None,  # No selection
        )

        response_json = json.loads(response)
        data = response_json["data"]["testMutation"]

        # Verify that standard Success fields are present
        assert "status" in data, "status field should be present"
        assert "message" in data, "message field should be present"
        assert "entity" in data, "entity field should be present"

        print(f"\nBackward compat verified. Fields present: {list(data.keys())}")


class TestRealWorldScenarios:
    """Test real-world usage scenarios."""

    def test_typical_create_mutation(self) -> None:
        """Benchmark typical create mutation scenario."""
        fraiseql_rs = _get_fraiseql_rs()

        result = {
            "status": "success",
            "message": "User created successfully",
            "entity_id": "user-123",
            "entity_type": "User",
            "entity": {
                "id": "user-123",
                "email": "test@example.com",
                "name": "Test User",
                "created_at": "2026-01-10T12:00:00Z",
            },
            "updated_fields": [],
            "cascade": None,
            "metadata": None,
            "is_simple_format": False,
        }

        # Common selection for create mutation
        selected_fields = ["id", "name", "email", "createdAt"]

        def measure() -> None:
            fraiseql_rs.build_mutation_response(
                json.dumps(result),
                "createUser",
                "CreateUserSuccess",
                "CreateUserError",
                "entity",
                "User",
                None,
                True,
                selected_fields,
            )

        num_iterations = 100
        elapsed = timeit.timeit(measure, number=num_iterations)
        per_call = elapsed / num_iterations

        print(f"\nTypical create mutation: {per_call * 1000:.3f}ms per call")
        assert per_call < 0.05, "Create mutation should be fast (< 50ms)"

    def test_typical_update_mutation(self) -> None:
        """Benchmark typical update mutation scenario."""
        fraiseql_rs = _get_fraiseql_rs()

        result = {
            "status": "success",
            "message": "User updated successfully",
            "entity_id": "user-123",
            "entity_type": "User",
            "entity": {
                "id": "user-123",
                "email": "test@example.com",
                "name": "Updated User",
                "updated_at": "2026-01-10T12:30:00Z",
            },
            "updated_fields": ["name", "email"],
            "cascade": None,
            "metadata": None,
            "is_simple_format": False,
        }

        # Common selection for update mutation
        selected_fields = ["id", "updatedAt", "updatedFields"]

        def measure() -> None:
            fraiseql_rs.build_mutation_response(
                json.dumps(result),
                "updateUser",
                "UpdateUserSuccess",
                "UpdateUserError",
                "entity",
                "User",
                None,
                True,
                selected_fields,
            )

        num_iterations = 100
        elapsed = timeit.timeit(measure, number=num_iterations)
        per_call = elapsed / num_iterations

        print(f"\nTypical update mutation: {per_call * 1000:.3f}ms per call")
        assert per_call < 0.05, "Update mutation should be fast (< 50ms)"
