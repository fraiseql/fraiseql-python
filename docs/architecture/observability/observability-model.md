---
title: "FraiseQL Observability Model: Metrics, Logging, and Tracing"
description: FraiseQL provides a comprehensive observability model covering three pillars - metrics, logs, and traces - for PostgreSQL-backed GraphQL APIs running on FastAPI.
keywords: ["observability", "metrics", "tracing", "logging", "prometheus", "monitoring"]
tags: ["documentation", "reference"]
---

# FraiseQL Observability Model: Metrics, Logging, and Tracing

**Audience:** Operations engineers, SRE teams, platform architects, application developers

---

## Executive Summary

FraiseQL provides observability across three pillars:

1. **Metrics** — Quantitative measurements (queries/second, latency, errors) exposed in Prometheus format.
2. **Logs** — Structured event records (per-request, debug, errors), including security audit events.
3. **Traces** — Distributed request flow via OpenTelemetry (end-to-end execution path).

All observability is built into the FastAPI application FraiseQL serves. You opt in with a few setup calls:

```python
from fastapi import FastAPI
from fraiseql.monitoring import setup_metrics, MetricsConfig
from fraiseql.tracing import setup_tracing, TracingConfig

app = FastAPI()
setup_metrics(app, MetricsConfig(namespace="fraiseql"))
setup_tracing(app, TracingConfig(service_name="fraiseql"))
```

**Core principle**: Observable by default. Metrics, health endpoints, and tracing hooks are part of the framework; you wire them in once and they instrument every operation.

---

## 1. Metrics Framework

FraiseQL ships a Prometheus integration in `fraiseql.monitoring`. Calling
`setup_metrics(app, config)` adds the metrics middleware and a `/metrics`
endpoint (default path) that serves the standard Prometheus exposition format.

```python
from fastapi import FastAPI
from fraiseql.monitoring import setup_metrics, MetricsConfig

app = FastAPI()

metrics = setup_metrics(
    app,
    MetricsConfig(
        enabled=True,
        namespace="fraiseql",        # prefix for every metric name
        metrics_path="/metrics",     # Prometheus scrape endpoint
        exclude_paths={"/metrics", "/health", "/ready"},
    ),
)
```

`setup_metrics` returns a `FraiseQLMetrics` instance. You can retrieve the
global instance later with `get_metrics()`.

### 1.1 Metric Categories

The built-in `FraiseQLMetrics` collector covers these dimensions:

```text
┌─────────────────────────┐
│ Operation Metrics       │ GraphQL queries/mutations counted by type & name
├─────────────────────────┤
│ Latency Metrics         │ Query/mutation/DB-query duration histograms
├─────────────────────────┤
│ Error Metrics           │ Errors by error_type, error_code, operation
├─────────────────────────┤
│ Resource Metrics        │ Active/idle/total DB connections, response time
├─────────────────────────┤
│ Business Metrics        │ Custom prometheus_client Counters/Gauges you define
└─────────────────────────┘
```

### 1.2 Core Metrics (Always Available)

With `namespace="fraiseql"` (the default), the collector emits the following
series.

**1.2.1 GraphQL Query Metrics**

```text
fraiseql_graphql_queries_total{operation_type="query",operation_name="users"} 5000
fraiseql_graphql_query_duration_seconds_bucket{operation_type="query",operation_name="users",le="0.05"} 4500
fraiseql_graphql_query_duration_seconds_sum{operation_type="query",operation_name="users"} 225
fraiseql_graphql_query_duration_seconds_count{operation_type="query",operation_name="users"} 5000
fraiseql_graphql_queries_success{operation_type="query"} 4980
fraiseql_graphql_queries_errors{operation_type="query"} 20
```

**1.2.2 Mutation Metrics**

```text
fraiseql_graphql_mutations_total{mutation_name="create_user"} 250
fraiseql_graphql_mutation_duration_seconds_sum{mutation_name="create_user"} 37.5
fraiseql_graphql_mutation_duration_seconds_count{mutation_name="create_user"} 250
fraiseql_graphql_mutations_success{mutation_name="create_user",result_type="CreateUserSuccess"} 240
fraiseql_graphql_mutations_errors{mutation_name="create_user",error_type="CreateUserError"} 10
```

