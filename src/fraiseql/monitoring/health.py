"""Health check utilities for application monitoring.

Provides composable health check patterns allowing applications to register
custom checks for databases, caches, external services, etc.

Example:
    >>> from fraiseql.monitoring import HealthCheck, CheckResult, HealthStatus
    >>>
    >>> health = HealthCheck()
    >>>
    >>> async def check_database() -> CheckResult:
    ...     # Your database connectivity check
    ...     return CheckResult(
    ...         name="database",
    ...         status=HealthStatus.HEALTHY,
    ...         message="Connected to PostgreSQL",
    ...         metadata={"pool_size": 10}
    ...     )
    >>>
    >>> health.add_check("database", check_database)
    >>> result = await health.run_checks()
    >>> print(result["status"])  # "healthy"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

__all__ = [
    "CheckFunction",
    "CheckResult",
    "HealthCheck",
    "HealthStatus",
    "check_database",
]


class HealthStatus(Enum):
    """Health status enumeration.

    Attributes:
        HEALTHY: All checks passing, system fully operational
        UNHEALTHY: Critical failure, system cannot serve requests
        DEGRADED: Some checks failing but system still operational
    """

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"


@dataclass
class CheckResult:
    """Result of a health check.

    Attributes:
        name: Name of the check (e.g., "database", "redis", "s3")
        status: Health status of this specific check
        message: Human-readable description of the check result
        metadata: Optional metadata (e.g., pool stats, response times, versions)

    Example:
        >>> result = CheckResult(
        ...     name="database",
        ...     status=HealthStatus.HEALTHY,
        ...     message="PostgreSQL 16.3 connected",
        ...     metadata={"pool_size": 10, "active": 3, "idle": 7}
        ... )
    """

    name: str
    status: HealthStatus
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


CheckFunction = Callable[[], Awaitable[CheckResult]]


class HealthCheck:
    """Composable health check runner.

    Allows applications to register custom health checks and run them collectively.
    Framework provides the pattern, applications control what checks to include.

    The HealthCheck class follows a composable pattern where:
    - Each check is independent and returns a CheckResult
    - Checks run concurrently (can be extended to use asyncio.gather)
    - Overall status degrades if any check fails
    - Exceptions are caught and reported as unhealthy

    Example:
        >>> from fraiseql.monitoring import HealthCheck, CheckResult, HealthStatus
        >>>
        >>> health = HealthCheck()
        >>>
        >>> async def check_database() -> CheckResult:
        ...     try:
        ...         pool = get_db_pool()
        ...         async with pool.connection() as conn:
        ...             await conn.execute("SELECT 1")
        ...         return CheckResult(
        ...             name="database",
        ...             status=HealthStatus.HEALTHY,
        ...             message="Database connection successful"
        ...         )
        ...     except Exception as e:
        ...         return CheckResult(
        ...             name="database",
        ...             status=HealthStatus.UNHEALTHY,
        ...             message=f"Database connection failed: {e}"
        ...         )
        >>>
        >>> health.add_check("database", check_database)
        >>> result = await health.run_checks()
        >>> print(result["status"])  # "healthy" or "degraded"

    Attributes:
        _checks: Dictionary mapping check names to check functions
    """

    def __init__(self) -> None:
        """Initialize health check runner."""
        self._checks: dict[str, CheckFunction] = {}

    def add_check(self, name: str, check_fn: CheckFunction) -> None:
        """Register a health check function.

        Args:
            name: Unique name for this check (e.g., "database", "redis", "s3")
            check_fn: Async function that returns CheckResult

        Raises:
            ValueError: If a check with this name is already registered

        Example:
            >>> health = HealthCheck()
            >>> health.add_check("database", check_database_fn)
            >>> health.add_check("redis", check_redis_fn)
        """
        if name in self._checks:
            msg = f"Health check '{name}' is already registered"
            raise ValueError(msg)
        self._checks[name] = check_fn

    async def run_checks(self) -> dict[str, Any]:
        """Run all registered health checks.

        Executes all registered checks and aggregates results. If any check
        returns UNHEALTHY or raises an exception, the overall status becomes DEGRADED.

        Returns:
            Dictionary with overall status and individual check results:
            ```python
            {
                "status": "healthy" | "degraded",
                "checks": {
                    "database": {
                        "status": "healthy",
                        "message": "Connected to PostgreSQL 16.3",
                        "metadata": {"pool_size": 10, "active": 3}
                    },
                    "redis": {
                        "status": "unhealthy",
                        "message": "Connection timeout",
                    }
                }
            }
            ```

        Note:
            - Empty checks list returns {"status": "healthy", "checks": {}}
            - Exceptions in checks are caught and reported as unhealthy
            - Overall status is degraded if ANY check fails
        """
        results: dict[str, dict[str, Any]] = {}
        overall_status = HealthStatus.HEALTHY

        for name, check_fn in self._checks.items():
            try:
                # Run the check
                result = await check_fn()

                # Store result
                results[name] = {
                    "status": result.status.value,
                    "message": result.message,
                }

                # Add metadata if present
                if result.metadata:
                    results[name]["metadata"] = result.metadata

                # Update overall status - any failure degrades the system
                if result.status == HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.DEGRADED

            except Exception as e:
                # Catch exceptions and report as unhealthy
                results[name] = {
                    "status": HealthStatus.UNHEALTHY.value,
                    "message": f"Check failed: {e!s}",
                }
                overall_status = HealthStatus.DEGRADED

        return {
            "status": overall_status.value,
            "checks": results,
        }


async def check_database(pool: Any | None = None, timeout_seconds: float = 5.0) -> CheckResult:
    """Database connectivity health check for Kubernetes readiness probes.

    Performs a real database connectivity check by executing SELECT 1.
    Checks connection pool statistics and validates database is responsive.

    This check is designed for Kubernetes readiness probes - if the database
    is unavailable, the pod should not receive traffic.

    Args:
        pool: PostgreSQL connection pool (psycopg.AsyncConnectionPool).
              If None, returns healthy (useful for testing without database).
        timeout_seconds: Maximum time in seconds to wait for database response (default: 5.0)

    Returns:
        CheckResult: Database health check with pool statistics

    Example:
        >>> from psycopg_pool import AsyncConnectionPool
        >>> pool = AsyncConnectionPool("postgresql://...")
        >>> health = HealthCheck()
        >>> health.add_check("database", lambda: check_database(pool))
        >>> result = await health.run_checks()

    Note:
        - Returns HEALTHY if pool is None (allows testing without database)
        - Returns UNHEALTHY if connection fails or times out
        - Includes pool statistics (size, available, waiting) in metadata
    """
    if pool is None:
        # No database configured - return healthy for testing
        return CheckResult(
            name="database",
            status=HealthStatus.HEALTHY,
            message="Database pool not configured (standalone mode)",
        )

    try:
        # Get a connection from the pool with timeout
        import asyncio

        # Execute simple query to verify connectivity
        async with (
            asyncio.timeout(timeout_seconds),
            pool.connection() as conn,
            conn.cursor() as cursor,
        ):
            await cursor.execute("SELECT 1")
            result = await cursor.fetchone()

            if result and result[0] == 1:
                # Database is responsive - collect pool stats
                metadata = {}

                # Get pool statistics if available
                if hasattr(pool, "_pool"):
                    # psycopg3 AsyncConnectionPool internals
                    p = pool._pool
                    if hasattr(p, "_nconns"):
                        metadata["pool_size"] = p._nconns
                    if hasattr(p, "_connections"):
                        metadata["pool_connections"] = len(p._connections)

                return CheckResult(
                    name="database",
                    status=HealthStatus.HEALTHY,
                    message="Database connection successful",
                    metadata=metadata,
                )

            # SELECT 1 returned unexpected result
            return CheckResult(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"Unexpected database response: {result}",
            )

    except TimeoutError:
        return CheckResult(
            name="database",
            status=HealthStatus.UNHEALTHY,
            message=f"Database connection timeout ({timeout_seconds}s)",
        )
    except Exception as e:
        return CheckResult(
            name="database",
            status=HealthStatus.UNHEALTHY,
            message=f"Database connection failed: {e!s}",
        )
