"""Pre-built health check functions for common dependencies.

Provides ready-to-use health check functions for:
- Database connectivity
- Connection pool statistics
- Other common services

These can be used directly or serve as examples for custom checks.

Example:
    >>> from fraiseql.monitoring import HealthCheck
    >>> from fraiseql.monitoring.health_checks import check_database, check_pool_stats
    >>>
    >>> health = HealthCheck()
    >>> health.add_check("database", check_database)
    >>> health.add_check("pool", check_pool_stats)
    >>> result = await health.run_checks()
"""

from __future__ import annotations

from fraiseql.monitoring.health import CheckResult, HealthStatus

__all__ = [
    "check_database",
    "check_pool_stats",
    "check_query_stats",
]


async def check_database() -> CheckResult:
    """Check database connectivity.

    Attempts to connect to the database and execute a simple query (SELECT version()).
    Returns HEALTHY if connection succeeds, UNHEALTHY otherwise.

    Returns:
        CheckResult with:
        - status: HEALTHY if connected, UNHEALTHY if connection fails
        - message: Success message or error description
        - metadata: Database version information (if available)

    Example:
        >>> from fraiseql.monitoring import HealthCheck
        >>> from fraiseql.monitoring.health_checks import check_database
        >>>
        >>> health = HealthCheck()
        >>> health.add_check("database", check_database)
        >>> result = await health.run_checks()
    """
    try:
        from fraiseql.fastapi.dependencies import get_db_pool

        pool = get_db_pool()

        if pool is None:
            return CheckResult(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message="Database connection pool not available",
            )

        # Test connectivity with simple query
        async with pool.connection() as conn:
            result = await conn.execute("SELECT version()")
            db_version_row = await result.fetchone()
            db_version = db_version_row[0] if db_version_row else "unknown"

            # Parse PostgreSQL version number (e.g., "PostgreSQL 16.3 ...")
            version_parts = db_version.split()
            pg_version = version_parts[1] if len(version_parts) > 1 else "unknown"

        return CheckResult(
            name="database",
            status=HealthStatus.HEALTHY,
            message=f"Database connection successful (PostgreSQL {pg_version})",
            metadata={
                "database_version": pg_version,
                "full_version": db_version,
            },
        )

    except Exception as e:
        return CheckResult(
            name="database",
            status=HealthStatus.UNHEALTHY,
            message=f"Database connection failed: {e!s}",
        )


async def check_pool_stats() -> CheckResult:
    """Check database connection pool statistics.

    Retrieves current pool statistics including:
    - Total connections
    - Active connections
    - Idle connections
    - Pool utilization percentage

    Returns HEALTHY with pool statistics, or UNHEALTHY if pool unavailable.

    Returns:
        CheckResult with:
        - status: HEALTHY if pool available, UNHEALTHY otherwise
        - message: Pool utilization summary
        - metadata: Detailed pool statistics

    Example:
        >>> from fraiseql.monitoring import HealthCheck
        >>> from fraiseql.monitoring.health_checks import check_pool_stats
        >>>
        >>> health = HealthCheck()
        >>> health.add_check("pool", check_pool_stats)
        >>> result = await health.run_checks()
    """
    try:
        from fraiseql.fastapi.dependencies import get_db_pool

        pool = get_db_pool()

        if pool is None:
            return CheckResult(
                name="database_pool",
                status=HealthStatus.UNHEALTHY,
                message="Database connection pool not available",
            )

        # Get pool statistics
        stats = pool.get_stats()
        pool_size = stats.get("pool_size", 0)
        pool_available = stats.get("pool_available", 0)
        active_connections = pool_size - pool_available
        idle_connections = pool_available

        # Calculate utilization percentage
        max_size = pool.max_size
        usage_percentage = round((pool_size / max_size) * 100, 1) if max_size > 0 else 0

        # Determine message based on usage
        active_ratio = f"{active_connections}/{max_size}"
        if usage_percentage >= 90:
            message = f"Pool highly utilized ({usage_percentage}% - {active_ratio} active)"
        elif usage_percentage >= 75:
            message = f"Pool moderately utilized ({usage_percentage}% - {active_ratio} active)"
        else:
            message = f"Pool healthy ({usage_percentage}% utilized - {active_ratio} active)"

        return CheckResult(
            name="database_pool",
            status=HealthStatus.HEALTHY,
            message=message,
            metadata={
                "pool_size": pool_size,
                "active_connections": active_connections,
                "idle_connections": idle_connections,
                "max_connections": max_size,
                "min_connections": pool.min_size,
                "usage_percentage": usage_percentage,
            },
        )

    except Exception as e:
        return CheckResult(
            name="database_pool",
            status=HealthStatus.UNHEALTHY,
            message=f"Failed to retrieve pool stats: {e!s}",
        )


async def check_query_stats() -> CheckResult:
    """Check if pg_stat_statements extension is available.

    This is an **optional** (non-critical) check. A missing
    pg_stat_statements extension should not make the overall health
    endpoint report unhealthy — it simply means query-level performance
    data is not collected.

    Returns:
        CheckResult with:
        - status: HEALTHY if pg_stat_statements is available
        - status: UNHEALTHY if collector is not initialized or extension missing
        - message: Description of current state
    """
    from fraiseql.monitoring.query_stats import get_query_stats_collector

    collector = get_query_stats_collector()
    if collector is None:
        return CheckResult(
            name="query_stats",
            status=HealthStatus.UNHEALTHY,
            message="QueryStatsCollector not initialized",
        )

    try:
        available = await collector.is_available()
    except Exception as e:
        return CheckResult(
            name="query_stats",
            status=HealthStatus.UNHEALTHY,
            message=f"Failed to check pg_stat_statements: {e!s}",
        )

    if available:
        return CheckResult(
            name="query_stats",
            status=HealthStatus.HEALTHY,
            message="pg_stat_statements available",
        )

    return CheckResult(
        name="query_stats",
        status=HealthStatus.UNHEALTHY,
        message="pg_stat_statements extension not loaded",
    )
