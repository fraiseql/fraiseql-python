---
title: Distributed Tracing in FraiseQL
description: FraiseQL provides OpenTelemetry-based distributed tracing for tracking GraphQL requests across service boundaries. Built on W3C Trace Context standards, it enables end-to-end request correlation, performance analysis, and debugging.
keywords: ["deployment", "scaling", "performance", "monitoring", "troubleshooting"]
tags: ["documentation", "reference"]
---

# Distributed Tracing in FraiseQL

## Overview

FraiseQL provides distributed tracing built on [OpenTelemetry](https://opentelemetry.io/). It instruments your FraiseQL application — running as a FastAPI app under `uvicorn` — so you can track GraphQL operations across the full request lifecycle: HTTP request, GraphQL execution, and the PostgreSQL queries underneath.

Trace context propagates using the W3C Trace Context standard, so traces stitch together across service boundaries and into any backend you point at (Jaeger, Zipkin, or any OTLP collector).

## Key Features

- **OpenTelemetry-based**: Standard SDK, standard exporters, no proprietary wire format
- **W3C Trace Context Support**: Standard-compliant trace propagation across services
- **HTTP request tracing**: Each request gets a span via `TracingMiddleware`
- **GraphQL operation tracing**: Query and mutation spans with operation type and name
- **PostgreSQL auto-instrumentation**: psycopg queries are traced automatically
- **Configurable sampling**: Trace a fraction of traffic in high-volume scenarios
- **Path exclusion**: Skip health/metrics/docs endpoints from tracing
- **Variable sanitization**: Redact sensitive GraphQL variables before they reach a span

## Installation

Tracing depends on the OpenTelemetry SDK and exporters. Install the tracing extra (and the exporter for your backend):

```bash
# OpenTelemetry SDK + OTLP/Jaeger exporters and psycopg instrumentation
pip install "fraiseql[tracing]"

# Or install the OpenTelemetry packages directly
pip install opentelemetry-sdk \
    opentelemetry-exporter-otlp \
    opentelemetry-instrumentation-psycopg
```

If OpenTelemetry is not installed, FraiseQL's tracing degrades to a no-op: `setup_tracing` and the tracer still work, but no spans are emitted.

## Quick Start

Create your app with `create_fraiseql_app`, then call `setup_tracing` on the returned FastAPI app:

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.tracing import setup_tracing, TracingConfig

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    production=True,
)

# Enable distributed tracing on the FastAPI app
setup_tracing(
    app,
    TracingConfig(
        service_name="my-graphql-api",
        service_version="1.4.0",
        deployment_environment="production",
        export_format="otlp",
        export_endpoint="http://otel-collector:4317",
        sample_rate=1.0,
    ),
)
```

Run it with `uvicorn`:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

`setup_tracing(app, config)` adds `TracingMiddleware` to the app (when `config.enabled` is true) and returns a `FraiseQLTracer`. The middleware opens a SERVER span per request, extracts inbound W3C trace context from the request headers, and automatically instruments psycopg so each PostgreSQL query becomes a child span.

## Configuration

All configuration lives on the `TracingConfig` dataclass (`from fraiseql.tracing import TracingConfig`). These are the real, verified fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Master switch; when `False`, no middleware is added |
| `service_name` | `str` | `"fraiseql"` | Reported as `service.name` on the OTel resource |
| `service_version` | `str` | `"unknown"` | Reported as `service.version` |
| `deployment_environment` | `str` | `"development"` | Reported as `deployment.environment` |
| `sample_rate` | `float` | `1.0` | Fraction of traces to sample (`0.0`–`1.0`) |
| `export_endpoint` | `str \| None` | `None` | Collector endpoint; no exporter is attached if unset |
| `export_format` | `str` | `"otlp"` | One of `"otlp"`, `"jaeger"`, `"zipkin"` |
| `export_timeout_ms` | `int` | `30000` | Export timeout in milliseconds |
| `propagate_traces` | `bool` | `True` | Inject/extract W3C trace context on headers |
| `exclude_paths` | `set[str]` | `{"/health", "/ready", "/metrics", "/docs", "/openapi.json"}` | Request paths skipped by the middleware |
| `attributes` | `dict[str, Any]` | `{}` | Custom attributes added to every span and the resource |

`sample_rate` must be between `0.0` and `1.0`, and `export_format` must be one of `otlp`, `jaeger`, `zipkin` — both are validated when the config is constructed.

Example with custom resource attributes and a reduced sample rate:

```python
from fraiseql.tracing import setup_tracing, TracingConfig

