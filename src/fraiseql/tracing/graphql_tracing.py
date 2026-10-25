"""GraphQL-specific tracing integration for FraiseQL.

Provides enhanced OpenTelemetry tracing with GraphQL-aware features:
- Operation type detection (query, mutation, subscription)
- Variable sanitization for security
- Query length limiting
- Resolver-level tracing
"""

import types
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from fraiseql.tracing.opentelemetry import get_tracer
from fraiseql.utils.annotations import wraps

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    trace = None
    Status = None
    StatusCode = None


@dataclass
class TracingConfig:
    """Configuration for GraphQL-specific tracing.

    Attributes:
        trace_resolvers: Whether to trace individual field resolvers
        include_variables: Whether to include variables in traces (security risk)
        sanitize_variables: Whether to redact sensitive variable values
        sanitize_patterns: Patterns to match for variable sanitization
        max_query_length: Maximum query length to include in traces
    """

    trace_resolvers: bool = True
    include_variables: bool = False
    sanitize_variables: bool = True
    sanitize_patterns: set[str] = field(
        default_factory=lambda: {
            "password",
            "token",
            "secret",
            "key",
            "auth",
            "credential",
            "api_key",
            "apikey",
            "session",
            "cookie",
            "authorization",
        }
    )
    max_query_length: int = 1000