**1.2.3 Database Metrics**

```text
fraiseql_db_connections_active 43
fraiseql_db_connections_idle 5
fraiseql_db_connections_total 50

fraiseql_db_queries_total{query_type="select",table_name="v_user"} 5000
fraiseql_db_query_duration_seconds_sum{query_type="select"} 175
fraiseql_db_query_duration_seconds_count{query_type="select"} 5000
```

**1.2.4 Cache Metrics**

These reflect FraiseQL's PostgreSQL-backed result cache
(`fraiseql.caching`), labelled by `cache_type`:

```text
fraiseql_cache_hits_total{cache_type="result"} 3500
fraiseql_cache_misses_total{cache_type="result"} 500   # ~87% hit rate
```

**1.2.5 Error Metrics**

```text
fraiseql_errors_total{error_type="QueryTimeout",error_code="DB_TIMEOUT",operation="users"} 25
fraiseql_errors_total{error_type="PermissionError",error_code="FORBIDDEN",operation="admin_panel"} 500
fraiseql_errors_total{error_type="ValidationError",error_code="INVALID_TYPE",operation="create_user"} 80
```

**1.2.6 HTTP & Response Time Metrics**

The metrics middleware records request-level series for every non-excluded path:

```text
fraiseql_http_requests_total{method="POST",endpoint="/graphql",status="200"} 8500
fraiseql_http_request_duration_seconds_sum{method="POST",endpoint="/graphql"} 382.5
fraiseql_http_request_duration_seconds_count{method="POST",endpoint="/graphql"} 8500
fraiseql_response_time_seconds_sum 382.5
fraiseql_response_time_seconds_count 8500
```

### 1.3 Custom Business Metrics

There is no metric decorator. Custom business metrics use standard
`prometheus_client` objects that you define once and update inside your
resolvers. Register them against the same registry the collector uses, or
the default registry, so they are scraped from the `/metrics` endpoint.

```python
from prometheus_client import Counter, Gauge

# Define business metrics once, at module scope.
USERS_CREATED = Counter(
    "app_users_created_total",
    "Number of users created",
)
ORDER_REVENUE = Gauge(
    "app_order_revenue",
    "Total order revenue in USD",
)

@fraiseql.mutation
async def create_user(info, input: CreateUserInput) -> CreateUserSuccess | CreateUserError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_user", {"name": input.name, "email": input.email}
    )
    if not result.get("success"):
        return CreateUserError(message=result.get("message", "failed"))

    USERS_CREATED.inc()                       # update business metric
    return CreateUserSuccess(user=User(**result["user"]))
```

For computed fields, attach a resolver with `@fraiseql.field` and update a
gauge inside it:

```python
@fraiseql.type(sql_source="v_order", jsonb_column="data")
class Order:
    id: ID
    total: float

    @fraiseql.field
    def revenue_bucket(self, info) -> str:
        ORDER_REVENUE.set(self.total)
        return "high" if self.total > 10_000 else "normal"
```

Custom metrics appear in the same Prometheus output:

```text
app_users_created_total 1250
app_order_revenue 450000.5
```

### 1.4 Metric Export Format

The `/metrics` endpoint serves the standard Prometheus text exposition format
produced by `prometheus_client.generate_latest`:

```text
# HELP fraiseql_graphql_queries_total Total number of GraphQL queries
# TYPE fraiseql_graphql_queries_total counter
fraiseql_graphql_queries_total{operation_type="query",operation_name="users"} 5000

# HELP fraiseql_graphql_query_duration_seconds GraphQL query execution time in seconds
# TYPE fraiseql_graphql_query_duration_seconds histogram
fraiseql_graphql_query_duration_seconds_bucket{operation_type="query",operation_name="users",le="0.01"} 500
fraiseql_graphql_query_duration_seconds_bucket{operation_type="query",operation_name="users",le="0.05"} 4500
fraiseql_graphql_query_duration_seconds_bucket{operation_type="query",operation_name="users",le="0.1"} 4800
fraiseql_graphql_query_duration_seconds_bucket{operation_type="query",operation_name="users",le="+Inf"} 5000
fraiseql_graphql_query_duration_seconds_sum{operation_type="query",operation_name="users"} 225
fraiseql_graphql_query_duration_seconds_count{operation_type="query",operation_name="users"} 5000
```

