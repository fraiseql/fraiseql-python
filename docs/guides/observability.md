<!-- Skip to main content -->
---

title: Observability Guide for FraiseQL
description: - Observability fundamentals (logs, metrics, traces - the three pillars)
keywords: ["debugging", "implementation", "best-practices", "deployment", "tutorial"]
tags: ["documentation", "reference"]
---

# Observability Guide for FraiseQL

**Status:** ✅ Production Ready
**Audience:** DevOps, SREs, Architects
**Reading Time:** 15-20 minutes

---

## Prerequisites

### Required Knowledge

- Observability fundamentals (logs, metrics, traces - the three pillars)
- Structured logging and JSON formats
- Time-series metrics and Prometheus concepts
- Distributed tracing and span concepts
- Audit logging and compliance requirements
- Multi-tenancy data isolation patterns (PostgreSQL Row-Level Security)

### Required Software

- FraiseQL v1 (Python 3.13+, served as a FastAPI app)
- PostgreSQL 14+
- Prometheus (for metrics collection)
- Grafana (for visualization) or alternative dashboarding tool
- Jaeger, Zipkin, or any OTLP-compatible backend (for distributed tracing)
- Log aggregation tool (ELK, Splunk, DataDog, New Relic, or similar)
- curl or a GraphQL client for testing

### Required Infrastructure

- A running FraiseQL FastAPI application (`uvicorn app:app`)
- PostgreSQL database
- Prometheus scrape-compatible endpoint (FraiseQL exposes `/metrics`)
- Log collection infrastructure (syslog, vector, fluentd, etc.)
- Trace backend (Jaeger collector, Zipkin server, or OTLP collector)
- Metrics storage (Prometheus or similar time-series database)
- Grafana or visualization tool
- Network connectivity between all components

#### Optional but Recommended

- Kubernetes monitoring (Prometheus Operator)
- Alert manager for anomaly detection
- Custom Grafana dashboards/templates
- Distributed tracing sampling strategies
- Log retention and archival policies
- Metrics correlation tools

**Time Estimate:** 1-3 hours for basic setup, 4-8 hours for production configuration with alerting

## 1. Overview

Observability in FraiseQL means understanding **what's happening** in your system through three pillars:

1. **Logs** — Detailed records of what occurred (queries, mutations, errors, decisions)
2. **Metrics** — Aggregated measurements (rates, latencies, counts)
3. **Traces** — Request flows from entry to exit with timing

FraiseQL exposes observability at two levels:

- **Application level** — The FastAPI app emits Prometheus metrics (`/metrics`), OpenTelemetry
  traces, health checks, and structured Python logs. These are wired in via the helpers in
  `fraiseql.monitoring` and `fraiseql.tracing`.
- **Database level** — Because reads and writes run through PostgreSQL views (`v_`/`tv_`) and
  functions (`fn_`), the database is a rich source of truth: `pg_stat_statements`,
  `pg_stat_activity`, and any audit tables you maintain in your own schema.

This combination enables:

- **Performance analysis** — Query execution patterns visible in metrics, traces, and PostgreSQL stats
- **Deterministic debugging** — Mutation outcomes returned as structured success/error results
- **Compliance audits** — Application-defined audit tables capture user/tenant context
- **Real-time alerts** — Prometheus alerting rules over the exported metrics
- **Multi-tenant isolation** — All observations scoped by tenant via Row-Level Security

---

## 2. Application Metrics (Prometheus)

FraiseQL ships first-class Prometheus integration in `fraiseql.monitoring`. Call `setup_metrics`
on the FastAPI app returned by `create_fraiseql_app`; it registers a `/metrics` endpoint and an
HTTP middleware that records request counts, durations, and error rates.

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.monitoring import setup_metrics, MetricsConfig

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    production=True,
)

