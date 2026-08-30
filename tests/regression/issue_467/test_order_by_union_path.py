"""Issue #467, third leg: ordering across a partial-period UNION.

Confirmed before writing any code, as the phase asked: the UNION builder already
orders on the wrapper. Every branch projects one column — the
``json_build_object(...)::text`` the Rust pipeline reads — and the statement ends
in ``ORDER BY 1``, a positional reference to it. There is no per-branch JSONB
path in a sort position to fix.

These tests pin that, and pin what used to be the gap next to it: ``order_by`` was
never passed to ``_build_partial_period_union_query`` at all, so a caller's sort was
accepted and silently discarded. Fixed with #468 — ``TestCallerOrderBy`` below is the
rewrite of the ``TestKnownGap`` that recorded it.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.db import FraiseQLRepository, _table_metadata, _type_registry, register_type_for_view

COLUMNS = {"id", "data", "date", "model_category"}
MAPPING = {"dimensions.item.model.category": "model_category"}
WHERE = {"date": {"gte": "2025-01-15"}}


class _Stats:
    """Stand-in for the reporter's @fraise_type analytics class."""


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    for view in [v for v in _table_metadata if v.startswith("v_467")]:
        del _table_metadata[view]
    for view in [v for v in _type_registry if v.startswith("v_467")]:
        del _type_registry[view]


def _register(view_name: str) -> None:
    register_type_for_view(
        view_name,
        _Stats,
        table_columns=COLUMNS,
        has_jsonb_data=True,
        jsonb_column="data",
        aggregation={
            "dimensions": "dimensions",
            "measures": {"measures.cost": "SUM"},
            "native_dimensions": ["date"],
            "native_dimension_mapping": MAPPING,
            "fine_grain_view": f"{view_name}_day",
            "time_grain_column": "date",
            "time_grain_trunc": "month",
        },
    )


def _make_pool() -> Any:
    mock_pool = MagicMock()
    ctx = mock_pool.connection.return_value
    ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
    ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_pool


async def _rendered_sql(view_name: str, **find_kwargs: Any) -> str:
    repo = FraiseQLRepository(_make_pool())
    info = MagicMock()
    info.schema = None

    with (
        patch(
            "fraiseql.core.ast_parser.extract_field_paths_from_info",
            return_value=[
                MagicMock(path=["date"]),
                MagicMock(path=["dimensions", "item", "model", "category"]),
                MagicMock(path=["measures", "cost"]),
            ],
        ),
        patch(
            "fraiseql.db.execute_via_rust_pipeline",
            new_callable=AsyncMock,
            return_value=b'{"data":{"x":[]}}',
        ) as mock_execute,
    ):
        await repo.find(view_name, info=info, where=WHERE, **find_kwargs)

    return mock_execute.call_args[0][1].as_string(None)


class TestUnionOrdering:
    @pytest.mark.asyncio
    async def test_union_orders_on_the_wrapper_column(self) -> None:
        _register("v_467_union_order")

        rendered = await _rendered_sql("v_467_union_order")

        assert "UNION ALL" in rendered
        assert rendered.endswith(" ORDER BY 1")
        # Exactly one sort position, on the single projected column.
        assert rendered.count("ORDER BY") == 1

    @pytest.mark.asyncio
    async def test_no_per_branch_jsonb_path_in_a_sort_position(self) -> None:
        _register("v_467_union_order_paths")

        rendered = await _rendered_sql("v_467_union_order_paths")

        after_order_by = rendered[rendered.index("ORDER BY") :]
        assert "->" not in after_order_by
        assert after_order_by == "ORDER BY 1"

    @pytest.mark.asyncio
    async def test_mapped_group_by_key_is_native_in_every_branch(self) -> None:
        """The sort is positional, so the branch keys still have to line up."""
        _register("v_467_union_order_keys")

        rendered = await _rendered_sql("v_467_union_order_keys")

        branches = rendered.count("UNION ALL") + 1
        assert rendered.count("GROUP BY") == branches
        assert rendered.count('"t"."model_category"') >= branches


