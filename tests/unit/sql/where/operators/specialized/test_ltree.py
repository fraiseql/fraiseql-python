"""Comprehensive tests for all LTree hierarchical path operators.

This module consolidates all LTree operator tests into a single, well-organized file.

Test Coverage:
- Basic operators: eq, neq, in, notin
- Hierarchical operators: ancestor_of, descendant_of, matches_lquery, matches_ltxtquery
- Depth operators: depth_eq, depth_gt, depth_gte, depth_lt, depth_lte, depth_neq
- Array operators: matches_any_lquery, in_array, array_contains
- Path analysis: nlevel, subpath, index, index_eq, index_gte
- Path manipulation: concat, lca
"""

import pytest
from psycopg.sql import SQL

from fraiseql.sql.operators import LTreeOperatorStrategy
from fraiseql.sql.where.operators.ltree import (
    build_ancestor_of_sql,
    build_depth_eq_sql,
    build_depth_gt_sql,
    build_depth_gte_sql,
    build_depth_lt_sql,
    build_depth_lte_sql,
    build_depth_neq_sql,
    build_descendant_of_sql,
    build_ltree_eq_sql,
    build_ltree_in_sql,
    build_ltree_neq_sql,
    build_ltree_notin_sql,
    build_matches_lquery_sql,
    build_matches_ltxtquery_sql,
)
from fraiseql.types import LTree

# ============================================================================
# BASIC OPERATORS: eq, neq, in, notin
# ============================================================================


class TestLTreeBasicOperators:
    """Test basic LTree operators via LTreeOperatorStrategy."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_ltree_eq_operator(self) -> None:
        """Test exact path equality."""
        result = self.strategy.build_sql("eq", "top.science.physics", self.path_sql, LTree)
        expected = "(data->>'path')::ltree = 'top.science.physics'::ltree"
        assert result.as_string(None) == expected

    def test_ltree_neq_operator(self) -> None:
        """Test exact path inequality."""
        result = self.strategy.build_sql("neq", "top.technology", self.path_sql, LTree)
        expected = "(data->>'path')::ltree != 'top.technology'::ltree"
        assert result.as_string(None) == expected

    def test_ltree_in_operator(self) -> None:
        """Test path in list."""
        paths = ["top.science", "top.technology", "top.arts"]
        result = self.strategy.build_sql("in", paths, self.path_sql, LTree)
        expected = "(data->>'path')::ltree IN ('top.science'::ltree, 'top.technology'::ltree, 'top.arts'::ltree)"
        assert result.as_string(None) == expected

    def test_ltree_notin_operator(self) -> None:
        """Test path not in list."""
        paths = ["top.science.physics", "top.science.chemistry"]
        result = self.strategy.build_sql("notin", paths, self.path_sql, LTree)
        expected = "(data->>'path')::ltree NOT IN ('top.science.physics'::ltree, 'top.science.chemistry'::ltree)"
        assert result.as_string(None) == expected

    def test_single_item_lists(self) -> None:
        """Test single item lists for in/notin operators."""
        # Single item IN
        result_in = self.strategy.build_sql("in", ["top.science"], self.path_sql, LTree)
        expected_in = "(data->>'path')::ltree IN ('top.science'::ltree)"
        assert result_in.as_string(None) == expected_in

        # Single item NOT IN
        result_notin = self.strategy.build_sql("notin", ["top.arts"], self.path_sql, LTree)
        expected_notin = "(data->>'path')::ltree NOT IN ('top.arts'::ltree)"
        assert result_notin.as_string(None) == expected_notin

    def test_empty_lists_for_in_notin(self) -> None:
        """Test empty lists for in/notin operators."""
        # Empty IN list
        result_in = self.strategy.build_sql("in", [], self.path_sql, LTree)
        expected_in = "(data->>'path')::ltree IN ()"
        assert result_in.as_string(None) == expected_in

        # Empty NOT IN list
        result_notin = self.strategy.build_sql("notin", [], self.path_sql, LTree)
        expected_notin = "(data->>'path')::ltree NOT IN ()"
        assert result_notin.as_string(None) == expected_notin


class TestLTreeBasicDirectFunctions:
    """Test ltree basic operator functions directly."""

    def test_ltree_eq_direct(self):
        """Test ltree equality function directly."""
        path_sql = SQL("data->>'path'")
        result = build_ltree_eq_sql(path_sql, "top.science.physics")
        sql_str = result.as_string(None)
        assert sql_str == "(data->>'path')::ltree = 'top.science.physics'::ltree"

    def test_ltree_neq_direct(self):
        """Test ltree inequality function directly."""
        path_sql = SQL("data->>'path'")
        result = build_ltree_neq_sql(path_sql, "top.technology")
        sql_str = result.as_string(None)
        assert sql_str == "(data->>'path')::ltree != 'top.technology'::ltree"

    def test_ltree_in_direct(self):
        """Test ltree IN function directly."""
        path_sql = SQL("data->>'path'")
        result = build_ltree_in_sql(path_sql, ["top.science", "top.technology"])
        sql_str = result.as_string(None)
        assert (
            sql_str == "(data->>'path')::ltree IN ('top.science'::ltree, 'top.technology'::ltree)"
        )

    def test_ltree_notin_direct(self):
        """Test ltree NOT IN function directly."""
        path_sql = SQL("data->>'path'")
        result = build_ltree_notin_sql(path_sql, ["top.arts", "top.sports"])
        sql_str = result.as_string(None)
        assert sql_str == "(data->>'path')::ltree NOT IN ('top.arts'::ltree, 'top.sports'::ltree)"


# ============================================================================
# HIERARCHICAL OPERATORS: ancestor_of, descendant_of, matches_lquery, matches_ltxtquery
# ============================================================================


class TestLTreeHierarchicalOperators:
    """Test LTree hierarchical relationship operators."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_ltree_ancestor_of_operator(self) -> None:
        """Test @> operator (path1 is ancestor of path2)."""
        # "top.science" @> "top.science.physics" = true
        result = self.strategy.build_sql("ancestor_of", "top.science.physics", self.path_sql, LTree)
        expected = "(data->>'path')::ltree @> 'top.science.physics'::ltree"
        assert result.as_string(None) == expected

    def test_ltree_descendant_of_operator(self) -> None:
        """Test <@ operator (path1 is descendant of path2)."""
        # "top.science.physics" <@ "top.science" = true
        result = self.strategy.build_sql("descendant_of", "top.science", self.path_sql, LTree)
        expected = "(data->>'path')::ltree <@ 'top.science'::ltree"
        assert result.as_string(None) == expected

    def test_ltree_matches_lquery(self) -> None:
        """Test ~ operator (path matches lquery pattern)."""
        # "top.science.physics" ~ "*.science.*" = true
        result = self.strategy.build_sql("matches_lquery", "*.science.*", self.path_sql, LTree)
        expected = "(data->>'path')::ltree ~ '*.science.*'::lquery"
        assert result.as_string(None) == expected

    def test_ltree_matches_ltxtquery(self) -> None:
        """Test ? operator (path matches ltxtquery text search)."""
        # "top.science.physics" ? "science & physics" = true
        result = self.strategy.build_sql(
            "matches_ltxtquery", "science & physics", self.path_sql, LTree
        )
        expected = "(data->>'path')::ltree ? 'science & physics'::ltxtquery"
        assert result.as_string(None) == expected

    def test_hierarchical_operators_complex_paths(self) -> None:
        """Test hierarchical operators with deeply nested paths."""
        # Test deeply nested ancestor relationship
        deep_ancestor = "top.academics.university.department.faculty.professor.research"
        result_ancestor = self.strategy.build_sql(
            "ancestor_of", deep_ancestor, self.path_sql, LTree
        )
        expected_ancestor = "(data->>'path')::ltree @> 'top.academics.university.department.faculty.professor.research'::ltree"
        assert result_ancestor.as_string(None) == expected_ancestor

        # Test complex lquery pattern
        complex_pattern = "top.academics.university.*.faculty.*"
        result_lquery = self.strategy.build_sql(
            "matches_lquery", complex_pattern, self.path_sql, LTree
        )
        expected_lquery = "(data->>'path')::ltree ~ 'top.academics.university.*.faculty.*'::lquery"
        assert result_lquery.as_string(None) == expected_lquery


