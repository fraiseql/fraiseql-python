# FraiseQL Grafana Dashboards

Grafana dashboards over the data FraiseQL actually records: the error tables of
`src/fraiseql/monitoring/schema.sql`, the HTTP metrics of `setup_metrics`, PostgreSQL's
own statistics views, and the tables of the PostgreSQL APQ backend.

## Overview

| Dashboard | File | Datasource | Reads | Needs |
|-----------|------|------------|-------|-------|
| Error Monitoring | `error_monitoring.json` | PostgreSQL | `tb_error_log`, `tb_error_occurrence`, `tb_error_notification_log` | `schema.sql` loaded, errors captured with `PostgreSQLErrorTracker` |
| Performance Metrics | `performance_metrics.json` | Prometheus | `fraiseql_http_*`, `fraiseql_response_time_seconds`, `fraiseql_errors_total` | `setup_metrics(app)`, Prometheus scraping `GET /metrics` |
| Database Pool | `database_pool.json` | PostgreSQL | `pg_stat_activity`, `pg_stat_database`, `pg_stat_user_tables`, `v_query_stats` | nothing (`v_query_stats` panels: `pg_stat_statements`) |
| APQ Storage | `apq_effectiveness.json` | PostgreSQL | `apq_queries`, `apq_responses` | `apq_storage_backend="postgresql"` |

There is no cache hit rate dashboard: nothing in FraiseQL records cache hits or misses
(`fraiseql_cache_hits_total` / `fraiseql_cache_misses_total` exist, but only your own
calls to `metrics.record_cache_hit()` / `record_cache_miss()` give them values), and the
APQ hit counters (`fraiseql.monitoring.apq_metrics`) live in the process, served as JSON,
not to Prometheus. For the same reason the database dashboard reads connections from
PostgreSQL, not from the `fraiseql_db_connections_*` gauges, which stay at 0 unless your
code calls `metrics.update_db_connections()`.

## Quick Start

### Prerequisites

- Grafana 11+ (the dashboards use the `grafana-postgresql-datasource` plugin id; on an
  older Grafana, set the type of each PostgreSQL dashboard's `datasource` variable to
  `postgres`)
- A PostgreSQL datasource pointing at the application database
- A Prometheus datasource, for the Performance Metrics dashboard
- What each dashboard needs (table above):

```bash
# Error tables (and v_query_stats, if pg_stat_statements is installed first)
psql "$DATABASE_URL" -f src/fraiseql/monitoring/schema.sql
```

```python
from fraiseql.monitoring import setup_metrics
from fraiseql.monitoring.postgres_error_tracker import init_error_tracker

metrics = setup_metrics(app)  # MetricsMiddleware + GET /metrics (needs prometheus_client)
tracker = init_error_tracker(pool, environment="production")
# ... await tracker.capture_exception(exc, context={"user": {"user_id": user_id}})
```

### Automatic Import

```bash
cd grafana/

# Using default Grafana settings (localhost:3000, admin/admin)
./import_dashboards.sh

# Or with custom settings
GRAFANA_URL=https://grafana.mycompany.com \
GRAFANA_USER=admin \
GRAFANA_PASSWORD=secret \
./import_dashboards.sh
```

The script creates a "FraiseQL" folder, checks for the PostgreSQL and Prometheus
datasources (it can create the PostgreSQL one from `POSTGRES_HOST`, `POSTGRES_DB`,
`POSTGRES_USER` and `POSTGRES_PASSWORD`), imports the 4 dashboards and prints their URLs.

### Manual Import

1. Open Grafana, **Dashboards → New → Import**
2. Upload a `.json` file from this directory (the file wraps the dashboard in
   `{"dashboard": ...}`; paste the inner `dashboard` object if the UI refuses it)
3. Pick the datasource in the dashboard's `datasource` variable

Every panel reads the dashboard's `datasource` variable, so a dashboard works with any
datasource of the right type, whatever its name.

## Dashboard Details

Time-range panels use Grafana's macros (`$__timeFilter`, `$__timeGroupAlias`,
`$__rate_interval`, `$__range`), so they follow the time picker.

### 1. Error Monitoring

Errors captured by `PostgreSQLErrorTracker.capture_exception()`: one row per distinct
error (fingerprint) in `tb_error_log`, one row per occurrence in `tb_error_occurrence`.
The `environment` variable filters on `tb_error_log.environment`, the `environment` the
tracker was created with (default `production`).

| Panel | Shows |
|-------|-------|
| Error Rate Over Time | occurrences per interval |
| Error Distribution by Type | occurrences by `error_type` |
| Top 10 Error Fingerprints | open errors (`unresolved`, `investigating`) with the most occurrences in the range, with affected users |
| Error Resolution Status | distinct errors seen in the range, by `status` |
| Errors by Environment | occurrences in every environment |
| Recent Errors (Last Hour) | the last 20 occurrences, with user and trace id |
| Users Affected by Errors | distinct `user_context->>'user_id'` per interval |
| Notification Deliveries | `tb_error_notification_log` by channel and status (`sent`, `failed`) |