# Adds /metrics, the metrics middleware, and a global FraiseQLMetrics instance
metrics = setup_metrics(
    app,
    MetricsConfig(
        enabled=True,
        namespace="fraiseql",          # prefix for every metric name
        metrics_path="/metrics",        # Prometheus scrape path
        exclude_paths={"/metrics", "/health", "/ready", "/startup"},
        labels={"service": "orders-api", "env": "production"},
    ),
)
```

`MetricsConfig` (from `fraiseql.monitoring`) accepts:

| Field | Purpose | Default |
|-------|---------|---------|
| `enabled` | Toggle collection on/off | `True` |
| `namespace` | Prefix applied to every metric name | `"fraiseql"` |
| `metrics_path` | URL path Prometheus scrapes | `"/metrics"` |
| `buckets` | Histogram bucket boundaries for latency metrics | sensible default set |
| `exclude_paths` | Paths skipped by the HTTP metrics middleware | health/metrics paths |
| `labels` | Extra labels applied to all metrics | `{}` |

Install the optional dependency to enable real metrics (FraiseQL degrades to no-op placeholders
when it is absent):

```bash
uv pip install prometheus-client
```

### 2.1 What gets exported

The middleware and the `FraiseQLMetrics` collector track, among others:

- `fraiseql_http_requests_total{method,endpoint,status}` — request counts
- `fraiseql_http_request_duration_seconds{method,endpoint}` — request latency histogram
- GraphQL query/mutation counts and durations
- Error counts by type and operation

Scrape config for Prometheus:

```yaml
scrape_configs:
  - job_name: fraiseql
    metrics_path: /metrics
    static_configs:
      - targets: ["fraiseql-app:8000"]
```

### 2.2 Recording custom metrics

Wrap a resolver or any callable with `with_metrics` to record execution time and success/failure
against the global metrics instance:

```python
from fraiseql.monitoring import with_metrics

@with_metrics("query")
async def expensive_report(info) -> Report:
    db = info.context["db"]
    return await db.find_one("v_report", id=info.variable_values["id"])
```

You can also reach the live collector directly with `get_metrics()` to record bespoke values.

---

## 3. Distributed Tracing (OpenTelemetry)

FraiseQL provides OpenTelemetry tracing in `fraiseql.tracing`. Call `setup_tracing` on the app to
add the tracing middleware; it automatically instruments psycopg so PostgreSQL queries appear as
spans, and exports to an OTLP, Jaeger, or Zipkin backend.

```python
from fraiseql.tracing import setup_tracing, TracingConfig

setup_tracing(
    app,
    TracingConfig(
        enabled=True,
        service_name="orders-api",
        service_version="1.4.0",
        deployment_environment="production",
        sample_rate=0.1,                       # 10% sampling
        export_format="otlp",                  # "otlp" | "jaeger" | "zipkin"
        export_endpoint="http://otel-collector:4317",
        propagate_traces=True,                  # W3C trace-context propagation
        exclude_paths={"/health", "/ready", "/metrics", "/docs", "/openapi.json"},
    ),
)
```

Install the OpenTelemetry extras you need (FraiseQL no-ops cleanly if they are missing):

```bash
uv pip install opentelemetry-sdk opentelemetry-exporter-otlp \
    opentelemetry-instrumentation-psycopg
```

### 3.1 Span structure

With tracing enabled you get spans for:

- The inbound HTTP request (method, route, status)
- The GraphQL operation (operation type and name)
- Each PostgreSQL statement (via the psycopg instrumentor)

Helper utilities `trace_graphql_operation` and `trace_database_query` (also exported from
`fraiseql.tracing`) let you add custom spans around your own logic, and `get_tracer()` returns the
active `FraiseQLTracer`.

### 3.2 Correlating traces with logs

Because trace and span IDs are propagated via W3C trace-context, include them in your structured
log lines (see section 5) so a log entry can be pivoted to its trace in Jaeger/Zipkin and back.

---

## 4. Health Checks

FraiseQL exposes a composable `HealthCheck` runner plus ready-made checks in
`fraiseql.monitoring`. Register the checks you care about and serve the aggregate result from a
FastAPI route for Kubernetes liveness/readiness probes.

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

@app.get("/health")
async def healthz():
    result = await health.run_checks()
    return result
```

Each check returns a `CheckResult` with a `HealthStatus`; the overall status degrades to unhealthy
if any check fails, and exceptions are caught and reported rather than crashing the probe.

---

## 5. Logging Patterns

