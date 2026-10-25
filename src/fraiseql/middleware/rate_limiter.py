"""Rate limiting middleware for FraiseQL.

This module provides rate limiting functionality to prevent API abuse
and ensure fair usage of resources. Supports both PostgreSQL and in-memory backends.
"""

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, Protocol

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from fraiseql.audit import get_security_logger
from fraiseql.audit.security_logger import SecurityEvent, SecurityEventSeverity, SecurityEventType

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

try:
    from psycopg_pool import AsyncConnectionPool  # noqa: TC002

    PSYCOPG_AVAILABLE = True
except ImportError:
    PSYCOPG_AVAILABLE = False


class RateLimitExceeded(HTTPException):
    """Raised when rate limit is exceeded."""

    def __init__(self, retry_after: int, detail: str = "Rate limit exceeded") -> None:
        """Initialize rate limit exception."""
        super().__init__(
            status_code=429,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )


@dataclass
class RateLimitInfo:
    """Information about current rate limit status."""

    allowed: bool
    remaining: int
    reset_after: int  # Seconds until reset
    retry_after: int = 0  # Seconds to wait if blocked
    minute_requests: int = 0
    hour_requests: int = 0
    minute_limit: int = 0
    hour_limit: int = 0


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    # Whether rate limiting is enabled
    enabled: bool = True

    # Request limits
    requests_per_minute: int = 60
    requests_per_hour: int = 1000

    # Burst size (allows short bursts above steady rate)
    burst_size: int = 10

    # Window type: "sliding" or "fixed"
    window_type: str = "sliding"

    # Custom key function to identify clients
    key_func: Optional[Callable[[Request], str]] = None

    # IP whitelist (never rate limited)
    whitelist: list[str] = field(default_factory=list)

    # IP blacklist (always blocked)
    blacklist: list[str] = field(default_factory=list)


class RateLimiter(Protocol):
    """Protocol for rate limiter implementations."""

    async def check_rate_limit(self, key: str) -> RateLimitInfo:
        """Check if request is allowed under rate limit."""
        ...

    async def get_rate_limit_info(self, key: str) -> RateLimitInfo:
        """Get current rate limit status for a key."""
        ...

    async def cleanup_expired(self) -> int:
        """Clean up expired entries."""
        ...


