---
title: Production Monitoring
description: Managing tracked errors and their notifications, metrics of your own, logging, query performance, database pool and alerting for FraiseQL applications
tags:
  - monitoring
  - production
  - observability
  - error-tracking
  - PostgreSQL
  - metrics
---

# Production Monitoring

[Observability](observability.md) introduces FraiseQL's three monitoring pieces:
error tracking in PostgreSQL, Prometheus metrics and OpenTelemetry tracing, and how
to set each one up. This page covers running them in production: managing the
errors you track and their notifications, the metrics FraiseQL doesn't record for
you, logging, query performance, the database pool, alerts and dashboards.

| Need | What FraiseQL provides | What you add |
|------|------------------------|--------------|
| Error tracking | `PostgreSQLErrorTracker`, the tables of `schema.sql`, email / Slack / webhook notifications | The `capture_exception` calls, notification rules |
| Metrics | `setup_metrics`: HTTP metrics and a `GET /metrics` endpoint | Per-operation, pool and cache metrics, and metrics of your own |
| Tracing | `setup_tracing`: a span per HTTP request, psycopg spans | Spans in your resolvers |
| Logging | Standard `logging` loggers under `fraiseql.*` | Formatter, handlers, request logging |
| Query performance | Query depth / complexity limits, `v_query_stats` and `QueryStatsCollector` over `pg_stat_statements` | PostgreSQL's slow-statement log |
| Health | `HealthCheck`, `check_database`, `check_pool_stats` (see [Health Checks](health-checks.md)) | |
| Alerting | Error notifications | Prometheus alert rules and Alertmanager |
| Dashboards | Grafana dashboards in `grafana/` | |

## Error Tracking