FraiseQL uses the standard Python `logging` module. Configure log level and format with
`logging.basicConfig(...)` (or your aggregator's handler) when you start the app — there is no
separate logging config file. Run the app with `uvicorn app:app` and your logging configuration
applies to FraiseQL's loggers (which live under the `fraiseql` namespace).

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
# Turn up FraiseQL detail selectively
logging.getLogger("fraiseql").setLevel(logging.INFO)
logging.getLogger("fraiseql.sql").setLevel(logging.DEBUG)  # log generated SQL while debugging
```

### 5.1 Structured logging

For machine-parseable logs, attach a JSON formatter (for example `python-json-logger`) and include
correlation fields. A typical structured log line:

```json
{
  "timestamp": "2026-01-11T15:00:00.123456Z",
  "level": "INFO",
  "message": "User created successfully",
  "service": "orders-api",
  "component": "mutation",
  "request_id": "req_550e8400-e29b-41d4-a716-446655440000",
  "trace_id": "trace_550e8400...",
  "user_id": "user_550e8400-e29b-41d4-a716-446655440001",
  "tenant_id": "org_550e8400-e29b-41d4-a716-446655440002",
  "entity_type": "User",
  "entity_id": "550e8400-e29b-41d4-a716-446655440003",
  "status": "new",
  "duration_ms": 245
}
```

### 5.2 Log levels

| Level | Purpose | Examples |
|-------|---------|----------|
| **ERROR** | Unexpected failures | Mutation failed, database connection lost, authorization denied |
| **WARN** | Expected but notable | Validation failure, no-op, conflict, rate limit |
| **INFO** | Normal operations | Mutation completed, query executed, auth check passed |
| **DEBUG** | Development troubleshooting | Generated SQL, authorization decision, field projection |

### 5.3 Error tracking

`fraiseql.monitoring` includes a PostgreSQL-native error tracker (a Sentry-style replacement) that
persists captured exceptions to your database, and a notification system (`EmailChannel`,
`SlackChannel`, `WebhookChannel`) to alert on them.

```python
from fraiseql.monitoring import init_error_tracker, get_error_tracker

tracker = init_error_tracker(db_pool, environment="production")

try:
    await risky_operation()
except Exception as exc:
    await tracker.capture_exception(exc, context={"request_id": request_id})
```

---

## 6. Request Tracing & Correlation

Every request should carry a **request ID / correlation ID** that flows through GraphQL execution
and PostgreSQL calls. Generate or read it in your `context_getter`, store it in `info.context`, and
thread it into both your log lines and your audit writes.

```python
import uuid

async def context_getter(request):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    return {
        "request_id": request_id,
        "tenant_id": request.headers.get("X-Tenant-ID"),
    }

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users],
    context_getter=context_getter,
)
```

Inside a `fn_` function you can persist the correlation ID alongside the write so audit rows are
traceable back to the originating request:

```sql
CREATE OR REPLACE FUNCTION fn_create_user(
    input_request_id UUID,
    input_user_id UUID,
    input_email TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
BEGIN
    -- ... perform the write ...
    INSERT INTO app.tb_audit_log (request_id, user_id, action, object_type)
    VALUES (input_request_id, input_user_id, 'create', 'User');

    RETURN jsonb_build_object('success', true);
END;
$$;
```

### Trace context fields to carry

| Field | Purpose | Example |
|-------|---------|---------|
| `request_id` | Link all operations in a request | `req_550e8400...` |
| `user_id` | Who initiated the request | `uuid` |
| `tenant_id` | Which organization | `uuid` |
| `session_id` | User session | `sess_abc123` |
| `trace_id` | Distributed tracing | `trace_550e8400...` |
| `span_id` | Operation within trace | `span_001` |

---

## 7. Database Observability (PostgreSQL)

Because all reads and writes run through PostgreSQL, the database's own statistics views are a
core part of FraiseQL observability. Enable `pg_stat_statements` and query the standard views.

### 7.1 Most expensive statements

```sql
-- pg_stat_statements: most expensive queries
SELECT
    calls,
    total_exec_time,
    mean_exec_time,
    query
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 20;
```

### 7.2 Connection pool and active queries

```sql
-- Connection state distribution
SELECT state, COUNT(*) AS count
FROM pg_stat_activity
GROUP BY state;

-- Active (non-idle) queries and their durations
SELECT
    pid,
    usename,
    application_name,
    state,
    EXTRACT(EPOCH FROM (NOW() - state_change)) AS duration_sec,
    query
FROM pg_stat_activity
WHERE state != 'idle'
ORDER BY state_change ASC;
```

### 7.3 Table access patterns and sizes

```sql
-- Sequential vs index scans per table
SELECT
    schemaname,
    relname AS tablename,
    seq_scan,
    seq_tup_read,
    idx_scan,
    idx_tup_fetch
FROM pg_stat_user_tables
ORDER BY seq_scan DESC;

-- Table / index sizes
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC;
```

### 7.4 Inspecting query plans

```sql
-- Analyze a read view's execution plan
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT * FROM v_user WHERE id = $1;

-- Look for:
-- - Sequential scans that should be index scans
-- - High costs (optimization opportunity)
-- - Buffer hits (cache effectiveness)
```

---

## 8. Query & Mutation Observability

### 8.1 Slow query detection

Use the application metrics histogram (section 2) to find slow GraphQL operations, and confirm at
the SQL layer with `pg_stat_statements` and `EXPLAIN ANALYZE` against the underlying `v_`/`tv_`
view. If you maintain your own query-timing table, you can aggregate percentiles:

```sql
-- Aggregate your application-level query timing table
SELECT
    query_name,
    COUNT(*) AS count,
    AVG(execution_time_ms) AS avg_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY execution_time_ms) AS p95_ms,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY execution_time_ms) AS p99_ms
