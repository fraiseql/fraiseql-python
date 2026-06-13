# Query Performance Statistics (pg_stat_statements)

FraiseQL integrates with PostgreSQL's `pg_stat_statements` extension to surface
database-side query performance data. This gives you visibility into actual
execution times, buffer cache utilization, and call frequencies — information
that application-level timing alone cannot provide.

## Prerequisites

1. **Add to `shared_preload_libraries`** (requires server restart):

   ```ini
   # postgresql.conf
   shared_preload_libraries = 'pg_stat_statements'
   ```

2. **Create the extension** (per database):

   ```sql
   CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
   ```

3. **Apply the monitoring schema** (`schema.sql`), which creates:
   - `v_query_stats` view with computed cache hit ratios
   - `get_query_stats()` parameterized function
   - `pg_stat_statements_available()` helper for graceful degradation

> **Migration ordering**: `pg_stat_statements` must be in
> `shared_preload_libraries` before applying `schema.sql`. The schema creation
> succeeds either way (it skips view creation if the extension is missing), but
> queries will return empty until the extension is loaded and a restart is done.

## Python API

```python
from fraiseql.monitoring import init_query_stats, get_query_stats_collector

# Initialize with your database pool (typically at app startup)
collector = init_query_stats(db_pool)

# Fetch top 20 queries by total execution time
stats = await collector.get_stats(top_n=20, order_by="total_exec_time")
for s in stats:
    print(
        f"{s.query_preview[:60]}  calls={s.calls}  "
        f"mean={s.mean_exec_time_ms:.1f}ms  cache_hit={s.cache_hit_ratio:.1f}%"
    )

# Check if the extension is available
if await collector.is_available():
    print("pg_stat_statements is active")

# Reset counters (e.g., after a deployment)
await collector.reset_stats()
```

### `get_stats()` parameters

| Parameter  | Default             | Description                                  |
|-----------|---------------------|----------------------------------------------|
| `top_n`   | `20`                | Maximum number of queries to return          |
| `order_by`| `"total_exec_time"` | Sort metric: `total_exec_time`, `mean_exec_time`, `calls`, `cache_hit_ratio` |

### Graceful degradation

If `pg_stat_statements` is not installed or not in `shared_preload_libraries`:

- `get_stats()` returns an empty list and logs a warning (once)
- `is_available()` returns `False`
- No exceptions are raised

### `reset_stats()` permissions

`pg_stat_statements_reset()` requires the `pg_read_all_stats` role or superuser
on PostgreSQL 14+. If the application role lacks this permission:

```python
from fraiseql.core.exceptions import FraiseQLError

try:
    await collector.reset_stats()
except FraiseQLError as e:
    # "Cannot reset pg_stat_statements: insufficient privileges."
    print(e)
```

To grant the required permission:

```sql
GRANT pg_read_all_stats TO fraiseql_app;
```

## CLI

```bash
# Display top 20 queries by total execution time
fraiseql query-stats --database-url postgresql://localhost/mydb

# Top 10 by mean execution time
fraiseql query-stats --top-n 10 --order-by mean_exec_time

# Sort by cache hit ratio (find poorly-cached queries)
fraiseql query-stats --order-by cache_hit_ratio

# Reset all query statistics (with confirmation prompt)
fraiseql query-stats --reset
```

The CLI uses the `DATABASE_URL` environment variable if `--database-url` is not
provided.

## Prometheus integration

FraiseQL ships a custom queries YAML for
[postgres_exporter](https://github.com/prometheus-community/postgres_exporter),
located at `deploy/docker/postgres_exporter_queries.yml`.

### Setup

```yaml
# docker-compose.yml
services:
  postgres-exporter:
    image: prometheuscommunity/postgres-exporter:latest
    environment:
      DATA_SOURCE_NAME: "postgresql://prometheus:prometheus_password@db:5432/fraiseql_prod?sslmode=disable"
    volumes:
      - ./postgres_exporter_queries.yml:/etc/postgres_exporter/queries.yml:ro
    command:
      - "--extend.query-path=/etc/postgres_exporter/queries.yml"
    ports:
      - "9187:9187"
```

The `prometheus` role (created by `init.sql`) has `pg_monitor` which grants
read access to `pg_stat_statements`.

### Exposed metrics

| Metric                                    | Type    | Description                          |
|------------------------------------------|---------|--------------------------------------|
| `fraiseql_pg_query_stats_calls`          | counter | Total calls per query (top 50)       |
| `fraiseql_pg_query_stats_total_exec_time_seconds` | gauge | Total exec time per query   |
| `fraiseql_pg_query_stats_mean_exec_time_seconds`  | gauge | Mean exec time per query    |
| `fraiseql_pg_query_stats_rows_returned`  | counter | Total rows returned per query        |
| `fraiseql_pg_query_stats_cache_hit_ratio`| gauge   | Cache hit ratio per query (%)        |
| `fraiseql_pg_database_cache_hit_cache_hit_ratio` | gauge | Overall database cache hit ratio |

## Health check

The `check_query_stats()` health check function reports whether
`pg_stat_statements` is available. It is an **optional** (non-critical) check:
a missing extension does not make the overall health endpoint fail.

```python
from fraiseql.monitoring import HealthCheck, check_query_stats

health = HealthCheck()
health.add_check("query_stats", check_query_stats)
```

## Interpreting the data

### Cache hit ratio

The buffer cache hit ratio measures the percentage of block reads served from
PostgreSQL's shared buffer cache (vs. reading from disk):

- **> 99%**: Excellent. Working set fits in memory.
- **95-99%**: Good. Minor disk reads, typically acceptable.
- **< 95%**: Investigate. May need more `shared_buffers`, or queries are
  scanning too much data.
- **< 90%**: Action needed. Either the working set exceeds memory or queries
  need optimization (missing indexes, full table scans).

### Identifying slow queries

Sort by `mean_exec_time` to find queries that are individually slow:

```bash
fraiseql query-stats --order-by mean_exec_time --top-n 10
```

Sort by `total_exec_time` to find queries consuming the most total database
time (high call count * moderate latency):

```bash
fraiseql query-stats --order-by total_exec_time
```

## Operational guidance

### `pg_stat_statements.max` tuning

The default is 5000 statements. If your application generates diverse query
patterns (e.g., dynamic filters, many tables), this limit may be too low.
Symptoms of exhaustion:

- Statement eviction (older entries are replaced)
- Unreliable aggregate statistics

Check current usage:

```sql
SELECT count(*) FROM pg_stat_statements;
-- If close to pg_stat_statements.max, consider increasing it
```

### When to reset statistics

Reset counters after:

- **Deployments**: Changed queries make old stats misleading
- **Index changes**: Before/after comparison requires a clean baseline
- **Periodically**: Stale accumulation over months dilutes recent patterns

```bash
fraiseql query-stats --reset
```

### PgBouncer caveat

`pg_stat_statements` tracks per-backend statistics. With PgBouncer in
**transaction mode**, connections are multiplexed across backends. Per-query
stats (calls, timing, rows) remain accurate, but the `userid` column may
reflect the pooler's role rather than the application user.

This does not affect the `v_query_stats` view, which does not expose `userid`.
