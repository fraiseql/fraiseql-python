"""Issue #467: a mapping whose target is the time-grain column changes dispatch.

The rewrite runs inside ``_normalize_where``, which the partial-period probe
calls *before* ``_extract_lower_date_bound``. So a mapping like
``{"dimensions.dateInfo.date": "date"}`` — the exact shape the issue's casing
example uses — now makes a nested date filter visible to the bound extractor,
and a query that previously took the single-query path takes the UNION path.

That is arguably more correct: the filter really is a bound on the time-grain
column, and honouring it is the whole point of partial-period awareness. It is
also a dispatch change, so it is pinned here rather than discovered in
production.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.db import FraiseQLRepository, _table_metadata, _type_registry, register_type_for_view

COLUMNS = {"id", "data", "date"}
NESTED_DATE_WHERE = {"dimensions": {"dateInfo": {"date": {"gte": "2025-01-15"}}}}


class _Stats:
    """Stand-in for the reporter's @fraise_type analytics class."""


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    for view in [v for v in _table_metadata if v.startswith("v_467")]:
        del _table_metadata[view]
    for view in [v for v in _type_registry if v.startswith("v_467")]:
        del _type_registry[view]


def _register(view_name: str, mapping: dict[str, str]) -> None:
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
            "native_dimension_mapping": mapping,
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


async def _rendered_sql(view_name: str, where: dict) -> str:
    repo = FraiseQLRepository(_make_pool())
    info = MagicMock()
    info.schema = None

    with (
        patch(
            "fraiseql.core.ast_parser.extract_field_paths_from_info",
            return_value=[
                MagicMock(path=["date"]),
                MagicMock(path=["dimensions", "dateInfo", "date"]),
                MagicMock(path=["measures", "cost"]),
            ],
        ),
        patch(
            "fraiseql.db.execute_via_rust_pipeline",
            new_callable=AsyncMock,
            return_value=b'{"data":{"x":[]}}',
        ) as mock_execute,
    ):
        await repo.find(view_name, info=info, where=where)

    return mock_execute.call_args[0][1].as_string(None)


class TestTimeGrainTargetedMapping:
    """Pinned behaviour: the mapped nested date filter drives partial-period dispatch."""

    @pytest.mark.asyncio
    async def test_nested_date_filter_now_routes_through_the_union_path(self) -> None:
        _register("v_467_dispatch", {"dimensions.date_info.date": "date"})

        rendered = await _rendered_sql("v_467_dispatch", NESTED_DATE_WHERE)

        assert "UNION ALL" in rendered

    @pytest.mark.asyncio
    async def test_the_bound_is_encoded_per_branch_not_left_in_extra_where(self) -> None:
        """The UNION builder strips conditions on the time-grain column."""
        _register("v_467_dispatch_bounds", {"dimensions.date_info.date": "date"})

        rendered = await _rendered_sql("v_467_dispatch_bounds", NESTED_DATE_WHERE)

        assert "'2025-01-15'" in rendered
        assert "'2025-02-01'" in rendered
        # One date predicate pair per branch, none carried over as extra_where.
        branches = rendered.count("UNION ALL") + 1
        assert rendered.count('"date" >= ') == branches
        assert '"date" >= %s' not in rendered

    @pytest.mark.asyncio
    async def test_camelcase_key_spelling_dispatches_identically(self) -> None:
        """D2: keys are normalized at registration, so both spellings dispatch alike."""
        _register("v_467_dispatch_camel", {"dimensions.dateInfo.date": "date"})

        rendered = await _rendered_sql("v_467_dispatch_camel", NESTED_DATE_WHERE)

        assert "UNION ALL" in rendered

    @pytest.mark.asyncio
    async def test_an_unmapped_nested_date_filter_still_takes_the_single_query_path(
        self,
    ) -> None:
        """Without the mapping the bound is invisible — the contrast that makes it a change."""
        _register("v_467_dispatch_none", {"dimensions.item.model.category": "date"})

        rendered = await _rendered_sql("v_467_dispatch_none", NESTED_DATE_WHERE)

        assert "UNION ALL" not in rendered
        assert "->> 'date'" in rendered
