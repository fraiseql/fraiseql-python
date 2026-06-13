"""Unit tests for QueryStatsCollector and QueryStatsSnapshot."""

from unittest.mock import AsyncMock, MagicMock, patch

import psycopg
import psycopg.errors
import pytest

from fraiseql.core.exceptions import FraiseQLError
from fraiseql.monitoring.query_stats import (
    QueryStatsCollector,
    QueryStatsSnapshot,
    get_query_stats_collector,
    init_query_stats,
)

# ---------------------------------------------------------------------------
# QueryStatsSnapshot
# ---------------------------------------------------------------------------


class TestQueryStatsSnapshot:
    """Test the frozen dataclass."""

    def test_create_snapshot(self) -> None:
        snap = QueryStatsSnapshot(
            queryid=12345,
            query_preview="SELECT * FROM users",
            calls=100,
            total_exec_time_ms=500.5,
            mean_exec_time_ms=5.005,
            min_exec_time_ms=0.1,
            max_exec_time_ms=50.0,
            rows_returned=1000,
            shared_blks_hit=900,
            shared_blks_read=100,
            cache_hit_ratio=90.0,
        )
        assert snap.queryid == 12345
        assert snap.calls == 100
        assert snap.cache_hit_ratio == 90.0

    def test_snapshot_is_frozen(self) -> None:
        snap = QueryStatsSnapshot(
            queryid=1,
            query_preview="SELECT 1",
            calls=1,
            total_exec_time_ms=0.1,
            mean_exec_time_ms=0.1,
            min_exec_time_ms=0.1,
            max_exec_time_ms=0.1,
            rows_returned=1,
            shared_blks_hit=1,
            shared_blks_read=0,
            cache_hit_ratio=100.0,
        )
        with pytest.raises(AttributeError):
            snap.calls = 2  # type: ignore[misc]

    def test_snapshot_field_count(self) -> None:
        """Ensure field count matches v_query_stats view (minus toplevel)."""
        import dataclasses

        fields = dataclasses.fields(QueryStatsSnapshot)
        assert len(fields) == 11


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_pool(rows=None, side_effect=None):
    """Create a mock AsyncConnectionPool that returns predefined rows."""
    pool = MagicMock()
    conn = AsyncMock()
    cursor_result = AsyncMock()

    if rows is not None:
        cursor_result.fetchone = AsyncMock(return_value=rows[0] if rows else None)
        cursor_result.fetchall = AsyncMock(return_value=rows)
    else:
        cursor_result.fetchone = AsyncMock(return_value=None)
        cursor_result.fetchall = AsyncMock(return_value=[])

    if side_effect:
        conn.execute = AsyncMock(side_effect=side_effect)
    else:
        conn.execute = AsyncMock(return_value=cursor_result)

    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)

    connection_cm = AsyncMock()
    connection_cm.__aenter__ = AsyncMock(return_value=conn)
    connection_cm.__aexit__ = AsyncMock(return_value=False)

    pool.connection = MagicMock(return_value=connection_cm)

    return pool, conn


SAMPLE_ROW = (
    12345,  # queryid
    "SELECT * FROM users WHERE id = $1",  # query_preview
    100,  # calls
    500.50,  # total_exec_time_ms
    5.005,  # mean_exec_time_ms
    0.10,  # min_exec_time_ms
    50.00,  # max_exec_time_ms
    1000,  # rows_returned
    900,  # shared_blks_hit
    100,  # shared_blks_read
    90.00,  # cache_hit_ratio
)


# ---------------------------------------------------------------------------
# QueryStatsCollector.get_stats
# ---------------------------------------------------------------------------