Other backends (CloudWatch, Datadog, OTLP) consume these metrics by pointing
their respective Prometheus-scrape integrations at the `/metrics` endpoint.

### 1.5 Querying Metrics in Prometheus

```promql
# Average query latency
rate(fraiseql_graphql_query_duration_seconds_sum[5m]) / rate(fraiseql_graphql_query_duration_seconds_count[5m])

# Query error rate
rate(fraiseql_graphql_queries_errors[5m]) / rate(fraiseql_graphql_queries_total[5m])

# Cache hit rate
rate(fraiseql_cache_hits_total[5m]) / (rate(fraiseql_cache_hits_total[5m]) + rate(fraiseql_cache_misses_total[5m]))

# P99 query latency
histogram_quantile(0.99, rate(fraiseql_graphql_query_duration_seconds_bucket[5m]))

# Top queries by latency
topk(5, rate(fraiseql_graphql_query_duration_seconds_sum[5m]) / rate(fraiseql_graphql_query_duration_seconds_count[5m]))
```

---

## 2. Structured Logging

FraiseQL uses Python's standard `logging`. Application code logs through the
`fraiseql.*` logger hierarchy, and security-relevant events go through the
dedicated audit logger in `fraiseql.audit`.

### 2.1 Log Levels & Categories

| Level | Usage |
|-------|-------|
| **DEBUG** | Development, detailed flow |
| **INFO** | Significant events (query/mutation completion) |
| **WARNING** | Unusual but handled situations |
| **ERROR** | Failed operations |
| **CRITICAL** | System failures |

Configure levels through standard Python logging or `FRAISEQL_`-prefixed
environment variables. Retention is a property of your log pipeline (e.g.
Loki, CloudWatch), not the framework.

### 2.2 Security Audit Logging

`fraiseql.audit` provides a structured `SecurityLogger` for security events.
Events are typed via `SecurityEventType` and severities via
`SecurityEventSeverity`, then serialized to structured JSON.

```python
from fraiseql.audit import (
    SecurityLogger,
    SecurityEvent,
    SecurityEventType,
    SecurityEventSeverity,
    set_security_logger,
)

security = SecurityLogger(log_to_stdout=True, log_to_file=False)
set_security_logger(security)

# Convenience helpers exist for common events:
security.log_auth_failure(reason="invalid_password", attempted_username="user-456")
security.log_authorization_denied(
    user_id="user-456",
    resource="AdminPanel.api_keys",
    action="read",
    reason="insufficient_role",
)

# Or emit a fully structured event:
security.log_event(
    SecurityEvent(
        event_type=SecurityEventType.QUERY_COMPLEXITY_EXCEEDED,
        severity=SecurityEventSeverity.WARNING,
        user_id="user-456",
        resource="searchUsers",
        reason="depth_limit",
    )
)
```

Available `SecurityEventType` values cover authentication (`AUTH_SUCCESS`,
`AUTH_FAILURE`, `AUTH_TOKEN_EXPIRED`, ...), authorization (`AUTHZ_DENIED`,
`AUTHZ_FIELD_DENIED`, `AUTHZ_PERMISSION_DENIED`, `AUTHZ_ROLE_DENIED`), rate
limiting, CSRF, query security (`QUERY_COMPLEXITY_EXCEEDED`,
`QUERY_DEPTH_EXCEEDED`, `QUERY_TIMEOUT`, `QUERY_MALICIOUS_PATTERN`), data
access, configuration, and system events.

### 2.3 Example Log Entries

Security events are serialized as structured JSON:

```json
{
  "timestamp": "2026-01-15T10:30:45.002Z",
  "event_type": "authz.role_denied",
  "severity": "warning",
  "user_id": "user-456",
  "resource": "AdminPanel.api_keys",
  "reason": "insufficient_role"
}
```

A typical application query log entry (your own logger):

```json
{
  "timestamp": "2026-01-15T10:30:45.045Z",
  "level": "info",
  "logger": "fraiseql.query",
  "message": "Query executed successfully",
  "operation": {"type": "query", "name": "users", "duration_ms": 45},
  "database": {"engine": "postgresql", "query_time_ms": 35, "rows_returned": 20}
}
```

