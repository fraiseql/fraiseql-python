"""Issue #467, third leg: ordering across a partial-period UNION.

Confirmed before writing any code, as the phase asked: the UNION builder already
orders on the wrapper. Every branch projects one column — the
``json_build_object(...)::text`` the Rust pipeline reads — and the statement ends
in ``ORDER BY 1``, a positional reference to it. There is no per-branch JSONB
path in a sort position to fix.

These tests pin that, and pin the gap next to it.
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


class TestKnownGap:
    """Not a desired property — a gap pinned so a future fix trips this loudly."""

    @pytest.mark.asyncio
    async def test_caller_order_by_does_not_reach_the_union_query(self) -> None:
        """``order_by`` is never passed to ``_build_partial_period_union_query``.

        Same family as #467 — a declaration accepted and silently discarded — but
        a different mechanism, so it is recorded here rather than fixed in this
        phase. When it is fixed, this test should be rewritten, not deleted.
        """
        _register("v_467_union_order_dropped")

        rendered = await _rendered_sql(
            "v_467_union_order_dropped",
            order_by={"dimensions": {"item": {"model": {"category": "desc"}}}},
        )

        assert rendered.endswith(" ORDER BY 1")
        assert "DESC" not in rendered
