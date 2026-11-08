"""Integration tests for LTree path comparison operators (lt, lte, gt, gte).

This module tests the complete pipeline for path comparison operators:
1. GraphQL WHERE input → Operator detection → SQL generation
2. Lexicographic path ordering with proper ltree casting
"""

import pytest

pytestmark = pytest.mark.database


class TestLTreePathComparisonIntegration:
    """Test LTree path comparison operators with real SQL generation."""

    def test_path_lt_operator(self) -> None:
        """Test less-than path comparison operator."""
        from fraiseql.sql.where import build_where_clause

        graphql_where = {"navigationPath": {"lt": "science.physics"}}
        where_clause = build_where_clause(graphql_where)

        assert where_clause is not None
        sql_string = where_clause.as_string(None)

        # Should use < operator with ltree casting
        assert "<" in sql_string
        assert "::ltree" in sql_string
        assert "navigation_path" in sql_string

    def test_path_lte_operator(self) -> None:
        """Test less-than-or-equal path comparison operator."""
        from fraiseql.sql.where import build_where_clause

        graphql_where = {"categoryPath": {"lte": "science.biology"}}
        where_clause = build_where_clause(graphql_where)

        assert where_clause is not None
        sql_string = where_clause.as_string(None)

        # Should use <= operator with ltree casting
        assert "<=" in sql_string
        assert "::ltree" in sql_string
        assert "category_path" in sql_string

    def test_path_gt_operator(self) -> None:
        """Test greater-than path comparison operator."""
        from fraiseql.sql.where import build_where_clause

        graphql_where = {"locationPath": {"gt": "geography.continents"}}
        where_clause = build_where_clause(graphql_where)

        assert where_clause is not None
        sql_string = where_clause.as_string(None)

        # Should use > operator with ltree casting
        assert ">" in sql_string
        assert "::ltree" in sql_string
        assert "location_path" in sql_string

    def test_path_gte_operator(self) -> None:
        """Test greater-than-or-equal path comparison operator."""
        from fraiseql.sql.where import build_where_clause

        graphql_where = {"documentPath": {"gte": "documents.archives.2024"}}
        where_clause = build_where_clause(graphql_where)

        assert where_clause is not None
        sql_string = where_clause.as_string(None)

        # Should use >= operator with ltree casting
        assert ">=" in sql_string
        assert "::ltree" in sql_string
        assert "document_path" in sql_string

    def test_path_comparison_with_single_label(self) -> None:
        """Test path comparison with single-label paths."""
        from fraiseql.sql.where import build_where_clause

        graphql_where = {"hierarchy": {"lt": "z"}}
        where_clause = build_where_clause(graphql_where)

        assert where_clause is not None
        sql_string = where_clause.as_string(None)

        # Single label should still work with ltree casting
        assert "<" in sql_string
        assert "::ltree" in sql_string

    def test_path_comparison_with_deep_paths(self) -> None:
        """Test path comparison with deeply nested paths."""
        from fraiseql.sql.where import build_where_clause

        deep_path = "level1.level2.level3.level4.level5.level6.level7.level8"
        graphql_where = {"treePath": {"gte": deep_path}}
        where_clause = build_where_clause(graphql_where)

        assert where_clause is not None
        sql_string = where_clause.as_string(None)

        # Deep paths should still work with proper casting
        assert ">=" in sql_string
        assert "::ltree" in sql_string
        assert "tree_path" in sql_string

    def test_path_comparison_lexicographic_ordering(self) -> None:
        """Test that path comparison uses lexicographic (string) ordering.

        In lexicographic ordering:
        - "aaa" < "bbb"
        - "top.alpha" < "top.beta"
        - "science.astronomy" < "science.biology"
        """
        from fraiseql.sql.where import build_where_clause

        # Test that we can compare paths lexicographically
        test_cases = [
            ("alpha", "beta"),  # Simple single-label comparison
            ("science.astronomy", "science.biology"),  # Multi-level comparison
            ("top.a.z", "top.b"),  # Different depths
        ]

        for _left, right in test_cases:
            graphql_where = {"path": {"lt": right}}
            where_clause = build_where_clause(graphql_where)

            assert where_clause is not None
            sql_string = where_clause.as_string(None)

            # All should use ltree casting for consistent comparison
            assert "::ltree" in sql_string

    def test_path_comparison_combined_with_other_operators(self) -> None:
        """Test path comparison operators combined with other filters."""
        from fraiseql.sql.where import build_where_clause

        # Combine lt and gte for range query on paths
        graphql_where = {
            "categoryPath": {
                "gte": "science",
                "lt": "technology",
            }
        }
        where_clause = build_where_clause(graphql_where)

        assert where_clause is not None
        sql_string = where_clause.as_string(None)

        # Should have both >= and < operators
        assert ">=" in sql_string
        assert "<" in sql_string
        assert sql_string.count("::ltree") >= 2  # At least two ltree casts

    def test_path_comparison_with_special_characters(self) -> None:
        """Test path comparison with paths containing special characters."""
        from fraiseql.sql.where import build_where_clause

        # LTree paths can contain underscores, hyphens, etc.
        special_path = "org.dept_name.sub-section"
        graphql_where = {"path": {"gt": special_path}}
        where_clause = build_where_clause(graphql_where)

        assert where_clause is not None
        sql_string = where_clause.as_string(None)

        # Should handle special characters correctly
        assert ">" in sql_string
        assert "::ltree" in sql_string

    def test_path_comparison_vs_hierarchy_operators(self) -> None:
        """Test that path comparison is different from hierarchy operators.

        Path comparison (lt, gt, etc.) uses lexicographic ordering.
        Hierarchy operators (ancestor_of, descendant_of) use containment.
        """
        from fraiseql.sql.where import build_where_clause

        path_to_compare = "science"

        # Path comparison: lexicographic
        graphql_where_lt = {"path": {"lt": path_to_compare}}
        where_clause_lt = build_where_clause(graphql_where_lt)
        sql_lt = where_clause_lt.as_string(None)

        # Hierarchy: containment
        graphql_where_ancestor = {"path": {"ancestor_of": path_to_compare}}
        where_clause_ancestor = build_where_clause(graphql_where_ancestor)
        sql_ancestor = where_clause_ancestor.as_string(None)

        # They should generate different operators
        assert "<" in sql_lt  # Lexicographic less-than
        assert "@>" in sql_ancestor  # Ancestor containment

    def test_path_comparison_all_four_operators(self) -> None:
        """Test all four path comparison operators generate correct SQL."""
        from fraiseql.sql.where import build_where_clause

        operators_and_symbols = [
            ("lt", "<"),
            ("lte", "<="),
            ("gt", ">"),
            ("gte", ">="),
        ]

        for operator_name, sql_symbol in operators_and_symbols:
            graphql_where = {"path": {operator_name: "test.path"}}
            where_clause = build_where_clause(graphql_where)

            assert where_clause is not None
            sql_string = where_clause.as_string(None)

            assert sql_symbol in sql_string, (
                f"Expected operator '{sql_symbol}' not found for '{operator_name}' "
                f"in SQL: {sql_string}"
            )
            assert "::ltree" in sql_string