"Affected users" counts the `user_id` key of the `user` context you pass to
`capture_exception(exc, context={"user": {"user_id": ...}})`; without it the user panels
are empty.

```sql
-- Error Rate Over Time
SELECT
  $__timeGroupAlias(eo.occurred_at, $__interval),
  COUNT(*) AS errors
FROM tb_error_occurrence eo
JOIN tb_error_log el ON el.error_id = eo.error_id
WHERE $__timeFilter(eo.occurred_at)
  AND el.environment = '$environment'
GROUP BY 1
ORDER BY 1
```

### 2. Performance Metrics (Prometheus)

The HTTP metrics `MetricsMiddleware` records on every request (except `/metrics`,
`/health`, `/ready`, `/startup`). The `job` variable is Prometheus's scrape label.

| Panel | Query |
|-------|-------|
| Request Rate (req/sec) | `sum by (endpoint) (rate(fraiseql_http_requests_total[$__rate_interval]))` |
| Response Time Percentiles | `histogram_quantile(0.95, sum by (le) (rate(fraiseql_http_request_duration_seconds_bucket[$__rate_interval])))` (P50, P95, P99) |
| Slowest Endpoints (P99) | P99 of `fraiseql_http_request_duration_seconds` by `method`, `endpoint` over the range |
| Responses by Status | `sum by (status) (increase(fraiseql_http_requests_total[$__range]))` |
| Requests by Endpoint | top 10 `endpoint` by requests over the range |
| 5xx Rate by Endpoint | share of `status=~"5.."` responses, by endpoint |
| Unhandled Exceptions by Type | `sum by (error_type) (rate(fraiseql_errors_total[$__rate_interval]))` |
| Average Response Time | `fraiseql_response_time_seconds_sum / _count` over the range |

All GraphQL operations go to one endpoint (`/graphql`), and a GraphQL error comes back
with status 200: per-operation numbers need `@with_metrics` on your resolvers
(`fraiseql_graphql_queries_total`, labels `operation_type`, `operation_name`), and errors
in the response body are on the Error Monitoring dashboard. See
`docs/production/runbooks/README.md` (Metrics Quick Reference) for every metric.

### 3. Database Pool

Read from PostgreSQL itself, so it works without any FraiseQL configuration. These are
current values (the connections now, counters since the last statistics reset):
PostgreSQL keeps no history of them, so there are no time series.

| Panel | Reads |
|-------|-------|
| Active / Idle / Idle in Transaction / Total Connections | `pg_stat_activity`, client backends of the current database |
| Connection Utilization | client backends of the server / `max_connections` |
| Connections by Application | `pg_stat_activity` by `application_name`, user, state |
| Longest Running Queries | non-idle backends, oldest `query_start` first |
| Top Queries by Total Time | `v_query_stats` |
| Slowest Queries by Mean Time | `v_query_stats`, statements called 10+ times |
| Buffer Cache Hit Ratio | `pg_stat_database` (`blks_hit / (blks_hit + blks_read)`) |
| Top Tables by Scans | `pg_stat_user_tables` |

Set `application_name` in the app's connection string
(`postgresql://.../db?application_name=myapp`) to tell its pool apart from other clients.

`v_query_stats` is created by `schema.sql` only when `pg_stat_statements` is installed
(`shared_preload_libraries = 'pg_stat_statements'`, then
`CREATE EXTENSION pg_stat_statements`) before the schema is loaded; without it those two
panels report a missing relation.

```sql
-- Idle in Transaction
SELECT COUNT(*) AS idle_in_transaction
FROM pg_stat_activity
WHERE datname = current_database()
  AND backend_type = 'client backend'
  AND state LIKE 'idle in transaction%'
```

### 4. APQ Storage

The persisted queries stored by the PostgreSQL APQ backend
(`apq_storage_backend="postgresql"`), which creates `apq_queries` and `apq_responses` on
first use. With another `table_prefix` in `apq_backend_config`, replace `apq_` in the
queries. The default memory backend stores nothing in PostgreSQL.

| Panel | Reads |
|-------|-------|
| Stored Persisted Queries | `COUNT(*)` of `apq_queries` |
| New Persisted Queries | queries registered in the range (`created_at`) |
| Cached Responses | `COUNT(*)` of `apq_responses` (only with `apq_cache_responses=True`) |
| APQ Storage Size | `pg_total_relation_size` of both tables |
| APQ Storage Growth | queries registered per interval |
| Cached Responses by Tenant | `apq_responses` by `tenant_id` |
| Recently Registered Queries | the last 20 queries registered in the range |
| Largest Persisted Queries | `OCTET_LENGTH(query)`: the bytes a hash-only request saves |

APQ hit and miss counts are not stored: they are in the process
(`fraiseql.monitoring.apq_metrics.get_global_metrics()`), which the router of
`fraiseql.fastapi.apq_metrics_router` serves as JSON under `/admin/apq/` once you mount it.