class TestLTreeHierarchicalDirectFunctions:
    """Test ltree hierarchical operator functions directly."""

    def test_ancestor_of_direct(self):
        """Test ancestor_of function directly."""
        path_sql = SQL("data->>'path'")
        result = build_ancestor_of_sql(path_sql, "top.science.physics")
        sql_str = result.as_string(None)
        assert sql_str == "(data->>'path')::ltree @> 'top.science.physics'::ltree"

    def test_descendant_of_direct(self):
        """Test descendant_of function directly."""
        path_sql = SQL("data->>'path'")
        result = build_descendant_of_sql(path_sql, "top.science")
        sql_str = result.as_string(None)
        assert sql_str == "(data->>'path')::ltree <@ 'top.science'::ltree"

    def test_matches_lquery_direct(self):
        """Test matches_lquery function directly."""
        path_sql = SQL("data->>'path'")
        result = build_matches_lquery_sql(path_sql, "*.science.*")
        sql_str = result.as_string(None)
        assert sql_str == "(data->>'path')::ltree ~ '*.science.*'::lquery"

    def test_matches_ltxtquery_direct(self):
        """Test matches_ltxtquery function directly."""
        path_sql = SQL("data->>'path'")
        result = build_matches_ltxtquery_sql(path_sql, "science & physics")
        sql_str = result.as_string(None)
        assert sql_str == "(data->>'path')::ltree ? 'science & physics'::ltxtquery"


# ============================================================================
# DEPTH OPERATORS: depth_eq, depth_gt, depth_gte, depth_lt, depth_lte, depth_neq
# ============================================================================


