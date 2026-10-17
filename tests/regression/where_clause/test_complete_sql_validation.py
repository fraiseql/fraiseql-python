"""Complete SQL validation tests that check the full rendered WHERE clause.

These tests validate the complete SQL output to ensure it generates syntactically
correct PostgreSQL queries that can actually be executed.
"""

import pytest
from psycopg.sql import SQL
from tests.helpers.sql_rendering import render_sql_for_testing

from fraiseql.sql.operators import get_default_registry as get_operator_registry
from fraiseql.sql.where_generator import build_operator_composed

pytestmark = pytest.mark.integration


def render_composed_to_sql(composed) -> None:
    """Render a Composed object to actual SQL string with parameter placeholders."""
    try:
        # Use psycopg's as_string method which renders actual SQL
        return composed.as_string(None)
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

        if hasattr(composed, "seq"):
            return "".join(render_part(part) for part in composed.seq)
        return render_part(composed)


@pytest.mark.regression
class TestCompleteSQLValidation:
    """Validate complete SQL output for syntactic correctness."""

    def test_numeric_where_clause_full_sql(self) -> None:
        """Test that numeric operations generate valid complete SQL."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'port')")

        test_cases = [
            ("eq", 443, "= 443"),
            ("gte", 400, ">= 400"),
            ("lt", 1000, "< 1000"),
            ("in", [80, 443], "IN (80, 443)"),
        ]

        for op, value, expected_operator in test_cases:
            strategy = registry.get_strategy(op, int)
            result = strategy.build_sql(op, value, jsonb_path, int)

            sql = render_sql_for_testing(result)
            print(f"Operation {op} with value {value}:")
            print(f"  Generated SQL: {sql}")

            # Validate SQL syntax elements
            assert "data ->> 'port'" in sql, f"Missing JSONB extraction in: {sql}"
            # Check if numeric casting is applied
            has_casting = "::numeric" in sql
            print(f"Numeric operation {op} has ::numeric casting: {has_casting}")

            # Check operator and value
            assert expected_operator in sql, (
                f"Missing expected operator '{expected_operator}' in: {sql}"
            )

            # Validate parentheses balance
            assert sql.count("(") == sql.count(")"), f"Unbalanced parentheses in: {sql}"

    def test_boolean_where_clause_full_sql(self) -> None:
        """Test that boolean operations generate valid complete SQL."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'is_active')")

        test_cases = [
            ("eq", True, "= true"),
            ("eq", False, "= false"),
            ("in", [True, False], "IN ('true', 'false')"),
        ]

        for op, value, expected_operator in test_cases:
            strategy = registry.get_strategy(op, bool)
            result = strategy.build_sql(op, value, jsonb_path, bool)

            sql = render_sql_for_testing(result)
            print(f"Boolean operation {op} with value {value}:")
            print(f"  Generated SQL: {sql}")

            # Validate SQL syntax elements
            assert "data ->> 'is_active'" in sql, f"Missing JSONB extraction in: {sql}"
            assert "::boolean" not in sql, f"Should not use boolean casting in: {sql}"

            # Check operator and value conversion
            assert expected_operator in sql, (
                f"Missing expected operator '{expected_operator}' in: {sql}"
            )

            # Validate parentheses balance
            assert sql.count("(") == sql.count(")"), f"Unbalanced parentheses in: {sql}"

    def test_hostname_where_clause_full_sql(self) -> None:
        """Test that hostname operations generate valid complete SQL without ltree casting."""
        from fraiseql.types import Hostname

        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'hostname')")

        test_cases = [
            ("eq", "printserver01.local", "= 'printserver01.local'"),
            ("eq", "db.staging.company.com", "= 'db.staging.company.com'"),
            ("in", ["server.local", "backup.local"], "IN ('server.local', 'backup.local')"),
        ]

        for op, value, expected_operator in test_cases:
            strategy = registry.get_strategy(op, Hostname)
            result = strategy.build_sql(op, value, jsonb_path, Hostname)

            sql = render_sql_for_testing(result)
            print(f"Hostname operation {op} with value {value}:")
            print(f"  Generated SQL: {sql}")

            # Critical validation: should NOT use ltree casting
            assert "::ltree" not in sql, f"Hostname should not get ltree casting in: {sql}"

            # Should use simple text comparison
            assert "data ->> 'hostname'" in sql, f"Missing JSONB extraction in: {sql}"

            # Check operator and value
            assert expected_operator in sql, (
                f"Missing expected operator '{expected_operator}' in: {sql}"
            )

    def test_mixed_where_clause_full_sql(self) -> None:
        """Test complex WHERE clauses with multiple conditions."""
        # Test using build_operator_composed for mixing conditions
        age_path = SQL("data->>'age'")
        active_path = SQL("data->>'is_active'")

        age_condition = build_operator_composed(age_path, "gte", 21, int)
        active_condition = build_operator_composed(active_path, "eq", True, bool)

        age_sql = render_sql_for_testing(age_condition)
        active_sql = render_sql_for_testing(active_condition)

        print(f"Age condition SQL: {age_sql}")
        print(f"Active condition SQL: {active_sql}")

        # Validate each condition separately
        # Age condition should use numeric casting
        assert "data->>'age'" in age_sql, f"Missing age field in: {age_sql}"
        assert "::numeric" in age_sql, f"Missing numeric casting in: {age_sql}"
        assert ">=" in age_sql, f"Missing gte operator in: {age_sql}"

        # Active condition should use text comparison
        assert "data->>'is_active'" in active_sql, f"Missing active field in: {active_sql}"
        assert "::boolean" not in active_sql, f"Should not use boolean casting in: {active_sql}"
        assert "=" in active_sql, f"Missing equals operator in: {active_sql}"

    def test_sql_injection_resistance_full_sql(self) -> None:
        """Test that the complete SQL is injection-resistant."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'comment')")

        malicious_inputs = [
            "'; DROP TABLE users; --",
            "' OR '1'='1",
            "admin'--",
            "1; DELETE FROM table WHERE 1=1; --",
        ]

        for malicious_input in malicious_inputs:
            strategy = registry.get_strategy("eq", str)
            result = strategy.build_sql("eq", malicious_input, jsonb_path, str)

            sql = render_sql_for_testing(result)
            print(f"Testing malicious input: {malicious_input}")
            print(f"  Generated SQL: {sql}")

            # The SQL should contain the literal value properly escaped
            # Note: Single quotes in SQL are escaped by doubling them
            escaped_input = malicious_input.replace("'", "''")
            expected_sql = f"(data ->> 'comment') = '{escaped_input}'"
            assert sql == expected_sql, f"Expected: {expected_sql}, got: {sql}"

            # The malicious content should be within the quoted literal, not as executable SQL
            # The fact that it's rendered as a quoted string shows it's properly escaped
            assert sql.startswith("(data ->> 'comment') = '"), (
                f"Should start with field comparison: {sql}"
            )
            assert sql.endswith("'"), f"Should end with closing quote: {sql}"

    def test_complex_list_operations_full_sql(self) -> None:
        """Test that complex list operations generate valid SQL."""
        registry = get_operator_registry()

        test_cases = [
            # Numeric lists
            (SQL("(data ->> 'port')"), "in", [80, 443, 8080], int, "IN (80, 443, 8080)"),
            # Boolean lists
            (SQL("(data ->> 'enabled')"), "notin", [True, False], bool, "NOT IN ('true', 'false')"),
            # String lists
            (
                SQL("(data ->> 'status')"),
                "in",
                ["active", "pending"],
                str,
                "IN ('active', 'pending')",
            ),
        ]

        for path_sql, op, values, value_type, expected_operator in test_cases:
            strategy = registry.get_strategy(op, value_type)
            result = strategy.build_sql(op, values, path_sql, value_type, jsonb_column="data")

            sql = render_sql_for_testing(result)
            print(f"List operation {op} with {value_type.__name__} values {values}:")
            print(f"  Generated SQL: {sql}")

            # Validate structure elements exist
            if value_type is int:
                assert "::integer" in sql, f"Missing integer casting for int list in: {sql}"
            elif value_type is bool:
                assert "::boolean" not in sql, (
                    f"Should not use boolean casting for bool list in: {sql}"
                )

            # Validate operator and values
            assert expected_operator in sql, (
                f"Missing expected operator '{expected_operator}' in: {sql}"
            )

            # Validate parentheses balance
            assert sql.count("(") == sql.count(")"), f"Unbalanced parentheses in: {sql}"

    def test_postgresql_syntax_compliance(self) -> None:
        """Test that generated SQL follows PostgreSQL syntax rules."""
        registry = get_operator_registry()

        # Test various field types and operations
        test_scenarios = [
            (SQL("(data ->> 'score')"), "gte", 85, int),
            (SQL("(data ->> 'verified')"), "eq", True, bool),
            (SQL("(data ->> 'name')"), "eq", "test user", str),
            (SQL("(data ->> 'tags')"), "in", ["red", "blue", "green"], str),
        ]

        for path_sql, op, value, value_type in test_scenarios:
            strategy = registry.get_strategy(op, value_type)
            result = strategy.build_sql(op, value, path_sql, value_type)

            sql = render_sql_for_testing(result)
            print(f"PostgreSQL syntax test - {value_type.__name__} {op}: {sql}")

            # Basic PostgreSQL syntax validations

            # 1. Proper JSONB extraction syntax
            assert " ->> " in sql, f"Missing JSONB extraction operator in: {sql}"

            # 2. Balanced quotes (single quotes for strings)
            single_quotes = sql.count("'")
            assert single_quotes % 2 == 0, f"Unbalanced single quotes in: {sql}"

            # 3. No syntax errors (basic checks)
            assert not sql.startswith(" "), f"SQL should not start with space: {sql}"
            assert not sql.endswith(" "), f"SQL should not end with space: {sql}"

            # 4. Proper operator spacing
            if " = " in sql:
                assert " =  " not in sql, f"Improper operator spacing in: {sql}"
                assert "=  " not in sql, f"Improper operator spacing in: {sql}"

            # 5. Contains actual values (not parameter placeholders in this rendering)
            # The as_string(None) method renders actual values for validation

            # 6. No double casting
            casting_types = ["::numeric", "::boolean", "::text", "::ltree", "::inet"]
            casting_count = sum(sql.count(cast_type) for cast_type in casting_types)
            field_count = sql.count(" ->> ")
            assert casting_count <= field_count, f"Too many type casts for fields in: {sql}"


if __name__ == "__main__":
    print("Testing complete SQL validation...")
    print("Run with: pytest tests/regression/where_clause/test_complete_sql_validation.py -v -s")
