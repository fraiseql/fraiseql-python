"""Issue #468, Cycle 3: which date bounds may trigger the partial-period rewrite.

The UNION builder re-encodes the date bounds as per-branch ``AND`` literals. That
is only equivalent to the caller's filter when the bound is a top-level conjunct.
Two shapes are therefore excluded, and this pins both:

* a date bound nested inside an ``OR`` group — ``_extract_lower_date_bound`` only
  scans top-level conditions, so it never fired; now that the group survives the
  rebuild (#468) this has to stay true, or the predicate would appear both as a
  branch literal and inside the preserved group;
* a clause whose top-level conditions are ``OR``-joined — the rewrite would turn
  ``date >= X OR status = 'a'`` into ``date in [branch] AND status = 'a'`` and
  silently drop every row that matched on the date alone.

Both fall back to the standard single-statement query, which is correct and merely
unoptimised.
"""

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.db import FraiseQLRepository, _table_metadata, _type_registry, register_type_for_view
from fraiseql.where_clause import FieldCondition, WhereClause

COLUMNS = {"id", "data", "date", "status", "model_category"}


class _Stats:
    """Stand-in for an aggregated analytics type."""


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    for view in [v for v in _table_metadata if v.startswith("v_468")]:
        del _table_metadata[view]
    for view in [v for v in _type_registry if v.startswith("v_468")]:
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
            "native_dimension_mapping": {"dimensions.item.model.category": "model_category"},
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


async def _rendered(view_name: str, **find_kwargs: Any) -> tuple[str, list[Any]]:
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
        await repo.find(view_name, info=info, **find_kwargs)

    call = mock_execute.call_args[0]
    return call[1].as_string(None), list(call[2] or [])


class TestDateBoundInsideOrGroup:
    @pytest.mark.asyncio
    async def test_nested_date_bound_does_not_route_through_the_union(self) -> None:
        _register("v_468_or_date")

        rendered, params = await _rendered(
            "v_468_or_date",
            where={
                "OR": [
                    {"date": {"gte": "2025-01-15"}},
                    {"status": {"eq": "active"}},
                ]
            },
        )

        assert "UNION ALL" not in rendered
        # The whole OR group survives, exactly once, as the caller wrote it.
        assert rendered.count(" OR ") == 1
        assert rendered.count('"date"') >= 1
        assert rendered.count('"status"') == 1
        assert params == ["2025-01-15", "active"]

    @pytest.mark.asyncio
    async def test_a_top_level_bound_alongside_an_or_group_still_routes(self) -> None:
        """The exclusion is about *where* the bound sits, not about OR being present."""
        _register("v_468_or_date_mixed")

        rendered, _ = await _rendered(
            "v_468_or_date_mixed",
            where={
                "date": {"gte": "2025-01-15"},
                "OR": [{"status": {"eq": "active"}}, {"status": {"eq": "pending"}}],
            },
        )

        assert "UNION ALL" in rendered


class TestOrJoinedTopLevelConditions:
    @pytest.mark.asyncio
    async def test_or_joined_conditions_do_not_route_through_the_union(self) -> None:
        """``logical_op="OR"`` reaches here via a pre-built WhereClause (#468).

        ``_normalize_where`` returns a ``WhereClause`` unchanged, so a caller can
        hand one in directly. Its top-level conditions are then OR-joined, and
        pulling the date bound out to per-branch ``AND`` literals would widen the
        date filter into a mandatory one.
        """
        _register("v_468_or_joined")

        where = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["date"],
                    operator="gte",
                    value=date(2025, 1, 15),
                    lookup_strategy="sql_column",
                    target_column="date",
                ),
                FieldCondition(
                    field_path=["status"],
                    operator="eq",
                    value="active",
                    lookup_strategy="sql_column",
                    target_column="status",
                ),
            ],
            logical_op="OR",
        )

        rendered, params = await _rendered("v_468_or_joined", where=where)

        assert "UNION ALL" not in rendered
        assert " OR " in rendered
        assert params == [date(2025, 1, 15), "active"]

    @pytest.mark.asyncio
    async def test_and_joined_conditions_still_route(self) -> None:
        _register("v_468_and_joined")

        where = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["date"],
                    operator="gte",
                    value=date(2025, 1, 15),
                    lookup_strategy="sql_column",
                    target_column="date",
                ),
                FieldCondition(
                    field_path=["status"],
                    operator="eq",
                    value="active",
                    lookup_strategy="sql_column",
                    target_column="status",
                ),
            ],
            logical_op="AND",
        )

        rendered, _ = await _rendered("v_468_and_joined", where=where)

        assert "UNION ALL" in rendered