class TestLTreeDepthOperators:
    """Test LTree depth (nlevel) operators."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_depth_eq_operator(self) -> None:
        """Test filtering paths by exact depth."""
        result = self.strategy.build_sql("depth_eq", 3, self.path_sql, LTree)
        expected = "nlevel((data->>'path')::ltree) = 3"
        assert result.as_string(None) == expected

    def test_depth_gt_operator(self) -> None:
        """Test filtering paths deeper than specified level."""
        result = self.strategy.build_sql("depth_gt", 2, self.path_sql, LTree)
        expected = "nlevel((data->>'path')::ltree) > 2"
        assert result.as_string(None) == expected

    def test_depth_gte_operator(self) -> None:
        """Test filtering paths at least as deep as specified level."""
        result = self.strategy.build_sql("depth_gte", 4, self.path_sql, LTree)
        expected = "nlevel((data->>'path')::ltree) >= 4"
        assert result.as_string(None) == expected

    def test_depth_lt_operator(self) -> None:
        """Test filtering paths shallower than specified level."""
        result = self.strategy.build_sql("depth_lt", 3, self.path_sql, LTree)
        expected = "nlevel((data->>'path')::ltree) < 3"
        assert result.as_string(None) == expected

    def test_depth_lte_operator(self) -> None:
        """Test filtering paths at most as deep as specified level."""
        result = self.strategy.build_sql("depth_lte", 2, self.path_sql, LTree)
        expected = "nlevel((data->>'path')::ltree) <= 2"
        assert result.as_string(None) == expected

    def test_depth_neq_operator(self) -> None:
        """Test filtering paths not equal to specified depth."""
        result = self.strategy.build_sql("depth_neq", 3, self.path_sql, LTree)
        expected = "nlevel((data->>'path')::ltree) != 3"
        assert result.as_string(None) == expected

    def test_depth_with_zero(self) -> None:
        """Test depth filtering with single-level paths."""
        result = self.strategy.build_sql("depth_eq", 1, self.path_sql, LTree)
        expected = "nlevel((data->>'path')::ltree) = 1"
        assert result.as_string(None) == expected


class TestLTreeDepthDirectFunctions:
    """Test ltree depth operator functions directly."""

    def test_depth_eq_direct(self):
        """Test depth equality function directly."""
        path_sql = SQL("data->>'path'")
        result = build_depth_eq_sql(path_sql, 3)
        sql_str = result.as_string(None)
        assert sql_str == "nlevel((data->>'path')::ltree) = 3"

    def test_depth_gt_direct(self):
        """Test depth greater than function directly."""
        path_sql = SQL("data->>'path'")
        result = build_depth_gt_sql(path_sql, 2)
        sql_str = result.as_string(None)
        assert sql_str == "nlevel((data->>'path')::ltree) > 2"

    def test_depth_gte_direct(self):
        """Test depth greater than or equal function directly."""
        path_sql = SQL("data->>'path'")
        result = build_depth_gte_sql(path_sql, 1)
        sql_str = result.as_string(None)
        assert sql_str == "nlevel((data->>'path')::ltree) >= 1"

    def test_depth_lt_direct(self):
        """Test depth less than function directly."""
        path_sql = SQL("data->>'path'")
        result = build_depth_lt_sql(path_sql, 5)
        sql_str = result.as_string(None)
        assert sql_str == "nlevel((data->>'path')::ltree) < 5"

    def test_depth_lte_direct(self):
        """Test depth less than or equal function directly."""
        path_sql = SQL("data->>'path'")
        result = build_depth_lte_sql(path_sql, 4)
        sql_str = result.as_string(None)
        assert sql_str == "nlevel((data->>'path')::ltree) <= 4"

    def test_depth_neq_direct(self):
        """Test depth inequality function directly."""
        path_sql = SQL("data->>'path'")
        result = build_depth_neq_sql(path_sql, 3)
        sql_str = result.as_string(None)
        assert sql_str == "nlevel((data->>'path')::ltree) != 3"


# ============================================================================
# ARRAY OPERATORS: matches_any_lquery, in_array, array_contains
# ============================================================================


class TestLTreeArrayOperators:
    """Test LTree array matching operators."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_ltree_matches_any_in_array(self) -> None:
        """Test ? operator with ltree array - matches any path."""
        patterns = ["top.science.*", "top.technology.*"]
        result = self.strategy.build_sql("matches_any_lquery", patterns, self.path_sql, LTree)
        expected = "(data->>'path')::ltree ? ARRAY['top.science.*', 'top.technology.*']"
        assert result.as_string(None) == expected

    def test_ltree_path_in_array(self) -> None:
        """Test <@ operator - path is contained in array."""
        valid_paths = ["top.science", "top.technology", "top.arts"]
        result = self.strategy.build_sql("in_array", valid_paths, self.path_sql, LTree)
        expected = "(data->>'path')::ltree <@ ARRAY['top.science'::ltree, 'top.technology'::ltree, 'top.arts'::ltree]"
        assert result.as_string(None) == expected

    def test_ltree_array_contains_path(self) -> None:
        """Test @> operator with path array - array contains path."""
        paths_array = ["top.science", "top.technology", "top.arts"]
        target_path = "top.science"
        result = self.strategy.build_sql(
            "array_contains", (paths_array, self.path_sql, target_path), LTree
        )
        expected = "ARRAY['top.science'::ltree, 'top.technology'::ltree, 'top.arts'::ltree] @> 'top.science'::ltree"
        assert result.as_string(None) == expected

    def test_matches_any_lquery_single_pattern(self) -> None:
        """Test matches_any_lquery with single pattern."""
        patterns = ["*.science.*"]
        result = self.strategy.build_sql("matches_any_lquery", patterns, self.path_sql, LTree)
        expected = "(data->>'path')::ltree ? ARRAY['*.science.*']"
        assert result.as_string(None) == expected

    def test_in_array_empty_list(self) -> None:
        """Test in_array with empty list."""
        result = self.strategy.build_sql("in_array", [], self.path_sql, LTree)
        expected = "(data->>'path')::ltree <@ ARRAY[]"
        assert result.as_string(None) == expected

    def test_matches_any_lquery_with_complex_patterns(self) -> None:
        """Test matches_any_lquery with complex lquery patterns."""
        patterns = ["top.*.physics", "*.science.*", "top.arts.music.*"]
        result = self.strategy.build_sql("matches_any_lquery", patterns, self.path_sql, LTree)
        expected = (
            "(data->>'path')::ltree ? ARRAY['top.*.physics', '*.science.*', 'top.arts.music.*']"
        )
        assert result.as_string(None) == expected

    def test_in_array_with_deep_paths(self) -> None:
        """Test in_array with deeply nested paths."""
        valid_paths = [
            "top.academics.university.department.faculty.professor",
            "top.academics.university.department.staff.admin",
            "top.business.company.division.team",
        ]
        result = self.strategy.build_sql("in_array", valid_paths, self.path_sql, LTree)
        expected = "(data->>'path')::ltree <@ ARRAY['top.academics.university.department.faculty.professor'::ltree, 'top.academics.university.department.staff.admin'::ltree, 'top.business.company.division.team'::ltree]"
        assert result.as_string(None) == expected


