---
title: FraiseQL v1 Observability & Monitoring Guide
description: FraiseQL v1 provides a Python observability toolkit — Prometheus metrics, OpenTelemetry tracing, health/readiness checks, query statistics, PostgreSQL-native error tracking, and security audit logging — wired into your FastAPI app.
keywords: ["deployment", "scaling", "performance", "monitoring", "troubleshooting"]
tags: ["documentation", "reference"]
---

# FraiseQL v1 Observability & Monitoring Guide

## Overview

FraiseQL v1 ships a Python observability toolkit that you compose onto the FastAPI app returned by `create_fraiseql_app(...)`. It integrates Prometheus metrics, OpenTelemetry distributed tracing, composable health checks (with built-in `/health` and `/ready` endpoints), `pg_stat_statements`-backed query statistics, PostgreSQL-native error tracking, and structured security audit logging.

Everything runs **inside your FastAPI/uvicorn process** — there is no separate server and no build step. You import helpers from `fraiseql.monitoring`, `fraiseql.tracing`, and `fraiseql.audit`, then call them on the app at startup.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture](#architecture)
3. [Monitoring Stack Components](#monitoring-stack-components)
4. [Integration Patterns](#integration-patterns)
5. [Deployment Configuration](#deployment-configuration)
6. [Alerting and SLOs](#alerting-and-slos)
7. [Best Practices](#best-practices)
8. [Troubleshooting](#troubleshooting)

## Quick Start

### Minimal Setup

Wire metrics and tracing onto the FastAPI app, then run it with uvicorn:

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.monitoring import setup_metrics, MetricsConfig
from fraiseql.tracing import setup_tracing, TracingConfig

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    production=True,
)

# Prometheus metrics + /metrics endpoint
setup_metrics(app, MetricsConfig(namespace="fraiseql"))

# OpenTelemetry distributed tracing
setup_tracing(app, TracingConfig(service_name="fraiseql"))
```

```bash
# Run the app
uvicorn myapp:app --host 0.0.0.0 --port 8000

# Scrape Prometheus metrics
curl http://localhost:8000/metrics

# Liveness probe
curl http://localhost:8000/health

# Readiness probe (checks the database + schema)
curl http://localhost:8000/ready
```

The `/health` and `/ready` endpoints are added automatically by `create_fraiseql_app`. `setup_metrics` adds the `/metrics` endpoint (path configurable via `MetricsConfig.metrics_path`).

### With Prometheus + Grafana

```bash
# 1. Start Docker services (app + Prometheus + Grafana)
docker compose up -d

# 2. Open Grafana
open http://localhost:3000

# 3. Add a Prometheus datasource
#    - URL: http://prometheus:9090
#    - Set as default

# 4. Build dashboards from the fraiseql_* metric series
```

### Accessing Metrics

```bash
# Prometheus text exposition format (scraped by Prometheus)
curl http://localhost:8000/metrics
```

The response is standard Prometheus text. With the default `namespace="fraiseql"` you will see series such as:

```text
# HELP fraiseql_graphql_queries_total Total number of GraphQL queries
# TYPE fraiseql_graphql_queries_total counter
fraiseql_graphql_queries_total{operation_type="query",operation_name="users"} 1250
# HELP fraiseql_graphql_query_duration_seconds GraphQL query execution time in seconds
# TYPE fraiseql_graphql_query_duration_seconds histogram
fraiseql_graphql_query_duration_seconds_sum{operation_type="query",operation_name="users"} 29.4
fraiseql_graphql_query_duration_seconds_count{operation_type="query",operation_name="users"} 1250
```

> Metrics collection requires the optional `prometheus_client` dependency. If it is not installed, `setup_metrics` degrades gracefully and the `/metrics` endpoint returns placeholder output.

## OpenTelemetry Integration

### Initialization

FraiseQL v1 provides OpenTelemetry distributed tracing through `setup_tracing(app, config)`. It installs a `TracingMiddleware` on the FastAPI app and (when the OpenTelemetry SDK is available) auto-instruments psycopg so database calls become child spans:

```python
from fraiseql.tracing import setup_tracing, TracingConfig

tracer = setup_tracing(
    app,
    TracingConfig(
        service_name="fraiseql",
        service_version="1.0.0",
        deployment_environment="production",
        sample_rate=1.0,                      # 1.0 = 100% sampling
        export_format="otlp",                 # "otlp", "jaeger", or "zipkin"
        export_endpoint="http://otel-collector:4317",
    ),
)
```

`TracingConfig` validates that `sample_rate` is between `0.0` and `1.0` and that `export_format` is one of `otlp`, `jaeger`, or `zipkin`. Paths in `exclude_paths` (`/health`, `/ready`, `/metrics`, `/docs`, `/openapi.json`) are not traced.

> Tracing requires the optional OpenTelemetry packages. When they are not installed, the tracer becomes a no-op and the middleware passes requests through untouched.

### Trace Context Propagation

The tracer propagates context using the standard W3C `traceparent` header. The `TracingMiddleware` extracts incoming context from request headers; you can inject the current context into outgoing requests:

```python
from fraiseql.tracing import get_tracer

tracer = get_tracer()

# Propagate the current trace into a downstream HTTP call
headers = tracer.inject_context({})
# headers now contains a "traceparent" entry when propagation is enabled
```

The W3C `traceparent` format is:

```text
traceparent: 00-{32-hex-trace-id}-{16-hex-span-id}-{trace-flags}
            Example: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
```

**Components**:

- **Version** (2 hex digits): `00`
- **Trace ID** (32 hex digits): unique request identifier across services
- **Span ID** (16 hex digits): unique operation within the trace
- **Trace Flags** (2 hex digits): `01` = sampled, `00` = not sampled

### Span Creation and Management

The `FraiseQLTracer` exposes context managers for instrumenting work explicitly. Each is a no-op when tracing is disabled:

```python
from fraiseql.tracing import get_tracer

tracer = get_tracer()

# Trace a database query (sets db.system=postgresql, db.statement, etc.)
with tracer.trace_database_query("SELECT", "v_user", "SELECT data FROM v_user"):
    rows = await db.find("v_user")

# Trace a GraphQL operation
with tracer.trace_graphql_query("GetUser", query_text, variables):
    result = await execute(query_text, variables)
```

Decorator helpers are also exported for convenience:

```python
from fraiseql.tracing import trace_graphql_operation, trace_database_query

@trace_graphql_operation("query", "GetUser")
async def run_get_user(query: str, variables: dict | None = None) -> dict:
    ...

@trace_database_query("SELECT", "v_user")
async def load_users(sql: str) -> list[dict]:
    ...
```

### Recording Custom Metrics

The Prometheus collector returned by `setup_metrics` (also reachable via `get_metrics()`) records GraphQL, mutation, database, cache, and error metrics:

```python
from fraiseql.monitoring import get_metrics

metrics = get_metrics()
if metrics is not None:
    metrics.record_query(
        operation_type="query",
        operation_name="GetUser",
        duration_ms=45.0,
        success=True,
    )
    metrics.record_db_query(query_type="SELECT", table_name="v_user", duration_ms=12.0)
    metrics.record_cache_hit(cache_type="result")
```

The `with_metrics(...)` decorator records timing and success/failure automatically for `"query"` / `"mutation"` operation types.

---

## Architecture

### Three Observability Layers

```text
┌─────────────────────────────────────────────────────────────┐
│                    Visualization Layer                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │    Grafana   │  │   Kibana     │  │   DataDog    │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────────┐
│                   Backend/Aggregation Layer                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │  Prometheus  │  │ Elasticsearch│  │  Jaeger/OTLP │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────────┐
│            FraiseQL FastAPI App (Python)                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Metrics — setup_metrics(app, MetricsConfig(...))     │   │
│  │  - GraphQL query/mutation count, duration, errors     │   │
│  │  - Database query + connection-pool gauges            │   │
│  │  - Cache hits/misses, HTTP request metrics            │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Tracing — setup_tracing(app, TracingConfig(...))     │   │
│  │  - W3C traceparent propagation                        │   │
│  │  - Auto-instrumented psycopg spans                    │   │
│  │  - GraphQL operation / DB / cache span helpers        │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Health — HealthCheck + built-in /health & /ready     │   │
│  │  - check_database / check_pool_stats / check_query_…  │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Performance + Audit                                  │   │
│  │  - QueryStatsCollector (pg_stat_statements)           │   │
│  │  - PostgreSQLErrorTracker (Sentry replacement)        │   │
│  │  - SecurityLogger (security audit events)             │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Monitoring Stack Components

### 1. Prometheus Metrics

**Purpose**: Real-time metric collection and time-series analysis.

**Setup**: `setup_metrics(app, MetricsConfig(...))`. The `namespace` (default `"fraiseql"`) prefixes every metric name. Configuration lives in `MetricsConfig`:

```python
from fraiseql.monitoring import MetricsConfig

config = MetricsConfig(
    enabled=True,
    namespace="fraiseql",
    metrics_path="/metrics",
    exclude_paths={"/metrics", "/health", "/ready", "/startup"},
)
```

**Key metrics** (shown with the default `fraiseql` namespace):

- `fraiseql_graphql_queries_total` — total GraphQL queries (labels: `operation_type`, `operation_name`)
- `fraiseql_graphql_queries_success` / `fraiseql_graphql_queries_errors` — query outcomes
- `fraiseql_graphql_query_duration_seconds` — query duration histogram
- `fraiseql_graphql_mutations_total` / `..._success` / `..._errors` — mutation counters
- `fraiseql_db_queries_total` / `fraiseql_db_query_duration_seconds` — database operations
- `fraiseql_db_connections_active` / `..._idle` / `..._total` — connection-pool gauges
- `fraiseql_cache_hits_total` / `fraiseql_cache_misses_total` — cache efficiency
- `fraiseql_errors_total` — errors (labels: `error_type`, `error_code`, `operation`)
- `fraiseql_http_requests_total` / `fraiseql_http_request_duration_seconds` — HTTP metrics

**Endpoint**: `/metrics` (Prometheus text exposition format).

### 2. Structured Logging

**Purpose**: Contextual logging for debugging and analysis.

FraiseQL emits standard Python `logging` records. Configure JSON output (for example with `python-json-logger`) so each line carries request context and timing:

```json
{
  "timestamp": "2026-01-16T15:30:45.123Z",
  "level": "INFO",
  "message": "GraphQL query executed",
  "operation": "GetUser",
  "user_id": "user123",
  "duration_ms": 23.5,
  "db_queries": 2,
  "cache_hit": true
}
```

Set the level via `logging.basicConfig(level=...)` or your logging config. Security-relevant events are emitted as structured JSON by the security audit logger (see [Security Audit Logging](#5-security-audit-logging)).

### 3. Distributed Tracing

**Purpose**: Request correlation across service boundaries.

Enabled with `setup_tracing(app, TracingConfig(...))`. Uses the W3C `traceparent` header for propagation and exports spans via OTLP, Jaeger, or Zipkin.

**Key features**:

- Automatic W3C trace context extraction and propagation
- Auto-instrumented psycopg database spans
- Per-operation span helpers (`trace_graphql_query`, `trace_database_query`, `trace_cache_operation`)
- Configurable sampling via `sample_rate`

### 4. Performance Monitoring

**Purpose**: Detailed performance analysis and optimization.

FraiseQL surfaces PostgreSQL query statistics through the `QueryStatsCollector`, which reads the `v_query_stats` view backed by the `pg_stat_statements` extension:

```python
from fraiseql.monitoring import init_query_stats

# At startup, with your psycopg AsyncConnectionPool
collector = init_query_stats(pool)

# Later — top queries by total execution time
stats = await collector.get_stats(top_n=20, order_by="total_exec_time")
for s in stats:
    print(f"{s.query_preview[:60]}  calls={s.calls}  mean={s.mean_exec_time_ms}ms")
```

Valid `order_by` values: `total_exec_time`, `mean_exec_time`, `calls`, `cache_hit_ratio`. The collector degrades gracefully (returns an empty list) when `pg_stat_statements` is not installed. The companion health check `check_query_stats` reports whether the extension is available.

### 5. Security Audit Logging

**Purpose**: Record authentication, authorization, rate-limiting, and query-security events.

The security logger (`fraiseql.audit`) writes structured `SecurityEvent` records to stdout and/or a file:

```python
from fraiseql.audit import get_security_logger, SecurityEventType

security = get_security_logger()

security.log_auth_failure(
    reason="invalid_token",
    ip_address="203.0.113.42",
    attempted_username="alice",
)

security.log_authorization_denied(
    user_id="user123",
    resource="Order",
    action="read",
    reason="missing role",
)
```

`SecurityEventType` covers authentication (`AUTH_SUCCESS`, `AUTH_FAILURE`, …), authorization (`AUTHZ_DENIED`, `AUTHZ_FIELD_DENIED`, …), rate limiting, CSRF, query security (complexity/depth/timeout), and system events. The log file path defaults to `security_events.log` and can be overridden with `FRAISEQL_SECURITY_LOG_PATH`.

### 6. Error Tracking (PostgreSQL-native)

**Purpose**: Capture exceptions with full context — a Sentry replacement using your own database.

```python
from fraiseql.monitoring import init_error_tracker

# At startup, with your psycopg AsyncConnectionPool
tracker = init_error_tracker(pool, environment="production", release_version="1.0.0")

# Capture an exception with context
try:
    await risky_operation()
except Exception as exc:
    await tracker.capture_exception(exc, context={"request": request_data})
```

Errors are grouped by fingerprint, store full stack traces and request/user context, and can be correlated with OpenTelemetry `trace_id`/`span_id`.

### 7. Health and Readiness Checks

**Purpose**: Kubernetes liveness/readiness probes.

`create_fraiseql_app` registers two endpoints automatically:

- `GET /health` — liveness probe; returns `{"status": "healthy", "service": "fraiseql"}` while the process is up.
- `GET /ready` — readiness probe; validates the database pool, runs a `SELECT`, and confirms the schema is loaded. Returns `503` when not ready.

For richer composite checks, use the `HealthCheck` runner with the pre-built check functions:

```python
from fraiseql.monitoring import (
    HealthCheck,
    check_database,
    check_pool_stats,
    check_query_stats,
)

health = HealthCheck()
health.add_check("database", check_database)
health.add_check("pool", check_pool_stats)
health.add_check("query_stats", check_query_stats)

result = await health.run_checks()
# {"status": "healthy" | "degraded", "checks": {...}}
```

`check_database` and `check_pool_stats` read the app's connection pool via `fraiseql.fastapi.dependencies.get_db_pool`. You can expose `health.run_checks()` from a custom FastAPI route if you want a single aggregated report.

## Integration Patterns

### Pattern 1: Compose the full stack at startup

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.monitoring import (
    setup_metrics, MetricsConfig,
    init_query_stats, init_error_tracker,
)
from fraiseql.tracing import setup_tracing, TracingConfig
from fraiseql.fastapi.dependencies import get_db_pool

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    production=True,
)

setup_metrics(app, MetricsConfig(namespace="fraiseql"))
setup_tracing(app, TracingConfig(service_name="fraiseql", deployment_environment="production"))


@app.on_event("startup")
async def init_observability() -> None:
    pool = get_db_pool()
    init_query_stats(pool)
    init_error_tracker(pool, environment="production")
```

### Pattern 2: Capture and correlate errors

```python
from fraiseql.monitoring import get_error_tracker, get_metrics

async def handle_operation(operation_name: str) -> None:
    metrics = get_metrics()
    tracker = get_error_tracker()
    try:
        await do_work()
    except Exception as exc:
        if metrics is not None:
            metrics.record_error(
                error_type=type(exc).__name__,
                error_code="HANDLER_ERROR",
                operation=operation_name,
            )
        if tracker is not None:
            await tracker.capture_exception(exc, context={"operation": operation_name})
        raise
```

### Pattern 3: Performance analysis dashboard

Real-time monitoring with Grafana:

```bash
# 1. Configure the Grafana datasource
curl -X POST http://localhost:3000/api/datasources \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Prometheus",
    "type": "prometheus",
    "url": "http://prometheus:9090",
    "access": "proxy",
    "isDefault": true
  }'

# 2. Build panels from fraiseql_* series, e.g.:
#    rate(fraiseql_graphql_queries_total[5m])
#    histogram_quantile(0.95, rate(fraiseql_graphql_query_duration_seconds_bucket[5m]))
```

### Pattern 4: Alerting rules

Set up Prometheus alerting against the `fraiseql_*` series:

```yaml
# prometheus/alerts.yml
groups:
  - name: fraiseql
    rules:
      # High error rate
      - alert: HighErrorRate
        expr: |
          (rate(fraiseql_graphql_queries_errors[5m]) /
           rate(fraiseql_graphql_queries_total[5m])) > 0.05
        annotations:
          summary: "GraphQL error rate above 5%"

      # High latency (p95)
      - alert: HighLatency
        expr: |
          histogram_quantile(0.95,
            rate(fraiseql_graphql_query_duration_seconds_bucket[5m])) > 0.5
        annotations:
          summary: "p95 query latency above 500ms"
```

## Deployment Configuration

### Docker Compose (Development)

```yaml
services:
  app:
    build: .
    command: uvicorn myapp:app --host 0.0.0.0 --port 8000
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://user:pass@postgres:5432/db
      FRAISEQL_ENVIRONMENT: development
    depends_on:
      - postgres

  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    depends_on:
      - prometheus

volumes:
  postgres_data:
```

`prometheus.yml` should scrape the app's `/metrics` endpoint:

```yaml
scrape_configs:
  - job_name: fraiseql
    metrics_path: /metrics
    static_configs:
      - targets: ["app:8000"]
```

### Kubernetes (Production)

Run the app with uvicorn and wire the probes to the built-in endpoints:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fraiseql
spec:
  replicas: 3
  selector:
    matchLabels:
      app: fraiseql
  template:
    metadata:
      labels:
        app: fraiseql
    spec:
      containers:
        - name: app
          image: my-fraiseql-app:latest
          command: ["uvicorn", "myapp:app", "--host", "0.0.0.0", "--port", "8000"]
          ports:
            - containerPort: 8000
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: fraiseql-secrets
                  key: database-url
            - name: FRAISEQL_ENVIRONMENT
              value: production
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /ready
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
```

Configuration is supplied through `create_fraiseql_app(...)` keyword arguments, `FraiseQLConfig`, or `FRAISEQL_`-prefixed environment variables — there is no TOML config file.

## Alerting and SLOs

### Recommended Alert Thresholds

| Metric | Threshold | Severity | Action |
|--------|-----------|----------|--------|
| Query Error Rate | > 5% | Warning | Investigate |
| Query Error Rate | > 10% | Critical | Page on-call |
| Query Latency p95 | > 200ms | Warning | Analyze |
| Query Latency p95 | > 1s | Critical | Page on-call |
| Cache Hit Rate | < 50% | Warning | Review caching |
| DB Pool Utilization | > 90% | Warning | Scale pool/replicas |
| Server Error Rate | > 1% | Critical | Page on-call |

### Sample SLOs

```text
Service Level Objectives:

1. Availability SLO: 99.95% (about 4 hours/month downtime)
   - Alert if: error_rate > 0.5% for 5 minutes

2. Latency SLO: 95th percentile < 200ms
   - Alert if: p95_latency > 250ms for 10 minutes

3. Cache Efficiency: > 60% hit rate
   - Alert if: cache_hit_ratio < 50% for 30 minutes

4. Query Success: > 99.9%
   - Alert if: success_rate < 99% for 5 minutes
```

## Best Practices

### 1. Logging Best Practices

DO:

- Include request IDs in log entries
- Log at appropriate levels (DEBUG/TRACE only in development)
- Include business context (`user_id`, `operation`, `tenant_id`)
- Use structured JSON output

DON'T:

- Log sensitive data (passwords, tokens, PII)
- Use vague error messages
- Mix structured and unstructured logs
- Omit context information

### 2. Metrics Best Practices

DO:

- Keep the default `fraiseql` namespace consistent across services
- Track both success and error cases
- Monitor resource usage (connections, CPU, memory)
- Use histograms (`*_duration_seconds_bucket`) for percentiles

DON'T:

- Create unbounded label cardinality (e.g., raw IDs as labels)
- Export sensitive information in labels
- Change metric names without versioning dashboards
- Track PII in metrics

### 3. Tracing Best Practices

DO:

- Create spans at system boundaries
- Propagate the `traceparent` header across services
- Sample appropriately for traffic volume (`sample_rate`)
- Set meaningful span/operation names

DON'T:

- Trace every trivial operation at 100% under heavy load
- Store sensitive data in span attributes
- Forget to close manual spans (use the context managers)
- Trace the excluded probe/health paths

### 4. Performance Monitoring

DO:

- Install `pg_stat_statements` and review `QueryStatsCollector` output
- Track cache efficiency
- Analyze database performance against the pool gauges
- Use percentiles, not just averages

DON'T:

- Ignore performance trends
- Rely on averages alone
- Skip error analysis
- Assume caching is always beneficial

## Troubleshooting

### Metrics Not Appearing in Prometheus

**Symptoms**: `/metrics` works but Prometheus scrape fails.

**Solutions**:

1. Confirm `setup_metrics(app, ...)` runs before the app serves traffic.
2. Verify the target is reachable: `curl http://app:8000/metrics`.
3. Check Prometheus health: `curl http://prometheus:9090/-/healthy`.
4. Ensure `prometheus_client` is installed (otherwise output is placeholder data).
5. Check the scrape `metrics_path` matches `MetricsConfig.metrics_path`.

### Missing Log Entries

**Symptoms**: Some requests are not logged.

**Solutions**:

1. Set the log level: `logging.basicConfig(level=logging.DEBUG)`.
2. Verify your logging handler/formatter is configured.
3. Check for log buffering (may add a small delay).
4. Ensure the application is not crashing silently.

### Trace Context Lost Between Services

**Symptoms**: Trace IDs not propagating.

**Solutions**:

1. Verify `setup_tracing` ran and the OpenTelemetry SDK is installed.
2. Confirm the `traceparent` header is set on outgoing calls (use `tracer.inject_context(...)`).
3. Check the header format: `00-{32-hex}-{16-hex}-{2-hex}`.
4. Ensure downstream services parse and re-propagate the header.

### `/ready` Returns 503

**Symptoms**: Readiness probe fails while `/health` succeeds.

**Solutions**:

1. Confirm `DATABASE_URL` is correct and PostgreSQL is reachable.
2. Inspect the JSON body — the `checks` map names the failing dependency.
3. Verify the connection pool initialized at startup.
4. Confirm the GraphQL schema built without errors.

### Empty Query Statistics

**Symptoms**: `QueryStatsCollector.get_stats()` returns an empty list.

**Solutions**:

1. Install the extension: `CREATE EXTENSION pg_stat_statements;`.
2. Add `pg_stat_statements` to `shared_preload_libraries` and restart PostgreSQL.
3. Run `check_query_stats` to confirm availability.
4. Ensure the database role can read the stats views.

## Additional Resources

- [Distributed Tracing Guide](./distributed-tracing.md)
- [Configuration Reference](./configuration.md)
- [Production Deployment](../production/deployment.md)

## Support

For issues or questions about observability in FraiseQL v1:

- Check the [troubleshooting section](#troubleshooting)
- Raise the log level to `DEBUG` for verbose output
- Enable tracing for detailed execution flow
- File an issue with metrics/logs/traces attached
