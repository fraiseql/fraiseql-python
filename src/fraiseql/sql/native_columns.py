"""One answer to "does this field path have a flat SQL column?".

Three declarations can put a field on a real column instead of inside the JSONB
snapshot, and they are checked in a fixed order:

1. ``native_columns`` — a **set**, so it can only say "this field *is* a column"
   (``native_dimensions``, #337).
2. ``column_mapping`` — a **path → column dict**, so it also reaches a deep path
   whose column is named something else entirely (``column_mapping=`` /
   ``aggregation["native_dimension_mapping"]``, #467).
3. ``native_measures`` — the same shape as ``column_mapping``, for measure paths.

The order matters: a field that is itself a column wins over a mapped path. Two
different expressions for one logical field is how a GROUP BY constraint gets
violated, so every builder that renders such a field has to agree — which is the
reason this lives in one function rather than in each of them.
"""

from collections.abc import Mapping
from collections.abc import Set as AbstractSet


def resolve_native_column(
    field_path: str,
    *,
    native_columns: AbstractSet[str] | None = None,
    column_mapping: Mapping[str, str] | None = None,
    native_measures: Mapping[str, str] | None = None,
) -> str | None:
    """Return the flat SQL column *field_path* resolves to, or None for JSONB.

    Args:
        field_path:       Dotted field path, e.g. ``"dimensions.item.model.category"``.
        native_columns:   Field names that are themselves columns on the view.
        column_mapping:   Declared path → column names.
        native_measures:  Declared measure path → column names. Callers that
                          render a **sort key** must leave this out: a measure is
                          aggregated in the SELECT list, so sorting on its raw
                          column would not be grouped.

    Returns:
        The column name, or None when the path has to be read out of JSONB.
    """
    if native_columns and field_path in native_columns:
        return field_path
    if column_mapping and field_path in column_mapping:
        return column_mapping[field_path]
    if native_measures and field_path in native_measures:
        return native_measures[field_path]
    return None