class TestLTreeArrayValidation:
    """Test validation for array operators."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_matches_any_lquery_requires_list(self) -> None:
        """Test that matches_any_lquery operator requires a list."""
        with pytest.raises(TypeError):
            self.strategy.build_sql("matches_any_lquery", "not-a-list", self.path_sql, LTree)

    def test_in_array_requires_list(self) -> None:
        """Test that in_array operator requires a list."""
        with pytest.raises(TypeError):
            self.strategy.build_sql("in_array", "not-a-list", self.path_sql, LTree)

    def test_array_contains_requires_tuple(self) -> None:
        """Test that array_contains operator requires a tuple (array, target)."""
        with pytest.raises((TypeError, ValueError)):
            self.strategy.build_sql("array_contains", ["top.science"], self.path_sql, LTree)


# ============================================================================
# PATH ANALYSIS OPERATORS: nlevel, subpath, index, index_eq, index_gte
# ============================================================================


class TestLTreePathAnalysisOperators:
    """Test LTree path analysis operators."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_ltree_nlevel_operator(self) -> None:
        """Test nlevel(ltree) - returns number of labels in path."""
        result = self.strategy.build_sql("nlevel", None, self.path_sql, LTree)
        expected = "nlevel((data->>'path')::ltree)"
        assert result.as_string(None) == expected

    def test_ltree_subpath_operator(self) -> None:
        """Test subpath(ltree, offset, len) - extract subpath."""
        offset, length = 1, 2
        result = self.strategy.build_sql("subpath", (offset, self.path_sql, length), LTree)
        expected = "subpath((data->>'path')::ltree, 1, 2)"
        assert result.as_string(None) == expected

    def test_ltree_subpath_from_start(self) -> None:
        """Test subpath from start (offset=0)."""
        offset, length = 0, 2
        result = self.strategy.build_sql("subpath", (offset, self.path_sql, length), LTree)
        expected = "subpath((data->>'path')::ltree, 0, 2)"
        assert result.as_string(None) == expected

    def test_ltree_subpath_single_element(self) -> None:
        """Test subpath extracting single element."""
        offset, length = 2, 1
        result = self.strategy.build_sql("subpath", (offset, self.path_sql, length), LTree)
        expected = "subpath((data->>'path')::ltree, 2, 1)"
        assert result.as_string(None) == expected

    def test_ltree_index_operator(self) -> None:
        """Test index(ltree, ltree) - position of sublabel."""
        sublabel = "science"
        result = self.strategy.build_sql("index", sublabel, self.path_sql, LTree)
        expected = "index((data->>'path')::ltree, 'science'::ltree)"
        assert result.as_string(None) == expected

    def test_ltree_index_eq_operator(self) -> None:
        """Test filtering by exact position of sublabel."""
        sublabel, position = "science", 1
        result = self.strategy.build_sql("index_eq", (sublabel, self.path_sql, position), LTree)
        expected = "index((data->>'path')::ltree, 'science'::ltree) = 1"
        assert result.as_string(None) == expected

    def test_ltree_index_gte_operator(self) -> None:
        """Test filtering by minimum position of sublabel."""
        sublabel, min_position = "physics", 2
        result = self.strategy.build_sql(
            "index_gte", (sublabel, self.path_sql, min_position), LTree
        )
        expected = "index((data->>'path')::ltree, 'physics'::ltree) >= 2"
        assert result.as_string(None) == expected

    def test_filter_by_sublabel_presence(self) -> None:
        """Test filtering paths that contain a specific sublabel."""
        sublabel, min_position = "science", 0
        result = self.strategy.build_sql(
            "index_gte", (sublabel, self.path_sql, min_position), LTree
        )
        expected = "index((data->>'path')::ltree, 'science'::ltree) >= 0"
        assert result.as_string(None) == expected