class TestCallerOrderBy:
    """``order_by`` now reaches the UNION query (#468).

    Every branch projects exactly one column, so a sort key has to be projected
    alongside it and referenced from an outer SELECT — that keeps the statement's
    output at the single ``json_build_object(...)::text`` column the Rust pipeline
    reads, while sorting on a typed expression rather than on the JSON text.
    """

    @pytest.mark.asyncio
    async def test_mapped_dimension_path_orders_on_the_flat_column(self) -> None:
        _register("v_467_union_order_mapped")

        rendered = await _rendered_sql(
            "v_467_union_order_mapped",
            order_by={"dimensions": {"item": {"model": {"category": "desc"}}}},
        )

        branches = rendered.count("UNION ALL") + 1
        assert rendered.endswith(' ORDER BY "u"."s0" DESC')
        # The sort key is projected once per branch, as the mapped flat column.
        assert rendered.count('"t"."model_category"') >= 2 * branches
        assert "ORDER BY 1" not in rendered

    @pytest.mark.asyncio
    async def test_native_dimension_orders_on_the_branch_expression(self) -> None:
        """``date`` is truncated per branch — the sort must use the same expression."""
        _register("v_467_union_order_native")

        rendered = await _rendered_sql("v_467_union_order_native", order_by={"date": "asc"})

        assert rendered.endswith(' ORDER BY "u"."s0" ASC')
        assert "ORDER BY 1" not in rendered

    @pytest.mark.asyncio
    async def test_measure_alias_orders_on_the_aggregate(self) -> None:
        _register("v_467_union_order_measure")

        rendered = await _rendered_sql(
            "v_467_union_order_measure", order_by={"measures": {"cost": "desc"}}
        )

        assert rendered.endswith(' ORDER BY "u"."s0" DESC')

    @pytest.mark.asyncio
    async def test_outer_select_projects_exactly_one_column(self) -> None:
        """The Rust pipeline reads ``row[0]``; the sort keys must not reach it."""
        _register("v_467_union_order_shape")

        rendered = await _rendered_sql(
            "v_467_union_order_shape",
            order_by={"dimensions": {"item": {"model": {"category": "desc"}}}},
        )

        assert rendered.startswith('SELECT "u"."d" FROM (')
        assert ') AS "u"("d", "s0") ORDER BY ' in rendered

    @pytest.mark.asyncio
    async def test_two_sort_keys_are_projected_separately(self) -> None:
        """The bare-dict form, which is the one that recurses into nested paths.

        The list-of-dicts form collapses ``{"measures": {"cost": "desc"}}`` to
        ``measures`` ASC before it ever reaches column resolution — input parsing,
        pre-existing, and recorded in phase 03's notes rather than fixed here.
        """
        _register("v_467_union_order_two")

        rendered = await _rendered_sql(
            "v_467_union_order_two",
            order_by={"date": "asc", "measures": {"cost": "desc"}},
        )

        assert ') AS "u"("d", "s0", "s1") ORDER BY ' in rendered
        assert rendered.endswith(' ORDER BY "u"."s0" ASC, "u"."s1" DESC')

    @pytest.mark.asyncio
    async def test_unsortable_field_falls_back_to_the_wrapper_column(self) -> None:
        """An aggregated query can only sort on a grouped key or a measure.

        A field that is neither is skipped rather than emitted as invalid SQL.
        """
        _register("v_467_union_order_unknown")

        rendered = await _rendered_sql("v_467_union_order_unknown", order_by={"nope": "desc"})

        assert rendered.endswith(" ORDER BY 1")
        assert "DESC" not in rendered

    @pytest.mark.asyncio
    async def test_no_order_by_is_byte_identical_to_before(self) -> None:
        """No sort requested → today's exact statement, unwrapped."""
        _register("v_467_union_order_none")

        rendered = await _rendered_sql("v_467_union_order_none")

        assert rendered.startswith("SELECT json_build_object(")
        assert rendered.endswith(" ORDER BY 1")
        assert ' AS "u"(' not in rendered