class GraphQLTracer:
    """GraphQL-specific tracer with security considerations.

    Features:
    - Automatic operation type detection
    - Variable sanitization to prevent sensitive data leakage
    - Query truncation for performance
    - Resolver-level tracing
    """

    def __init__(self, config: Optional[TracingConfig] = None) -> None:
        """Initialize GraphQL tracer."""
        self._config = config or TracingConfig()
        self._otel_tracer = get_tracer() if OPENTELEMETRY_AVAILABLE else None

    @property
    def config(self) -> TracingConfig:
        """Get tracing configuration."""
        return self._config

    def trace_query(
        self,
        operation_name: Optional[str],
        query: str,
        variables: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Context manager for tracing GraphQL queries."""
        return self._trace_operation("query", operation_name, query, variables)

    def trace_mutation(
        self,
        operation_name: Optional[str],
        query: str,
        variables: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Context manager for tracing GraphQL mutations."""
        return self._trace_operation("mutation", operation_name, query, variables)

    def trace_subscription(
        self,
        operation_name: Optional[str],
        query: str,
        variables: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Context manager for tracing GraphQL subscriptions."""
        return self._trace_operation("subscription", operation_name, query, variables)

    def trace_resolver(self, field_name: str, parent_type: str) -> Callable:
        """Decorator for tracing GraphQL field resolvers."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            if not self._config.trace_resolvers or not self._otel_tracer:
                return func

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                span_name = f"graphql.resolver.{parent_type}.{field_name}"
                with self._otel_tracer.tracer.start_as_current_span(
                    span_name,
                    kind=trace.SpanKind.INTERNAL,
                ) as span:
                    span.set_attribute("graphql.field.name", field_name)
                    span.set_attribute("graphql.field.parent_type", parent_type)

                    try:
                        result = await func(*args, **kwargs)
                        return result
                    except Exception as e:
                        if Status and StatusCode:
                            span.record_exception(e)
                            span.set_status(Status(StatusCode.ERROR, str(e)))
                        raise

            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                span_name = f"graphql.resolver.{parent_type}.{field_name}"
                with self._otel_tracer.tracer.start_as_current_span(
                    span_name,
                    kind=trace.SpanKind.INTERNAL,
                ) as span:
                    span.set_attribute("graphql.field.name", field_name)
                    span.set_attribute("graphql.field.parent_type", parent_type)

                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        if Status and StatusCode:
                            span.record_exception(e)
                            span.set_status(Status(StatusCode.ERROR, str(e)))
                        raise

            import asyncio

            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        return decorator

    def _trace_operation(
        self,
        operation_type: str,
        operation_name: Optional[str],
        query: str,
        variables: Optional[dict[str, Any]],
    ):
        """Generic operation tracing context manager."""
        if not self._otel_tracer:
            return _NoOpContext()

        return _GraphQLOperationContext(
            tracer=self._otel_tracer,
            operation_type=operation_type,
            operation_name=operation_name,
            query=query,
            variables=variables,
            config=self._config,
        )

    def _detect_operation_type(self, query: str) -> str:
        """Detect GraphQL operation type from query string."""
        query_lower = query.strip().lower()
        if query_lower.startswith("query"):
            return "query"
        if query_lower.startswith("mutation"):
            return "mutation"
        if query_lower.startswith("subscription"):
            return "subscription"
        # Default to query for anonymous operations
        return "query"

    def _truncate_query(self, query: str) -> str:
        """Truncate query if it exceeds maximum length."""
        if len(query) <= self._config.max_query_length:
            return query

        truncated = query[: self._config.max_query_length - 3] + "..."
        return truncated

    def _sanitize_variables(self, variables: dict[str, Any]) -> dict[str, Any]:
        """Sanitize sensitive variable values for tracing."""
        if not self._config.sanitize_variables:
            return variables

        def _sanitize_value(key: str, value: Any) -> Any:
            key_lower = key.lower()
            if any(pattern in key_lower for pattern in self._config.sanitize_patterns):
                return "[REDACTED]"

            if isinstance(value, dict):
                return {k: _sanitize_value(k, v) for k, v in value.items()}
            if isinstance(value, list):
                return [_sanitize_value(str(i), item) for i, item in enumerate(value)]
            return value

        return {k: _sanitize_value(k, v) for k, v in variables.items()}


class _GraphQLOperationContext:
    """Context manager for GraphQL operation tracing."""

    def __init__(
        self,
        tracer: Any,
        operation_type: str,
        operation_name: Optional[str],
        query: str,
        variables: Optional[dict[str, Any]],
        config: TracingConfig,
    ) -> None:
        self.tracer = tracer
        self.operation_type = operation_type
        self.operation_name = operation_name
        self.query = query
        self.variables = variables
        self.config = config
        self.span = None

    def __enter__(self) -> Any:
        span_name = f"graphql.{self.operation_type}"
        if self.operation_name:
            span_name += f".{self.operation_name}"

        self.span = self.tracer.tracer.start_as_current_span(
            span_name,
            kind=trace.SpanKind.INTERNAL,
        )
        self.span.__enter__()

        # Set GraphQL attributes
        self.span.set_attribute("graphql.operation.type", self.operation_type)
        if self.operation_name:
            self.span.set_attribute("graphql.operation.name", self.operation_name)

        # Add truncated query
        truncated_query = self._truncate_query(self.query)
        self.span.set_attribute("graphql.document", truncated_query)

        # Add sanitized variables if enabled
        if self.config.include_variables and self.variables:
            sanitized_vars = self._sanitize_variables(self.variables)
            self.span.add_event("graphql.variables", {"variables": str(sanitized_vars)})

        return self.span

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        if self.span:
            if exc_val and Status and StatusCode:
                self.span.record_exception(exc_val)
                self.span.set_status(Status(StatusCode.ERROR, str(exc_val)))
            self.span.__exit__(exc_type, exc_val, exc_tb)

    def _truncate_query(self, query: str) -> str:
        """Truncate query if it exceeds maximum length."""
        if len(query) <= self.config.max_query_length:
            return query
        return query[: self.config.max_query_length - 3] + "..."

    def _sanitize_variables(self, variables: dict[str, Any]) -> dict[str, Any]:
        """Sanitize sensitive variable values."""
        if not self.config.sanitize_variables:
            return variables

        def _sanitize_value(key: str, value: Any) -> Any:
            key_lower = key.lower()
            if any(pattern in key_lower for pattern in self.config.sanitize_patterns):
                return "[REDACTED]"

            if isinstance(value, dict):
                return {k: _sanitize_value(k, v) for k, v in value.items()}
            if isinstance(value, list):
                return [_sanitize_value(str(i), item) for i, item in enumerate(value)]
            return value

        return {k: _sanitize_value(k, v) for k, v in variables.items()}


class _NoOpContext:
    """No-op context manager when OpenTelemetry is not available."""

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        pass
