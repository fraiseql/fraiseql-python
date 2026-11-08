# Grafana Dashboard Tests

Tests for the dashboards in `grafana/` (error_monitoring, performance_metrics,
database_pool, apq_effectiveness) and their import script.

## Test Files

### `test_dashboard_structure.py`

- Every dashboard file exists and is valid JSON, with the Grafana fields (title, tags,
  panels, time, refresh, templating)
- Panels have an id, title, type, grid position and targets; a PostgreSQL panel's
  targets have `rawSql`, a Prometheus panel's targets have `expr`
- Every panel reads the dashboard's `datasource` variable
- Every `$variable` a query uses is defined by the dashboard (`$__*` are Grafana's)
- Each dashboard has its expected panels and tags

### `test_sql_queries.py`

Static checks of the `rawSql` queries:

- SELECT and FROM present, semicolons only at the end
- Tables are the real ones: `tb_error_log`, `tb_error_occurrence`,
  `tb_error_notification_log`, `v_query_stats` (`src/fraiseql/monitoring/schema.sql`),
  `apq_queries`, `apq_responses` (PostgreSQL APQ backend), PostgreSQL statistics views;
  no `monitoring.` schema
- Time-column queries use `$__timeFilter(...)`, `$__timeFrom()`/`$__timeTo()` or `NOW()`
- Queries on the error tables filter on `'$environment'`
- Queries on FraiseQL tables filter on indexed columns; LIMIT at most 1000
- Variables quoted, no dynamic SQL, GROUP BY with non-aggregate columns, quoted JSONB keys

### `test_prometheus_queries.py`

Every `fraiseql_*` metric in a PromQL expression is exported by `FraiseQLMetrics`
(after `MetricsMiddleware` records a request), with every label the expression selects
or groups by; `job` and `instance` come from the Prometheus scrape.

### `test_queries_run_in_postgres.py` (integration)

Loads `schema.sql` and the APQ backend's tables into a test schema, inserts a few rows,
replaces Grafana's macros (`$__timeFilter`, `$__timeGroupAlias`, `$environment`, ...)
with concrete values, and runs every `rawSql`. The `v_query_stats` queries are skipped
when PostgreSQL has no `pg_stat_statements` in `shared_preload_libraries` (the test
container has it). Uses the `class_db_pool` and `test_schema` fixtures: Docker, or
`TEST_DATABASE_URL`.

### `test_import_script.py`

`import_dashboards.sh`: shebang, `set -e`, configuration variables, connectivity check,
import function, the dashboard file list, messages, exit codes, file checks, and
shellcheck when installed.

## Running Tests

```bash
uv run pytest tests/grafana/ -v

# Without a database
uv run pytest tests/grafana/ -v --ignore=tests/grafana/test_queries_run_in_postgres.py
```

## Known Exceptions

Documented in `conftest.py`:

- **No environment filter**: `error_monitoring / Errors by Environment` compares every
  environment.
- **No time filter**: `apq_effectiveness / Largest Persisted Queries` lists the largest
  queries whatever their age.
- **No GROUP BY**: `error_monitoring / Error Resolution Status` is a single row of
  `COUNT(*) FILTER (...)`.

## Adding or Removing a Dashboard

1. Update `DASHBOARD_FILES` in `test_dashboard_structure.py` and `test_sql_queries.py`,
   the list in `test_import_script.py`, and `DASHBOARD_FILES` in
   `grafana/import_dashboards.sh`
2. Add its expected panels and tags to `test_dashboard_structure.py`
3. Query only tables FraiseQL creates and metrics it exports: the query-run and
   PromQL tests fail otherwise
4. Add a documented exception to `conftest.py` if a static rule doesn't fit

## Troubleshooting

- **"Unknown table"**: the query reads a table FraiseQL doesn't create; if it does,
  add it to `EXPECTED_TABLES` in `test_sql_queries.py`.
- **"is not exported" / "has no label"**: the metric or label isn't in
  `src/fraiseql/monitoring/metrics/collectors.py`.
- **A `test_query_runs` case fails**: run the query (with the macros replaced) in psql
  against a database loaded with `schema.sql`.
- **Shellcheck test skipped**: install shellcheck (`apt-get install shellcheck`).
