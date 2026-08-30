"""ORDER BY on a declared column mapping — the third leg (issue #467, adjacent).

``native_columns`` is a *set of column names*, so it can express "this top-level
field is a flat column" and nothing more. A declared mapping is a *path → column*
dict, which does not fit that shape, so it was never passed to the ORDER BY
generator at all: sorting on ``dimensions.item.model.category`` re-ran the whole
``jsonb_build_object`` per row, on a key the SELECT list had already computed
natively.

The expression this produces must be byte-identical to the one the GROUP BY
builder produces for the same path — PostgreSQL requires a sort key to be grouped
or functionally determined by the grouping, and two different expressions for one
logical field is exactly how that constraint gets violated.
"""

import pytest

from fraiseql.sql.order_by_generator import OrderBy, OrderBySet, OrderDirection

MAPPING = {"dimensions.item.model.category": "model_category"}


def _sql(order_by: OrderBy, **kwargs: object) -> str:
    return order_by.to_sql("data", **kwargs).as_string(None)


class TestOrderByColumnMapping:
    def test_mapped_path_sorts_on_the_column(self) -> None:
        rendered = _sql(OrderBy(field="dimensions.item.model.category"), column_mapping=MAPPING)

        assert rendered == '"t"."model_category" ASC'

    def test_direction_is_preserved(self) -> None:
        rendered = _sql(
            OrderBy(field="dimensions.item.model.category", direction=OrderDirection.DESC),
            column_mapping=MAPPING,
        )

        assert rendered == '"t"."model_category" DESC'

    def test_string_direction_is_preserved(self) -> None:
        rendered = _sql(
            OrderBy(field="dimensions.item.model.category", direction="desc"),
            column_mapping=MAPPING,
        )

        assert rendered == '"t"."model_category" DESC'

    def test_unmapped_path_is_unchanged(self) -> None:
        """Byte-identical to today for anything the mapping does not name."""
        order_by = OrderBy(field="dimensions.item.model.name")

        assert _sql(order_by, column_mapping=MAPPING) == _sql(order_by)
        assert _sql(order_by) == "data -> 'dimensions' -> 'item' -> 'model' -> 'name' ASC"

    def test_no_mapping_is_unchanged(self) -> None:
        order_by = OrderBy(field="dimensions.item.model.category")

        assert _sql(order_by, column_mapping=None) == _sql(order_by)

    def test_column_identifier_is_quoted(self) -> None:
        """The target comes from a registration, but it still goes through Identifier."""
        rendered = _sql(OrderBy(field="x"), column_mapping={"x": 'weird"; DROP TABLE t; --'})

        assert "DROP TABLE t" in rendered
        assert rendered.startswith('"t"."weird""; DROP TABLE t; --"')


class TestPrecedence:
    """Same precedence as the GROUP BY builder, or the two expressions diverge."""

    def test_native_column_wins_over_a_mapping_on_the_same_field(self) -> None:
        rendered = _sql(
            OrderBy(field="date"),
            native_columns={"date"},
            column_mapping={"date": "period_date"},
        )

        assert rendered == '"t"."date" ASC'

    def test_mapping_applies_where_native_columns_does_not_reach(self) -> None:
        rendered = _sql(
            OrderBy(field="dimensions.item.model.category"),
            native_columns={"date"},
            column_mapping=MAPPING,
        )

        assert rendered == '"t"."model_category" ASC'


class TestMatchesGroupByExpression:
    """The sort key must render exactly as the GROUP BY key for the same path."""

    @pytest.mark.parametrize(
        ("field", "native_columns", "column_mapping"),
        [
            ("date", {"date"}, MAPPING),
            ("dimensions.item.model.category", {"date"}, MAPPING),
        ],
    )
    def test_expression_matches_build_field(
        self, field: str, native_columns: set[str], column_mapping: dict[str, str]
    ) -> None:
        from fraiseql.db import _build_non_jsonb_field_expr

        expected_column = field if field in native_columns else column_mapping[field]
        group_by_expr = _build_non_jsonb_field_expr(expected_column, "t").as_string(None)

        rendered = _sql(
            OrderBy(field=field),
            native_columns=native_columns,
            column_mapping=column_mapping,
        )

        assert rendered == f"{group_by_expr} ASC"


class TestOrderBySet:
    def test_set_threads_the_mapping_to_every_instruction(self) -> None:
        order_set = OrderBySet(
            [
                OrderBy(field="date", direction="asc"),
                OrderBy(field="dimensions.item.model.category", direction="desc"),
                OrderBy(field="dimensions.item.model.name", direction="asc"),
            ]
        )

        rendered = order_set.to_sql(
            "data", native_columns={"date"}, column_mapping=MAPPING
        ).as_string(None)

        assert rendered == (
            'ORDER BY "t"."date" ASC, '
            '"t"."model_category" DESC, '
            "data -> 'dimensions' -> 'item' -> 'model' -> 'name' ASC"
        )

    def test_set_without_a_mapping_is_unchanged(self) -> None:
        order_set = OrderBySet([OrderBy(field="dimensions.item.model.category")])

        assert order_set.to_sql("data", column_mapping=None).as_string(None) == order_set.to_sql(
            "data"
        ).as_string(None)