class TestLTreePathAnalysisValidation:
    """Test validation for path analysis operators."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_subpath_requires_tuple(self) -> None:
        """Test that subpath operator requires a tuple (offset, length)."""
        with pytest.raises((TypeError, ValueError)):
            self.strategy.build_sql("subpath", 1, self.path_sql, LTree)

    def test_index_eq_requires_tuple(self) -> None:
        """Test that index_eq operator requires a tuple (sublabel, position)."""
        with pytest.raises((TypeError, ValueError)):
            self.strategy.build_sql("index_eq", "science", self.path_sql, LTree)

    def test_index_gte_requires_tuple(self) -> None:
        """Test that index_gte operator requires a tuple (sublabel, min_position)."""
        with pytest.raises((TypeError, ValueError)):
            self.strategy.build_sql("index_gte", "physics", self.path_sql, LTree)


# ============================================================================
# PATH MANIPULATION OPERATORS: concat, lca
# ============================================================================


class TestLTreePathManipulationOperators:
    """Test LTree path manipulation operators."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_ltree_concat_operator(self) -> None:
        """Test || operator - concatenate paths."""
        suffix = "physics.quantum"
        result = self.strategy.build_sql("concat", suffix, self.path_sql, LTree)
        expected = "(data->>'path')::ltree || 'physics.quantum'::ltree"
        assert result.as_string(None) == expected

    def test_ltree_concat_single_label(self) -> None:
        """Test concatenating single label to path."""
        result = self.strategy.build_sql("concat", "physics", self.path_sql, LTree)
        expected = "(data->>'path')::ltree || 'physics'::ltree"
        assert result.as_string(None) == expected

    def test_ltree_concat_empty_string(self) -> None:
        """Test concatenating empty string."""
        result = self.strategy.build_sql("concat", "", self.path_sql, LTree)
        expected = "(data->>'path')::ltree || ''::ltree"
        assert result.as_string(None) == expected

    def test_ltree_lca_operator(self) -> None:
        """Test lca(ltree[]) - lowest common ancestor."""
        paths = ["top.science.physics", "top.science.chemistry", "top.science.biology"]
        result = self.strategy.build_sql("lca", paths, self.path_sql, LTree)
        expected = "lca(ARRAY['top.science.physics'::ltree, 'top.science.chemistry'::ltree, 'top.science.biology'::ltree])"
        assert result.as_string(None) == expected

    def test_ltree_lca_two_paths(self) -> None:
        """Test lca with just two paths."""
        paths = ["top.science", "top.technology"]
        result = self.strategy.build_sql("lca", paths, self.path_sql, LTree)
        expected = "lca(ARRAY['top.science'::ltree, 'top.technology'::ltree])"
        assert result.as_string(None) == expected

    def test_ltree_lca_single_path(self) -> None:
        """Test lca with single path (edge case)."""
        paths = ["top.science.physics"]
        result = self.strategy.build_sql("lca", paths, self.path_sql, LTree)
        expected = "lca(ARRAY['top.science.physics'::ltree])"
        assert result.as_string(None) == expected

    def test_concat_with_special_characters(self) -> None:
        """Test concat with paths containing underscores and numbers."""
        suffix = "version_2.release_1"
        result = self.strategy.build_sql("concat", suffix, self.path_sql, LTree)
        expected = "(data->>'path')::ltree || 'version_2.release_1'::ltree"
        assert result.as_string(None) == expected

    def test_lca_with_deep_paths(self) -> None:
        """Test lca with deeply nested paths."""
        paths = [
            "top.academics.university.department.faculty.professor.research.papers",
            "top.academics.university.department.faculty.professor.teaching.courses",
            "top.academics.university.department.staff.admin.budget",
        ]
        result = self.strategy.build_sql("lca", paths, self.path_sql, LTree)
        expected = "lca(ARRAY['top.academics.university.department.faculty.professor.research.papers'::ltree, 'top.academics.university.department.faculty.professor.teaching.courses'::ltree, 'top.academics.university.department.staff.admin.budget'::ltree])"
        assert result.as_string(None) == expected


