"""LTree hierarchical path operators for building SQL WHERE conditions.

This module provides clean functions to build SQL for LTree hierarchical operations
using proper PostgreSQL ltree casting and specialized hierarchical operators.

Basic comparison operators use the generic base builders. LTree-specific hierarchical
operators (@>, <@, ~, ?) are implemented directly as they have no generic equivalent.
"""

from psycopg.sql import SQL, Composed, Literal

from .base_builders import build_comparison_sql, build_in_list_sql


def build_ltree_eq_sql(path_sql: SQL, value: str) -> Composed:
    """Build SQL for LTree equality with proper ltree casting.

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: LTree path string value

    Returns:
        Composed SQL: (path)::ltree = 'value'::ltree
    """
    return build_comparison_sql(path_sql, value, "=", "ltree")


def build_ltree_neq_sql(path_sql: SQL, value: str) -> Composed:
    """Build SQL for LTree inequality with proper ltree casting.

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: LTree path string value

    Returns:
        Composed SQL: (path)::ltree != 'value'::ltree
    """
    return build_comparison_sql(path_sql, value, "!=", "ltree")


def build_ltree_in_sql(path_sql: SQL, value: list[str]) -> Composed:
    """Build SQL for LTree IN list with proper ltree casting.

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: List of LTree path strings

    Returns:
        Composed SQL: (path)::ltree IN ('val1'::ltree, 'val2'::ltree, ...)

    Raises:
        TypeError: If value is not a list
    """
    return build_in_list_sql(path_sql, value, "IN", "ltree")


def build_ltree_notin_sql(path_sql: SQL, value: list[str]) -> Composed:
    """Build SQL for LTree NOT IN list with proper ltree casting.

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: List of LTree path strings

    Returns:
        Composed SQL: (path)::ltree NOT IN ('val1'::ltree, 'val2'::ltree, ...)

    Raises:
        TypeError: If value is not a list
    """
    return build_in_list_sql(path_sql, value, "NOT IN", "ltree")


# LTree-specific hierarchical operators (no generic equivalent)


def build_ancestor_of_sql(path_sql: SQL, value: str) -> Composed:
    """Build SQL for LTree ancestor_of (@>) relationship.

    The @> operator checks if the left path is an ancestor of the right path.

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: LTree path string value to check as descendant

    Returns:
        Composed SQL: (path)::ltree @> 'value'::ltree
    """
    return Composed([SQL("("), path_sql, SQL(")::ltree @> "), Literal(value), SQL("::ltree")])


def build_descendant_of_sql(path_sql: SQL, value: str) -> Composed:
    """Build SQL for LTree descendant_of (<@) relationship.

    The <@ operator checks if the left path is a descendant of the right path.

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: LTree path string value to check as ancestor

    Returns:
        Composed SQL: (path)::ltree <@ 'value'::ltree
    """
    return Composed([SQL("("), path_sql, SQL(")::ltree <@ "), Literal(value), SQL("::ltree")])


def build_matches_lquery_sql(path_sql: SQL, value: str) -> Composed:
    """Build SQL for LTree matches_lquery (~) pattern matching.

    The ~ operator checks if the left path matches the lquery pattern.

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: lquery pattern string (e.g., "science.*")

    Returns:
        Composed SQL: (path)::ltree ~ 'pattern'::lquery
    """
    return Composed([SQL("("), path_sql, SQL(")::ltree ~ "), Literal(value), SQL("::lquery")])


def build_matches_ltxtquery_sql(path_sql: SQL, value: str) -> Composed:
    """Build SQL for LTree matches_ltxtquery (?) text query.

    The @ operator checks if the left path matches the ltxtquery text pattern.

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: ltxtquery text pattern string

    Returns:
        Composed SQL: (path)::ltree @ 'pattern'::ltxtquery
    """
    return Composed([SQL("("), path_sql, SQL(")::ltree @ "), Literal(value), SQL("::ltxtquery")])


# Depth operators for ltree paths


def build_depth_eq_sql(path_sql: SQL, value: int) -> Composed:
    """Build SQL for LTree depth equality check using nlevel().

    The nlevel() function returns the depth (number of levels) in an ltree path.

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: Integer depth value to compare

    Returns:
        Composed SQL: nlevel((path)::ltree) = value

    Example:
        nlevel('science.physics.quantum'::ltree) = 3
    """
    return Composed([SQL("nlevel(("), path_sql, SQL(")::ltree) = "), Literal(value)])


def build_depth_gt_sql(path_sql: SQL, value: int) -> Composed:
    """Build SQL for LTree depth greater than check using nlevel().

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: Integer depth value to compare

    Returns:
        Composed SQL: nlevel((path)::ltree) > value
    """
    return Composed([SQL("nlevel(("), path_sql, SQL(")::ltree) > "), Literal(value)])


def build_depth_gte_sql(path_sql: SQL, value: int) -> Composed:
    """Build SQL for LTree depth greater than or equal check using nlevel().

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: Integer depth value to compare

    Returns:
        Composed SQL: nlevel((path)::ltree) >= value
    """
    return Composed([SQL("nlevel(("), path_sql, SQL(")::ltree) >= "), Literal(value)])


def build_depth_lt_sql(path_sql: SQL, value: int) -> Composed:
    """Build SQL for LTree depth less than check using nlevel().

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: Integer depth value to compare

    Returns:
        Composed SQL: nlevel((path)::ltree) < value
    """
    return Composed([SQL("nlevel(("), path_sql, SQL(")::ltree) < "), Literal(value)])


def build_depth_lte_sql(path_sql: SQL, value: int) -> Composed:
    """Build SQL for LTree depth less than or equal check using nlevel().

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: Integer depth value to compare

    Returns:
        Composed SQL: nlevel((path)::ltree) <= value
    """
    return Composed([SQL("nlevel(("), path_sql, SQL(")::ltree) <= "), Literal(value)])


def build_depth_neq_sql(path_sql: SQL, value: int) -> Composed:
    """Build SQL for LTree depth inequality check using nlevel().

    Args:
        path_sql: The SQL path expression (e.g., data->>'category_path')
        value: Integer depth value to compare

    Returns:
        Composed SQL: nlevel((path)::ltree) != value
    """
    return Composed([SQL("nlevel(("), path_sql, SQL(")::ltree) != "), Literal(value)])