Setting up the tracker, capturing errors and reading them back are in
[Observability](observability.md#error-tracking). In short, start the tracker on the
app's pool in a `lifespan` passed to `create_fraiseql_app`:

```python
from contextlib import asynccontextmanager

from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.dependencies import get_db_pool
from fraiseql.monitoring import init_error_tracker


@asynccontextmanager
async def lifespan(app):
    init_error_tracker(get_db_pool(), environment="production", release_version="2.4.1")
    yield


app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb", types=[User], queries=[users], lifespan=lifespan
)
```

FraiseQL captures nothing on its own: call
`await get_error_tracker().capture_exception(error, context=...)` where you handle
errors. A capture that fails (no `schema.sql`, no partition for the month) is logged
and returns `""`; it never raises.

### Managing Errors

`resolve_error` marks an error resolved. A new occurrence of a resolved error sets it
back to `unresolved`:

```python
from fraiseql.monitoring import get_error_tracker

tracker = get_error_tracker()
for error in await tracker.get_unresolved_errors(limit=50):
    if error["error_type"] == "PaymentTimeout":
        await tracker.resolve_error(error["error_id"], resolved_by="alice", resolution_notes="Gateway fixed")
```

The tracker has no methods for the other statuses (`ignored`, `investigating`) or for
assigning an error: update `tb_error_log` directly.

```sql
-- Assign an error and mark it as being investigated
UPDATE tb_error_log
SET status = 'investigating', assigned_to = 'dev@example.com'
WHERE error_id = '...';

-- Ignore a known error
UPDATE tb_error_log
SET status = 'ignored'
WHERE error_type = 'ExternalApiTimeout';
```

`ignored` is a label: an ignored error is still captured, counted, and notified by
the rules that match it. To stop its notifications, narrow or disable those rules
(see [Notifications](#notifications)).

### Querying Errors

Errors are rows in `tb_error_log` (one per fingerprint) and `tb_error_occurrence`
(one per capture, partitioned by month on `occurred_at`). More queries are in
[Observability](observability.md#reading-and-resolving-errors).

```sql
-- One error, with its last 10 occurrences
SELECT e.error_type, e.error_message, e.status, e.occurrence_count,
       o.occurred_at, o.request_context, o.user_context, o.stack_trace
FROM tb_error_log e
JOIN tb_error_occurrence o ON o.error_id = e.error_id
WHERE e.error_fingerprint = '...'
  AND o.occurred_at > NOW() - INTERVAL '30 days'
ORDER BY o.occurred_at DESC
LIMIT 10;

-- Users with the most errors this week (from context={"user": {"user_id": ...}})
SELECT o.user_context->>'user_id' AS user_id,
       COUNT(*) AS occurrences,
       array_agg(DISTINCT e.error_type) AS error_types
FROM tb_error_occurrence o
JOIN tb_error_log e ON e.error_id = o.error_id
WHERE o.occurred_at > NOW() - INTERVAL '7 days'
  AND o.user_context ? 'user_id'
GROUP BY 1
ORDER BY occurrences DESC
LIMIT 20;

-- Occurrences per hour, last 24 hours
SELECT date_trunc('hour', occurred_at) AS hour, COUNT(*) AS occurrences
FROM tb_error_occurrence
WHERE occurred_at > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour;

-- Totals, unresolved errors, distinct types, mean time to resolve (hours)
SELECT * FROM get_error_stats(24);
```

### Notifications

When the tracker captures an error (`enable_notifications=True`, the default), it
sends a notification for each enabled rule of `tb_error_notification_config` that
matches the error, in a background task. The full description, and a custom channel
example, are in [Observability](observability.md#notifications). The columns of a
rule:

| Column | Meaning |
|--------|---------|
| `error_fingerprint`, `error_type` | Match this fingerprint / exception class name; NULL matches every error |
| `severity`, `environment` | Arrays; the error's severity / environment must be in them; NULL matches every error |
| `min_occurrence_count` | Send only once the error has occurred this many times (default 1) |
| `rate_limit_minutes` | At most one notification per error and rule in this window (default 60; 0 for no limit) |
| `channel_type` | `email`, `slack`, `webhook`, or a channel registered with `NotificationManager.register_channel` |
| `channel_config` | JSONB passed to the channel (below) |
| `enabled` | Rules with `false` are skipped |

The `channel_config` keys of the built-in channels:

| `channel_type` | Keys |
|----------------|------|
| `email` | `to` (list, required), `subject` (default `"Error Alert: {error_type}"`), `template`, and the SMTP settings `smtp_host` (required), `smtp_port` (587), `smtp_user`, `smtp_password`, `use_tls` (true), `from_address` |
| `slack` | `webhook_url` (required), `channel`, `username` |
| `webhook` | `url` (required), `method` (default `POST`), `headers` |

```sql
-- Errors of the payment code: once they have occurred 10 times, then at most once an hour
INSERT INTO tb_error_notification_config
    (error_type, environment, min_occurrence_count, rate_limit_minutes, channel_type, channel_config)
VALUES
    ('PaymentError', ARRAY['production'], 10, 60, 'webhook',
     '{"url": "https://hooks.example.com/errors", "headers": {"Authorization": "Bearer ..."}}');

-- Stop a rule
UPDATE tb_error_notification_config SET enabled = false WHERE config_id = '...';
```

There is no rule for "every Nth occurrence": `min_occurrence_count` sets when the
first notification is sent and `rate_limit_minutes` how often the next ones are.

The webhook channel sends the error as JSON: `error_id`, `error_fingerprint`,
`error_type`, `error_message`, `severity`, `occurrence_count`, `first_seen`,
`last_seen` (ISO 8601), `environment`, `release_version` and `stack_trace`. A 2xx
response counts as sent.

Every attempt is logged in `tb_error_notification_log`, with the reason of a failure:

```sql
SELECT n.sent_at, n.channel_type, n.recipient, n.status, n.error_message, e.error_type
FROM tb_error_notification_log n
JOIN tb_error_log e ON e.error_id = n.error_id
WHERE n.sent_at > NOW() - INTERVAL '24 hours'
ORDER BY n.sent_at DESC;
```

`tb_error_notification_log` is partitioned by month, like `tb_error_occurrence`: run
`SELECT ensure_monitoring_partitions(2);` every month (see
[Retention and Partitions](observability.md#retention-and-partitions)).

### Errors and Traces

With [tracing](observability.md#distributed-tracing) on, pass the current span's ids
to `capture_exception`; the error's `trace_id` then finds the request in your tracing
backend (Jaeger, Tempo, ...):

```python
from opentelemetry import trace

import fraiseql
from fraiseql.monitoring import get_error_tracker


@fraiseql.query
async def invoice(info, id: int) -> Invoice | None:
    try:
        return await info.context["db"].find_one("v_invoice", mandatory_filters={"id": id})
    except Exception as error:
        span = trace.get_current_span().get_span_context()
        await get_error_tracker().capture_exception(
            error,
            context={"request": {"operation": "invoice", "invoice_id": id}},
            trace_id=format(span.trace_id, "032x"),
            span_id=format(span.span_id, "016x"),
        )
        raise
```

```sql
SELECT error_type, error_message, last_seen, trace_id
FROM tb_error_log
WHERE trace_id IS NOT NULL
ORDER BY last_seen DESC
LIMIT 20;
```

`schema.sql` also creates `otel_traces` and `otel_metrics`, but nothing in FraiseQL
writes to them: spans go to the exporter of `setup_tracing`.

### Coming from Sentry

| Sentry | FraiseQL |
|--------|----------|
| `sentry_sdk.init(dsn=..., environment=..., release=...)` | `init_error_tracker(pool, environment=..., release_version=...)`, after loading `schema.sql` |
| `sentry_sdk.capture_exception(error)` | `await get_error_tracker().capture_exception(error)` |
| `sentry_sdk.capture_message(text)` | `await get_error_tracker().capture_message(text, level="warning")` |
| `set_user`, `set_context`, `set_tag` | `capture_exception(error, context={"user": {...}, "request": {...}, "application": {...}}, tags=[...])` |
| Issue grouping | Fingerprint of the exception type and the frame where it was raised, or `context={"fingerprint": "..."}` |
| Alert rules | Rows of `tb_error_notification_config` |
| `traces_sample_rate` | `TracingConfig(sample_rate=...)` with `setup_tracing` |

What isn't provided: automatic capture of every unhandled exception, a web UI (use
SQL or the `error_monitoring.json` Grafana dashboard), release health, and front-end
error tracking.

## Caching

`PostgresCache` (`fraiseql.caching`) is a key-value cache in an UNLOGGED table
(`fraiseql_cache` by default, created on first use). UNLOGGED tables skip the
write-ahead log, so writes are cheaper than in a regular table, but PostgreSQL empties
them after a crash and doesn't replicate them: treat the content as disposable. All
app instances on the same database share it. The full guide, including
`CachedRepository`, is [Caching](../performance/caching.md).

```python
from fraiseql.caching import PostgresCache

cache = PostgresCache(pool)

await cache.set("user:123", {"name": "Alice"}, ttl=3600)  # ttl in seconds, required
value = await cache.get("user:123")                       # None when missing or expired
await cache.delete("user:123")
await cache.delete_pattern("user:*")                      # * (or %) is a wildcard

removed = await cache.cleanup_expired()  # expired rows stay until you call this
stats = await cache.get_stats()
# {'total_entries': ..., 'expired_entries': ..., 'active_entries': ..., 'table_size_bytes': ...}
```

Expired entries are never returned, but they stay in the table until
`cleanup_expired()` runs: call it periodically, from a background task or a
scheduler. There is no batch `get_many` / `set_many`.

Coming from Redis: `redis.set(key, value, ex=ttl)` is `cache.set(key, value, ttl=ttl)`,
`get` and `delete` are the same, and deleting the keys of `redis.keys(pattern)` is
`cache.delete_pattern(pattern)`. Values must be JSON-serializable.

## Metrics

`setup_metrics(app)` records the HTTP metrics of every request and serves
`GET /metrics` (see [Observability](observability.md#metrics)). The metrics FraiseQL
exports, and which of them it records itself, are listed in the
[runbooks' metrics reference](runbooks/README.md#metrics-quick-reference). The others
get values only from your code, as below.

### Per-Operation Metrics

All GraphQL operations share the `/graphql` endpoint. For one series per resolver,
decorate it with `@with_metrics("query")` under the FraiseQL decorator:

```python
import fraiseql
from fraiseql.monitoring import with_metrics


@fraiseql.query
@with_metrics("query")
async def users(info) -> list[User]:
    return await info.context["db"].find("v_user")
```

Each call increments `fraiseql_graphql_queries_total{operation_type="query",
operation_name="users"}`, observes `fraiseql_graphql_query_duration_seconds` with the
same labels, and increments `fraiseql_graphql_queries_success_total` or
`fraiseql_graphql_queries_errors_total` (label `operation_type` only). An exception
raised by the resolver is also counted in `fraiseql_errors_total`, with
`operation` set to the function name. `@with_metrics("mutation")` on a function
mutation records the same metrics with `operation_type="mutation"`.

```promql
# Calls per second, by resolver
sum by (operation_name) (rate(fraiseql_graphql_queries_total[5m]))

# p95 duration, by resolver
histogram_quantile(0.95, sum by (le, operation_name) (rate(fraiseql_graphql_query_duration_seconds_bucket[5m])))
```

### Database Pool Metrics

The `fraiseql_db_connections_active`, `_idle` and `_total` gauges read 0 until your
code sets them. Sample the app's pool from a task started in the app's lifespan:

```python
import asyncio
from contextlib import asynccontextmanager

from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.dependencies import get_db_pool
from fraiseql.monitoring import setup_metrics


async def report_pool(pool, metrics, interval: float = 15) -> None:
    while True:
        stats = pool.get_stats()
        size, idle = stats.get("pool_size", 0), stats.get("pool_available", 0)
        metrics.update_db_connections(active=size - idle, idle=idle, total=size)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(report_pool(get_db_pool(), metrics))
    yield
    task.cancel()


app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb", types=[User], queries=[users], lifespan=lifespan
)
metrics = setup_metrics(app)
```

`pool_size` is the number of connections the pool holds, `pool_available` the idle
ones; the pool's limit is `pool.max_size`.

### Metrics of Your Own

`/metrics` serves the registry of the `FraiseQLMetrics` instance that `setup_metrics`
returns (`metrics.registry`), not `prometheus_client`'s default one. Register your
own metrics on it to have them served:

```python
from prometheus_client import Counter, ProcessCollector

metrics = setup_metrics(app)

orders_created = Counter(
    "myapp_orders_created_total", "Orders created", ["channel"], registry=metrics.registry
)
ProcessCollector(registry=metrics.registry)  # process_cpu_seconds_total, process_resident_memory_bytes, ...

orders_created.labels(channel="web").inc()
```

`FraiseQLMetrics` also has `record_mutation(mutation_name, duration_ms, success,
result_type=None, error_type=None)`, `record_db_query(query_type, table_name,
duration_ms)` and `record_cache_hit(cache_type)` / `record_cache_miss(cache_type)` for
the mutation, database and cache metrics.

## Logging

FraiseQL logs with the standard `logging` module, on loggers named after its modules
(`fraiseql.fastapi.routers`, `fraiseql.monitoring.notifications`, ...), and adds no
handler to them: your application's logging configuration decides the format and the
destination. To set FraiseQL's level apart from your own:

```python
import logging

logging.getLogger("fraiseql").setLevel(logging.WARNING)
```

The exception is the security log (`fraiseql.security`: authentication, rate limiting,
rejected queries). The first security event sets that logger to `INFO` and gives it
two handlers of its own, stderr and the file `security_events.log` in the working
directory (`FRAISEQL_SECURITY_LOG_PATH` to change it); its records also propagate to
your handlers. Each record's message is the event as JSON. To send security events
only through your own handlers, set the security logger yourself before the first
event:

```python
from fraiseql.audit import SecurityLogger, set_security_logger

set_security_logger(SecurityLogger(log_to_file=False, log_to_stdout=False))
```

### Structured Logging

A formatter that writes one JSON object per line, with the `extra` fields you pass:

```python
import json
import logging
from datetime import UTC, datetime

STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Fields passed with logger.info(..., extra={...})
        entry.update({k: v for k, v in vars(record).items() if k not in STANDARD_ATTRS})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])

logger = logging.getLogger("myapp")
logger.info("Order created", extra={"order_id": "order-456", "duration_ms": 125.5})
# {"timestamp": "...", "level": "INFO", "logger": "myapp", "message": "Order created", "order_id": "order-456", "duration_ms": 125.5}
```

### Request Logging

FraiseQL doesn't log requests or assign request ids. A middleware on the app does
both:

```python
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("myapp.requests")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Request failed", extra={"request_id": request_id, "path": request.url.path})
            raise
        logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestLoggingMiddleware)
```

A GraphQL error comes back with status 200, so this logs it as a success; errors
inside the response are for the error tracker. For log aggregation, see
[Loki Integration](loki-integration.md).

## Query Performance

### Request Latency

`fraiseql_http_request_duration_seconds` times every request, by `method` and
`endpoint`:

```promql
# p95 latency of /graphql
histogram_quantile(0.95, sum by (le) (rate(fraiseql_http_request_duration_seconds_bucket{endpoint="/graphql"}[5m])))
```

For latency by operation, use `@with_metrics` (see
[Per-Operation Metrics](#per-operation-metrics)) or tracing.

### Query Depth and Complexity

FraiseQL can reject a query that is too deep or too expensive before running it.
The limits are off by default; set them on `FraiseQLConfig`:

```python
from fraiseql.fastapi import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    complexity_enabled=True,
    complexity_max_score=1000,
    complexity_max_depth=10,
)
```

A rejected query gets a GraphQL error with code `QUERY_TOO_COMPLEX` or
`QUERY_TOO_DEEP`, and a `query.complexity_exceeded` / `query.depth_exceeded` entry in
the security log. There is no metric for them. To see the score of a query before you
choose a limit, measure it with the same code:

```python
from fraiseql import build_fraiseql_schema
from fraiseql.gql.query_limits import QueryLimits

schema = build_fraiseql_schema(query_types=[users])
cost = QueryLimits().measure(schema, "{ users(limit: 50) { id name } }")
print(cost.depth, cost.complexity)
```

A scalar field costs 1, an object field 1 plus its selections, and a list field 1
plus its selections times the list size (its `limit` or `first` argument, else
`complexity_default_list_size`, 10).

### Slow SQL

FraiseQL has no SQL echo setting (`database_echo` has no effect). Log statements in
PostgreSQL:

```sql
-- Development: log every statement
ALTER DATABASE myapp SET log_statement = 'all';

-- Production: log slow statements only (> 1s)
ALTER DATABASE myapp SET log_min_duration_statement = 1000;
```

With `pg_stat_statements` installed (`shared_preload_libraries = 'pg_stat_statements'`,
then `CREATE EXTENSION pg_stat_statements`) before `schema.sql` is loaded, the schema
also creates the view `v_query_stats`, and `QueryStatsCollector` reads it:

```python
from fraiseql.monitoring import init_query_stats

collector = init_query_stats(pool)
if await collector.is_available():
    for s in await collector.get_stats(top_n=10, order_by="mean_exec_time"):
        print(f"{s.mean_exec_time_ms:8.1f} ms  {s.calls:6} calls  {s.query_preview[:80]}")
```

`order_by` is one of `total_exec_time`, `mean_exec_time`, `calls` and
`cache_hit_ratio`. Without the extension, `get_stats` returns an empty list.

## Database Monitoring

The app's pool is a psycopg `AsyncConnectionPool`, returned by
`fraiseql.fastapi.dependencies.get_db_pool()` once the app has started.
`pool.get_stats()` reports its counters (`pool_size`, `pool_available`,
`requests_waiting`, `requests_num`, ...); feed them to Prometheus as in
[Database Pool Metrics](#database-pool-metrics), or expose them on a health endpoint
with `check_pool_stats` (see [Health Checks](health-checks.md)).

PostgreSQL's own view of the connections, whatever the app reports:

```sql
SELECT state, COUNT(*) AS connections, MAX(NOW() - state_change) AS longest_in_state
FROM pg_stat_activity
WHERE datname = current_database()
  AND backend_type = 'client backend'
GROUP BY state;
```

Set `application_name` in the connection string
(`postgresql://.../mydb?application_name=orders-api`) to tell the app's connections
apart. The `database_pool.json` Grafana dashboard shows these views.

## Alerting

FraiseQL has no alerting of its own besides error notifications. Alert on the metrics
with Prometheus rules, and route them (Slack, email, PagerDuty, ...) with
Alertmanager. These rules use only metrics `setup_metrics` records:

```yaml
# prometheus-alerts.yml
groups:
  - name: fraiseql
    rules:
      - alert: FraiseQLHigh5xxRate
        expr: |
          sum(rate(fraiseql_http_requests_total{status=~"5.."}[5m]))
            / sum(rate(fraiseql_http_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "More than 5% of requests fail with a 5xx status"
          description: "5xx ratio is {{ $value | humanizePercentage }}"

      - alert: FraiseQLHighLatency
        expr: |
          histogram_quantile(0.99,
            sum by (le) (rate(fraiseql_http_request_duration_seconds_bucket{endpoint="/graphql"}[5m]))
          ) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "p99 latency of /graphql above 1s"
          description: "p99 latency is {{ $value | humanizeDuration }}"

      - alert: FraiseQLUnhandledExceptions
        expr: sum by (error_type) (increase(fraiseql_errors_total[10m])) > 0
        labels:
          severity: warning
        annotations:
          summary: "Unhandled {{ $labels.error_type }} exceptions"
```

With the pool gauges fed (see [Database Pool Metrics](#database-pool-metrics)), add
a rule on them; the limit isn't exported, so write it in the rule:

```yaml
      - alert: FraiseQLPoolSaturated
        expr: fraiseql_db_connections_active / 20 > 0.9  # 20 = the pool's max_size
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Database pool more than 90% used"
```

A GraphQL error (a failed resolver, a rejected query) comes back with status 200 and
counts in none of these metrics. Alert on those with error notifications, or with
`@with_metrics` and `fraiseql_graphql_queries_errors_total`.

## Dashboards

The `grafana/` directory of the repository has four dashboards, and a script to import
them (see `grafana/README.md`):

| Dashboard | Datasource | Shows |
|-----------|------------|-------|
| `error_monitoring.json` | PostgreSQL | `tb_error_log`, `tb_error_occurrence`, `tb_error_notification_log` |
| `performance_metrics.json` | Prometheus | The HTTP metrics of `setup_metrics` |
| `database_pool.json` | PostgreSQL | `pg_stat_activity`, `pg_stat_database`, `pg_stat_user_tables`, `v_query_stats` |
| `apq_effectiveness.json` | PostgreSQL | The tables of the PostgreSQL APQ backend |

## Next Steps

- [Observability](observability.md) - Error tracking, metrics and tracing setup
- [Runbooks](runbooks/README.md) - Incident procedures and Prometheus queries
- [Health Checks](health-checks.md) - Application health monitoring
- [Deployment](deployment.md) - Production deployment patterns
- [Performance](../performance/index.md) - Performance optimization
