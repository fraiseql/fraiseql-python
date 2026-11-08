"""Integration components for FraiseQL metrics.

This module provides middleware, decorators, and FastAPI integration
for metrics collection.
"""

import time
from typing import Any, Awaitable, Callable, Optional

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from fraiseql.utils.annotations import wraps

from .collectors import FraiseQLMetrics
from .config import CONTENT_TYPE_LATEST, MetricsConfig

# Global metrics instance
_metrics_instance: Optional[FraiseQLMetrics] = None


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to collect HTTP metrics.

    This middleware automatically tracks HTTP request metrics including:
    - Request count by method, endpoint, and status
    - Request duration
    - Error rates
    """

    def __init__(
        self, app: FastAPI, metrics: FraiseQLMetrics, config: MetricsConfig | None = None
    ) -> None:
        """Initialize metrics middleware."""
        super().__init__(app)
        self.metrics = metrics
        self.config = config or MetricsConfig()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process request and record metrics."""
        return await self.process_request(request, call_next)

    async def process_request(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process request with metrics collection."""
        # Skip excluded paths
        if request.url.path in self.config.exclude_paths:
            return await call_next(request)

        # Start timing
        start_time = time.time()

        # Process request
        try:
            response = await call_next(request)
            duration = (time.time() - start_time) * 1000  # Convert to ms

            # Record metrics
            self.metrics.http_requests_total.labels(
                method=request.method,
                endpoint=request.url.path,
                status=response.status_code,
            ).inc()

            self.metrics.http_request_duration.labels(
                method=request.method,
                endpoint=request.url.path,
            ).observe(duration / 1000)

            self.metrics.record_response_time(duration)

            return response

        except Exception as e:
            duration = (time.time() - start_time) * 1000

            # Record error metrics
            self.metrics.http_requests_total.labels(
                method=request.method,
                endpoint=request.url.path,
                status=500,
            ).inc()

            self.metrics.record_error(
                error_type=type(e).__name__,
                error_code="HTTP_ERROR",
                operation=f"{request.method} {request.url.path}",
            )

            raise


def get_metrics() -> FraiseQLMetrics | None:
    """Get the global metrics instance.

    Returns:
        The global FraiseQLMetrics instance, or None if not set up.
    """
    return _metrics_instance


def setup_metrics(app: FastAPI, config: MetricsConfig | None = None) -> FraiseQLMetrics:
    """Set up metrics collection on a FastAPI app.

    This function:
    - Creates or retrieves the global metrics instance
    - Adds metrics middleware to the app
    - Adds a /metrics endpoint for Prometheus scraping

    Args:
        app: FastAPI application instance
        config: Optional metrics configuration

    Returns:
        FraiseQLMetrics instance

    Example:
        ```python
        from fastapi import FastAPI
        from fraiseql.monitoring.metrics import setup_metrics

        app = FastAPI()
        metrics = setup_metrics(app)
        ```
    """
    config = config or MetricsConfig()

    # Create or get metrics instance
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = FraiseQLMetrics(config)
    metrics = _metrics_instance

    # Add middleware
    if config.enabled:
        app.add_middleware(MetricsMiddleware, metrics=metrics, config=config)

    # Add metrics endpoint
    @app.get(config.metrics_path, include_in_schema=False)
    async def metrics_endpoint() -> Response:
        """Prometheus metrics endpoint."""
        return Response(
            content=metrics.generate_metrics(),
            media_type=CONTENT_TYPE_LATEST,
        )

    return metrics


def with_metrics(operation_type: str = "operation") -> Callable:
    """Decorator to automatically record metrics for a function.

    This decorator tracks:
    - Execution time
    - Success/failure status
    - Error types and codes

    Args:
        operation_type: Type of operation (query, mutation, etc.)

    Example:
        ```python
        @with_metrics("query")
        async def get_user(user_id: int) -> User:
            # Function implementation
            return user
        ```
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            metrics = get_metrics()
            start_time = time.time()
            success = False

            try:
                result = await func(*args, **kwargs)
                success = True
                return result
            except Exception as e:
                if metrics:
                    metrics.record_error(
                        error_type=type(e).__name__,
                        error_code=getattr(e, "code", "UNKNOWN"),
                        operation=func.__name__,
                    )
                raise
            finally:
                if metrics:
                    duration_ms = (time.time() - start_time) * 1000
                    if operation_type in ("query", "mutation"):
                        metrics.record_query(
                            operation_type=operation_type,
                            operation_name=func.__name__,
                            duration_ms=duration_ms,
                            success=success,
                        )

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            metrics = get_metrics()
            start_time = time.time()
            success = False

            try:
                result = func(*args, **kwargs)
                success = True
                return result
            except Exception as e:
                if metrics:
                    metrics.record_error(
                        error_type=type(e).__name__,
                        error_code=getattr(e, "code", "UNKNOWN"),
                        operation=func.__name__,
                    )
                raise
            finally:
                if metrics:
                    duration_ms = (time.time() - start_time) * 1000
                    if operation_type in ("query", "mutation"):
                        metrics.record_query(
                            operation_type=operation_type,
                            operation_name=func.__name__,
                            duration_ms=duration_ms,
                            success=success,
                        )

        # Return appropriate wrapper based on function type
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