A query timeout (ERROR):

```json
{
  "timestamp": "2026-01-15T10:30:45.000Z",
  "level": "error",
  "logger": "fraiseql.query",
  "message": "Query timeout",
  "operation": {"type": "query", "name": "users", "duration_ms": 30000},
  "error": {"code": "DB_QUERY_TIMEOUT", "retryable": true}
}
```

---

## 3. Distributed Tracing

FraiseQL ships an OpenTelemetry integration in `fraiseql.tracing`. Calling
`setup_tracing(app, config)` instruments the FastAPI app and (when the
OpenTelemetry packages are installed) auto-instruments the psycopg driver so
database spans nest under request spans.

```python
from fastapi import FastAPI
from fraiseql.tracing import setup_tracing, TracingConfig

app = FastAPI()

setup_tracing(
    app,
    TracingConfig(
        enabled=True,
        service_name="fraiseql",
        service_version="1.0.0",
        deployment_environment="production",
        sample_rate=0.1,                       # 10% of traces
        export_format="otlp",                  # otlp, jaeger, or zipkin
        export_endpoint="http://otel-collector:4317",
        exclude_paths={"/health", "/ready", "/metrics"},
    ),
)
```

`setup_tracing` returns a `FraiseQLTracer`; retrieve it later with
`get_tracer()`. Helper functions `trace_graphql_operation` and
`trace_database_query` create spans around specific operations.

### 3.1 Trace Context Propagation

Tracing follows the OpenTelemetry / W3C Trace Context model. Inbound
requests carrying a `traceparent` header continue the existing trace; the
psycopg instrumentation links database spans to the GraphQL operation span.

```text
Client Request
  ↓ (traceparent header)
FraiseQL FastAPI app
  ├─ Span: graphql.operation
  │  ├─ Span: authorization
  │  ├─ Span: database.query   (auto-instrumented psycopg)
  │  └─ Span: response.transform
  └─ Returns response (trace continues downstream)
```

### 3.2 W3C Trace Context Headers

```text
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
tracestate: congo=t61rcWpm35YzTP60
```

Header format:

```text
traceparent: version-trace_id-parent_span_id-trace_flags
00         = version 0 (W3C spec v1)
4bf92...   = trace ID (16 bytes hex)
00f067...  = parent span ID (8 bytes hex)
01         = trace flags (01 = sampled)
```

### 3.3 Span Hierarchy

A typical GraphQL query produces a span tree like:

```text
Span: graphql.operation (root)
├─ duration: 45ms
├─ attributes:
│  ├─ graphql.operation.name: "users"
│  └─ graphql.operation.type: "query"
│
├─ Span: authorization (child)
│  ├─ duration: 3ms
│  └─ attributes:
│     └─ allowed: true
│
├─ Span: database.query (child, psycopg auto-instrumented)
│  ├─ duration: 35ms
│  └─ attributes:
│     ├─ db.system: "postgresql"
│     ├─ db.statement: "SELECT data FROM v_user WHERE ..."
│     └─ db.rows: 20
│
└─ Span: response.transform (child)
   ├─ duration: 5ms
   └─ attributes:
      └─ format: "json"
```

### 3.4 Sampling Strategy

`sample_rate` controls head-based sampling (0.0–1.0). A value of `0.1` samples
10% of traces; `1.0` samples everything. For lower-traffic, error-focused
visibility, run a high sample rate in staging and a lower one in production,
then rely on metrics and logs to surface anomalies.

```python
TracingConfig(sample_rate=0.1)   # 10% in production
TracingConfig(sample_rate=1.0)   # 100% in staging / debugging
```

### 3.5 Trace Export

The exporter is selected by `export_format` (`"otlp"`, `"jaeger"`, or
`"zipkin"`) and pointed at your collector with `export_endpoint`. OTLP is the
recommended transport; from an OpenTelemetry Collector you can fan out to
Jaeger, Tempo, Datadog, or any OTLP-compatible backend.

```python
# OTLP (recommended) → OpenTelemetry Collector
TracingConfig(export_format="otlp", export_endpoint="http://otel-collector:4317")

# Direct to Jaeger
TracingConfig(export_format="jaeger", export_endpoint="jaeger-agent:6831")
```

