---
title: Observability
description: PostgreSQL-native error tracking, Prometheus metrics and OpenTelemetry tracing for FraiseQL applications
tags:
  - observability
  - production
  - tracing
  - metrics
  - error-tracking
  - PostgreSQL
  - logging
---

# Observability

FraiseQL has three observability pieces. None is on by default; each is set up in
your application code:

| Piece | API | Where the data goes |
|-------|-----|---------------------|
| Error tracking | `fraiseql.monitoring.init_error_tracker` | PostgreSQL tables `tb_error_log`, `tb_error_occurrence` |
| Metrics | `fraiseql.monitoring.setup_metrics` | A Prometheus `/metrics` endpoint |
| Tracing | `fraiseql.tracing.setup_tracing` | An OpenTelemetry exporter (OTLP, Jaeger or Zipkin) |

Errors live in your database, so you can query them with SQL and join them with
your own tables. Metrics and traces go to the tools built for them (Prometheus,
an OpenTelemetry collector).

## Error Tracking

`PostgreSQLErrorTracker` stores exceptions in PostgreSQL, grouped by fingerprint
(like Sentry issues), with every occurrence kept in a partitioned table.

### Schema

The tables, views and functions are in `schema.sql`, in the installed
`fraiseql.monitoring` package. FraiseQL doesn't create them: run the file once per
database, as part of your migrations.

```bash
SCHEMA=$(python -c "import fraiseql.monitoring, pathlib; print(pathlib.Path(fraiseql.monitoring.__file__).parent / 'schema.sql')")
psql "$DATABASE_URL" -f "$SCHEMA"
```

It creates:

