"""OpenTelemetry tracing integration for FraiseQL.

This module provides distributed tracing capabilities using OpenTelemetry,
enabling visibility into GraphQL operations across the entire request lifecycle.
"""

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Awaitable, Callable, Generator, Optional

from fastapi import FastAPI, Request, Response

from fraiseql.utils.annotations import wraps

logger = logging.getLogger(__name__)

try:
    from opentelemetry import context as otel_context  # type: ignore[import-untyped]
    from opentelemetry import trace  # type: ignore[import-untyped]
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter  # type: ignore[import-untyped]
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found,import-untyped]
        OTLPSpanExporter,
    )

    try:
        from opentelemetry.exporter.zipkin.json import (  # type: ignore[import-not-found]
            ZipkinExporter,  # type: ignore[import-untyped]
        )
    except ImportError:
        ZipkinExporter = None  # type: ignore[assignment]
    from opentelemetry.instrumentation.psycopg import (  # type: ignore[import-not-found,import-untyped]
        PsycopgInstrumentor,
    )
    from opentelemetry.propagate import extract, inject  # type: ignore[import-untyped]
    from opentelemetry.sdk.resources import Resource  # type: ignore[import-untyped]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-untyped]
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import-untyped]
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased  # type: ignore[import-untyped]
    from opentelemetry.semconv.trace import SpanAttributes  # type: ignore[import-untyped]
    from opentelemetry.trace import Status, StatusCode  # type: ignore[import-untyped]

    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    # Define placeholder classes and functions
    trace = None  # type: ignore[assignment]
    otel_context = None  # type: ignore[assignment]
    JaegerExporter = None  # type: ignore[assignment]
    OTLPSpanExporter = None  # type: ignore[assignment]
    ZipkinExporter = None  # type: ignore[assignment]
    PsycopgInstrumentor = None  # type: ignore[assignment]

    def extract(*args: Any, **kwargs: Any) -> dict[str, Any]:  # type: ignore[misc]
        """Placeholder for extract when opentelemetry is not available."""
        return {}

    def inject(*args: Any, **kwargs: Any) -> None:  # type: ignore[misc]
        """Placeholder for inject when opentelemetry is not available."""
        return

    Resource = None  # type: ignore[assignment]
    TracerProvider = None  # type: ignore[assignment]
    BatchSpanProcessor = None  # type: ignore[assignment]
    TraceIdRatioBased = None  # type: ignore[assignment]

    class SpanAttributes:  # type: ignore[misc]
        """Placeholder span attributes when OpenTelemetry is not available."""

        HTTP_METHOD = "http.method"
        HTTP_URL = "http.url"
        HTTP_STATUS_CODE = "http.status_code"
        HTTP_TARGET = "http.target"
        HTTP_SCHEME = "http.scheme"
        HTTP_HOST = "http.host"
        GRAPHQL_OPERATION_TYPE = "graphql.operation.type"
        GRAPHQL_OPERATION_NAME = "graphql.operation.name"
        DB_SYSTEM = "db.system"
        DB_STATEMENT = "db.statement"

    class StatusCode:  # type: ignore[misc]
        """Placeholder status code when OpenTelemetry is not available."""

        OK = "OK"
        ERROR = "ERROR"

    class Status:  # type: ignore[misc]
        """Placeholder status when OpenTelemetry is not available."""

        def __init__(self, code: str, description: str = "") -> None:
            """Initialize placeholder status."""
            self.code = code
            self.description = description


from starlette.middleware.base import BaseHTTPMiddleware

# Global tracer instance
_tracer_instance: Optional["FraiseQLTracer"] = None