---

## 4. Alerting Rules

FraiseQL has no alert decorator or built-in alert engine. Alerting is done the
standard Prometheus way: write alerting rules over the metrics exposed at
`/metrics`, and route them with Alertmanager.

### 4.1 Example Prometheus Alert Rules (`alerts.yml`)

```yaml
groups:
  - name: fraiseql.alerts
    interval: 30s
    rules:
      - alert: QueryLatencyHigh
        expr: histogram_quantile(0.95, rate(fraiseql_graphql_query_duration_seconds_bucket[5m])) > 1.0
        for: 5m
        annotations:
          summary: "Query latency high (p95 > 1s)"

      - alert: QueryErrorRateHigh
        expr: rate(fraiseql_graphql_queries_errors[5m]) / rate(fraiseql_graphql_queries_total[5m]) > 0.01
        for: 5m
        annotations:
          summary: "Query error rate > 1%"

      - alert: CacheHitRateLow
        expr: rate(fraiseql_cache_hits_total[5m]) / (rate(fraiseql_cache_hits_total[5m]) + rate(fraiseql_cache_misses_total[5m])) < 0.5
        for: 10m
        annotations:
          summary: "Cache hit rate below 50%"
          remediation: "Review cache TTLs or invalidation rules"

      - alert: DatabaseConnectionPoolExhausted
        expr: fraiseql_db_connections_active / fraiseql_db_connections_total > 0.9
        for: 2m
        annotations:
          summary: "Database connection pool 90% utilized"
          remediation: "Increase pool size or check for connection leaks"

      - alert: ErrorRateHigh
        expr: rate(fraiseql_errors_total[5m]) > 5
        for: 5m
        annotations:
          summary: "Elevated error rate"
```

### 4.2 Application-Specific Alerts

Define alerts over your own business metrics (Section 1.3) the same way:

```yaml
groups:
  - name: app.business.alerts
    rules:
      - alert: NoUserSignups
        expr: rate(app_users_created_total[1h]) == 0
        for: 1h
        annotations:
          summary: "No user signups in the last hour"
```

### 4.3 Alert Routing & Notification (Alertmanager)

```yaml
route:
  receiver: default
  routes:
    - match: {severity: critical}
      receiver: pagerduty
    - match: {severity: high}
      receiver: slack_eng
    - match: {severity: medium}
      receiver: email

receivers:
  - name: pagerduty
    pagerduty_configs:
      - routing_key: <secret>
  - name: slack_eng
    slack_configs:
      - api_url: "https://hooks.slack.com/..."
  - name: email
    email_configs:
      - to: alerts@company.com
```

---

## 5. Health Checks & Readiness Probes

The FastAPI app created by `create_fraiseql_app` exposes two endpoints out of
the box: `/health` (liveness) and `/ready` (readiness).

### 5.1 Built-in Health Endpoints

```text
# Liveness probe (is the process alive?)
GET /health
200 OK {"status": "healthy", "service": "fraiseql"}

# Readiness probe (can it serve traffic?)
GET /ready
200 OK {
  "status": "ready",
  "checks": {"database": "ok", "schema": "ok"}
}
```

`/ready` validates that the database pool is reachable (a simple query test)
and that the GraphQL schema is loaded; it returns `503 Service Unavailable`
when the app is not ready.

### 5.2 Composable Health Checks

For richer checks, compose your own with `HealthCheck` from
`fraiseql.monitoring`, using the pre-built check functions:

```python
from fraiseql.monitoring import (
    HealthCheck,
    CheckResult,
    HealthStatus,
    check_database,
    check_pool_stats,
)

health = HealthCheck()
health.add_check("database", lambda: check_database(pool))
health.add_check("pool", lambda: check_pool_stats(pool))

# Add a custom check:
async def check_external_api() -> CheckResult:
    ok = await ping_dependency()
    return CheckResult(
        name="external_api",
        status=HealthStatus.HEALTHY if ok else HealthStatus.UNHEALTHY,
        message="reachable" if ok else "unreachable",
    )

health.add_check("external_api", check_external_api)

result = await health.run_checks()
# {"status": "healthy", "checks": {"database": {...}, "pool": {...}, ...}}
```