## Configuration

### Time Ranges and Refresh

| Dashboard | Default range | Refresh |
|-----------|---------------|---------|
| Error Monitoring | last 24 hours | 30s |
| Performance Metrics | last 1 hour | 30s |
| Database Pool | last 1 hour | 30s |
| APQ Storage | last 7 days | 5m |

### PostgreSQL Datasource and Read-Only User

```sql
CREATE USER grafana_readonly WITH PASSWORD 'secure_password';
GRANT CONNECT ON DATABASE your_database TO grafana_readonly;
GRANT USAGE ON SCHEMA public TO grafana_readonly;

-- Error Monitoring
GRANT SELECT ON tb_error_log, tb_error_occurrence, tb_error_notification_log TO grafana_readonly;

-- APQ Storage
GRANT SELECT ON apq_queries, apq_responses TO grafana_readonly;

-- Database Pool: other sessions' state and query text, and v_query_stats
GRANT pg_read_all_stats TO grafana_readonly;
GRANT SELECT ON v_query_stats TO grafana_readonly;
```

Without `pg_read_all_stats` the user sees only its own sessions in `pg_stat_activity`
and `<insufficient privilege>` instead of other users' query text.

Use the schema the tables were created in instead of `public` if `schema.sql` was loaded
with another `search_path`, and add it to the datasource user's `search_path`.

## Troubleshooting

### Dashboards Show "No Data"

1. **Error Monitoring**: check that errors are being captured, in the selected environment:

   ```sql
   SELECT environment, COUNT(*) AS errors, MAX(last_seen) AS latest
   FROM tb_error_log
   GROUP BY environment;
   ```

2. **Performance Metrics**: check that `GET /metrics` on the app returns
   `fraiseql_http_requests_total`, and that the Prometheus target is up.
3. **APQ Storage**: `relation "apq_queries" does not exist` means the app uses the memory
   APQ backend, or has not stored a query yet.
4. **Database Pool**, `relation "v_query_stats" does not exist`: install
   `pg_stat_statements`, then load `schema.sql` again (it is idempotent).

### Import Script Fails

```bash
# Check Grafana is running
curl http://localhost:3000/api/health

# Verify credentials
GRAFANA_USER=admin GRAFANA_PASSWORD=your_password ./import_dashboards.sh

# Create the PostgreSQL datasource from the script
POSTGRES_HOST=localhost:5432 \
POSTGRES_DB=myapp \
POSTGRES_USER=grafana_readonly \
POSTGRES_PASSWORD=password \
./import_dashboards.sh
```

### Query Performance

The error queries filter on `occurred_at` and `last_seen`, and join on `error_id`, all
indexed by `schema.sql`; `tb_error_occurrence` is partitioned by month, so a time filter
reads only the partitions in range. Keep partitions ahead with
`SELECT ensure_error_occurrence_partitions(2)` (from cron or pg_cron), and drop old ones
with `drop_old_error_occurrence_partitions(6)`.

## Customization

### Adding Panels

```sql
-- Errors by release
SELECT
  release_version,
  SUM(occurrence_count) AS occurrences
FROM tb_error_log
WHERE $__timeFilter(last_seen)
  AND environment = '$environment'
GROUP BY release_version
ORDER BY occurrences DESC
```

### Alerting

1. **Error spike** (PostgreSQL):

   ```sql
   SELECT COUNT(*) AS errors
   FROM tb_error_occurrence eo
   JOIN tb_error_log el ON el.error_id = eo.error_id
   WHERE eo.occurred_at > NOW() - INTERVAL '5 minutes'
     AND el.environment = 'production'
   ```

   Alert if `errors > 100`.

2. **5xx rate** (Prometheus):

   ```promql
   100 * sum(rate(fraiseql_http_requests_total{status=~"5.."}[5m]))
     / sum(rate(fraiseql_http_requests_total[5m]))
   ```

   Alert if above 1.

3. **Connection exhaustion** (PostgreSQL):

   ```sql
   WITH conns AS (
     SELECT COUNT(*) AS used FROM pg_stat_activity WHERE backend_type = 'client backend'
   )
   SELECT ROUND(100.0 * used / current_setting('max_connections')::int, 1) AS utilization
   FROM conns
   ```

   Alert if `utilization > 90`.

## Testing

```bash
uv run pytest tests/grafana/ -v
```

- `test_dashboard_structure.py`, `test_sql_queries.py`, `test_import_script.py`: JSON
  structure, datasources, variables, SQL conventions, import script
- `test_prometheus_queries.py`: every metric and label in the PromQL is one FraiseQL exports
- `test_queries_run_in_postgres.py`: every SQL query runs against `schema.sql` and the APQ
  tables in PostgreSQL (integration; needs Docker or `TEST_DATABASE_URL`)

See `tests/grafana/README.md` for details.
