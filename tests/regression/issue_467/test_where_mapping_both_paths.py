"""Issue #467: one call site, both query paths.

The rewrite is applied in ``FraiseQLRepository._normalize_where``, the single
entry point both builders funnel through — the standard ``_build_find_query``
via ``_build_where_clause``, and the partial-period UNION dispatch via its own
bound probe. These tests assert on the SQL each path actually hands to the
executor, so a call site that only covers one of them fails here.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.db import FraiseQLRepository, _table_metadata, _type_registry, register_type_for_view

COLUMNS = {"id", "data", "date", "item_id", "model_category"}
MAPPING = {"dimensions.item.model.category": "model_category"}
WHERE = {
    "date": {"gte": "2025-01-15"},
    "dimensions": {"item": {"model": {"category": {"eq": "laser"}}}},
}


class _Stats:
    """Stand-in for the reporter's @fraise_type analytics class."""


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    for view in [v for v in _table_metadata if v.startswith("v_467")]:
        del _table_metadata[view]
    for view in [v for v in _type_registry if v.startswith("v_467")]:
        del _type_registry[view]


def _aggregation(**extra: Any) -> dict[str, Any]:
    return {
        "dimensions": "dimensions",
        "measures": {"measures.cost": "SUM"},
        "native_dimensions": ["date"],
        "native_dimension_mapping": MAPPING,
        **extra,
    }


def _field_paths() -> list[Any]:
    return [
        MagicMock(path=["date"]),
        MagicMock(path=["dimensions", "item", "model", "category"]),
        MagicMock(path=["measures", "cost"]),
    ]


def _make_pool() -> Any:
    mock_pool = MagicMock()
    ctx = mock_pool.connection.return_value
    ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
    ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_pool


async def _rendered_sql(view_name: str, where: dict) -> tuple[str, list[Any]]:
    """Run find() to completion and return the SQL it handed the executor."""
    repo = FraiseQLRepository(_make_pool())
    info = MagicMock()
    info.schema = None

    with (
        patch(
            "fraiseql.core.ast_parser.extract_field_paths_from_info",
            return_value=_field_paths(),
        ),
        patch(
            "fraiseql.db.execute_via_rust_pipeline",
            new_callable=AsyncMock,
            return_value=b'{"data":{"x":[]}}',
        ) as mock_execute,
    ):
        await repo.find(view_name, info=info, where=where)

    statement, params = mock_execute.call_args[0][1], mock_execute.call_args[0][2]
    return statement.as_string(None), params


class TestPartialPeriodUnionPath:
    """A coarse view with ``fine_grain_view`` routes through the UNION builder."""

    @pytest.mark.asyncio
    async def test_mapped_predicate_is_a_column_in_every_branch(self) -> None:
        register_type_for_view(
            "v_467_union_month",
            _Stats,
            table_columns=COLUMNS,
            has_jsonb_data=True,
            jsonb_column="data",
            aggregation=_aggregation(
                fine_grain_view="v_467_union_day",
                time_grain_column="date",
                time_grain_trunc="month",
            ),
        )

        rendered, params = await _rendered_sql("v_467_union_month", WHERE)

        branches = rendered.count("UNION ALL") + 1
        assert branches >= 2, "expected the window to straddle a period boundary"
        assert rendered.count('"model_category" = ') == branches
        assert "->> 'category'" not in rendered
        assert params.count("laser") == branches

    @pytest.mark.asyncio
    async def test_date_bounds_stay_per_branch_literals(self) -> None:
        register_type_for_view(
            "v_467_union_bounds",
            _Stats,
            table_columns=COLUMNS,
            has_jsonb_data=True,
            jsonb_column="data",
            aggregation=_aggregation(
                fine_grain_view="v_467_union_bounds_day",
                time_grain_column="date",
                time_grain_trunc="month",
            ),
        )

        rendered, params = await _rendered_sql("v_467_union_bounds", WHERE)

        # The date filter is encoded per branch as Literals by the UNION builder,
        # never as a parameter, and never left in the extra_where.
        assert "'2025-01-15'" in rendered
        assert "'2025-02-01'" in rendered
        assert "2025-01-15" not in params


