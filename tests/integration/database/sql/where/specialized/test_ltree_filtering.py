import pytest

pytestmark = pytest.mark.database

#!/usr/bin/env python3
"""End-to-end integration tests for LTree hierarchical path filtering functionality.

This module tests the complete LTree filtering pipeline:
1. GraphQL WHERE input → Field detection → Operator selection → SQL generation
2. Real hierarchical path operations with specialized PostgreSQL ltree operators
"""

from psycopg.sql import SQL

from fraiseql.sql.where import build_where_clause, detect_field_type, get_operator_function
from fraiseql.sql.where.core.field_detection import FieldType


class TestEndToEndLTreeFiltering:
    """Test complete LTree filtering pipeline with hierarchical path operations."""

    def test_graphql_ltree_equality_filtering(self) -> None:
        """Test LTree equality filtering reproduces expected behavior."""
        # Simulate GraphQL WHERE input for LTree path filtering
        graphql_where = {"categoryPath": {"eq": "top.science.astrophysics"}}

        # Build WHERE clause using our clean architecture
        where_clause = build_where_clause(graphql_where)

        # Verify we get proper SQL with ::ltree casting
        assert where_clause is not None
        sql_string = where_clause.as_string(None)

        # Should generate LTree equality with proper casting
        expected_patterns = [
            "category_path",  # Field name conversion
            "::ltree",  # PostgreSQL LTree casting
            "= 'top.science.astrophysics'",  # Value comparison (PostgreSQL handles string literals)
        ]

        for pattern in expected_patterns:
            assert pattern in sql_string, f"Expected pattern '{pattern}' not found in: {sql_string}"

    def test_ltree_hierarchical_operations(self) -> None:
        """Test LTree hierarchical operations with ancestor_of and descendant_of."""
        # Test ancestor_of operation
        graphql_where_ancestor = {
            "categoryPath": {"ancestor_of": "top.science.astrophysics.black_holes"}
        }

        where_clause_ancestor = build_where_clause(graphql_where_ancestor)
        sql_ancestor = where_clause_ancestor.as_string(None)

        # Should contain @> operator for ancestor relationship
        assert "@>" in sql_ancestor
        assert "::ltree" in sql_ancestor
        assert "'top.science.astrophysics.black_holes'::ltree" in sql_ancestor

        # Test descendant_of operation
        graphql_where_descendant = {"categoryPath": {"descendant_of": "top.science"}}

        where_clause_descendant = build_where_clause(graphql_where_descendant)
        sql_descendant = where_clause_descendant.as_string(None)

        # Should contain <@ operator for descendant relationship
        assert "<@" in sql_descendant
        assert "::ltree" in sql_descendant
        assert "'top.science'::ltree" in sql_descendant

    def test_ltree_pattern_matching_operations(self) -> None:
        """Test LTree pattern matching with matches_lquery and matches_ltxtquery."""
        # Test lquery pattern matching
        graphql_where_lquery = {"navigationPath": {"matches_lquery": "science.*"}}

        where_clause_lquery = build_where_clause(graphql_where_lquery)
        sql_lquery = where_clause_lquery.as_string(None)

        # Should contain ~ operator for lquery pattern matching
        assert "~" in sql_lquery
        assert "::lquery" in sql_lquery
        assert "'science.*'::lquery" in sql_lquery

        # Test ltxtquery text matching
        graphql_where_ltxtquery = {"navigationPath": {"matches_ltxtquery": "astrophysics"}}

        where_clause_ltxtquery = build_where_clause(graphql_where_ltxtquery)
        sql_ltxtquery = where_clause_ltxtquery.as_string(None)

        # Should contain @ operator for ltxtquery text matching
        assert " @ " in sql_ltxtquery
        assert "::ltxtquery" in sql_ltxtquery
        assert "'astrophysics'::ltxtquery" in sql_ltxtquery

    def test_ltree_list_operations(self) -> None:
        """Test LTree IN and NOT IN list operations."""
        ltree_paths = ["top.science.physics", "top.science.chemistry", "top.technology.computing"]

        # Test IN operation
        graphql_where_in = {"categoryPath": {"in": ltree_paths}}

        where_clause_in = build_where_clause(graphql_where_in)
        sql_in = where_clause_in.as_string(None)

        # Should contain all LTree paths with proper casting
        assert "::ltree IN (" in sql_in
        for path in ltree_paths:
            assert f"'{path}'::ltree" in sql_in

    def test_field_name_conversion_snake_to_camel_ltree(self) -> None:
        """Test that field names are correctly converted from camelCase to snake_case."""
        graphql_where = {"categoryTreePath": {"neq": "top.science.biology"}}  # camelCase

        where_clause = build_where_clause(graphql_where)
        sql_string = where_clause.as_string(None)

        # Should convert to snake_case in database query
        assert "category_tree_path" in sql_string
        assert "::ltree" in sql_string

    def test_field_detection_recognizes_ltree_fields(self) -> None:
        """Test that field detection correctly identifies LTree fields."""
        # Test field name detection
        ltree_field_names = [
            "category_path",
            "categoryPath",
            "navigation_path",
            "navigationPath",
            "tree_path",
            "treePath",
            "hierarchy_path",
            "hierarchyPath",
            "path",
            "tree",
            "hierarchy",
            "taxonomyPath",
        ]

        for field_name in ltree_field_names:
            field_type = detect_field_type(field_name, "top.science.physics", None)
            assert field_type == FieldType.LTREE, (
                f"Field '{field_name}' should be detected as LTREE"
            )

    def test_field_detection_recognizes_ltree_values(self) -> None:
        """Test that field detection recognizes LTree path values."""
        ltree_values = [
            "top.science.physics",  # Standard hierarchical path
            "root.category.subcategory",  # Different root
            "a.b.c.d.e.f",  # Deep hierarchy
            "single_level",  # Single level (edge case)
            "top.tech_category.web_dev",  # With underscores
        ]

        for ltree_value in ltree_values:
            # Use a clearly LTree field name to ensure LTree detection
            field_type = detect_field_type("category_path", ltree_value, None)
            assert field_type == FieldType.LTREE, (
                f"Value '{ltree_value}' should be detected as LTREE"
            )

    def test_operator_function_selection_for_ltree(self) -> None:
        """Test that correct operator functions are selected for LTree fields."""
        # Basic operators
        basic_operators = ["eq", "neq", "in", "notin"]

        for operator in basic_operators:
            func = get_operator_function(FieldType.LTREE, operator)
            assert func is not None, f"Should have operator function for LTREE.{operator}"

            # Test that it generates proper SQL
            path_sql = SQL("data->>'category_path'")
            test_value = (
                "top.science.physics" if operator in ["eq", "neq"] else ["top.science.physics"]
            )

            result = func(path_sql, test_value)
            sql_string = result.as_string(None)

            assert "::ltree" in sql_string, f"LTree operator {operator} should use ::ltree casting"

        # Hierarchical operators
        hierarchical_operators = ["ancestor_of", "descendant_of"]

        for operator in hierarchical_operators:
            func = get_operator_function(FieldType.LTREE, operator)
            assert func is not None, f"Should have operator function for LTREE.{operator}"

            # Test that it generates proper SQL with hierarchical operators
            path_sql = SQL("data->>'category_path'")
            test_value = "top.science"

            result = func(path_sql, test_value)
            sql_string = result.as_string(None)

            assert "::ltree" in sql_string, (
                f"LTree hierarchical operator {operator} should use ::ltree casting"
            )
            if operator == "ancestor_of":
                assert "@>" in sql_string, "ancestor_of should use @> operator"
            elif operator == "descendant_of":
                assert "<@" in sql_string, "descendant_of should use <@ operator"

        # Pattern matching operators
        pattern_operators = ["matches_lquery", "matches_ltxtquery"]

        for operator in pattern_operators:
            func = get_operator_function(FieldType.LTREE, operator)
            assert func is not None, f"Should have operator function for LTREE.{operator}"

            # Test that it generates proper SQL with pattern operators
            path_sql = SQL("data->>'category_path'")
            test_value = "science.*" if operator == "matches_lquery" else "astrophysics"

            result = func(path_sql, test_value)
            sql_string = result.as_string(None)

            if operator == "matches_lquery":
                assert "~" in sql_string, "matches_lquery should use ~ operator"
                assert "::lquery" in sql_string, "matches_lquery should use ::lquery casting"
            elif operator == "matches_ltxtquery":
                assert " @ " in sql_string, "matches_ltxtquery should use @ operator"
                assert "::ltxtquery" in sql_string, (
                    "matches_ltxtquery should use ::ltxtquery casting"
                )

    def test_complex_hierarchical_paths(self) -> None:
        """Test LTree operators with complex, deeply nested paths."""
        complex_path = (
            "top.academics.university.computer_science.artificial_intelligence.machine_learning"
        )

        graphql_where = {"researchPath": {"eq": complex_path}}

        where_clause = build_where_clause(graphql_where)
        sql_string = where_clause.as_string(None)

        # Should handle complex paths correctly
        assert "::ltree" in sql_string
        assert complex_path in sql_string

    def test_mixed_field_types_with_ltree_operations(self) -> None:
        """Test WHERE clause with LTree, MAC, and IP address field types together."""
        graphql_where = {
            "categoryPath": {"ancestor_of": "top.science.physics"},
            "macAddress": {"eq": "00:11:22:33:44:55"},
            "ipAddress": {"eq": "192.168.1.100"},
        }

        where_clause = build_where_clause(graphql_where)
        sql_string = where_clause.as_string(None)

        # Should handle all field types correctly
        assert "@>" in sql_string  # LTree hierarchical operator
        assert "::ltree" in sql_string  # LTree casting
        assert "::macaddr" in sql_string  # MAC address casting
        assert "::inet" in sql_string  # IP address casting
        assert " AND " in sql_string  # Multiple conditions
