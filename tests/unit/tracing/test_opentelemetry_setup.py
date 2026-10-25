"""fraiseql.tracing turns on with the tracing extra, and its spans are exported."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.tracing import opentelemetry as otel
from fraiseql.tracing import setup_tracing
from fraiseql.tracing.opentelemetry import FraiseQLTracer, TracingConfig

_EXPORTER = InMemorySpanExporter()


def _global_provider() -> TracerProvider:
    """The process's TracerProvider (OpenTelemetry sets it once), exporting to memory."""
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    if not getattr(provider, "_fraiseql_test_exporter", False):
        provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))
        provider._fraiseql_test_exporter = True  # type: ignore[attr-defined]
    return provider


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    _global_provider()
    monkeypatch.setattr(otel, "_tracer_instance", None)
    _EXPORTER.clear()
    yield _EXPORTER
    _EXPORTER.clear()


async def _no_db_context(request, user=None) -> dict:
    return {"user": user}


def _app(*queries):
    from fraiseql.fastapi.dependencies import set_db_pool

    set_db_pool(MagicMock())  # the queries don't read the database
    return create_fraiseql_app(
        database_url="postgresql://test/test",
        queries=list(queries),
        production=False,
        context_getter=_no_db_context,
    )


def test_opentelemetry_is_available_without_the_jaeger_exporter() -> None:
    assert otel.OPENTELEMETRY_AVAILABLE is True


def test_graphql_request_produces_a_span(spans: InMemorySpanExporter, clear_registry) -> None:
    @fraiseql.query
    async def hello(info) -> str:
        return "world"

    app = _app(hello)
    tracer = setup_tracing(app, TracingConfig(service_name="test-api"))
    assert tracer.tracer is not None

    response = TestClient(app).post("/graphql", json={"query": "{ hello }"})

    assert response.json()["data"] == {"hello": "world"}
    [span] = [s for s in spans.get_finished_spans() if s.name == "POST /graphql"]
    assert span.kind is trace.SpanKind.SERVER
    assert span.attributes["http.status_code"] == 200


def test_excluded_paths_have_no_span(spans: InMemorySpanExporter, clear_registry) -> None:
    @fraiseql.query
    async def hello(info) -> str:
        return "world"

    app = _app(hello)
    setup_tracing(app, TracingConfig(exclude_paths={"/graphql"}))

    TestClient(app).post("/graphql", json={"query": "{ hello }"})

    assert not [s for s in spans.get_finished_spans() if s.name == "POST /graphql"]


def test_trace_graphql_query_records_a_span(spans: InMemorySpanExporter) -> None:
    tracer = FraiseQLTracer(TracingConfig())

    with tracer.trace_graphql_query("GetUsers", "query GetUsers { users { id } }"):
        pass

    [span] = spans.get_finished_spans()
    assert span.name == "graphql.query.GetUsers"
    assert span.attributes["graphql.operation.name"] == "GetUsers"


def test_console_exporter() -> None:
    tracer = FraiseQLTracer.__new__(FraiseQLTracer)
    tracer.config = TracingConfig(export_format="console")

    assert isinstance(tracer._create_exporter(), ConsoleSpanExporter)


def test_jaeger_asks_for_otlp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(otel, "JaegerExporter", None)
    tracer = FraiseQLTracer.__new__(FraiseQLTracer)
    tracer.config = TracingConfig(export_format="jaeger", export_endpoint="localhost:6831")

    with pytest.raises(ImportError, match="OTLP"):
        tracer._create_exporter()


def test_request_span_continues_the_incoming_trace(
    spans: InMemorySpanExporter, clear_registry
) -> None:
    @fraiseql.query
    async def hello(info) -> str:
        return "world"

    app = _app(hello)
    setup_tracing(app, TracingConfig())
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    parent_id = "00f067aa0ba902b7"

    TestClient(app).post(
        "/graphql",
        json={"query": "{ hello }"},
        headers={"traceparent": f"00-{trace_id}-{parent_id}-01"},
    )

    [span] = [s for s in spans.get_finished_spans() if s.name == "POST /graphql"]
    assert format(span.context.trace_id, "032x") == trace_id
    assert format(span.parent.span_id, "016x") == parent_id
