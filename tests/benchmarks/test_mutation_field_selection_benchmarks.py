"""Performance benchmarks for mutation field selection.

Tests measure:
- Response size with/without field selection
- Response time impact of field selection
- Scaling with field count
- Nested selection performance
"""

import json
from typing import Any

import pytest

from fraiseql import _get_fraiseql_rs
from fraiseql.mutations.mutation_resolver import (
    convert_selections_to_json,
    extract_field_selections,
)


class BenchmarkResponseSize:
    """Benchmark response size impact of field selection."""

    def test_no_selection_response_size(
        self, benchmark: Any, sample_mutation_result: dict[str, Any]
    ) -> None:
        """Measure baseline response size without field selection."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> int:
            response = fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "TestEntity",
                None,
                True,
                None,  # No selection
            )
            return len(response)

        result = benchmark(measure)
        # Store baseline for comparison
        benchmark.extra_info = {"response_size": result}

    def test_single_field_selection_response_size(
        self, benchmark: Any, sample_mutation_result: dict[str, Any]
    ) -> None:
        """Measure response size with single field selected."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> int:
            response = fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "TestEntity",
                None,
                True,
                ["entity"],  # Single field
            )
            return len(response)

        result = benchmark(measure)
        benchmark.extra_info = {"response_size": result}

    def test_multiple_field_selection_response_size(
        self, benchmark: Any, sample_mutation_result: dict[str, Any]
    ) -> None:
        """Measure response size with multiple fields selected."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> int:
            response = fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "TestEntity",
                None,
                True,
                ["status", "message", "entity"],
            )
            return len(response)

        result = benchmark(measure)
        benchmark.extra_info = {"response_size": result}

    def test_moderate_field_selection_response_size(
        self,
        benchmark: Any,
        sample_mutation_result: dict[str, Any],
        field_selections_moderate: list[str],
    ) -> None:
        """Measure response size with moderate field selection."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> int:
            response = fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "TestEntity",
                None,
                True,
                field_selections_moderate,
            )
            return len(response)

        result = benchmark(measure)
        benchmark.extra_info = {"response_size": result}


