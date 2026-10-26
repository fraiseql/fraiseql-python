"""``FraiseQLTracer`` redacts sensitive variables before it records them.

``trace_graphql_query`` / ``trace_graphql_mutation`` put ``str(variables)`` in a
span event as they came, so a ``password`` or ``token`` variable went to the
tracing backend; ``GraphQLTracer`` already redacted them.
"""

from contextlib import contextmanager

import pytest

pytest.importorskip("opentelemetry")

from fraiseql.tracing.opentelemetry import FraiseQLTracer, TracingConfig


class _Span:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def set_attribute(self, key: str, value: object) -> None:
        pass

    def add_event(self, name: str, attributes: dict) -> None:
        self.events.append((name, attributes))


class _Tracer:
    def __init__(self) -> None:
        self.span = _Span()

    @contextmanager
    def start_as_current_span(self, name: str, kind: object = None):
        yield self.span


VARIABLES = {
    "email": "ada@example.com",
    "password": "hunter2",
    "input": {"apiKey": "sk-live-123", "items": [{"sessionToken": "tok-456"}]},
}


@pytest.mark.parametrize("method", ["trace_graphql_query", "trace_graphql_mutation"])
def test_sensitive_variables_are_redacted(method: str) -> None:
    tracer = FraiseQLTracer(TracingConfig(enabled=False))
    tracer.tracer = _Tracer()

    with getattr(tracer, method)("login", "mutation { login }", VARIABLES):
        pass

    [(name, attributes)] = tracer.tracer.span.events
    recorded = attributes["variables"]
    assert name == "graphql.variables"
    assert "ada@example.com" in recorded
    for secret in ("hunter2", "sk-live-123", "tok-456"):
        assert secret not in recorded
    assert "[REDACTED]" in recorded
