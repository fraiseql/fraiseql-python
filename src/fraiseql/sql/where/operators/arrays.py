"""Array operators for PostgreSQL array filtering."""

from psycopg.sql import SQL, Composed, Literal


def build_array_eq_sql(path_sql: SQL, value: list) -> Composed:
    """Build SQL for array equality."""
    # Compare JSONB arrays directly
    import json

    json_str = json.dumps(value)
    # Literal quotes the JSON itself
    return Composed([path_sql, SQL(" = "), Literal(json_str), SQL("::jsonb")])


def build_array_neq_sql(path_sql: SQL, value: list) -> Composed:
    """Build SQL for array inequality."""
    # Compare JSONB arrays directly
    import json

    json_str = json.dumps(value)
    return Composed([path_sql, SQL(" != "), Literal(json_str), SQL("::jsonb")])


def build_array_contains_sql(path_sql: SQL, value: list) -> Composed:
    """Build SQL for array contains operator (@> in PostgreSQL)."""
    import json

    json_str = json.dumps(value)
    # Use @> operator: left_array @> right_array means left contains right
    return Composed([path_sql, SQL(" @> "), Literal(json_str), SQL("::jsonb")])


def build_array_contained_by_sql(path_sql: SQL, value: list) -> Composed:
    """Build SQL for array contained_by operator (<@ in PostgreSQL)."""
    import json

    json_str = json.dumps(value)
    # Use <@ operator: left_array <@ right_array means left is contained by right
    return Composed([path_sql, SQL(" <@ "), Literal(json_str), SQL("::jsonb")])


def build_array_overlaps_sql(path_sql: SQL, value: list) -> Composed:
    """Build SQL for array overlaps with automatic detection of native vs JSONB arrays.

    PostgreSQL has two array systems:
    1. Native arrays (TEXT[], INTEGER[], etc.) - use && operator
    2. JSONB arrays (stored in JSONB columns) - use ?| operator

    This function detects which type we're working with and generates the appropriate SQL.
    """
    from psycopg.sql import Identifier

    # Detect if this is a native column or JSONB path
    # Native columns come as Identifier("column_name")
    # JSONB paths come as Composed([Identifier("data"), SQL(" -> "), Literal("field")])
    is_native_column = isinstance(path_sql, Identifier)

    if is_native_column:
        # Native PostgreSQL array column - use && operator
        # Build ARRAY['item1', 'item2', ...] for the right-hand side
        import json

        json_str = json.dumps(value)
        # Cast to array type for native array comparison
        return Composed([path_sql, SQL(" && "), Literal(json_str), SQL("::text[]")])
    # JSONB array field - use ?| operator for element existence check
    # Build {"item1", "item2", ...} syntax for ?| operator
    if isinstance(value, list):
        array_elements = [str(item) for item in value]
        array_str = "{" + ",".join(f'"{elem}"' for elem in array_elements) + "}"
        return Composed([path_sql, SQL(" ?| "), Literal(array_str)])
    # Fallback for non-list values
    return Composed([path_sql, SQL(" ? "), Literal(str(value))])


def build_array_len_eq_sql(path_sql: SQL, value: int) -> Composed:
    """Build SQL for array length equality."""
    return Composed([SQL("jsonb_array_length("), path_sql, SQL(") = "), Literal(value)])


def build_array_len_neq_sql(path_sql: SQL, value: int) -> Composed:
    """Build SQL for array length inequality."""
    return Composed([SQL("jsonb_array_length("), path_sql, SQL(") != "), Literal(value)])


def build_array_len_gt_sql(path_sql: SQL, value: int) -> Composed:
    """Build SQL for array length greater than."""
    return Composed([SQL("jsonb_array_length("), path_sql, SQL(") > "), Literal(value)])


def build_array_len_gte_sql(path_sql: SQL, value: int) -> Composed:
    """Build SQL for array length greater than or equal."""
    return Composed([SQL("jsonb_array_length("), path_sql, SQL(") >= "), Literal(value)])


def build_array_len_lt_sql(path_sql: SQL, value: int) -> Composed:
    """Build SQL for array length less than."""
    return Composed([SQL("jsonb_array_length("), path_sql, SQL(") < "), Literal(value)])


def build_array_len_lte_sql(path_sql: SQL, value: int) -> Composed:
    """Build SQL for array length less than or equal."""
    return Composed([SQL("jsonb_array_length("), path_sql, SQL(") <= "), Literal(value)])


def build_array_any_eq_sql(path_sql: SQL, value: str) -> Composed:
    """Build SQL for array any element equals operator using ANY()."""
    # Use ANY() to check if the value equals any element in the array
    return Composed(
        [
            Literal(value),
            SQL(" = ANY(ARRAY(SELECT jsonb_array_elements_text("),
            path_sql,
            SQL(")))"),
        ]
    )


def build_array_all_eq_sql(path_sql: SQL, value: str) -> Composed:
    """Build SQL for array all elements equal operator using ALL()."""
    # Use ALL() to check if the value equals all elements in the array
    return Composed(
        [
            Literal(value),
            SQL(" = ALL(ARRAY(SELECT jsonb_array_elements_text("),
            path_sql,
            SQL(")))"),
        ]
    )
