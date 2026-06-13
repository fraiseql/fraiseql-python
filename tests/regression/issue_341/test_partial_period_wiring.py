"""Tests for Issue #341 Phase 04: Dispatch logic in db.find().

Verifies that:
- db.find() calls _build_partial_period_union_query for non-aligned date filters
  when fine_grain_view metadata is registered.
- db.find() calls _build_partial_period_union_query for aligned date filters too
  (Branch 3 always fires for fine-grain metadata).
- db.find() falls back to _build_find_query when no date filter is present.
- db.find() is unchanged for views without fine_grain_view metadata.
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
    """Return (mock_pool, mock_conn)."""
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


def _mock_result() -> bytes:
    return b'{"data":{"v_events_month":[]}}'


def _register_with_fine_grain(view_name: str = "v_events_month") -> None:
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
            "time_grain_trunc": "month",
        },
    )


def _register_plain(view_name: str = "v_plain") -> None:
    register_type_for_view(
        view_name,
        EventDataPoint,
        table_columns={"id", "name"},
    )


class TestFindDispatch:
    def setup_method(self) -> None:
        self._original = _table_metadata.copy()

    def teardown_method(self) -> None:
        _table_metadata.clear()
        _table_metadata.update(self._original)

    @pytest.mark.asyncio
    async def test_find_triggers_union_for_non_aligned_filter(self) -> None:
        """db.find() must call _build_partial_period_union_query for non-aligned date."""
        _register_with_fine_grain()
        mock_pool, _ = _make_pool()
        repo = FraiseQLRepository(mock_pool)

        fake_query = DatabaseQuery(MagicMock(), {})
        mock_result = _mock_result()

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
                return_value=mock_result,
            ),
        ):
            await repo.find(
                "v_events_month",
                info=_make_info(),
                where={"date": {"gte": "2025-01-15"}},
            )

        mock_union.assert_called_once()
        mock_single.assert_not_called()

    @pytest.mark.asyncio
    async def test_find_triggers_union_for_aligned_filter(self) -> None:
        """Aligned date filters also go through the UNION path (Branch 3 always fires)."""
        _register_with_fine_grain()
        mock_pool, _ = _make_pool()
        repo = FraiseQLRepository(mock_pool)

        fake_query = DatabaseQuery(MagicMock(), {})
        mock_result = _mock_result()

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
                return_value=mock_result,
            ),
        ):
            await repo.find(
                "v_events_month",
                info=_make_info(),
                where={"date": {"gte": "2025-02-01"}},  # aligned
            )

        mock_union.assert_called_once()
        mock_single.assert_not_called()

    @pytest.mark.asyncio
    async def test_find_uses_single_query_without_date_filter(self) -> None:
        """No date filter → no lower bound → single-query path."""
        _register_with_fine_grain()
        mock_pool, _ = _make_pool()
        repo = FraiseQLRepository(mock_pool)

        mock_result = _mock_result()

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
            ) as mock_union,
            patch(
                "fraiseql.db.execute_via_rust_pipeline",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            await repo.find(
                "v_events_month",
                info=_make_info(),
                where={"tenant_id": {"eq": 1}},  # no date filter
            )

        mock_union.assert_not_called()

    @pytest.mark.asyncio
    async def test_find_unchanged_for_view_without_fine_grain(self) -> None:
        """No fine_grain_view registered → always single-query path."""
        _register_plain()
        mock_pool, _ = _make_pool()
        repo = FraiseQLRepository(mock_pool)

        mock_result = b'{"data":{"v_plain":[]}}'

        with (
            patch(
                "fraiseql.db._build_partial_period_union_query",
            ) as mock_union,
            patch(
                "fraiseql.db.execute_via_rust_pipeline",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            await repo.find("v_plain", info=_make_info())

        mock_union.assert_not_called()

    @pytest.mark.asyncio
    async def test_find_no_date_filter_no_union(self) -> None:
        """Even with fine_grain metadata, no date filter → single-query path."""
        _register_with_fine_grain()
        mock_pool, _ = _make_pool()
        repo = FraiseQLRepository(mock_pool)

        mock_result = _mock_result()

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
            ) as mock_union,
            patch(
                "fraiseql.db.execute_via_rust_pipeline",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            # No where clause at all
            await repo.find("v_events_month", info=_make_info())

        mock_union.assert_not_called()