config = TracingConfig(
    service_name="orders-api",
    service_version="2.1.0",
    deployment_environment="production",
    export_format="otlp",
    export_endpoint="http://otel-collector:4317",
    sample_rate=0.1,                       # sample 10% of traffic
    exclude_paths={"/health", "/metrics"},  # override the default exclusions
    attributes={"team": "payments", "region": "eu-west-1"},
)

setup_tracing(app, config)
```

## How It Works

### HTTP request spans

`TracingMiddleware` wraps every non-excluded request:

1. Extracts inbound W3C trace context from the request headers (when `propagate_traces` is on).
2. Starts a SERVER span named `"{method} {path}"`.
3. Records HTTP attributes (`http.method`, `http.target`, `http.scheme`, `http.host`, `http.status_code`).
4. Marks the span as an error and records the exception if the handler raises or returns a 4xx/5xx status.

### PostgreSQL query spans

When tracing is enabled and OpenTelemetry is installed, `FraiseQLTracer` calls `PsycopgInstrumentor().instrument()` once. From then on, every PostgreSQL query issued through psycopg — including the reads against your `v_`/`tv_` views and the `fn_` function calls behind mutations — is captured as a CLIENT span with `db.system = "postgresql"` and the SQL statement attached.

### GraphQL operation spans

`get_tracer()` returns the global `FraiseQLTracer`. Its context managers let you wrap GraphQL work explicitly:

```python
from fraiseql.tracing import get_tracer

tracer = get_tracer()

# Trace a query operation
with tracer.trace_graphql_query("GetUser", query_text, variables):
    result = await execute_query()

# Trace a mutation operation
with tracer.trace_graphql_mutation("CreateUser", query_text, variables):
    result = await execute_mutation()

# Trace a database operation directly
with tracer.trace_database_query("SELECT", "v_user", sql):
    rows = await run_sql(sql)
```

Each manager sets the relevant attributes (`graphql.operation.type`, `graphql.operation.name`, `graphql.document`, or `db.system`/`db.table`/`db.statement`), records exceptions, and sets an error status on failure.

### Decorator helpers

`trace_graphql_operation` and `trace_database_query` are decorators for wrapping your own functions. They work on both sync and async callables and reuse the global tracer:

```python
from fraiseql.tracing import trace_graphql_operation, trace_database_query

@trace_graphql_operation("query", "ListUsers")
async def list_users(query: str = "", variables: dict | None = None) -> list[User]:
    ...

@trace_database_query("SELECT", "v_user")
async def fetch_users(sql: str) -> list[dict]:
    ...
```

### GraphQL-aware tracing and variable sanitization

For finer GraphQL tracing — operation-type detection, query truncation, and per-resolver spans — use `GraphQLTracer` with its own `GraphQLTracingConfig`:

```python
from fraiseql.tracing import GraphQLTracer, GraphQLTracingConfig

gql_tracer = GraphQLTracer(
    GraphQLTracingConfig(
        trace_resolvers=True,
        include_variables=False,    # keep variables out of spans by default
        sanitize_variables=True,    # redact sensitive values if included
        max_query_length=1000,      # truncate long query documents
    )
)

with gql_tracer.trace_query("GetUser", query_text, variables):
    result = await execute_query()
```

When `include_variables` is enabled, values whose keys match the sanitize patterns (`password`, `token`, `secret`, `key`, `auth`, `credential`, `api_key`, `apikey`, `session`, `cookie`, `authorization`) are replaced with `[REDACTED]` before being recorded.

## Integration with Tracing Backends

FraiseQL exports through standard OpenTelemetry exporters. Pick a backend by setting `export_format` and pointing `export_endpoint` at the right collector.

### OTLP collector (recommended)

```python
from fraiseql.tracing import setup_tracing, TracingConfig

setup_tracing(
    app,
    TracingConfig(
        service_name="my-api",
        export_format="otlp",
        export_endpoint="http://otel-collector:4317",
    ),
)
```

An OTLP collector can fan traces out to Jaeger, Tempo, Datadog, Honeycomb, or any OTLP-compatible backend without changing your application code.

### Jaeger

```python
from fraiseql.tracing import setup_tracing, TracingConfig