### 5.3 Kubernetes Probes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fraiseql
spec:
  template:
    spec:
      containers:
        - name: fraiseql
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 2
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /ready
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
            timeoutSeconds: 2
            failureThreshold: 2
```

---

## 6. Query Performance Analysis

FraiseQL exposes PostgreSQL's own query statistics through
`QueryStatsCollector`, which reads `pg_stat_statements`. There is no built-in
process profiler; performance analysis leans on PostgreSQL's tooling.

### 6.1 pg_stat_statements Integration

```python
from fraiseql.monitoring import init_query_stats, get_query_stats_collector

collector = init_query_stats(pool)
stats = await collector.get_stats(top_n=20, order_by="total_exec_time")
for s in stats:
    print(f"{s.query_preview[:60]}  calls={s.calls}  mean_ms={s.mean_exec_time_ms:.2f}")
```

Each `QueryStatsSnapshot` includes `calls`, `total_exec_time_ms`,
`mean_exec_time_ms`, `min`/`max` exec time, `rows_returned`, shared block
hits/reads, and `cache_hit_ratio`. The collector degrades gracefully
(returns empty results) when the `pg_stat_statements` extension is not
installed.

### 6.2 Analyzing Slow Queries with EXPLAIN

Because every read resolves to a `v_`/`tv_` view, use PostgreSQL's
`EXPLAIN (ANALYZE, BUFFERS)` directly on the generated SQL to find missing
indexes:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT data FROM v_user WHERE data->>'status' = 'active';
```

If the plan shows a sequential scan over a large table, add an index on the
underlying write table:

```sql
CREATE INDEX idx_user_status ON tb_user (status);
```

### 6.3 Slow Query Logging

Combine the `QueryStatsCollector` output with a Prometheus alert on
`fraiseql_db_query_duration_seconds` to catch regressions, and enable
PostgreSQL's `log_min_duration_statement` to capture slow statements at the
database level.

---

## 7. Observability Configuration

### 7.1 Putting It Together

```python
from fastapi import FastAPI
from fraiseql.monitoring import setup_metrics, MetricsConfig, init_query_stats
from fraiseql.tracing import setup_tracing, TracingConfig
from fraiseql.audit import SecurityLogger, set_security_logger

app = FastAPI()

# Metrics → /metrics endpoint
setup_metrics(app, MetricsConfig(namespace="fraiseql", metrics_path="/metrics"))

# Tracing → OTLP collector
setup_tracing(
    app,
    TracingConfig(
        service_name="fraiseql",
        sample_rate=0.1,
        export_format="otlp",
        export_endpoint="http://otel-collector:4317",
    ),
)

# Security audit logging
set_security_logger(SecurityLogger(log_to_stdout=True, log_to_file=False))

# Query stats (requires pg_stat_statements)
init_query_stats(pool)
```

### 7.2 Configuration Reference

`MetricsConfig` fields: `enabled`, `namespace` (default `"fraiseql"`),
`metrics_path` (default `"/metrics"`), `buckets` (histogram boundaries),
`exclude_paths`, `labels`.

`TracingConfig` fields: `enabled`, `service_name`, `service_version`,
`deployment_environment`, `sample_rate`, `export_format`
(`otlp`/`jaeger`/`zipkin`), `export_endpoint`, `export_timeout_ms`,
`propagate_traces`, `exclude_paths`, `attributes`.

### 7.3 Environment Variables

Application-level toggles use the `FRAISEQL_` prefix and your own logging
configuration:

```bash
# Set the root logging level
FRAISEQL_LOG_LEVEL=debug

# Path for the security audit log file
FRAISEQL_SECURITY_LOG_PATH=/var/log/fraiseql/security_events.log
```

OpenTelemetry exporters also honor the standard `OTEL_*` environment
variables (e.g. `OTEL_EXPORTER_OTLP_ENDPOINT`) when the OpenTelemetry SDK is
installed.

---

## 8. Dashboard Examples

### 8.1 Grafana Dashboard: Query Performance

