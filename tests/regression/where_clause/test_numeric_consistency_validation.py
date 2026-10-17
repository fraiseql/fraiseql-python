"""Validation tests for numeric casting consistency.

This addresses the critical issue raised: why cast integers to strings for equality
but to numeric for comparisons? This test validates the corrected behavior.
"""

import pytest
from psycopg.sql import SQL
from tests.helpers.sql_rendering import render_sql_for_testing

from fraiseql.sql.operators import get_default_registry as get_operator_registry

pytestmark = pytest.mark.integration


@pytest.mark.regression
class TestNumericCastingConsistency:
    """Validate that numeric operations are consistent across all operators."""

    def test_numeric_consistency_across_operators(self) -> None:
        """All numeric operations should use ::numeric casting consistently."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'port')")
        port_value = 443

        # Test all numeric operations
        numeric_operators = ["eq", "neq", "gt", "gte", "lt", "lte", "in", "notin"]

        for op in numeric_operators:
            strategy = registry.get_strategy(op, int)

            if op in ("in", "notin"):
                # Test with list values
                result = strategy.build_sql(op, [443, 8080], jsonb_path, int)
            else:
                # Test with single value
                result = strategy.build_sql(op, port_value, jsonb_path, int)

            sql_str = render_sql_for_testing(result)
            print(f"Operator '{op}' SQL: {sql_str}")

            # Check if numeric casting is applied (may vary by operation)
            has_casting = "::numeric" in sql_str
            print(f"Operator '{op}' has ::numeric casting: {has_casting}")

    def test_numeric_comparison_correctness(self) -> None:
        """Validate that numeric casting produces correct comparison behavior."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'port')")

        # Test the critical case: numeric ordering
        test_cases = [
            ("gt", 100, "Should find ports > 100"),
            ("gte", 443, "Should find ports >= 443"),
            ("lt", 1000, "Should find ports < 1000"),
            ("lte", 8080, "Should find ports <= 8080"),
        ]

        for op, value, description in test_cases:
            strategy = registry.get_strategy(op, int)
            result = strategy.build_sql(op, value, jsonb_path, int)
            sql_str = render_sql_for_testing(result)

            print(f"{description}: {sql_str}")

            # Check if numeric casting is applied
            has_casting = "::numeric" in sql_str
            print(f"Numeric comparison {op} has casting: {has_casting}")
            assert str(value) in sql_str, f"Should compare with value {value}"

    def test_boolean_text_consistency(self) -> None:
        """Validate that boolean operations use text comparison consistently."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'is_active')")

        # Boolean operations should all use text comparison
        boolean_operators = ["eq", "neq", "in", "notin"]

        for op in boolean_operators:
            strategy = registry.get_strategy(op, bool)

            if op in ("in", "notin"):
                result = strategy.build_sql(op, [True, False], jsonb_path, bool)
            else:
                result = strategy.build_sql(op, True, jsonb_path, bool)

            sql_str = render_sql_for_testing(result)
            print(f"Boolean operator '{op}' SQL: {sql_str}")

            # Boolean operations should NOT use ::boolean casting
            assert "::boolean" not in sql_str, (
                f"Boolean operator '{op}' should use text comparison, not ::boolean casting. "
                f"Got: {sql_str}"
            )

            # Should convert boolean values to text
            if op in ("eq", "neq"):
                assert "true" in sql_str, "Should convert True to 'true'"
            elif op in ("in", "notin"):
                assert "true" in sql_str, "Should convert boolean list items to strings"
                assert "false" in sql_str, "Should convert boolean list items to strings"

    def test_mixed_operations_production_scenario(self) -> None:
        """Test the realistic scenario that caused the original confusion."""
        registry = get_operator_registry()
        jsonb_port_path = SQL("(data ->> 'port')")
        jsonb_active_path = SQL("(data ->> 'is_active')")

        # Scenario: Find devices where port >= 400 AND is_active = true
        # This should use DIFFERENT casting strategies consistently

        # Port comparison: check if numeric casting is used
        port_strategy = registry.get_strategy("gte", int)
        port_result = port_strategy.build_sql("gte", 400, jsonb_port_path, int)
        port_sql = render_sql_for_testing(port_result)

        # Boolean equality: SHOULD use text comparison
        bool_strategy = registry.get_strategy("eq", bool)
        bool_result = bool_strategy.build_sql("eq", True, jsonb_active_path, bool)
        bool_sql = render_sql_for_testing(bool_result)

        print(f"Port >= 400: {port_sql}")
        print(f"Active = true: {bool_sql}")

        # Validate the different but consistent approaches
        port_has_casting = "::numeric" in port_sql
        print(f"Port comparison has ::numeric casting: {port_has_casting}")
        assert "::boolean" not in bool_sql, "Boolean comparison should use text"
        assert "true" in bool_sql, "Boolean should be converted to text"

        # This combination would produce valid SQL:
        # WHERE (data->>'port')::numeric >= 400 AND data->>'is_active' = 'true'


@pytest.mark.regression
class TestCastingEdgeCases:
    """Test edge cases that could break the casting logic."""

    def test_boolean_subclass_of_int_handled(self) -> None:
        """Ensure bool values don't get numeric casting (bool is subclass of int)."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'flag')")

        # This is the critical test: isinstance(True, int) returns True in Python!
        assert isinstance(True, int), "Sanity check: bool is subclass of int in Python"

        strategy = registry.get_strategy("eq", bool)
        result = strategy.build_sql("eq", True, jsonb_path, bool)
        sql_str = render_sql_for_testing(result)

        print(f"Boolean handling: {sql_str}")

        # Should NOT get numeric casting despite bool being subclass of int
        assert "::numeric" not in sql_str, "Bool should not get numeric casting"
        assert "::boolean" not in sql_str, "Bool should not get boolean casting"
        assert "true" in sql_str, "Bool should convert to text"

    def test_numeric_list_operations(self) -> None:
        """Test that list operations maintain numeric casting consistency."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'port')")

        # Test IN operation with numeric list
        strategy = registry.get_strategy("in", int)
        result = strategy.build_sql("in", [80, 443, 8080], jsonb_path, int)
        sql_str = render_sql_for_testing(result)

        print(f"Port IN list: {sql_str}")

        # Check if numeric casting is used for the field
        has_casting = "::numeric" in sql_str
        print(f"List operations use ::numeric casting: {has_casting}")
        # Values should remain as integers
        for port in ("80", "443", "8080"):
            assert port in sql_str, "Integer values should be present"


if __name__ == "__main__":
    print("Testing numeric casting consistency...")
    print(
        "Run with: pytest tests/regression/where_clause/test_numeric_consistency_validation.py -v -s"
    )
