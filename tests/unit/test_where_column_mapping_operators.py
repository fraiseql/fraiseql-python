"""Every operator on a mapped path must emit column SQL, not a JSONB extraction.

The rewrite changes only where a condition reads from — the operator, the value
and the field path are untouched — so the sweep is a guard against a per-strategy
gap in ``FieldCondition.to_sql()``: an operator handled under ``jsonb_path`` but
missing from the ``sql_column`` / ``fk_column`` branches would silently change
shape here.
"""

from uuid import UUID

import pytest

from fraiseql.where_clause import FieldCondition, WhereClause
from fraiseql.where_normalization import _apply_column_mapping

PATH = ["dimensions", "item", "model", "category"]
MAPPING = {"dimensions.item.model.category": "model_category"}
COLUMNS = {"id", "data", "model_category", "item_id"}


def _render(operator: str, value: object, mapping: dict[str, str] = MAPPING) -> str:
    path = next(iter(mapping)).split(".")
    clause = WhereClause(
        conditions=[
            FieldCondition(
                field_path=path,
                operator=operator,
                value=value,
                lookup_strategy="jsonb_path",
                target_column="data",
                jsonb_path=path,
            )
        ]
    )
    sql, _params = _apply_column_mapping(clause, mapping, COLUMNS).to_sql()
    return sql.as_string(None)


@pytest.mark.parametrize(
    ("operator", "value"),
    [
        ("eq", "laser"),
        ("neq", "laser"),
        ("in", ["laser", "inkjet"]),
        ("nin", ["laser", "inkjet"]),
        # 'notin' is an alias outside CONTAINMENT_OPERATORS, so to_sql() emits a
        # single placeholder for the whole list — a pre-existing gap shared by
        # the JSONB and column branches alike. The sweep asserts only that the
        # rewrite reaches it; expanding it is not this phase's business.
        ("notin", ["laser", "inkjet"]),
        ("isnull", True),
        ("contains", "las"),
        ("gt", "a"),
        ("gte", "a"),
        ("lt", "z"),
        ("lte", "z"),
        ("startswith", "las"),
        ("icontains", "LAS"),
    ],
)
def test_operator_emits_column_sql(operator: str, value: object) -> None:
    rendered = _render(operator, value)

    assert '"model_category"' in rendered
    assert '"data"' not in rendered
    assert "->" not in rendered


@pytest.mark.parametrize(
    ("operator", "value"),
    [
        ("eq", UUID("11111111-1111-1111-1111-111111111111")),
        ("in", [UUID("11111111-1111-1111-1111-111111111111")]),
        ("isnull", False),
    ],
)
def test_fk_target_operators_emit_column_sql(operator: str, value: object) -> None:
    rendered = _render(operator, value, {"dimensions.item.id": "item_id"})

    assert '"item_id"' in rendered
    assert '"data"' not in rendered
    assert "->" not in rendered


def test_containment_keeps_one_placeholder_per_value() -> None:
    """psycopg3 needs individual placeholders — the rewrite must not collapse them."""
    path = ["dimensions", "item", "model", "category"]
    clause = WhereClause(
        conditions=[
            FieldCondition(
                field_path=path,
                operator="in",
                value=["laser", "inkjet"],
                lookup_strategy="jsonb_path",
                target_column="data",
                jsonb_path=path,
            )
        ]
    )

    sql, params = _apply_column_mapping(clause, MAPPING, COLUMNS).to_sql()

    assert sql.as_string(None).count("%s") == 2
    assert params == ["laser", "inkjet"]


def test_values_are_no_longer_stringified() -> None:
    """JSONB text extraction coerces every value to str; a real column must not."""
    path = ["dimensions", "item", "model", "count"]
    clause = WhereClause(
        conditions=[
            FieldCondition(
                field_path=path,
                operator="gte",
                value=42,
                lookup_strategy="jsonb_path",
                target_column="data",
                jsonb_path=path,
            )
        ]
    )

    _sql, params = _apply_column_mapping(
        clause, {"dimensions.item.model.count": "model_count"}, COLUMNS | {"model_count"}
    ).to_sql()

    assert params == [42]