```text
┌──────────────────────────────────────────────────────────┐
│ FraiseQL Query Performance Dashboard                       │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  Queries/sec ↑ 8500    Errors ↑ 0.2%    Cache Hit ↑ 87%   │
│                                                            │
│  ┌─────────────────────┐  ┌──────────────────────────┐    │
│  │ Query Latency (p95) │  │ Top Slow Queries         │    │
│  │ ████░░░░░░  245ms    │  │ 1. complex_search: 5.2s  │    │
│  └─────────────────────┘  │ 2. joined_query:   3.1s  │    │
│                           │ 3. nested_fetch:   2.8s  │    │
│  ┌─────────────────────┐  └──────────────────────────┘    │
│  │ Cache Hit Rate      │                                  │
│  │ ██████████ 87%      │   DB Connection Pool             │
│  └─────────────────────┘   Active: 43 / 50  (86%)         │
│                                                            │
└──────────────────────────────────────────────────────────┘
```

These panels are driven by the PromQL queries in Section 1.5 against the
`fraiseql_*` series.

### 8.2 Grafana Dashboard: System Health

```text
┌──────────────────────────────────────────────────────────┐
│ FraiseQL System Health Dashboard                           │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  DB Latency: 2.1ms   Active conns: 43/50   Errors/s: 0.1  │
│                                                            │
│  ┌─────────────────────┐  ┌──────────────────────────┐    │
│  │ Request Rate        │  │ Error Rate by Operation  │    │
│  │ 10K req/s           │  │ create_user:  0.4%       │    │
│  └─────────────────────┘  │ users:        0.1%       │    │
│                           └──────────────────────────┘    │
│  Cache Hit Rate: 87%                                       │
│                                                            │
└──────────────────────────────────────────────────────────┘
```

---

## 9. Troubleshooting Guide

### 9.1 Using Traces to Debug Slow Queries

**Problem**: A query is taking ~5 seconds.

```text
1. Inspect the trace span tree for graphql.operation (5000ms):
   ├─ authorization:      3ms     ✓ fast
   ├─ database.query:  4990ms     ✗ SLOW
   └─ response.transform: 5ms     ✓ fast

2. The database span is the culprit. Check its attributes:
   - db.system: postgresql
   - db.statement: SELECT data FROM v_user WHERE ...
   - db.rows: 100   (but the scan touched far more)

3. Run EXPLAIN (ANALYZE, BUFFERS) on that statement; if it's a seq scan,
   add an index on the underlying tb_ table:
   CREATE INDEX idx_user_status ON tb_user (status);

4. Re-trace: the database span drops to ~35ms.
```

### 9.2 Using Logs to Debug Authorization

**Problem**: Some users can't access a field.

```text
1. Find the security audit event:
   event_type: "authz.role_denied"
   user_id:    "user-456"
   resource:   "AdminPanel.api_keys"
   reason:     "insufficient_role"

2. Verify the user's roles (PostgreSQL or your auth provider):
   roles = ['user']   (not 'admin')

3. Verify ownership for owner-or-admin rules:
   SELECT fk_author FROM tb_post WHERE id = 'post-789';
   → owner is a different user

4. Conclusion: the denial is correct. The user must hold the required role
   or own the resource.
```

---

## 10. Best Practices

### 10.1 Observability Configuration

- Call `setup_metrics(app, ...)` and scrape `/metrics` in every environment.
- Sample traces (10% in production, higher in staging) to control cost.
- Emit security events through `SecurityLogger` for an auditable trail.
- Set Prometheus alert thresholds that match your SLOs.
- Track query latency p95/p99 and the cache hit rate.
- Wire `/health` and `/ready` into your liveness/readiness probes.

### 10.2 Using Traces Effectively

- Use the span tree to localize bottlenecks (auth vs. database vs. transform).
- Compare traces of slow vs. fast requests for the same operation.
- Watch for unexpected database spans inside response transformation.
- Add custom span attributes for request context where it aids debugging.

### 10.3 Interpreting Alerts

- High query latency → inspect `pg_stat_statements`, run `EXPLAIN`, add indexes.
- High error rate → group `fraiseql_errors_total` by `error_code`.
- Low cache hit rate → review cache TTLs / invalidation rules.
- Connection pool near capacity → raise pool size or hunt for leaks.

---

FraiseQL's observability model provides visibility into system behavior
through Prometheus metrics, structured and security-audit logs, and
OpenTelemetry traces — all served from the same FastAPI application, backed
by PostgreSQL.
