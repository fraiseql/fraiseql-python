"""Issue #468: the partial-period UNION path drops OR/NOT sub-clauses from the WHERE.

``_build_partial_period_union_query`` is handed an ``extra_where`` rebuilt from the
normalised clause's ``conditions`` only.  ``WhereClause`` carries three payloads —
``conditions``, ``nested_clauses`` and ``not_clause`` — so every ``OR`` group and
every ``NOT`` group is discarded and the UNION returns rows the filter excluded.

It fails open twice over: when the *only* top-level condition is the date bound,
``remaining_conditions`` is empty, ``extra_where`` is ``None``, and both branches
run with no filter at all beyond the date range.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.db import FraiseQLRepository, _table_metadata, _type_registry, register_type_for_view

COLUMNS = {"id", "data", "date", "status", "machine_id", "model_category"}
MAPPING = {"dimensions.item.model.category": "model_category"}


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


async def _rendered(view_name: str, **find_kwargs: Any) -> tuple[str, list[Any]]:
    """Return (rendered SQL, params) for a ``find()`` that routes through the UNION."""
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


def _branch_count(rendered: str) -> int:
    return rendered.count("UNION ALL") + 1


class TestOrGroupSurvives:
    @pytest.mark.asyncio
    async def test_or_group_reaches_every_branch(self) -> None:
        """An OR group alongside a surviving flat condition is still dropped."""
        _register("v_468_or_group")

        rendered, params = await _rendered(
            "v_468_or_group",
            where={
                "date": {"gte": "2025-01-15"},
                "machine_id": {"eq": "m-1"},
                "OR": [{"status": {"eq": "active"}}, {"status": {"eq": "pending"}}],
            },
        )

        branches = _branch_count(rendered)
        assert branches >= 2, "expected the partial-period UNION to be in play"
        # The flat condition already survives today — it is the control.
        assert rendered.count('"machine_id"') == branches
        # The OR group must survive too, once per branch, parenthesised.
        assert rendered.count('"status"') == 2 * branches
        assert rendered.count(" OR ") == branches
        assert params.count("active") == branches
        assert params.count("pending") == branches

    @pytest.mark.asyncio
    async def test_or_only_filter_is_not_dropped_entirely(self) -> None:
        """The fail-open case: the date bound is the *only* top-level condition.

        ``remaining_conditions`` is empty, so ``extra_where`` is ``None`` and both
        branches run with nothing but the per-branch date literals.
        """
        _register("v_468_or_only")

        rendered, params = await _rendered(
            "v_468_or_only",
            where={
                "date": {"gte": "2025-01-15"},
                "OR": [{"status": {"eq": "active"}}, {"status": {"eq": "pending"}}],
            },
        )

        branches = _branch_count(rendered)
        assert branches >= 2
        assert rendered.count('"status"') == 2 * branches
        assert params.count("active") == branches


class TestNotClauseSurvives:
    @pytest.mark.asyncio
    async def test_not_clause_reaches_every_branch(self) -> None:
        _register("v_468_not_clause")

        rendered, params = await _rendered(
            "v_468_not_clause",
            where={
                "date": {"gte": "2025-01-15"},
                "NOT": {"status": {"eq": "archived"}},
            },
        )

        branches = _branch_count(rendered)
        assert branches >= 2
        assert rendered.count("NOT (") == branches
        assert rendered.count('"status"') == branches
        assert params.count("archived") == branches


class TestNonUnionPathUnaffected:
    @pytest.mark.asyncio
    async def test_or_group_already_works_without_the_union(self) -> None:
        """The same filter on a view with no ``fine_grain_view`` is the baseline."""
        register_type_for_view(
            "v_468_plain",
            _Stats,
            table_columns=COLUMNS,
            has_jsonb_data=True,
            jsonb_column="data",
            aggregation={
                "dimensions": "dimensions",
                "measures": {"measures.cost": "SUM"},
                "native_dimensions": ["date"],
                "native_dimension_mapping": MAPPING,
            },
        )

        rendered, params = await _rendered(
            "v_468_plain",
            where={
                "date": {"gte": "2025-01-15"},
                "OR": [{"status": {"eq": "active"}}, {"status": {"eq": "pending"}}],
            },
        )

        assert "UNION ALL" not in rendered
        assert rendered.count('"status"') == 2
        assert "active" in params
        assert "pending" in params