class TestLTreePathManipulationValidation:
    """Test validation for path manipulation operators."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_lca_requires_list(self) -> None:
        """Test that lca operator requires a list of paths."""
        with pytest.raises(TypeError):
            self.strategy.build_sql("lca", "not-a-list", self.path_sql, LTree)

    def test_lca_empty_list(self) -> None:
        """Test lca with empty list."""
        with pytest.raises((TypeError, ValueError)):
            self.strategy.build_sql("lca", [], self.path_sql, LTree)


# ============================================================================
# EDGE CASES AND VALIDATION
# ============================================================================


class TestLTreeEdgeCases:
    """Test edge cases for LTree operators."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_special_characters_in_paths(self) -> None:
        """Test paths with underscores and numbers."""
        # Path with underscores
        result = self.strategy.build_sql("eq", "top.tech_category.web_dev", self.path_sql, LTree)
        expected = "(data->>'path')::ltree = 'top.tech_category.web_dev'::ltree"
        assert result.as_string(None) == expected

        # Path with numbers
        result = self.strategy.build_sql("eq", "top.version_2.release_1", self.path_sql, LTree)
        expected = "(data->>'path')::ltree = 'top.version_2.release_1'::ltree"
        assert result.as_string(None) == expected

    def test_single_level_paths(self) -> None:
        """Test operators with single-level paths."""
        # Single level equality
        result = self.strategy.build_sql("eq", "root", self.path_sql, LTree)
        expected = "(data->>'path')::ltree = 'root'::ltree"
        assert result.as_string(None) == expected

        # Single level ancestor_of
        result = self.strategy.build_sql("ancestor_of", "root.child", self.path_sql, LTree)
        expected = "(data->>'path')::ltree @> 'root.child'::ltree"
        assert result.as_string(None) == expected

    def test_deeply_nested_paths(self) -> None:
        """Test operators with deeply nested paths."""
        deep_path = "top.academics.university.department.faculty.professor.research.papers"

        # Deep equality
        result = self.strategy.build_sql("eq", deep_path, self.path_sql, LTree)
        expected = f"(data->>'path')::ltree = '{deep_path}'::ltree"
        assert result.as_string(None) == expected

        # Deep hierarchical relationship
        result = self.strategy.build_sql("ancestor_of", deep_path, self.path_sql, LTree)
        expected = f"(data->>'path')::ltree @> '{deep_path}'::ltree"
        assert result.as_string(None) == expected


# ============================================================================
# PATH COMPARISON OPERATORS: lt, gt, lte, gte
# ============================================================================


class TestLTreePathComparisonOperators:
    """Test LTree path comparison operators (lexicographic ordering)."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_path_lt_operator(self) -> None:
        """Test less than path comparison (lexicographic)."""
        result = self.strategy.build_sql("lt", "top.science", self.path_sql, LTree)
        expected = "(data->>'path')::ltree < 'top.science'::ltree"
        assert result.as_string(None) == expected

    def test_path_gt_operator(self) -> None:
        """Test greater than path comparison (lexicographic)."""
        result = self.strategy.build_sql("gt", "top.science", self.path_sql, LTree)
        expected = "(data->>'path')::ltree > 'top.science'::ltree"
        assert result.as_string(None) == expected

    def test_path_lte_operator(self) -> None:
        """Test less than or equal path comparison (lexicographic)."""
        result = self.strategy.build_sql("lte", "top.technology", self.path_sql, LTree)
        expected = "(data->>'path')::ltree <= 'top.technology'::ltree"
        assert result.as_string(None) == expected

    def test_path_gte_operator(self) -> None:
        """Test greater than or equal path comparison (lexicographic)."""
        result = self.strategy.build_sql("gte", "top.arts", self.path_sql, LTree)
        expected = "(data->>'path')::ltree >= 'top.arts'::ltree"
        assert result.as_string(None) == expected

    def test_path_comparison_with_deep_paths(self) -> None:
        """Test path comparison operators with deeply nested paths."""
        deep_path = "top.science.physics.quantum"

        # Less than
        result_lt = self.strategy.build_sql("lt", deep_path, self.path_sql, LTree)
        expected_lt = f"(data->>'path')::ltree < '{deep_path}'::ltree"
        assert result_lt.as_string(None) == expected_lt

        # Greater than
        result_gt = self.strategy.build_sql("gt", deep_path, self.path_sql, LTree)
        expected_gt = f"(data->>'path')::ltree > '{deep_path}'::ltree"
        assert result_gt.as_string(None) == expected_gt

        # Less than or equal
        result_lte = self.strategy.build_sql("lte", deep_path, self.path_sql, LTree)
        expected_lte = f"(data->>'path')::ltree <= '{deep_path}'::ltree"
        assert result_lte.as_string(None) == expected_lte

        # Greater than or equal
        result_gte = self.strategy.build_sql("gte", deep_path, self.path_sql, LTree)
        expected_gte = f"(data->>'path')::ltree >= '{deep_path}'::ltree"
        assert result_gte.as_string(None) == expected_gte

    def test_path_comparison_single_labels(self) -> None:
        """Test path comparison with single-label paths."""
        # Single label comparison
        result_lt = self.strategy.build_sql("lt", "animals", self.path_sql, LTree)
        expected_lt = "(data->>'path')::ltree < 'animals'::ltree"
        assert result_lt.as_string(None) == expected_lt

        result_gte = self.strategy.build_sql("gte", "plants", self.path_sql, LTree)
        expected_gte = "(data->>'path')::ltree >= 'plants'::ltree"
        assert result_gte.as_string(None) == expected_gte

    def test_path_comparison_are_operator_aliases(self) -> None:
        """Test that path comparisons work with ltree type."""
        # These operators should be recognized as valid for LTree type
        assert self.strategy.supports_operator("lt", LTree)
        assert self.strategy.supports_operator("gt", LTree)
        assert self.strategy.supports_operator("lte", LTree)
        assert self.strategy.supports_operator("gte", LTree)


class TestLTreeValidation:
    """Test LTree validation and error handling."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_ltree_in_requires_list(self) -> None:
        """Test that LTree IN operator requires a list."""
        with pytest.raises(TypeError, match="'in' operator requires a list"):
            build_ltree_in_sql(self.path_sql, "not-a-list")

    def test_ltree_notin_requires_list(self) -> None:
        """Test that LTree NOT IN operator requires a list."""
        with pytest.raises(TypeError, match="'notin' operator requires a list"):
            build_ltree_notin_sql(self.path_sql, "not-a-list")