FROM app.query_log
WHERE logged_at > NOW() - INTERVAL '24 hours'
GROUP BY query_name
HAVING AVG(execution_time_ms) > 50
ORDER BY avg_ms DESC;
```

### 8.2 N+1 detection

FraiseQL prevents N+1 access through **view composition** (nest related data inside the `data`
JSONB of a `v_`/`tv_` view) and **`@fraiseql.dataloader_field`** for batched field resolution. If a
trace (section 3) shows the same query repeated per parent row, switch to one of those patterns.

### 8.3 Cache hit/miss visibility

FraiseQL's PostgreSQL-backed result cache lives in `fraiseql.caching` (`PostgresCache`,
`ResultCache`, `CachedRepository`, `CacheStats`, `cached_query`, cascade-invalidation rules).
`CacheStats` exposes hit/miss counts you can surface as metrics or a dashboard panel:

```python
from fraiseql.caching import ResultCache, CacheStats

# After wiring a ResultCache / CachedRepository, read its stats
stats: CacheStats = result_cache.stats
hit_rate = stats.hits / max(stats.hits + stats.misses, 1)
```

---

## 9. Metrics & Telemetry from the Database

You can also derive business and operational metrics directly from PostgreSQL using runtime
auto-aggregation in your `v_`/`tv_` views or ad-hoc SQL. These complement the application metrics.

### 9.1 Request/mutation throughput

If you keep an application audit table (for example `app.tb_audit_log`), bucket it by time:

```sql
-- Mutations per minute over the last 24 hours
SELECT
    DATE_TRUNC('minute', created_at) AS minute,
    COUNT(*) AS mutations,
    ROUND(COUNT(*) / 60.0, 2) AS mutations_per_sec
FROM app.tb_audit_log
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY minute
ORDER BY minute DESC;
```

### 9.2 Error rates

```sql
-- Failure rate from your audit table
SELECT
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status LIKE 'failed:%' OR status IN ('not_found', 'forbidden'))
        / COUNT(*),
        2
    ) AS error_rate_pct
FROM app.tb_audit_log
WHERE created_at > NOW() - INTERVAL '24 hours';
```

### 9.3 Business metrics

```sql
-- New entities per day
SELECT
    DATE(created_at) AS date,
    object_type,
    COUNT(*) AS new_entities
FROM app.tb_audit_log
WHERE created_at > NOW() - INTERVAL '30 days'
  AND action = 'create'
