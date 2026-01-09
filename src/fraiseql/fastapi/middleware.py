"""Middleware for cache statistics.

Note: Cache statistics collection is now handled by the unified Rust FFI layer.
This middleware provides a compatibility layer for logging periodic stats.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class CacheStatsMiddleware(BaseHTTPMiddleware):
    """Log cache statistics periodically.

    Note: Cache statistics are now managed by the Rust pipeline (Phase 3c).
    This middleware provides a compatibility layer.
    """

    def __init__(self, app, log_interval: int = 100):
        super().__init__(app)
        self.log_interval = log_interval
        self.request_count = 0

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Log stats every N requests (if available from Rust layer)
        self.request_count += 1
        if self.request_count % self.log_interval == 0:
            try:
                # Cache stats collection moved to Rust FFI layer
                # This is a placeholder for future integration with Rust stats
                logger.debug(
                    f"Processed {self.request_count} requests (cache stats now in Rust layer)"
                )
            except Exception as e:
                logger.debug(f"Cache stats not yet available: {e}")

        return response