class TestStandardFindPath:
    """A view without ``fine_grain_view`` goes through ``_build_find_query``."""

    @pytest.mark.asyncio
    async def test_mapped_predicate_is_a_column(self) -> None:
        register_type_for_view(
            "v_467_plain_month",
            _Stats,
            table_columns=COLUMNS,
            has_jsonb_data=True,
            jsonb_column="data",
            aggregation=_aggregation(),
        )

        rendered, params = await _rendered_sql("v_467_plain_month", WHERE)

        assert "UNION ALL" not in rendered
        assert '"model_category" = ' in rendered
        assert "->> 'category'" not in rendered
        assert "laser" in params

    @pytest.mark.asyncio
    async def test_top_level_mapping_on_a_non_aggregated_view(self) -> None:
        """No aggregation at all — the mapping is a peer of fk_relationships (D1)."""
        register_type_for_view(
            "v_467_plain_rows",
            _Stats,
            table_columns=COLUMNS,
            has_jsonb_data=True,
            jsonb_column="data",
            column_mapping=MAPPING,
        )

        repo = FraiseQLRepository(_make_pool())
        info = MagicMock()
        info.schema = None

        with (
            patch(
                "fraiseql.core.ast_parser.extract_field_paths_from_info",
                return_value=[MagicMock(path=["id"])],
            ),
            patch(
                "fraiseql.db.execute_via_rust_pipeline",
                new_callable=AsyncMock,
                return_value=b'{"data":{"x":[]}}',
            ) as mock_execute,
        ):
            await repo.find(
                "v_467_plain_rows",
                info=info,
                where={"dimensions": {"item": {"model": {"category": {"eq": "laser"}}}}},
            )

        rendered = mock_execute.call_args[0][1].as_string(None)
        assert '"model_category" = ' in rendered
        assert "->> 'category'" not in rendered


class TestOneDeclarationEveryConsumer:
    """``column_mapping=`` supersedes the aggregation key, so it must reach GROUP BY.

    A new parameter that worked in WHERE and silently no-opped in GROUP BY — the
    one place the mechanism already worked — would recreate the exact trap this
    issue is about.
    """

    @pytest.mark.asyncio
    async def test_top_level_mapping_reaches_group_by(self) -> None:
        register_type_for_view(
            "v_467_groupby",
            _Stats,
            table_columns=COLUMNS,
            has_jsonb_data=True,
            jsonb_column="data",
            column_mapping=MAPPING,
            aggregation={
                "dimensions": "dimensions",
                "measures": {"measures.cost": "SUM"},
                "native_dimensions": ["date"],
            },
        )

        rendered, _params = await _rendered_sql("v_467_groupby", WHERE)

        assert '"t"."model_category"' in rendered
        assert "GROUP BY" in rendered
        assert "-> 'item' -> 'model' ->> 'category'" not in rendered

    @pytest.mark.asyncio
    async def test_top_level_mapping_reaches_group_by_on_the_union_path(self) -> None:
        register_type_for_view(
            "v_467_groupby_union",
            _Stats,
            table_columns=COLUMNS,
            has_jsonb_data=True,
            jsonb_column="data",
            column_mapping=MAPPING,
            aggregation={
                "dimensions": "dimensions",
                "measures": {"measures.cost": "SUM"},
                "native_dimensions": ["date"],
                "fine_grain_view": "v_467_groupby_union_day",
                "time_grain_column": "date",
                "time_grain_trunc": "month",
            },
        )

        rendered, _params = await _rendered_sql("v_467_groupby_union", WHERE)

        branches = rendered.count("UNION ALL") + 1
        assert branches >= 2
        assert rendered.count('"t"."model_category"') >= branches