# ============================================================================
# PHASE A: DEPTH AND INDEX OPERATORS FOR GRAPHQL SCHEMA
# ============================================================================


class TestLTreeDepthOperatorsGraphQL:
    """Test depth operators integrated with GraphQL schema."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_nlevel_eq_graphql_integration(self) -> None:
        """Test nlevel_eq operator generates correct SQL."""
        result = self.strategy.build_sql("nlevel_eq", 3, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "nlevel(" in sql_str
        assert "= 3" in sql_str
        assert "::ltree" in sql_str

    def test_nlevel_gt_graphql_integration(self) -> None:
        """Test nlevel_gt operator generates correct SQL."""
        result = self.strategy.build_sql("nlevel_gt", 2, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "nlevel(" in sql_str
        assert "> 2" in sql_str

    def test_nlevel_gte_graphql_integration(self) -> None:
        """Test nlevel_gte operator generates correct SQL."""
        result = self.strategy.build_sql("nlevel_gte", 1, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "nlevel(" in sql_str
        assert ">= 1" in sql_str

    def test_nlevel_lt_graphql_integration(self) -> None:
        """Test nlevel_lt operator generates correct SQL."""
        result = self.strategy.build_sql("nlevel_lt", 5, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "nlevel(" in sql_str
        assert "< 5" in sql_str

    def test_nlevel_lte_graphql_integration(self) -> None:
        """Test nlevel_lte operator generates correct SQL."""
        result = self.strategy.build_sql("nlevel_lte", 4, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "nlevel(" in sql_str
        assert "<= 4" in sql_str

    def test_nlevel_neq_graphql_integration(self) -> None:
        """Test nlevel_neq operator generates correct SQL."""
        result = self.strategy.build_sql("nlevel_neq", 2, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "nlevel(" in sql_str
        assert "!= 2" in sql_str

    def test_depth_eq_alias_graphql(self) -> None:
        """Test depth_eq alias works (should be same as nlevel_eq)."""
        result = self.strategy.build_sql("depth_eq", 3, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "nlevel(" in sql_str
        assert "= 3" in sql_str

    def test_depth_operators_are_recognized(self) -> None:
        """Test that all depth operators are recognized by strategy."""
        depth_operators = [
            "depth_eq",
            "depth_gt",
            "depth_gte",
            "depth_lt",
            "depth_lte",
            "depth_neq",
        ]
        for op in depth_operators:
            assert self.strategy.supports_operator(op, LTree), f"Operator {op} not supported"


class TestLTreeIndexOperatorsGraphQL:
    """Test index operators integrated with GraphQL schema."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_index_operator_graphql_integration(self) -> None:
        """Test index operator generates correct SQL."""
        result = self.strategy.build_sql("index", "science", self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "index(" in sql_str
        assert "science" in sql_str
        assert "::ltree" in sql_str

    def test_index_eq_operator_graphql_integration(self) -> None:
        """Test index_eq operator generates correct SQL."""
        result = self.strategy.build_sql("index_eq", ("science", self.path_sql, 1), LTree)
        sql_str = result.as_string(None)
        assert "index(" in sql_str
        assert "science" in sql_str
        assert "= 1" in sql_str

    def test_index_gte_operator_graphql_integration(self) -> None:
        """Test index_gte operator generates correct SQL."""
        result = self.strategy.build_sql("index_gte", ("physics", self.path_sql, 2), LTree)
        sql_str = result.as_string(None)
        assert "index(" in sql_str
        assert "physics" in sql_str
        assert ">= 2" in sql_str

    def test_index_operators_are_recognized(self) -> None:
        """Test that all index operators are recognized by strategy."""
        index_operators = ["index", "index_eq", "index_gte"]
        for op in index_operators:
            assert self.strategy.supports_operator(op, LTree), f"Operator {op} not supported"


# ============================================================================
# PHASE B: PATTERN MATCHING AND ARRAY OPERATORS FOR GRAPHQL SCHEMA
# ============================================================================


class TestLTreePatternMatchingGraphQL:
    """Test pattern matching operators integrated with GraphQL schema."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_matches_any_lquery_single_pattern(self) -> None:
        """Test matches_any_lquery with single pattern."""
        patterns = ["science.*"]
        result = self.strategy.build_sql("matches_any_lquery", patterns, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "?" in sql_str  # LQuery matching operator
        assert "ARRAY" in sql_str
        assert "::ltree" in sql_str

    def test_matches_any_lquery_multiple_patterns(self) -> None:
        """Test matches_any_lquery with multiple patterns."""
        patterns = ["science.*", "technology.*", "*.public"]
        result = self.strategy.build_sql("matches_any_lquery", patterns, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "?" in sql_str
        assert "ARRAY" in sql_str
        assert sql_str.count("'") >= 6  # At least 3 patterns with ltree casting

    def test_matches_any_lquery_complex_patterns(self) -> None:
        """Test matches_any_lquery with complex lquery patterns."""
        patterns = [
            "science.{2}.*",  # Exactly 2 levels then anything
            "*.astronomy.*",  # Anything then astronomy then anything
            "technology.*.public",  # Technology, any level, then public
        ]
        result = self.strategy.build_sql("matches_any_lquery", patterns, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "?" in sql_str
        assert "ARRAY" in sql_str

    def test_matches_any_lquery_is_recognized(self) -> None:
        """Test that matches_any_lquery operator is recognized."""
        assert self.strategy.supports_operator("matches_any_lquery", LTree)


class TestLTreeArrayOperatorsGraphQL:
    """Test array operators integrated with GraphQL schema."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_in_array_single_path(self) -> None:
        """Test in_array with single path."""
        paths = ["science.astronomy"]
        result = self.strategy.build_sql("in_array", paths, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "<@" in sql_str  # Path containment operator
        assert "ARRAY" in sql_str
        assert "::ltree" in sql_str

    def test_in_array_multiple_paths(self) -> None:
        """Test in_array with multiple allowed paths."""
        paths = ["science.astronomy", "science.biology", "science.physics"]
        result = self.strategy.build_sql("in_array", paths, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "<@" in sql_str
        assert "ARRAY" in sql_str
        assert sql_str.count("::ltree") >= 3

    def test_in_array_complex_paths(self) -> None:
        """Test in_array with deeply nested paths."""
        paths = [
            "org.dept.team.project.task",
            "org.admin.finance",
            "org.it.infrastructure.network",
        ]
        result = self.strategy.build_sql("in_array", paths, self.path_sql, LTree)
        sql_str = result.as_string(None)
        assert "<@" in sql_str
        assert "ARRAY" in sql_str

    def test_in_array_is_recognized(self) -> None:
        """Test that in_array operator is recognized."""
        assert self.strategy.supports_operator("in_array", LTree)

    def test_array_contains_operator(self) -> None:
        """Test array_contains operator (array field contains path)."""
        # Format: (array, target_path)
        array_val = ["public.documents", "shared.reports", "approved.archives"]
        target_path = "approved.archives"
        result = self.strategy.build_sql(
            "array_contains", (array_val, self.path_sql, target_path), LTree
        )
        sql_str = result.as_string(None)
        assert "@>" in sql_str  # Array containment operator
        assert "ARRAY" in sql_str
        assert "::ltree" in sql_str

    def test_array_contains_with_single_item_array(self) -> None:
        """Test array_contains with single item array."""
        array_val = ["public.documents"]
        target_path = "public.documents"
        result = self.strategy.build_sql(
            "array_contains", (array_val, self.path_sql, target_path), LTree
        )
        sql_str = result.as_string(None)
        assert "@>" in sql_str
        assert "ARRAY" in sql_str

    def test_array_contains_is_recognized(self) -> None:
        """Test that array_contains operator is recognized."""
        assert self.strategy.supports_operator("array_contains", LTree)


class TestLTreePhaseBAliasesAndEdgeCases:
    """Test Phase B operator aliases and edge cases."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.strategy = LTreeOperatorStrategy()
        self.path_sql = SQL("data->>'path'")

    def test_matches_any_lquery_requires_list(self) -> None:
        """Test that matches_any_lquery requires a list."""
        with pytest.raises(TypeError):
            self.strategy.build_sql("matches_any_lquery", "single-pattern", self.path_sql, LTree)

    def test_matches_any_lquery_rejects_empty_list(self) -> None:
        """Test that matches_any_lquery rejects empty pattern list."""
        with pytest.raises(ValueError):
            self.strategy.build_sql("matches_any_lquery", [], self.path_sql, LTree)

    def test_in_array_requires_list(self) -> None:
        """Test that in_array requires a list."""
        with pytest.raises(TypeError):
            self.strategy.build_sql("in_array", "single-path", self.path_sql, LTree)

    def test_array_contains_requires_tuple(self) -> None:
        """Test that array_contains requires tuple (array, target)."""
        with pytest.raises(TypeError):
            self.strategy.build_sql("array_contains", "not-a-tuple", self.path_sql, LTree)

    def test_array_contains_with_wrong_array_type(self) -> None:
        """Test that array_contains validates array is a list."""
        with pytest.raises(TypeError):
            self.strategy.build_sql(
                "array_contains", ("not-a-list", self.path_sql, "target"), LTree
            )