@dataclass
class TracingConfig:
    """Configuration for OpenTelemetry tracing."""

    enabled: bool = True
    service_name: str = "fraiseql"
    service_version: str = "unknown"
    deployment_environment: str = "development"

    # Sampling configuration
    sample_rate: float = 1.0  # 1.0 = 100% sampling

    # Export configuration
    export_endpoint: str | None = None
    export_format: str = "otlp"  # otlp, jaeger, zipkin
    export_timeout_ms: int = 30000

    # Context propagation
    propagate_traces: bool = True

    # Filtering
    exclude_paths: set[str] = dataclass_field(
        default_factory=lambda: {
            "/health",
            "/ready",
            "/metrics",
            "/docs",
            "/openapi.json",
        },
    )

    # Custom attributes to add to all spans
    attributes: dict[str, Any] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate configuration."""
        if not 0.0 <= self.sample_rate <= 1.0:
            msg = "sample_rate must be between 0.0 and 1.0"
            raise ValueError(msg)

        if self.export_format not in ("otlp", "jaeger", "zipkin"):
            msg = "export_format must be one of: otlp, jaeger, zipkin"
            raise ValueError(msg)


class FraiseQLTracer:
    """OpenTelemetry tracer for FraiseQL operations."""

    def __init__(self, config: TracingConfig | None = None) -> None:
        """Initialize tracer with configuration."""
        self.config = config or TracingConfig()
        self.tracer = self._setup_tracer()

        # Instrument psycopg automatically (but only once)
        if self.config.enabled and OPENTELEMETRY_AVAILABLE and PsycopgInstrumentor is not None:
            try:
                PsycopgInstrumentor().instrument()
            except Exception:
                # Already instrumented, ignore
                pass

    def _setup_tracer(self) -> Any | None:
        """Set up OpenTelemetry tracer with configured exporter."""
        if not self.config.enabled or not OPENTELEMETRY_AVAILABLE:
            # Return no-op tracer when disabled or not available
            return None

        # If a tracer provider is already set (e.g., in tests), use it
        existing_provider = trace.get_tracer_provider()
        # Check if it's a real TracerProvider instance (not NoOpTracerProvider)
        if existing_provider and type(existing_provider).__name__ == "TracerProvider":
            return trace.get_tracer(__name__)

        # Create resource with service information
        resource = Resource.create(
            {
                "service.name": self.config.service_name,
                "service.version": self.config.service_version,
                "deployment.environment": self.config.deployment_environment,
                **self.config.attributes,
            },
        )

        # Create sampler
        sampler = TraceIdRatioBased(self.config.sample_rate) if TraceIdRatioBased else None

        # Create tracer provider
        provider = TracerProvider(resource=resource, sampler=sampler) if TracerProvider else None
        if not provider:
            return trace.get_tracer(__name__) if trace else None  # type: ignore[return-value]

        # Add span processor with appropriate exporter
        if self.config.export_endpoint and BatchSpanProcessor:
            exporter = self._create_exporter()
            if exporter:
                processor = BatchSpanProcessor(exporter)
                provider.add_span_processor(processor)

        # Set as global tracer provider
        trace.set_tracer_provider(provider)

        return trace.get_tracer(
            instrumenting_module_name=__name__,
            tracer_provider=provider,
        )

    def _create_exporter(self) -> Any | None:
        """Create appropriate span exporter based on configuration."""
        if not OPENTELEMETRY_AVAILABLE:
            return None

        if self.config.export_format == "otlp" and OTLPSpanExporter:
            return OTLPSpanExporter(
                endpoint=self.config.export_endpoint,
                timeout=self.config.export_timeout_ms,
            )
        if self.config.export_format == "jaeger" and JaegerExporter:
            # Parse endpoint for Jaeger
            if self.config.export_endpoint and ":" in self.config.export_endpoint:
                host, port = self.config.export_endpoint.split(":")
                return JaegerExporter(
                    agent_host_name=host,
                    agent_port=int(port),
                )
            return JaegerExporter(agent_host_name=self.config.export_endpoint)
        if self.config.export_format == "zipkin":
            if ZipkinExporter:
                return ZipkinExporter(endpoint=self.config.export_endpoint)
            logger.warning(
                "Zipkin exporter requested but not available. "
                "Install opentelemetry-exporter-zipkin<1.20.0 for protobuf<4.0 compatibility. "
                "Falling back to console exporter."
            )
            return None
        # Return None for console exporter
        return None

    @contextmanager
    def trace_graphql_query(
        self, operation_name: str, query: str, variables: dict | None = None
    ) -> Generator[Any]:
        """Trace a GraphQL query operation."""
        if not self.tracer:
            # No-op context manager when tracer is not available
            yield None
            return

        with self.tracer.start_as_current_span(
            f"graphql.query.{operation_name}",
            kind=trace.SpanKind.SERVER,
        ) as span:
            # Add GraphQL attributes
            span.set_attribute("graphql.operation.type", "query")
            span.set_attribute("graphql.operation.name", operation_name)
            span.set_attribute("graphql.document", query)

            if variables:
                # Add variables as span events (to avoid sensitive data in attributes)
                span.add_event("graphql.variables", {"variables": str(variables)})

            # Add custom attributes from config
            for key, value in self.config.attributes.items():
                span.set_attribute(key, value)

            try:
                yield span
            except Exception as e:
                # Record exception
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    @contextmanager
    def trace_graphql_mutation(
        self,
        operation_name: str,
        query: str,
        variables: dict | None = None,
    ) -> Generator[Any]:
        """Trace a GraphQL mutation operation."""
        if not self.tracer:
            # No-op context manager when tracer is not available
            yield None
            return

        with self.tracer.start_as_current_span(
            f"graphql.mutation.{operation_name}",
            kind=trace.SpanKind.SERVER,
        ) as span:
            # Add GraphQL attributes
            span.set_attribute("graphql.operation.type", "mutation")
            span.set_attribute("graphql.operation.name", operation_name)
            span.set_attribute("graphql.document", query)

            if variables:
                span.add_event("graphql.variables", {"variables": str(variables)})

            # Add custom attributes
            for key, value in self.config.attributes.items():
                span.set_attribute(key, value)

            try:
                yield span
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    @contextmanager
    def trace_database_query(self, query_type: str, table: str, sql: str) -> Generator[Any]:
        """Trace a database query."""
        if not self.tracer:
            # No-op context manager when tracer is not available
            yield None
            return

        with self.tracer.start_as_current_span(
            f"db.{query_type}.{table}",
            kind=trace.SpanKind.CLIENT,
        ) as span:
            # Add database attributes
            span.set_attribute(SpanAttributes.DB_SYSTEM, "postgresql")
            span.set_attribute("db.operation", query_type)
            span.set_attribute("db.table", table)
            span.set_attribute(SpanAttributes.DB_STATEMENT, sql)

            try:
                yield span
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    @contextmanager
    def trace_cache_operation(self, operation: str, cache_type: str, key: str) -> Generator[Any]:
        """Trace a cache operation."""
        if not self.tracer:
            # No-op context manager when tracer is not available
            yield None
            return

        with self.tracer.start_as_current_span(
            f"cache.{operation}.{cache_type}",
            kind=trace.SpanKind.CLIENT,
        ) as span:
            span.set_attribute("cache.operation", operation)
            span.set_attribute("cache.type", cache_type)
            span.set_attribute("cache.key", key)

            try:
                yield span
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    def inject_context(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        """Inject current trace context into headers."""
        if headers is None:
            headers = {}

        if self.config.propagate_traces:
            inject(headers)

        return headers

    def extract_context(self, headers: dict[str, str]) -> Any:
        """Extract trace context from headers."""
        if self.config.propagate_traces:
            return extract(headers)
        return None


class TracingMiddleware(BaseHTTPMiddleware):
    """Middleware to trace HTTP requests."""

    def __init__(self, app: FastAPI, tracer: FraiseQLTracer) -> None:
        """Initialize tracing middleware."""
        super().__init__(app)
        self.tracer = tracer

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process request with tracing."""
        return await self.process_request(request, call_next)

    async def process_request(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process request and create trace span."""
        # Skip excluded paths
        if request.url.path in self.tracer.config.exclude_paths:
            return await call_next(request)

        # If tracer is not available, pass through
        if not self.tracer.tracer:
            return await call_next(request)

        # Extract trace context from headers
        ctx = self.tracer.extract_context(dict(request.headers))
        if ctx:
            otel_context.attach(ctx)

        # Start span
        with self.tracer.tracer.start_as_current_span(
            f"{request.method} {request.url.path}",
            kind=trace.SpanKind.SERVER,
        ) as span:
            # Add HTTP attributes
            span.set_attribute(SpanAttributes.HTTP_METHOD, request.method)
            span.set_attribute(SpanAttributes.HTTP_TARGET, request.url.path)
            span.set_attribute(SpanAttributes.HTTP_SCHEME, request.url.scheme)
            span.set_attribute(SpanAttributes.HTTP_HOST, request.url.hostname or "")

            # Add custom attributes
            for key, value in self.tracer.config.attributes.items():
                span.set_attribute(key, value)

            try:
                # Process request
                response = await call_next(request)

                # Add response attributes
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, response.status_code)

                if response.status_code >= 400:
                    span.set_status(Status(StatusCode.ERROR, f"HTTP {response.status_code}"))

                return response

            except Exception as e:
                # Record exception
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
                raise


def get_tracer() -> FraiseQLTracer:
    """Get the global tracer instance."""
    global _tracer_instance
    if _tracer_instance is None:
        _tracer_instance = FraiseQLTracer()
    return _tracer_instance


def setup_tracing(app: FastAPI, config: TracingConfig | None = None) -> FraiseQLTracer:
    """Set up distributed tracing on a FastAPI app.

    Args:
        app: FastAPI application instance
        config: Optional tracing configuration

    Returns:
        FraiseQLTracer instance
    """
    config = config or TracingConfig()

    # Create or get tracer instance
    global _tracer_instance
    if _tracer_instance is None:
        _tracer_instance = FraiseQLTracer(config)
    tracer = _tracer_instance

    # Add middleware
    if config.enabled:
        app.add_middleware(TracingMiddleware, tracer=tracer)

    return tracer


def trace_graphql_operation(operation_type: str, operation_name: str) -> Callable:
    """Decorator to trace GraphQL operations.

    Args:
        operation_type: Type of operation (query or mutation)
        operation_name: Name of the operation
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()

            # Extract query from args/kwargs
            query = kwargs.get("query", "")
            variables = kwargs.get("variables")

            if operation_type == "query":
                with tracer.trace_graphql_query(operation_name, query, variables):
                    return await func(*args, **kwargs)
            else:
                with tracer.trace_graphql_mutation(operation_name, query, variables):
                    return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()

            query = kwargs.get("query", "")
            variables = kwargs.get("variables")

            if operation_type == "query":
                with tracer.trace_graphql_query(operation_name, query, variables):
                    return func(*args, **kwargs)
            else:
                with tracer.trace_graphql_mutation(operation_name, query, variables):
                    return func(*args, **kwargs)

        # Return appropriate wrapper
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def trace_database_query(query_type: str, table: str) -> Callable:
    """Decorator to trace database queries.

    Args:
        query_type: Type of query (SELECT, INSERT, etc.)
        table: Table name
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()

            # Extract SQL from args/kwargs
            sql = args[0] if args else kwargs.get("sql", "")

            with tracer.trace_database_query(query_type, table, sql):
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()

            sql = args[0] if args else kwargs.get("sql", "")

            with tracer.trace_database_query(query_type, table, sql):
                return func(*args, **kwargs)

        # Return appropriate wrapper
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
