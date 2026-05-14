"""pg_stat_statements integration for query performance monitoring.

Provides a Python API to fetch and work with pg_stat_statements data,
following the singleton pattern established by postgres_error_tracker.py.

Example:
    >>> from fraiseql.monitoring import init_query_stats, get_query_stats_collector
    >>>
    >>> collector = init_query_stats(pool)
    >>> stats = await collector.get_stats(top_n=20, order_by="total_exec_time")
    >>> for s in stats:
    ...     print(f"{s.query_preview[:60]}  calls={s.calls}")
"""

import logging
from dataclasses import dataclass

import psycopg
from psycopg_pool import AsyncConnectionPool

from fraiseql.core.exceptions import FraiseQLError

logger = logging.getLogger(__name__)

VALID_ORDER_BY = frozenset({"total_exec_time", "mean_exec_time", "calls", "cache_hit_ratio"})

_ORDER_BY_COLUMN = {
    "total_exec_time": "total_exec_time_ms",
    "mean_exec_time": "mean_exec_time_ms",
    "calls": "calls",
    "cache_hit_ratio": "cache_hit_ratio",
}


@dataclass(frozen=True)
class QueryStatsSnapshot:
    """Immutable snapshot of a single query's statistics.

    Field order matches the v_query_stats SQL view columns.
    """

    queryid: int
    query_preview: str
    calls: int
    total_exec_time_ms: float
    mean_exec_time_ms: float
    min_exec_time_ms: float
    max_exec_time_ms: float
    rows_returned: int
    shared_blks_hit: int
    shared_blks_read: int
    cache_hit_ratio: float


class QueryStatsCollector:
    """Async collector for pg_stat_statements data.

    Uses the v_query_stats view created by schema.sql. Degrades gracefully
    when pg_stat_statements is not installed (returns empty results).
    """

    def __init__(self, db_pool: AsyncConnectionPool) -> None:
        self.db = db_pool
        self._available: bool | None = None
        self._warned: bool = False

    async def is_available(self) -> bool:
        """Check if pg_stat_statements extension is installed.

        Result is cached after first check. Returns False if the check
        itself fails.
        """
        if self._available is not None:
            return self._available

        try:
            async with self.db.connection() as conn:
                result = await conn.execute(
                    "SELECT 1 FROM pg_available_extensions "
                    "WHERE name = 'pg_stat_statements' "
                    "AND installed_version IS NOT NULL"
                )
                row = await result.fetchone()
                self._available = row is not None
        except psycopg.Error:
            logger.exception("Failed to check pg_stat_statements availability")
            self._available = False

        return self._available

    async def get_stats(
        self,
        top_n: int = 20,
        order_by: str = "total_exec_time",
    ) -> list[QueryStatsSnapshot]:
        """Fetch top N query statistics ordered by the specified metric.

        Args:
            top_n: Maximum number of queries to return.
            order_by: Ordering metric. One of: total_exec_time,
                mean_exec_time, calls, cache_hit_ratio.

        Returns:
            List of QueryStatsSnapshot, ordered by the specified metric
            descending. Empty list if pg_stat_statements is not available.

        Raises:
            ValueError: If order_by is not a valid metric name.
        """
        if order_by not in VALID_ORDER_BY:
            msg = f"Invalid order_by: {order_by!r}. Allowed: {', '.join(sorted(VALID_ORDER_BY))}"
            raise ValueError(msg)

        try:
            async with self.db.connection() as conn:
                column = _ORDER_BY_COLUMN[order_by]
                result = await conn.execute(
                    "SELECT queryid, query_preview, calls, "
                    "total_exec_time_ms, mean_exec_time_ms, "
                    "min_exec_time_ms, max_exec_time_ms, "
                    "rows_returned, shared_blks_hit, shared_blks_read, "
                    f"cache_hit_ratio FROM v_query_stats "
                    f"ORDER BY {column} DESC LIMIT %s",
                    (top_n,),
                )
                rows = await result.fetchall()
                return [
                    QueryStatsSnapshot(
                        queryid=row[0],
                        query_preview=row[1],
                        calls=row[2],
                        total_exec_time_ms=float(row[3]),
                        mean_exec_time_ms=float(row[4]),
                        min_exec_time_ms=float(row[5]),
                        max_exec_time_ms=float(row[6]),
                        rows_returned=row[7],
                        shared_blks_hit=row[8],
                        shared_blks_read=row[9],
                        cache_hit_ratio=float(row[10]),
                    )
                    for row in rows
                ]
        except (
            psycopg.errors.UndefinedTable,
            psycopg.errors.UndefinedFunction,
        ):
            if not self._warned:
                logger.warning("pg_stat_statements not available — returning empty query stats")
                self._warned = True
            self._available = False
            return []
        except psycopg.Error:
            logger.exception("Failed to fetch query stats")
            return []

    async def reset_stats(self) -> None:
        """Reset pg_stat_statements counters.

        Calls pg_stat_statements_reset() to clear all accumulated
        query statistics. Useful after deployments or configuration changes.

        Raises:
            FraiseQLError: If the database role lacks the required
                privileges (pg_read_all_stats or superuser).
        """
        try:
            async with self.db.connection() as conn:
                await conn.execute("SELECT pg_stat_statements_reset()")
        except psycopg.errors.InsufficientPrivilege as e:
            msg = (
                "Cannot reset pg_stat_statements: insufficient privileges. "
                "The database role needs pg_read_all_stats or superuser access."
            )
            raise FraiseQLError(msg) from e


# Global singleton
_collector_instance: QueryStatsCollector | None = None


def get_query_stats_collector() -> QueryStatsCollector | None:
    """Get the global QueryStatsCollector instance."""
    return _collector_instance


def init_query_stats(db_pool: AsyncConnectionPool) -> QueryStatsCollector:
    """Initialize the global QueryStatsCollector.

    Args:
        db_pool: psycopg async connection pool.

    Returns:
        Initialized QueryStatsCollector.
    """
    global _collector_instance
    _collector_instance = QueryStatsCollector(db_pool)
    logger.info("Initialized QueryStatsCollector")
    return _collector_instance