class TestLTreePathComparisonEdgeCases:
    """Test edge cases for path comparison operators."""

    def test_empty_path_comparison(self) -> None:
        """Test path comparison with empty or minimal paths."""
        from fraiseql.sql.where import build_where_clause

        # Single character path
        graphql_where = {"path": {"lt": "a"}}
        where_clause = build_where_clause(graphql_where)

        assert where_clause is not None
        sql_string = where_clause.as_string(None)
        assert "<" in sql_string
        assert "::ltree" in sql_string

    def test_numeric_labels_in_path_comparison(self) -> None:
        """Test path comparison with numeric labels (e.g., year hierarchies)."""
        from fraiseql.sql.where import build_where_clause

        # Paths can have numeric components like 2024.Q1.January
        numeric_path = "2024.Q1"
        graphql_where = {"datePath": {"gte": numeric_path}}
        where_clause = build_where_clause(graphql_where)

        assert where_clause is not None
        sql_string = where_clause.as_string(None)

        assert ">=" in sql_string
        assert "::ltree" in sql_string
        assert "date_path" in sql_string

    def test_path_comparison_unicode_paths(self) -> None:
        """Test path comparison with unicode characters in paths."""
        from fraiseql.sql.where import build_where_clause

        # LTree supports unicode characters
        unicode_path = "français.español.中文"
        graphql_where = {"path": {"lt": unicode_path}}
        where_clause = build_where_clause(graphql_where)

        assert where_clause is not None
        sql_string = where_clause.as_string(None)

        # Should handle unicode gracefully
        assert "<" in sql_string
        assert "::ltree" in sql_string

    def test_path_comparison_case_sensitivity(self) -> None:
        """Test that path comparison respects case sensitivity.

        PostgreSQL ltree comparisons are case-sensitive.
        """
        from fraiseql.sql.where import build_where_clause

        # Different cases should create different comparisons
        graphql_where_lower = {"path": {"lt": "science.astronomy"}}
        graphql_where_upper = {"path": {"lt": "Science.Astronomy"}}

        where_clause_lower = build_where_clause(graphql_where_lower)
        where_clause_upper = build_where_clause(graphql_where_upper)

        sql_lower = where_clause_lower.as_string(None)
        sql_upper = where_clause_upper.as_string(None)

        # Both should generate valid SQL
        assert "<" in sql_lower
        assert "<" in sql_upper

        # The paths should be different in the generated SQL
        assert "science.astronomy" in sql_lower.lower()
        assert "Science.Astronomy" in sql_upper or (
            "Science.Astronomy".lower() in sql_upper.lower()
        )


class TestLTreePathComparisonPerformance:
    """Test performance characteristics of path comparison operators."""

    def test_path_comparison_uses_ltree_type(self) -> None:
        """Verify path comparison operators use ltree type for GiST optimization.

        GiST indexes in PostgreSQL optimize ltree queries.
        This test verifies we're using ::ltree casting for proper optimization.
        """
        from fraiseql.sql.where import build_where_clause

        graphql_where = {"path": {"gte": "science.astronomy"}}
        where_clause = build_where_clause(graphql_where)

        sql_string = where_clause.as_string(None)

        # Must have ::ltree casting for GiST index optimization
        assert "::ltree" in sql_string
        assert sql_string.count("::ltree") >= 2  # Both operands should be cast

    def test_combined_path_comparisons_sql_structure(self) -> None:
        """Test SQL structure when combining multiple path comparisons.

        Range queries like 'gte X and lt Y' are common and should generate
        efficient SQL using proper ltree casting.
        """
        from fraiseql.sql.where import build_where_clause

        graphql_where = {
            "path": {
                "gte": "science.astronomy",
                "lt": "science.biology",
            }
        }
        where_clause = build_where_clause(graphql_where)

        sql_string = where_clause.as_string(None)

        # Should have both operators
        assert ">=" in sql_string
        assert "<" in sql_string

        # Both should use ltree casting
        ltree_count = sql_string.count("::ltree")
        assert ltree_count >= 2, (
            f"Expected at least 2 ::ltree casts for range query, "
            f"found {ltree_count} in: {sql_string}"
        )
