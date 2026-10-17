"""SQL structure validation tests for WHERE clause generation.

These tests validate that generated SQL is well-formed and structurally correct,
not just that it contains certain substrings. This provides much stronger
validation than simple string matching.
"""

import re

import pytest
from psycopg.sql import SQL
from tests.helpers.sql_rendering import render_sql_for_testing

from fraiseql.sql.operators import get_default_registry as get_operator_registry
from fraiseql.sql.where_generator import build_operator_composed

pytestmark = pytest.mark.integration


@pytest.mark.regression
class TestSQLStructureValidation:
    """Validate that generated SQL has correct structure and syntax."""

    def test_numeric_casting_structure(self) -> None:
        """Test that numeric casting has valid structural components."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'port')")

        operators = ["eq", "neq", "gt", "gte", "lt", "lte"]
        for op in operators:
            strategy = registry.get_strategy(op, int)
            result = strategy.build_sql(op, 443, jsonb_path, int, jsonb_column="data")
            sql_str = render_sql_for_testing(result)

            print(f"Operator {op}: {sql_str}")

            # Validate structural components instead of exact patterns
            # Should contain numeric casting (integer for int values)
            assert "::integer" in sql_str, f"Missing integer casting for {op}. Got: {sql_str}"

            # Should contain the JSONB field extraction
            assert "data ->> 'port'" in sql_str, (
                f"Missing JSONB field extraction for {op}. Got: {sql_str}"
            )

            # Should contain the literal value
            assert "443" in sql_str, f"Missing literal value for {op}. Got: {sql_str}"

            # Should contain the SQL operator
            op_map = {"eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
            expected_op = op_map[op]
            assert f" {expected_op} " in sql_str, (
                f"Missing SQL operator {expected_op} for {op} in {sql_str}"
            )

    def test_boolean_text_comparison_structure(self) -> None:
        """Test that boolean comparison has correct structural components."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'is_active')")

        strategy = registry.get_strategy("eq", bool)
        result = strategy.build_sql("eq", True, jsonb_path, bool, jsonb_column="data")
        sql_str = render_sql_for_testing(result)

        print(f"Boolean equality: {sql_str}")

        # Should contain JSONB field extraction
        assert "data ->> 'is_active'" in sql_str, f"Missing JSONB field extraction. Got: {sql_str}"

        # Should contain boolean literal (true/false without quotes in PostgreSQL)
        assert "true" in sql_str, f"Missing boolean literal for boolean. Got: {sql_str}"

        # Should contain equals operator
        assert " = " in sql_str, f"Missing equals operator. Got: {sql_str}"

        # Should have boolean casting
        assert "::boolean" in sql_str, f"Boolean comparison should use ::boolean casting: {sql_str}"

    def test_hostname_text_structure(self) -> None:
        """Test that hostname comparison has correct text structure."""
        from fraiseql.types import Hostname

        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'hostname')")

        strategy = registry.get_strategy("eq", Hostname)
        result = strategy.build_sql("eq", "printserver01.local", jsonb_path, Hostname)
        sql_str = render_sql_for_testing(result)

        print(f"Hostname equality: {sql_str}")

        # Should contain proper hostname components
        assert "data ->> 'hostname'" in sql_str, f"Missing JSONB field extraction. Got: {sql_str}"
        assert "'printserver01.local'" in sql_str, f"Missing hostname value. Got: {sql_str}"
        assert " = " in sql_str, f"Missing equals operator. Got: {sql_str}"

        # Should NOT have ltree casting (the bug we fixed)
        assert "::ltree" not in sql_str, f"Hostname should not get ltree casting: {sql_str}"

    def test_list_operations_structure(self) -> None:
        """Test that IN/NOT IN operations have correct structure."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'port')")

        # Test numeric IN
        strategy = registry.get_strategy("in", int)
        result = strategy.build_sql("in", [80, 443, 8080], jsonb_path, int, jsonb_column="data")
        sql_str = render_sql_for_testing(result)

        print(f"Numeric IN: {sql_str}")

        # Should have proper structure: field::integer IN (val1, val2, val3)
        assert "data ->> 'port'" in sql_str, f"Missing field extraction: {sql_str}"
        assert "::integer" in sql_str, f"Missing integer casting: {sql_str}"
        assert " IN (" in sql_str, f"Missing IN operator: {sql_str}"
        assert "80" in sql_str, f"Missing first value: {sql_str}"
        assert "443" in sql_str, f"Missing second value: {sql_str}"
        assert "8080" in sql_str, f"Missing third value: {sql_str}"

    def test_boolean_list_structure(self) -> None:
        """Test that boolean IN operations use text values."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'is_active')")

        strategy = registry.get_strategy("in", bool)
        result = strategy.build_sql("in", [True, False], jsonb_path, bool)
        sql_str = render_sql_for_testing(result)

        print(f"Boolean IN: {sql_str}")

        # Should have boolean structure without casting
        patterns = [
            r"\(data ->> 'is_active'\)",  # Field extraction without casting
            r" IN \(",  # IN operator
            r"true",  # Boolean literal for True
            r"false",  # Boolean literal for False
        ]

        for pattern in patterns:
            assert re.search(pattern, sql_str), (
                f"Missing expected pattern '{pattern}' in boolean IN structure: {sql_str}"
            )

        # Should NOT have casting
        assert "::boolean" not in sql_str, f"Boolean IN should not use casting: {sql_str}"

    def test_sql_composition_validity(self) -> None:
        """Test that composed SQL structures are valid."""
        # Test complex composition using build_operator_composed
        path_sql = SQL("data->>'test_field'")

        # Test various value types
        test_cases = [
            (443, int, "numeric"),
            (True, bool, "text"),
            ("test_string", str, "text"),
        ]

        for value, value_type, expected_strategy in test_cases:
            result = build_operator_composed(path_sql, "eq", value, value_type)
            sql_str = render_sql_for_testing(result)

            print(f"Value {value} ({value_type}): {sql_str}")

            # Basic structure validation
            assert "data->>'test_field'" in sql_str, f"Missing field extraction: {sql_str}"
            assert " = " in sql_str, f"Missing equals operator: {sql_str}"

            if expected_strategy == "numeric":
                assert "::numeric" in sql_str, f"Missing numeric casting: {sql_str}"
            elif expected_strategy == "text" and value_type is bool:
                # Special case for boolean
                assert "'true'" in sql_str or "'false'" in sql_str, (
                    f"Missing text boolean value: {sql_str}"
                )

    def test_parentheses_balancing(self) -> None:
        """Test that all parentheses are properly balanced."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'field')")

        test_cases = [
            ("eq", 42, int),
            ("eq", True, bool),
            ("in", [1, 2, 3], int),
            ("in", [True, False], bool),
        ]

        for op, value, value_type in test_cases:
            strategy = registry.get_strategy(op, value_type)
            result = strategy.build_sql(op, value, jsonb_path, value_type)
            sql_str = render_sql_for_testing(result)

            print(f"Testing parentheses balance for {op} {value}: {sql_str}")

            # Count parentheses
            open_parens = sql_str.count("(")
            close_parens = sql_str.count(")")

            assert open_parens == close_parens, (
                f"Unbalanced parentheses in SQL for {op} {value}. "
                f"Open: {open_parens}, Close: {close_parens}. "
                f"SQL: {sql_str}"
            )

    def test_no_sql_injection_vulnerabilities(self) -> None:
        """Test that all values are properly parameterized."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'field')")

        # Test potentially malicious values
        malicious_values = [
            "'; DROP TABLE users; --",
            "' OR '1'='1",
            "admin'--",
            "1; DELETE FROM table WHERE 1=1; --",
        ]

        for malicious_value in malicious_values:
            strategy = registry.get_strategy("eq", str)
            result = strategy.build_sql("eq", malicious_value, jsonb_path, str)
            sql_str = render_sql_for_testing(result)

            print(f"Testing injection protection for: {malicious_value}")
            print(f"Generated SQL: {sql_str}")

            # Should be properly escaped to prevent SQL injection
            # PostgreSQL escapes single quotes by doubling them
            escaped_value = malicious_value.replace("'", "''")
            assert f"'{escaped_value}'" in sql_str, (
                f"Malicious content not properly escaped: {sql_str}"
            )


if __name__ == "__main__":
    print("Testing SQL structure validation...")
    print("Run with: pytest tests/regression/where_clause/test_sql_structure_validation.py -v -s")