class InMemoryRateLimiter:
    """In-memory rate limiter for development/single instance."""

    def __init__(self, config: RateLimitConfig) -> None:
        """Initialize in-memory rate limiter."""
        self.config = config
        self._minute_windows: dict[str, deque] = defaultdict(deque)
        self._hour_windows: dict[str, deque] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check_rate_limit(self, key: str) -> RateLimitInfo:
        """Check if request is allowed under rate limit."""
        async with self._lock:
            now = time.time()

            # Clean old entries
            self._clean_window(self._minute_windows[key], now - 60)
            self._clean_window(self._hour_windows[key], now - 3600)

            minute_count = len(self._minute_windows[key])
            hour_count = len(self._hour_windows[key])

            # Check blacklist
            if key in self.config.blacklist:
                return RateLimitInfo(
                    allowed=False,
                    remaining=0,
                    reset_after=3600,
                    retry_after=3600,
                    minute_requests=minute_count,
                    hour_requests=hour_count,
                    minute_limit=0,
                    hour_limit=0,
                )

            # Check whitelist
            if key in self.config.whitelist:
                return RateLimitInfo(
                    allowed=True,
                    remaining=999999,
                    reset_after=0,
                    minute_requests=minute_count,
                    hour_requests=hour_count,
                    minute_limit=999999,
                    hour_limit=999999,
                )

            # Check burst allowance
            if minute_count < self.config.burst_size:
                allowed = True
            # Check minute limit
            elif (
                minute_count >= self.config.requests_per_minute
                or hour_count >= self.config.requests_per_hour
            ):
                allowed = False
            else:
                allowed = True

            if allowed:
                # Record request
                self._minute_windows[key].append(now)
                self._hour_windows[key].append(now)

                remaining_minute = max(0, self.config.requests_per_minute - minute_count - 1)
                remaining_hour = max(0, self.config.requests_per_hour - hour_count - 1)
                remaining = min(remaining_minute, remaining_hour)

                # Time until oldest request expires
                reset_after = 0
                if self._minute_windows[key]:
                    reset_after = int(60 - (now - self._minute_windows[key][0]))
            else:
                remaining = 0

                # Calculate retry after
                if minute_count >= self.config.requests_per_minute:
                    retry_after = int(60 - (now - self._minute_windows[key][0]))
                else:
                    retry_after = int(3600 - (now - self._hour_windows[key][0]))

                reset_after = retry_after

                # Log rate limit event
                security_logger = get_security_logger()
                security_logger.log_event(
                    SecurityEvent(
                        event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
                        severity=SecurityEventSeverity.WARNING,
                        metadata={
                            "key": key,
                            "minute_requests": minute_count,
                            "hour_requests": hour_count,
                        },
                    ),
                )

                return RateLimitInfo(
                    allowed=False,
                    remaining=0,
                    reset_after=reset_after,
                    retry_after=retry_after,
                    minute_requests=minute_count,
                    hour_requests=hour_count,
                    minute_limit=self.config.requests_per_minute,
                    hour_limit=self.config.requests_per_hour,
                )

            return RateLimitInfo(
                allowed=True,
                remaining=remaining,
                reset_after=reset_after,
                minute_requests=minute_count + 1,
                hour_requests=hour_count + 1,
                minute_limit=self.config.requests_per_minute,
                hour_limit=self.config.requests_per_hour,
            )

    async def get_rate_limit_info(self, key: str) -> RateLimitInfo:
        """Get current rate limit status without incrementing."""
        async with self._lock:
            now = time.time()

            # Clean old entries
            self._clean_window(self._minute_windows[key], now - 60)
            self._clean_window(self._hour_windows[key], now - 3600)

            minute_count = len(self._minute_windows[key])
            hour_count = len(self._hour_windows[key])

            remaining_minute = max(0, self.config.requests_per_minute - minute_count)
            remaining_hour = max(0, self.config.requests_per_hour - hour_count)
            remaining = min(remaining_minute, remaining_hour)

            reset_after = 0
            if self._minute_windows[key]:
                reset_after = int(60 - (now - self._minute_windows[key][0]))

            return RateLimitInfo(
                allowed=remaining > 0,
                remaining=remaining,
                reset_after=reset_after,
                minute_requests=minute_count,
                hour_requests=hour_count,
                minute_limit=self.config.requests_per_minute,
                hour_limit=self.config.requests_per_hour,
            )

    async def cleanup_expired(self) -> int:
        """Clean up expired entries."""
        async with self._lock:
            now = time.time()
            cleaned = 0

            # Clean empty windows
            empty_keys = []
            for key, window in self._minute_windows.items():
                self._clean_window(window, now - 60)
                if not window:
                    empty_keys.append(key)

            for key in empty_keys:
                del self._minute_windows[key]
                cleaned += 1

            empty_keys = []
            for key, window in self._hour_windows.items():
                self._clean_window(window, now - 3600)
                if not window:
                    empty_keys.append(key)

            for key in empty_keys:
                del self._hour_windows[key]
                cleaned += 1

            return cleaned

    async def get_limited_keys(self) -> set[str]:
        """Get all currently rate-limited keys."""
        async with self._lock:
            return set(self._minute_windows.keys()) | set(self._hour_windows.keys())

    def _clean_window(self, window: deque, cutoff: float) -> None:
        """Remove entries older than cutoff time."""
        while window and window[0] < cutoff:
            window.popleft()


class SlidingWindowRateLimiter(InMemoryRateLimiter):
    """Sliding window rate limiter for more accurate rate limiting."""

    # Inherits most functionality from InMemoryRateLimiter
    # The deque-based implementation already provides sliding window behavior


