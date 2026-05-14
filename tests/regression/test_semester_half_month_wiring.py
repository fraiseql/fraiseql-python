"""Tests for Issues #1516/#1517: Dispatch logic for semester and half_month.

Verifies that db.find() dispatches to _build_partial_period_union_query
when time_grain_trunc is "semester" or "half_month" with a date filter,
mirroring the existing tests in test_partial_period_wiring.py.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.db import (
    DatabaseQuery,
    FraiseQLRepository,
    _table_metadata,
    register_type_for_view,
)


class EventDataPoint:
    pass


def _make_pool() -> tuple[Any, Any]:
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    ctx = mock_pool.connection.return_value
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_pool, mock_conn


def _make_info() -> Any:
    info = MagicMock()
    info.schema = None
    return info


def _register_fine_grain(view_name: str, trunc: str) -> None:
    register_type_for_view(
        view_name,
        EventDataPoint,
        table_columns={"date", "data"},
        aggregation={
            "dimensions": "data",
            "measures": {"data.volume": "SUM"},
            "native_dimensions": ["date"],
            "fine_grain_view": "v_events_day",
            "time_grain_column": "date",
            "time_grain_trunc": trunc,
        },
    )


class TestSemesterDispatch:
    def setup_method(self) -> None:
        self._original = _table_metadata.copy()

    def teardown_method(self) -> None:
        _table_metadata.clear()
        _table_metadata.update(self._original)

    @pytest.mark.asyncio
    async def test_find_triggers_union_for_semester(self) -> None:
        _register_fine_grain("v_events_semester", "semester")
        mock_pool, _ = _make_pool()
        repo = FraiseQLRepository(mock_pool)
        fake_query = DatabaseQuery(MagicMock(), {})

        with (
            patch(
                "fraiseql.core.ast_parser.extract_field_paths_from_info",
                return_value=[
                    MagicMock(path=["date"]),
                    MagicMock(path=["data", "volume"]),
                ],
            ),
            patch(
                "fraiseql.db._build_partial_period_union_query",
                return_value=fake_query,
            ) as mock_union,
            patch(
                "fraiseql.db.FraiseQLRepository._build_find_query",
                return_value=fake_query,
            ) as mock_single,
            patch(
                "fraiseql.db.execute_via_rust_pipeline",
                new_callable=AsyncMock,
                return_value=b'{"data":{"v_events_semester":[]}}',
            ),
        ):
            await repo.find(
                "v_events_semester",
                info=_make_info(),
                where={"date": {"gte": "2024-03-15"}},
            )

        mock_union.assert_called_once()
        mock_single.assert_not_called()


class TestHalfMonthDispatch:
    def setup_method(self) -> None:
        self._original = _table_metadata.copy()

    def teardown_method(self) -> None:
        _table_metadata.clear()
        _table_metadata.update(self._original)

    @pytest.mark.asyncio
    async def test_find_triggers_union_for_half_month(self) -> None:
        _register_fine_grain("v_events_half_month", "half_month")
        mock_pool, _ = _make_pool()
        repo = FraiseQLRepository(mock_pool)
        fake_query = DatabaseQuery(MagicMock(), {})

        with (
            patch(
                "fraiseql.core.ast_parser.extract_field_paths_from_info",
                return_value=[
                    MagicMock(path=["date"]),
                    MagicMock(path=["data", "volume"]),
                ],
            ),
            patch(
                "fraiseql.db._build_partial_period_union_query",
                return_value=fake_query,
            ) as mock_union,
            patch(
                "fraiseql.db.FraiseQLRepository._build_find_query",
                return_value=fake_query,
            ) as mock_single,
            patch(
                "fraiseql.db.execute_via_rust_pipeline",
                new_callable=AsyncMock,
                return_value=b'{"data":{"v_events_half_month":[]}}',
            ),
        ):
            await repo.find(
                "v_events_half_month",
                info=_make_info(),
                where={"date": {"gte": "2025-03-10"}},
            )

        mock_union.assert_called_once()
        mock_single.assert_not_called()