| Object | What it holds |
|--------|---------------|
| `tb_error_log` | One row per fingerprint: `error_type`, `error_message`, `stack_trace`, `request_context` / `user_context` / `application_context` (JSONB), `severity`, `tags`, `environment`, `release_version`, `first_seen`, `last_seen`, `occurrence_count`, `status` (`unresolved`, `resolved`, `ignored`, `investigating`), `assigned_to`, `resolved_at`, `resolved_by`, `trace_id`, `span_id` |
| `tb_error_occurrence` | One row per capture (`error_id`, `occurred_at`, contexts, `stack_trace`, `breadcrumbs`, `trace_id`), partitioned by month on `occurred_at` |
| `tb_error_notification_config`, `tb_error_notification_log` | Notification rules and their delivery log (see [Notifications](#notifications)) |
| `v_active_errors`, `v_top_errors`, `v_error_trends` | Unresolved errors; the most frequent ones; errors per hour |
| `get_error_stats(p_hours)`, `resolve_error(p_error_id, p_resolved_by, p_resolution_notes)` | SQL counterparts of the tracker methods |
| `create_error_occurrence_partition(date)`, `ensure_error_occurrence_partitions(months_ahead)`, `drop_old_error_occurrence_partitions(retention_months)`, `get_partition_stats()` | Partition management (see [Retention](#retention-and-partitions)) |
| `otel_traces`, `otel_metrics` | Tables for spans and metrics. Nothing in FraiseQL writes to them: traces and metrics go to the exporters below |

The file creates the `tb_error_occurrence` partitions for the current month and
the next two. A capture fails (and is logged, not raised) when its month has no
partition, so create them ahead of time (see [Retention](#retention-and-partitions)).

### Setup

```python
from psycopg_pool import AsyncConnectionPool

from fraiseql.monitoring import init_error_tracker

pool = AsyncConnectionPool("postgresql://localhost/mydb", open=False)


async def startup() -> None:
    await pool.open()
    init_error_tracker(
        pool,
        environment="production",
        release_version="2.4.1",
        enable_notifications=False,  # see Notifications below
    )
```

`init_error_tracker` sets the process-wide tracker that `get_error_tracker()`
returns, and returns it.

### Capturing Errors

FraiseQL captures nothing on its own: call `capture_exception` where you handle
errors. A resolver's exception becomes a GraphQL error inside the response and
never reaches an HTTP middleware, so capture it in the resolver:

```python
import fraiseql
from fraiseql.monitoring import get_error_tracker


@fraiseql.query
async def invoice(info, id: int) -> Invoice | None:
    try:
        return await info.context["db"].find_one("v_invoice", mandatory_filters={"id": id})
    except Exception as error:
        tracker = get_error_tracker()
        if tracker is not None:
            await tracker.capture_exception(
                error,
                context={
                    "request": {"operation": "invoice", "invoice_id": id},
                    "user": {"user_id": str(info.context.get("user_id"))},
                },
                severity="error",
                tags=["billing"],
            )
        raise
```

`capture_exception(error, context=None, severity="error", tags=None, trace_id=None,
span_id=None)` returns the error's id. The `context` keys it reads are `request`,
`user` and `application` (stored in the matching JSONB columns), `breadcrumbs`
(stored with the occurrence) and `fingerprint` (a string that replaces the default
grouping). `capture_message(message, level="info", context=None, tags=None)` records
a message the same way.

Errors are grouped by a fingerprint of the exception type and the file, line and
function where it was raised (the last frame outside FraiseQL and `site-packages`).
A new occurrence of a known fingerprint increments `occurrence_count`, updates
`last_seen`, and re-opens a resolved error.

### Reading and Resolving Errors

```python
tracker = get_error_tracker()

errors = await tracker.get_unresolved_errors(limit=20, severity="error")
details = await tracker.get_error(errors[0]["error_id"])
stats = await tracker.get_error_stats(hours=24)
# {'total_errors': ..., 'unresolved_errors': ..., 'unique_error_types': ..., 'avg_resolution_time_hours': ...}

await tracker.resolve_error(errors[0]["error_id"], resolved_by="alice", resolution_notes="Fixed in 2.4.2")
```

Or in SQL:

```sql
-- Most frequent unresolved errors
SELECT error_type, error_message, occurrence_count, last_seen
FROM v_top_errors
LIMIT 10;

-- Errors of the last 24 hours, with the users they affected
SELECT
    e.error_type,
    e.error_message,
    COUNT(*) AS occurrences,
    COUNT(DISTINCT o.user_context->>'user_id') AS affected_users,
    MAX(o.occurred_at) AS last_seen
FROM tb_error_occurrence o
JOIN tb_error_log e ON e.error_id = o.error_id
WHERE o.occurred_at > NOW() - INTERVAL '24 hours'
GROUP BY e.error_id, e.error_type, e.error_message
ORDER BY occurrences DESC
LIMIT 20;

-- Occurrences per hour over the last week (filter on occurred_at to prune partitions)
SELECT date_trunc('hour', o.occurred_at) AS hour, e.error_type, COUNT(*) AS count
FROM tb_error_occurrence o
JOIN tb_error_log e ON e.error_id = o.error_id
WHERE o.occurred_at > NOW() - INTERVAL '7 days'
GROUP BY hour, e.error_type
ORDER BY hour DESC, count DESC;

-- Errors by release
SELECT release_version, COUNT(*) AS errors, SUM(occurrence_count) AS occurrences
FROM tb_error_log
GROUP BY release_version
ORDER BY occurrences DESC;
```

Because the errors are rows in your database, you can join them with your own
tables, for example on an id you put in the context:

```sql
SELECT e.error_type, e.error_message, o.occurred_at, i.amount
FROM tb_error_occurrence o
JOIN tb_error_log e ON e.error_id = o.error_id
JOIN tb_invoice i ON i.id = (o.request_context->>'invoice_id')::int
WHERE o.occurred_at > NOW() - INTERVAL '24 hours';
```

### Notifications

The tracker is meant to send a notification when it captures an error
(`enable_notifications=True`, the default): `NotificationManager` reads the enabled
rules of `tb_error_notification_config` that match the error (`error_fingerprint`,
`error_type`, `severity` and `environment` filters, NULL matching everything, and
`min_occurrence_count`), skips a rule that already sent for this error within its
`rate_limit_minutes`, sends through the rule's `channel_type` (`email`, `slack`,
`webhook`, or one added with `register_channel`), and logs the attempt in
`tb_error_notification_log`.

> **Known issue (1.31.0):** no notification is delivered. The manager builds the
> channel with the rule's `channel_config` as keyword arguments
> (`WebhookChannel(url=...)`), which the built-in channels don't accept, so the
> attempt fails with a `TypeError`; and `schema.sql` creates no partition for
> `tb_error_notification_log`, so the failure isn't logged either. Both are logged
> on the `fraiseql.monitoring.notifications` logger. Until this is fixed, pass
> `enable_notifications=False` and alert from your own job, for example on new rows
> of `v_active_errors`.

## Metrics

`setup_metrics(app)` adds a middleware that counts and times every HTTP request, and
a `GET /metrics` endpoint for Prometheus (it needs `prometheus_client`):

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.monitoring import MetricsConfig, setup_metrics

app = create_fraiseql_app(database_url="postgresql://localhost/mydb", types=[User], queries=[users])
metrics = setup_metrics(app, MetricsConfig(namespace="fraiseql"))
```

The metrics recorded on their own are `fraiseql_http_requests_total`,
`fraiseql_http_request_duration_seconds`, `fraiseql_response_time_seconds` and
`fraiseql_errors_total` (exceptions that escape the app). The GraphQL, database
pool and cache metrics only get values your code records (`@with_metrics`,
`metrics.update_db_connections(...)`, ...). The full list, and the queries to use
them, are in the [runbooks' metrics reference](runbooks/README.md#metrics-quick-reference).

## Distributed Tracing

`fraiseql.tracing.setup_tracing(app, TracingConfig(...))` is meant to open an
OpenTelemetry span per HTTP request and export it over OTLP, Jaeger or Zipkin.

> **Known issue (1.31.0):** `fraiseql.tracing` turns itself off unless the Jaeger
> exporter (`opentelemetry.exporter.jaeger.thrift`) imports, even for OTLP. The
> `tracing` extra doesn't install it, and its last release doesn't import with the
> OpenTelemetry SDK versions the extra installs, so `setup_tracing` adds no spans.

Set up OpenTelemetry yourself instead. With the `tracing` extra
(`pip install "fraiseql[tracing]"`), the SDK, the OTLP exporter and the psycopg
instrumentation are installed; this traces every SQL statement FraiseQL runs, and
spans you open in resolvers:

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

import fraiseql

provider = TracerProvider(
    resource=Resource.create({"service.name": "orders-api", "deployment.environment": "production"}),
    sampler=TraceIdRatioBased(0.1),  # keep 10% of traces
)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="http://otel-collector:4317", insecure=True)))
trace.set_tracer_provider(provider)
PsycopgInstrumentor().instrument()  # before the app opens its pool

tracer = trace.get_tracer("orders-api")


@fraiseql.query
async def users(info) -> list[User]:
    with tracer.start_as_current_span("users"):
        return await info.context["db"].find("v_user")
```

For a span per HTTP request, add `opentelemetry-instrumentation-fastapi` and call
`FastAPIInstrumentor.instrument_app(app)`. Pass the current span's ids to
`capture_exception(trace_id=..., span_id=...)` to find an error's trace in your
tracing backend.

## Retention and Partitions

`tb_error_occurrence` is partitioned by month (`tb_error_occurrence_YYYY_MM`), so
old occurrences are dropped a month at a time instead of deleted row by row:

```sql
-- Create the partitions for this month and the next 3 (idempotent)
SELECT * FROM ensure_error_occurrence_partitions(3);

-- Drop the partitions older than 6 months
SELECT * FROM drop_old_error_occurrence_partitions(6);

-- Rows and size per partition
SELECT * FROM get_partition_stats();
```

Run the first two monthly, from cron or pg_cron:

```bash
0 0 1 * * psql -d myapp -c "SELECT ensure_error_occurrence_partitions(3);"
0 0 1 * * psql -d myapp -c "SELECT drop_old_error_occurrence_partitions(6);"
```

`tb_error_log` (one row per fingerprint) isn't partitioned; prune resolved errors
yourself once their occurrences are gone:

```sql
DELETE FROM tb_error_log e
WHERE status = 'resolved'
  AND last_seen < NOW() - INTERVAL '6 months'
  AND NOT EXISTS (SELECT 1 FROM tb_error_occurrence o WHERE o.error_id = e.error_id);
```

Filter `tb_error_occurrence` queries on `occurred_at` so PostgreSQL scans only the
partitions in range.

## Dashboards

FraiseQL ships no Grafana dashboard for these tables. With PostgreSQL as a Grafana
data source, the SQL above makes table and time-series panels; for the Prometheus
metrics, see the runbooks' panels.

## Next Steps

- [Monitoring Guide](monitoring.md) - Detailed monitoring setup
- [Runbooks](runbooks/README.md) - Incident procedures and Prometheus queries
- [Deployment](deployment.md) - Production deployment patterns
- [Health Checks](health-checks.md) - Application health monitoring