GROUP BY DATE(created_at), object_type
ORDER BY date DESC;
```

> These queries assume an audit table you define in your own schema. FraiseQL does not impose a
> specific audit schema; model it to suit your compliance needs and query it like any other table.

---

## 10. Monitoring & Alerting

### 10.1 Key metrics to monitor

| Metric | Threshold | Action |
|--------|-----------|--------|
| **GraphQL error rate** | > 5% | Page on-call |
| **Query p95 latency** | > 100ms | Investigate slow queries |
| **Database connection pool** | > 80% | Add connections or optimize |
| **Authorization denials** | > 1% of requests | Review auth rules |

### 10.2 Prometheus alert rules

Alert directly on the exported Prometheus metrics rather than polling SQL:

```yaml
groups:
  - name: fraiseql
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(fraiseql_http_requests_total{status=~"5.."}[5m]))
            / sum(rate(fraiseql_http_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "FraiseQL 5xx error rate above 5%"

      - alert: HighP95Latency
        expr: |
          histogram_quantile(
            0.95,
            sum(rate(fraiseql_http_request_duration_seconds_bucket[5m])) by (le)
          ) > 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "FraiseQL p95 latency above 100ms"
```

### 10.3 Slow query alerting at the database

```sql
-- Find statements whose mean execution time exceeds 1 second
SELECT calls, mean_exec_time, query
FROM pg_stat_statements
WHERE mean_exec_time > 1000
ORDER BY mean_exec_time DESC;
```

---

## 11. Debugging Workflows

### 11.1 Debugging failed mutations

In v1 a `@fraiseql.mutation` resolver returns a typed success **or** error result built from the
JSONB its `fn_` function returns. To debug a failure:

1. Reproduce the mutation and capture the returned error result (message + code).
2. Inspect the `fn_` function's logic and any constraint it violated.
3. If you maintain an audit table, look up the row by `request_id` to see context.

```sql
-- Find the audit row for a failed write
SELECT *
FROM app.tb_audit_log
WHERE object_id = $1
  AND status LIKE 'failed:%'
ORDER BY created_at DESC
LIMIT 1;
```

### 11.2 Debugging slow queries

1. Identify the slow operation from metrics or a trace.
2. Run `EXPLAIN (ANALYZE, BUFFERS)` on the underlying `v_`/`tv_` view.
3. Verify indexes exist on the columns the view filters/joins on.
4. Check for N+1 patterns (section 8.2) and apply view composition or `@fraiseql.dataloader_field`.

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM v_user WHERE id = $1;
```

### 11.3 Debugging authorization failures

1. Confirm the auth context (`user_id`, roles, `tenant_id`) reached `info.context`.
2. Review the `Authorizer` passed to `create_fraiseql_app(authorizer=...)` or the
   `@fraiseql.query(authorizer=...)` decision.
3. For multi-tenant data, verify the Row-Level Security policy and that the session GUC
   (`app.tenant_id`) was set from the request context.

```sql
-- Confirm the tenant GUC is set the way RLS expects
SHOW app.tenant_id;
```

---

## 12. Production Patterns

### 12.1 Audit table archival

If you maintain audit/observability tables, archive and partition them to keep them fast:

```sql
-- Archive rows older than 90 days
CREATE TABLE IF NOT EXISTS app.tb_audit_log_archive (LIKE app.tb_audit_log);

INSERT INTO app.tb_audit_log_archive
SELECT * FROM app.tb_audit_log
WHERE created_at < NOW() - INTERVAL '90 days';

DELETE FROM app.tb_audit_log
WHERE created_at < NOW() - INTERVAL '90 days';

-- Or partition by month for faster time-range queries
CREATE TABLE app.tb_audit_log_2026_01 PARTITION OF app.tb_audit_log
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
```

### 12.2 Performance considerations

- **Sampling** — Trace at a low `sample_rate` (e.g. `0.1`) in production; metrics are cheap, traces are not.
- **Async, non-blocking writes** — Keep audit writes inside the same `fn_` transaction so they
  succeed or roll back with the mutation, and avoid heavy synchronous side effects on the hot path.
- **External aggregation** — Stream logs to an external aggregator (Splunk, DataDog, ELK) rather
  than querying large log tables in the database.
- **Exclude noisy paths** — `MetricsConfig.exclude_paths` and `TracingConfig.exclude_paths` keep
  `/health`, `/metrics`, and docs routes out of your telemetry.

### 12.3 Multi-tenant observability

Always scope observability data by tenant. Tenant context flows
request → `info.context["tenant_id"]` → session GUC → Row-Level Security, so your audit queries and
per-tenant dashboards should filter explicitly:

```sql
-- Per-tenant dashboard query
SELECT object_type, status, COUNT(*) AS count
FROM app.tb_audit_log
WHERE tenant_id = $1                       -- always filter by tenant
  AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY object_type, status;
```

---

## Summary

### Observability in FraiseQL is

1. **Two-layer** — Application metrics/traces/logs plus PostgreSQL statistics
2. **Standards-based** — Prometheus, OpenTelemetry, and standard Python logging
3. **Multi-tenant aware** — Scope every observation by tenant via Row-Level Security
4. **Traceable** — Correlation IDs link a request through GraphQL execution and SQL
5. **Queryable** — Use SQL over `pg_stat_*` and your own audit tables to aggregate metrics
6. **Audit-ready** — Application-defined audit tables capture user/tenant context for compliance

### Key building blocks

- `fraiseql.monitoring` — `setup_metrics`, `MetricsConfig`, `HealthCheck`, error tracking, notifications
- `fraiseql.tracing` — `setup_tracing`, `TracingConfig`, OpenTelemetry spans, psycopg instrumentation
- `fraiseql.caching` — `ResultCache` / `CacheStats` for cache hit/miss visibility
- PostgreSQL — `pg_stat_statements`, `pg_stat_activity`, `pg_stat_user_tables`, and `EXPLAIN ANALYZE`

---

## Troubleshooting

### "No metrics appear at /metrics"

**Cause:** `prometheus-client` is not installed, or `setup_metrics` was not called.

#### Diagnosis

1. Confirm the dependency: `uv pip show prometheus-client`.
2. Confirm `setup_metrics(app, ...)` runs at startup.
3. Curl the endpoint: `curl http://localhost:8000/metrics`.

#### Solutions

- Install the optional dependency: `uv pip install prometheus-client`.
- Call `setup_metrics(app, MetricsConfig(enabled=True))` after `create_fraiseql_app`.
- Verify `metrics_path` matches your Prometheus scrape config.

### "Traces are not exported"

**Cause:** OpenTelemetry SDK/exporter missing, tracing disabled, or no export endpoint configured.

#### Diagnosis

1. Confirm the packages: `uv pip show opentelemetry-sdk opentelemetry-exporter-otlp`.
2. Check `TracingConfig.enabled` and `export_endpoint`.
3. Confirm the collector is reachable from the app.

#### Solutions

- Install the SDK and exporter extras (see section 3).
- Set `export_endpoint` and a matching `export_format` (`otlp` / `jaeger` / `zipkin`).
- Increase `sample_rate` temporarily while debugging.

### "Logs are missing recent operations"

**Cause:** Log level too high, or logging not configured before the app starts.

#### Diagnosis

1. Check the effective level: `logging.getLogger("fraiseql").getEffectiveLevel()`.
2. Confirm `logging.basicConfig(...)` runs before requests are served.

#### Solutions

- Lower the level: `logging.getLogger("fraiseql").setLevel(logging.DEBUG)`.
- Add `logging.getLogger("fraiseql.sql").setLevel(logging.DEBUG)` to log generated SQL.
- Stream logs to an external aggregator (Splunk, DataDog, ELK) for retention.

### "Correlation IDs not present in logs"

**Cause:** The client isn't sending a request-ID header, or the `context_getter` doesn't capture it.

#### Diagnosis

1. Check inbound headers for `X-Request-ID` (or your chosen header).
2. Verify the `context_getter` writes `request_id` into `info.context`.

#### Solutions

- Always send a correlation ID from the client: `curl -H "X-Request-ID: abc-123" ...`.
- Generate one in `context_getter` when the header is absent (see section 6).
- Include `request_id` and `trace_id` in your structured log formatter.

### "Audit trail doesn't show who made a change"

**Cause:** User/tenant context not captured or not persisted by the `fn_` function.

#### Diagnosis

1. Confirm the JWT/auth middleware populates `info.context` with `user_id`/`tenant_id`.
2. Confirm your `fn_` function writes those values into your audit table.

#### Solutions

- Extract `user_id`/`tenant_id` in `context_getter` and pass them to `fn_` inputs.
- Persist them inside the mutation's `fn_` function in the same transaction as the write.
- For compliance, store a snapshot of the relevant fields in the audit row.

### "Performance degradation after enabling detailed observability"

**Cause:** High trace sampling or heavy synchronous audit/logging on the hot path.

#### Diagnosis

1. Compare latency with tracing/logging on vs off.
2. Check database CPU via `pg_stat_statements`.
3. Watch disk I/O if audit tables are large.

#### Solutions

- Lower `TracingConfig.sample_rate` (e.g. `0.05`).
- Keep audit writes inside the mutation transaction; avoid extra synchronous I/O per request.
- Archive/partition audit tables (section 12.1).
- Disable `DEBUG`-level logging in production.

### "Tenant data leaked in observability logs"

**Cause:** Sensitive data logged, or observations not scoped by tenant.

#### Diagnosis

- Audit log contents for PII/sensitive fields.
- Confirm every dashboard query filters by `tenant_id`.
- Review who can access the observability backends.

#### Solutions

- Sanitize logs: hash or mask PII before logging.
- Scope all observations by tenant (`WHERE tenant_id = $1`) and rely on Row-Level Security.
- Apply access controls on metrics/trace/log backends.
- Audit log contents regularly for compliance.

---

## See Also

- **[Monitoring & Observability Guide](./monitoring.md)** — Prometheus, OpenTelemetry, health checks setup
- **[Observability Architecture](../architecture/observability/observability-model.md)** — Technical architecture and design
- **[Production Deployment](./production-deployment.md)** — Observability in production environments