setup_tracing(
    app,
    TracingConfig(
        service_name="my-api",
        export_format="jaeger",
        export_endpoint="jaeger-agent:6831",  # host:port
    ),
)
```

For `jaeger`, the endpoint is parsed as `host:port` for the Jaeger agent.

### Zipkin

```python
from fraiseql.tracing import setup_tracing, TracingConfig

setup_tracing(
    app,
    TracingConfig(
        service_name="my-api",
        export_format="zipkin",
        export_endpoint="http://zipkin:9411/api/v2/spans",
    ),
)
```

The Zipkin exporter is optional. If it is not installed, FraiseQL logs a warning and falls back to no exporter — install a compatible `opentelemetry-exporter-zipkin` to enable it.

## W3C Trace Context Format

FraiseQL relies on OpenTelemetry's default W3C Trace Context propagation for interoperability. Downstream and upstream services exchange the `traceparent` header:

```text
Header: traceparent
Format: version-traceid-spanid-traceflags

Example:
traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01

Components:

- 00: Version (always 00 for the current version)
- 0af7651916cd43dd8448eb211c80319c: Trace ID (32 hex digits)
- b7ad6b7169203331: Span ID (16 hex digits)
- 01: Trace flags (2 hex digits)
  - 0x01: Sampled
  - 0x00: Not sampled
```

When `propagate_traces` is enabled, the middleware extracts this header on inbound requests, and the tracer can inject it on outbound calls via `tracer.inject_context(headers)`.

## Sampling Strategy

Control trace volume with `sample_rate`. FraiseQL uses OpenTelemetry's `TraceIdRatioBased` sampler under the hood:

```python
from fraiseql.tracing import TracingConfig

# Sample everything (development / low traffic)
TracingConfig(sample_rate=1.0)

# Sample 10% of traffic (high-volume production)
TracingConfig(sample_rate=0.1)

# Disable tracing entirely
TracingConfig(enabled=False)
```

Start at `1.0` in development and lower the rate as traffic grows. Because the sampler is trace-ID based, a sampling decision is consistent across all services that share a trace.

## Performance Considerations

- **PostgreSQL spans** are produced by the standard psycopg instrumentation; overhead is dominated by export, not capture.
- **Sampling** is the primary lever for high-volume systems — lower `sample_rate` to reduce both CPU and export cost.
- **Batched export**: spans are flushed through a `BatchSpanProcessor`, so export happens off the request path.
- **Excluded paths** (`exclude_paths`) keep health checks and metrics scrapes out of your trace data.

## Best Practices

1. **Name your service**: set `service_name`, `service_version`, and `deployment_environment` so traces are easy to filter.
2. **Use an OTLP collector**: export via OTLP and let the collector route to your backend(s).
3. **Tune sampling**: lower `sample_rate` as traffic grows; keep `1.0` in development.
4. **Exclude noise**: keep health/metrics/docs paths in `exclude_paths`.
5. **Never leak secrets**: keep `include_variables=False` (or `sanitize_variables=True`) so credentials never reach a span.
6. **Propagate context**: leave `propagate_traces=True` so multi-service requests correlate end to end.
7. **Correlate logs**: include the trace ID in your structured log records.

## Troubleshooting

### No traces appearing

- Confirm OpenTelemetry is installed (`pip install "fraiseql[tracing]"`); without it, tracing is a no-op.
- Confirm `enabled=True` and that `export_endpoint` points at a reachable collector.
- Check the request path is not in `exclude_paths`.
- Verify `sample_rate` is greater than `0.0`.

### Missing PostgreSQL query spans

- Ensure the psycopg instrumentation package is installed.
- Confirm `setup_tracing` ran (psycopg is instrumented when the tracer initializes with `enabled=True`).

### Broken cross-service correlation

- Verify `propagate_traces=True` on both services.
- Check the `traceparent` header is forwarded by any proxy in front of the app.
- Confirm the header format: `00-{32-hex}-{16-hex}-{2-hex}`.

## Testing

Tracing has full unit coverage. Run the tracing tests with pytest:

```bash
# Run the tracing tests
uv run pytest tests/ -k tracing

# Run the full test suite
uv run pytest tests/
```