class TestGetStats:
    """Test get_stats() method."""

    @pytest.mark.asyncio
    async def test_returns_snapshots(self) -> None:
        pool, _conn = _make_mock_pool(rows=[SAMPLE_ROW])
        collector = QueryStatsCollector(pool)
        stats = await collector.get_stats(top_n=5)

        assert len(stats) == 1
        assert isinstance(stats[0], QueryStatsSnapshot)
        assert stats[0].queryid == 12345
        assert stats[0].calls == 100
        assert stats[0].cache_hit_ratio == 90.0

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_data(self) -> None:
        pool, _conn = _make_mock_pool(rows=[])
        collector = QueryStatsCollector(pool)
        stats = await collector.get_stats()
        assert stats == []

    @pytest.mark.asyncio
    async def test_rejects_invalid_order_by(self) -> None:
        pool, _ = _make_mock_pool()
        collector = QueryStatsCollector(pool)
        with pytest.raises(ValueError, match="Invalid order_by"):
            await collector.get_stats(order_by="DROP TABLE")

    @pytest.mark.asyncio
    async def test_accepts_valid_order_by_values(self) -> None:
        pool, _ = _make_mock_pool(rows=[])
        collector = QueryStatsCollector(pool)
        for order in ("total_exec_time", "mean_exec_time", "calls", "cache_hit_ratio"):
            result = await collector.get_stats(order_by=order)
            assert result == []

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_undefined_table(self) -> None:
        pool, _ = _make_mock_pool(
            side_effect=psycopg.errors.UndefinedTable("v_query_stats")
        )
        collector = QueryStatsCollector(pool)
        stats = await collector.get_stats()
        assert stats == []
        assert collector._available is False

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_undefined_function(self) -> None:
        pool, _ = _make_mock_pool(
            side_effect=psycopg.errors.UndefinedFunction("pg_stat_statements")
        )
        collector = QueryStatsCollector(pool)
        stats = await collector.get_stats()
        assert stats == []
        assert collector._available is False

    @pytest.mark.asyncio
    async def test_warns_only_once(self) -> None:
        pool, _ = _make_mock_pool(
            side_effect=psycopg.errors.UndefinedTable("v_query_stats")
        )
        collector = QueryStatsCollector(pool)
        with patch(
            "fraiseql.monitoring.query_stats.logger"
        ) as mock_logger:
            await collector.get_stats()
            await collector.get_stats()
            assert mock_logger.warning.call_count == 1


# ---------------------------------------------------------------------------
# QueryStatsCollector.is_available
# ---------------------------------------------------------------------------


class TestIsAvailable:
    """Test is_available() method."""

    @pytest.mark.asyncio
    async def test_returns_true_when_extension_installed(self) -> None:
        pool, _ = _make_mock_pool(rows=[(1,)])
        collector = QueryStatsCollector(pool)
        assert await collector.is_available() is True

    @pytest.mark.asyncio
    async def test_returns_false_when_extension_missing(self) -> None:
        pool, _conn = _make_mock_pool(rows=[])
        # fetchone returns None when no rows
        result_mock = AsyncMock()
        result_mock.fetchone = AsyncMock(return_value=None)
        _conn.execute = AsyncMock(return_value=result_mock)
        collector = QueryStatsCollector(pool)
        assert await collector.is_available() is False

    @pytest.mark.asyncio
    async def test_caches_result(self) -> None:
        pool, _conn = _make_mock_pool(rows=[(1,)])
        collector = QueryStatsCollector(pool)
        await collector.is_available()
        await collector.is_available()
        # connection() should only be called once (cached)
        assert pool.connection.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self) -> None:
        pool, _ = _make_mock_pool(side_effect=psycopg.Error("connection failed"))
        collector = QueryStatsCollector(pool)
        assert await collector.is_available() is False


# ---------------------------------------------------------------------------
# QueryStatsCollector.reset_stats
# ---------------------------------------------------------------------------


class TestResetStats:
    """Test reset_stats() method."""

    @pytest.mark.asyncio
    async def test_calls_pg_stat_statements_reset(self) -> None:
        pool, conn = _make_mock_pool()
        collector = QueryStatsCollector(pool)
        await collector.reset_stats()
        conn.execute.assert_called_with("SELECT pg_stat_statements_reset()")

    @pytest.mark.asyncio
    async def test_raises_fraiseql_error_on_insufficient_privilege(self) -> None:
        pool, _ = _make_mock_pool(
            side_effect=psycopg.errors.InsufficientPrivilege(
                "permission denied"
            )
        )
        collector = QueryStatsCollector(pool)
        with pytest.raises(FraiseQLError, match="insufficient privileges"):
            await collector.reset_stats()


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """Test init_query_stats / get_query_stats_collector."""

    def test_collector_is_none_before_init(self) -> None:
        with patch(
            "fraiseql.monitoring.query_stats._collector_instance", None
        ):
            assert get_query_stats_collector() is None

    def test_init_returns_collector(self) -> None:
        pool = MagicMock()
        with patch(
            "fraiseql.monitoring.query_stats._collector_instance", None
        ):
            collector = init_query_stats(pool)
            assert isinstance(collector, QueryStatsCollector)

    def test_get_returns_initialized_collector(self) -> None:
        pool = MagicMock()
        collector = init_query_stats(pool)
        assert get_query_stats_collector() is collector
