"""Precise SQL validation tests that check actual SQL output structure.

These tests validate the actual rendered SQL, not just the internal Composed structure,
to ensure we generate valid, well-formed PostgreSQL queries.
"""

import pytest
from psycopg.sql import SQL
from tests.helpers.sql_rendering import render_sql_for_testing

from fraiseql.sql.operators import get_default_registry as get_operator_registry

pytestmark = pytest.mark.integration


@pytest.mark.regression
class TestPreciseSQLValidation:
    """Validate actual rendered SQL output for correctness."""

    def test_numeric_casting_renders_valid_sql(self) -> None:
        """Test that numeric operations render to valid PostgreSQL syntax."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'port')")

        strategy = registry.get_strategy("gte", int)
        result = strategy.build_sql("gte", 443, jsonb_path, int)

        # Use the same rendering approach as complete SQL validation
        try:
            # Use psycopg's as_string method which renders actual SQL
            rendered_sql = result.as_string(None)
        except Exception:
            # Fallback: manually render the structure
            def render_part(part) -> None:
                if hasattr(part, "as_string"):
                    return part.as_string(None)
                if hasattr(part, "string"):  # SQL object
                    return part.string
                if hasattr(part, "seq"):  # Nested Composed
                    return "".join(render_part(p) for p in part.seq)
                # Literal
                return "%s"  # Parameter placeholder

            if hasattr(result, "seq"):
                rendered_sql = "".join(render_part(part) for part in result.seq)
            else:
                rendered_sql = render_part(result)

        print(f"Rendered SQL: {rendered_sql}")

        # Should be valid PostgreSQL syntax
        expected_patterns = [
            "data ->> 'port'",  # JSONB extraction
            ">=",  # Comparison operator
        ]

        for pattern in expected_patterns:
            assert pattern in rendered_sql, f"Missing '{pattern}' in rendered SQL: {rendered_sql}"

        # Should have balanced parentheses
        assert rendered_sql.count("(") == rendered_sql.count(")"), (
            f"Unbalanced parentheses in: {rendered_sql}"
        )

    def test_boolean_comparison_renders_valid_sql(self) -> None:
        """Test that boolean operations render to valid text comparison SQL."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'is_active')")

        strategy = registry.get_strategy("eq", bool)
        result = strategy.build_sql("eq", True, jsonb_path, bool)

        # Check the structure components
        sql_str = render_sql_for_testing(result)
        print(f"Boolean SQL structure: {sql_str}")

        # Validate key structural elements
        assert "data ->> 'is_active'" in sql_str, "Should contain JSONB field extraction"
        assert "true" in sql_str, "Should use text literal for boolean"
        assert "::boolean" not in sql_str, "Should NOT use boolean casting"

        # Ensure proper operator
        assert " = " in sql_str, "Should use equality operator"

    def test_hostname_comparison_no_ltree_casting(self) -> None:
        """Test that hostname comparison doesn't incorrectly use ltree casting."""
        from fraiseql.types import Hostname

        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'hostname')")

        strategy = registry.get_strategy("eq", Hostname)
        result = strategy.build_sql("eq", "printserver01.local", jsonb_path, Hostname)

        sql_str = render_sql_for_testing(result)
        print(f"Hostname SQL structure: {sql_str}")

        # Critical validations
        assert "data ->> 'hostname'" in sql_str, "Should contain JSONB field extraction"
        assert "printserver01.local" in sql_str, "Should contain hostname value"
        assert "::ltree" not in sql_str, "Should NOT use ltree casting (this was the bug!)"

    def test_list_operations_have_correct_structure(self) -> None:
        """Test that IN operations have proper SQL structure."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'port')")

        # Test numeric IN
        strategy = registry.get_strategy("in", int)
        result = strategy.build_sql("in", [80, 443], jsonb_path, int)

        sql_str = render_sql_for_testing(result)
        print(f"IN operation structure: {sql_str}")

        # Should have proper components
        assert "data ->> 'port'" in sql_str, "Should contain JSONB field extraction"
        assert " IN (" in sql_str, "Should have IN operator"
        assert "80" in sql_str, "Should have first value"
        assert "443" in sql_str, "Should have second value"

    def test_composed_sql_has_balanced_structure(self) -> None:
        """Test that complex composed SQL maintains proper structure."""
        registry = get_operator_registry()

        test_cases = [
            (SQL("(data ->> 'age')"), "gte", 18, int, "numeric comparison"),
            (SQL("(data ->> 'active')"), "eq", True, bool, "boolean comparison"),
            (SQL("(data ->> 'tags')"), "in", ["red", "blue"], str, "string list"),
        ]

        for path_sql, op, value, value_type, description in test_cases:
            strategy = registry.get_strategy(op, value_type)
            result = strategy.build_sql(op, value, path_sql, value_type)

            sql_str = render_sql_for_testing(result)
            print(f"{description}: {sql_str}")

            # Basic structural validation - check rendered SQL
            assert "data ->>" in sql_str, f"Should contain JSONB extraction: {sql_str}"

            # Count parentheses for balance in rendered SQL
            open_count = sql_str.count("(")
            close_count = sql_str.count(")")
            assert open_count == close_count, (
                f"Unbalanced parentheses in {description}: "
                f"open={open_count}, close={close_count}, sql={sql_str}"
            )

    def test_no_sql_injection_in_structure(self) -> None:
        """Test that potentially malicious values are properly contained."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'comment')")

        malicious_input = "'; DROP TABLE users; --"
        strategy = registry.get_strategy("eq", str)
        result = strategy.build_sql("eq", malicious_input, jsonb_path, str)

        sql_str = render_sql_for_testing(result)
        print(f"Malicious input handling: {sql_str}")

        # The malicious content should be properly quoted
        escaped_input = malicious_input.replace("'", "''")  # PostgreSQL escaping
        assert f"'{escaped_input}'" in sql_str, f"Malicious content not properly escaped: {sql_str}"

        # Should not have raw SQL injection
        assert "DROP TABLE" not in sql_str.replace(f"'{escaped_input}'", ""), (
            f"Raw SQL injection detected outside of Literal: {sql_str}"
        )

    def test_type_consistency_validation(self) -> None:
        """Test that the same operation type produces consistent results."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'score')")

        # Test multiple calls to same operation
        strategy = registry.get_strategy("eq", int)
        result1 = strategy.build_sql("eq", 100, jsonb_path, int)
        result2 = strategy.build_sql("eq", 200, jsonb_path, int)

        sql1 = render_sql_for_testing(result1)
        sql2 = render_sql_for_testing(result2)

        print(f"First call: {sql1}")
        print(f"Second call: {sql2}")

        # Should have same structural pattern (only values differ)
        assert sql1.count("::numeric") == sql2.count("::numeric"), "Inconsistent casting"
        assert sql1.count(" = ") == sql2.count(" = "), "Inconsistent operators"
        assert "100" in sql1, "Values not properly differentiated"
        assert "200" in sql2, "Values not properly differentiated"


if __name__ == "__main__":
    print("Testing precise SQL validation...")
    print("Run with: pytest tests/regression/where_clause/test_precise_sql_validation.py -v -s")