class PostgreSQLRateLimiter:
    """PostgreSQL-based rate limiter for production/multi-instance deployments."""

    def __init__(
        self,
        config: RateLimitConfig,
        pool: "AsyncConnectionPool",
        table_name: str = "tb_rate_limit",
    ) -> None:
        """Initialize PostgreSQL rate limiter."""
        if not PSYCOPG_AVAILABLE:
            msg = "psycopg and psycopg_pool required for PostgreSQL rate limiter"
            raise ImportError(msg)

        self.config = config
        self.pool = pool
        self.table_name = table_name
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Ensure rate limit table exists."""
        if self._initialized:
            return

        async with self.pool.connection() as conn, conn.cursor() as cur:
            # Create rate limit table
            await cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    client_key TEXT NOT NULL,
                    request_time TIMESTAMPTZ NOT NULL,
                    window_type TEXT NOT NULL,
                    PRIMARY KEY (client_key, request_time, window_type)
                )
            """
            )

            # Create index for time-based queries
            await cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {self.table_name}_time_idx
                ON {self.table_name} (request_time)
            """
            )

            # Create index for client queries
            await cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {self.table_name}_client_idx
                ON {self.table_name} (client_key, window_type, request_time)
            """
            )

            await conn.commit()
            self._initialized = True

    async def check_rate_limit(self, key: str) -> RateLimitInfo:
        """Check if request is allowed under rate limit."""
        await self._ensure_initialized()

        now = time.time()

        async with self.pool.connection() as conn, conn.cursor() as cur:
            # Clean old entries first
            await cur.execute(
                f"""
                DELETE FROM {self.table_name}
                WHERE request_time < NOW() - INTERVAL '1 hour'
                """,
            )

            # Count recent requests
            await cur.execute(
                f"""
                SELECT COUNT(*) FROM {self.table_name}
                WHERE client_key = %s
                AND window_type = 'minute'
                AND request_time > NOW() - INTERVAL '1 minute'
                """,
                (key,),
            )
            minute_result = await cur.fetchone()
            minute_count = minute_result[0] if minute_result else 0

            await cur.execute(
                f"""
                SELECT COUNT(*) FROM {self.table_name}
                WHERE client_key = %s
                AND window_type = 'hour'
                AND request_time > NOW() - INTERVAL '1 hour'
                """,
                (key,),
            )
            hour_result = await cur.fetchone()
            hour_count = hour_result[0] if hour_result else 0

            # Check blacklist
            if key in self.config.blacklist:
                await conn.commit()
                return RateLimitInfo(
                    allowed=False,
                    remaining=0,
                    reset_after=3600,
                    retry_after=3600,
                    minute_requests=minute_count,
                    hour_requests=hour_count,
                    minute_limit=0,
                    hour_limit=0,
                )

            # Check whitelist
            if key in self.config.whitelist:
                await conn.commit()
                return RateLimitInfo(
                    allowed=True,
                    remaining=999999,
                    reset_after=0,
                    minute_requests=minute_count,
                    hour_requests=hour_count,
                    minute_limit=999999,
                    hour_limit=999999,
                )

            # Check burst allowance
            if minute_count < self.config.burst_size:
                allowed = True
            # Check minute and hour limits
            elif (
                minute_count >= self.config.requests_per_minute
                or hour_count >= self.config.requests_per_hour
            ):
                allowed = False
            else:
                allowed = True

            if allowed:
                # Record request
                await cur.execute(
                    f"""
                    INSERT INTO {self.table_name} (client_key, request_time, window_type)
                    VALUES (%s, TO_TIMESTAMP(%s), 'minute'),
                           (%s, TO_TIMESTAMP(%s), 'hour')
                    """,
                    (key, now, key, now),
                )

                remaining_minute = max(0, self.config.requests_per_minute - minute_count - 1)
                remaining_hour = max(0, self.config.requests_per_hour - hour_count - 1)
                remaining = min(remaining_minute, remaining_hour)

                # Calculate reset time
                await cur.execute(
                    f"""
                    SELECT request_time FROM {self.table_name}
                    WHERE client_key = %s AND window_type = 'minute'
                    ORDER BY request_time ASC
                    LIMIT 1
                    """,
                    (key,),
                )
                oldest_result = await cur.fetchone()
                if oldest_result:
                    oldest_time = oldest_result[0].timestamp()
                    reset_after = int(60 - (now - oldest_time))
                else:
                    reset_after = 0

                await conn.commit()

                return RateLimitInfo(
                    allowed=True,
                    remaining=remaining,
                    reset_after=reset_after,
                    minute_requests=minute_count + 1,
                    hour_requests=hour_count + 1,
                    minute_limit=self.config.requests_per_minute,
                    hour_limit=self.config.requests_per_hour,
                )

            # Rate limit exceeded
            if minute_count >= self.config.requests_per_minute:
                await cur.execute(
                    f"""
                    SELECT request_time FROM {self.table_name}
                    WHERE client_key = %s AND window_type = 'minute'
                    ORDER BY request_time ASC
                    LIMIT 1
                    """,
                    (key,),
                )
                oldest_result = await cur.fetchone()
                if oldest_result:
                    oldest_time = oldest_result[0].timestamp()
                    retry_after = int(60 - (now - oldest_time))
                else:
                    retry_after = 60
            else:
                await cur.execute(
                    f"""
                    SELECT request_time FROM {self.table_name}
                    WHERE client_key = %s AND window_type = 'hour'
                    ORDER BY request_time ASC
                    LIMIT 1
                    """,
                    (key,),
                )
                oldest_result = await cur.fetchone()
                if oldest_result:
                    oldest_time = oldest_result[0].timestamp()
                    retry_after = int(3600 - (now - oldest_time))
                else:
                    retry_after = 3600

            await conn.commit()

            # Log rate limit event
            security_logger = get_security_logger()
            security_logger.log_event(
                SecurityEvent(
                    event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
                    severity=SecurityEventSeverity.WARNING,
                    metadata={
                        "key": key,
                        "minute_requests": minute_count,
                        "hour_requests": hour_count,
                    },
                ),
            )

            return RateLimitInfo(
                allowed=False,
                remaining=0,
                reset_after=retry_after,
                retry_after=retry_after,
                minute_requests=minute_count,
                hour_requests=hour_count,
                minute_limit=self.config.requests_per_minute,
                hour_limit=self.config.requests_per_hour,
            )

    async def get_rate_limit_info(self, key: str) -> RateLimitInfo:
        """Get current rate limit status without incrementing."""
        await self._ensure_initialized()

        now = time.time()

        async with self.pool.connection() as conn, conn.cursor() as cur:
            # Count recent requests
            await cur.execute(
                f"""
                SELECT COUNT(*) FROM {self.table_name}
                WHERE client_key = %s
                AND window_type = 'minute'
                AND request_time > NOW() - INTERVAL '1 minute'
                """,
                (key,),
            )
            minute_result = await cur.fetchone()
            minute_count = minute_result[0] if minute_result else 0

            await cur.execute(
                f"""
                SELECT COUNT(*) FROM {self.table_name}
                WHERE client_key = %s
                AND window_type = 'hour'
                AND request_time > NOW() - INTERVAL '1 hour'
                """,
                (key,),
            )
            hour_result = await cur.fetchone()
            hour_count = hour_result[0] if hour_result else 0

            remaining_minute = max(0, self.config.requests_per_minute - minute_count)
            remaining_hour = max(0, self.config.requests_per_hour - hour_count)
            remaining = min(remaining_minute, remaining_hour)

            # Calculate reset time
            await cur.execute(
                f"""
                SELECT request_time FROM {self.table_name}
                WHERE client_key = %s AND window_type = 'minute'
                ORDER BY request_time ASC
                LIMIT 1
                """,
                (key,),
            )
            oldest_result = await cur.fetchone()
            if oldest_result:
                oldest_time = oldest_result[0].timestamp()
                reset_after = int(60 - (now - oldest_time))
            else:
                reset_after = 0

            return RateLimitInfo(
                allowed=remaining > 0,
                remaining=remaining,
                reset_after=reset_after,
                minute_requests=minute_count,
                hour_requests=hour_count,
                minute_limit=self.config.requests_per_minute,
                hour_limit=self.config.requests_per_hour,
            )

    async def cleanup_expired(self) -> int:
        """Clean up expired entries."""
        await self._ensure_initialized()

        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                f"""
                DELETE FROM {self.table_name}
                WHERE request_time < NOW() - INTERVAL '1 hour'
                """,
            )
            deleted = cur.rowcount
            await conn.commit()

            return deleted


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting."""

    def __init__(self, app: ASGIApp, rate_limiter: RateLimiter) -> None:
        """Initialize rate limiter middleware."""
        super().__init__(app)
        self.rate_limiter = rate_limiter

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process request with rate limiting."""
        # Skip rate limiting for certain paths
        if request.url.path in ["/health", "/metrics", "/"]:
            return await call_next(request)

        # Get client key
        if hasattr(self.rate_limiter, "config") and self.rate_limiter.config.key_func:
            key = self.rate_limiter.config.key_func(request)
        else:
            # Default to IP address
            key = request.client.host if request.client else "anonymous"

        # The rejections are returned, not raised: an HTTPException raised in a
        # BaseHTTPMiddleware never reaches FastAPI's exception handlers, which
        # sit inside it, so it would become a 500.

        # Check blacklist first
        if hasattr(self.rate_limiter, "config") and key in self.rate_limiter.config.blacklist:
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})

        # Check rate limit
        rate_limit_info = await self.rate_limiter.check_rate_limit(key)

        if not rate_limit_info.allowed:
            retry_after = max(1, rate_limit_info.retry_after)
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded. Retry after {retry_after} seconds."},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(rate_limit_info.minute_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                },
            )

        # Process request
        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(rate_limit_info.minute_limit)
        response.headers["X-RateLimit-Remaining"] = str(rate_limit_info.remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + rate_limit_info.reset_after)

        return response