class BenchmarkResponseTime:
    """Benchmark response time impact of field selection."""

    def test_no_selection_response_time(
        self, benchmark: Any, sample_mutation_result: dict[str, Any]
    ) -> None:
        """Measure baseline response time without field selection."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> str:
            return fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "TestEntity",
                None,
                True,
                None,  # No selection
            )

        benchmark(measure)

    def test_with_selection_response_time(
        self, benchmark: Any, sample_mutation_result: dict[str, Any]
    ) -> None:
        """Measure response time with field selection."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> str:
            return fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "TestEntity",
                None,
                True,
                ["entity"],
            )

        benchmark(measure)

    def test_moderate_selection_response_time(
        self,
        benchmark: Any,
        sample_mutation_result: dict[str, Any],
        field_selections_moderate: list[str],
    ) -> None:
        """Measure response time with moderate field selection."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> str:
            return fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "TestEntity",
                None,
                True,
                field_selections_moderate,
            )

        benchmark(measure)


class BenchmarkFieldExtraction:
    """Benchmark Python field extraction performance."""

    def test_field_extraction_simple(
        self, benchmark: Any, field_selections_simple: list[str]
    ) -> None:
        """Benchmark simple field extraction."""

        def measure() -> str | None:
            return convert_selections_to_json(
                {field: True for field in field_selections_simple}
            )

        benchmark(measure)

    def test_field_extraction_moderate(
        self, benchmark: Any, field_selections_moderate: list[str]
    ) -> None:
        """Benchmark moderate field extraction."""

        def measure() -> str | None:
            return convert_selections_to_json(
                {field: True for field in field_selections_moderate}
            )

        benchmark(measure)

    def test_field_extraction_large(
        self, benchmark: Any, field_selections_large: list[str]
    ) -> None:
        """Benchmark large field extraction (100 fields)."""

        def measure() -> str | None:
            return convert_selections_to_json(
                {field: True for field in field_selections_large}
            )

        benchmark(measure)

    def test_field_extraction_very_large(
        self, benchmark: Any, field_selections_very_large: list[str]
    ) -> None:
        """Benchmark very large field extraction (1000 fields)."""

        def measure() -> str | None:
            return convert_selections_to_json(
                {field: True for field in field_selections_very_large}
            )

        benchmark(measure)


class BenchmarkNestedSelections:
    """Benchmark nested field selection performance."""

    def test_nested_selection_3_levels(
        self, benchmark: Any, sample_mutation_result: dict[str, Any]
    ) -> None:
        """Benchmark nested selections (3 levels deep)."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> str:
            return fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "TestEntity",
                None,
                True,
                ["status", "entity"],
            )

        benchmark(measure)

    def test_large_response_with_selection(
        self, benchmark: Any, large_mutation_result: dict[str, Any]
    ) -> None:
        """Benchmark performance with large mutation response."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> str:
            return fraiseql_rs.build_mutation_response(
                json.dumps(large_mutation_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "NestedEntity",
                None,
                True,
                ["entity"],
            )

        benchmark(measure)


class BenchmarkScalingCharacteristics:
    """Benchmark how performance scales with different parameters."""

    def test_scaling_with_100_fields(
        self, benchmark: Any, sample_mutation_result: dict[str, Any]
    ) -> None:
        """Benchmark with 100 selected fields."""
        fraiseql_rs = _get_fraiseql_rs()
        fields = [f"field_{i}" for i in range(100)]

        def measure() -> str:
            return fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "TestEntity",
                None,
                True,
                fields,
            )

        benchmark(measure)

    def test_scaling_with_1000_fields(
        self, benchmark: Any, sample_mutation_result: dict[str, Any]
    ) -> None:
        """Benchmark with 1000 selected fields."""
        fraiseql_rs = _get_fraiseql_rs()
        fields = [f"field_{i}" for i in range(1000)]

        def measure() -> str:
            return fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "testMutation",
                "TestSuccess",
                "TestError",
                "entity",
                "TestEntity",
                None,
                True,
                fields,
            )

        benchmark(measure)

    def test_json_serialization_large_selection(
        self, benchmark: Any, field_selections_large: list[str]
    ) -> None:
        """Benchmark JSON serialization of large selection."""
        selections_dict = {field: True for field in field_selections_large}

        def measure() -> str:
            return json.dumps(selections_dict)

        benchmark(measure)

    def test_json_deserialization_large_selection(
        self, benchmark: Any, field_selections_large: list[str]
    ) -> None:
        """Benchmark JSON deserialization of large selection."""
        selections_json = json.dumps({field: True for field in field_selections_large})

        def measure() -> dict[str, Any]:
            return json.loads(selections_json)

        benchmark(measure)


class BenchmarkRealWorldScenarios:
    """Benchmark real-world mutation scenarios."""

    def test_typical_mutation_no_selection(
        self, benchmark: Any, sample_mutation_result: dict[str, Any]
    ) -> None:
        """Benchmark typical mutation without field selection."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> str:
            # Typical mutation: return status and basic fields
            return fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "createEntity",
                "CreateEntitySuccess",
                "CreateEntityError",
                "entity",
                "Entity",
                None,
                True,
                None,
            )

        benchmark(measure)

    def test_typical_mutation_with_selection(
        self, benchmark: Any, sample_mutation_result: dict[str, Any]
    ) -> None:
        """Benchmark typical mutation with field selection."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> str:
            # Typical query: select specific fields
            return fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "createEntity",
                "CreateEntitySuccess",
                "CreateEntityError",
                "entity",
                "Entity",
                None,
                True,
                ["id", "name", "status", "createdAt"],
            )

        benchmark(measure)

    def test_update_mutation_all_fields(
        self, benchmark: Any, sample_mutation_result: dict[str, Any]
    ) -> None:
        """Benchmark update mutation returning all fields."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> str:
            return fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "updateEntity",
                "UpdateEntitySuccess",
                "UpdateEntityError",
                "entity",
                "Entity",
                None,
                True,
                None,  # All fields
            )

        benchmark(measure)

    def test_update_mutation_partial_fields(
        self, benchmark: Any, sample_mutation_result: dict[str, Any]
    ) -> None:
        """Benchmark update mutation returning partial fields."""
        fraiseql_rs = _get_fraiseql_rs()

        def measure() -> str:
            return fraiseql_rs.build_mutation_response(
                json.dumps(sample_mutation_result),
                "updateEntity",
                "UpdateEntitySuccess",
                "UpdateEntityError",
                "entity",
                "Entity",
                None,
                True,
                ["id", "updatedAt", "updatedFields"],
            )

        benchmark(measure)
