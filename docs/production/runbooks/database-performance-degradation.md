# Database Performance Degradation Runbook

**Last Updated**: 2025-12-29
**Severity**: HIGH
**MTTR Target**: 15 minutes

---

## 📋 Overview

This runbook guides you through diagnosing and resolving database performance issues in FraiseQL applications. Database performance degradation can manifest as slow query responses, connection pool exhaustion, or query timeouts.

---

## 🚨 Symptoms

### Primary Indicators

- GraphQL queries taking > 5 seconds
- Database connection pool exhausted
- Query timeout errors (> 30 seconds)
- High database CPU usage (> 80%)
- Increasing query latency over time

### Prometheus Metrics to Monitor

```promql
# Query duration exceeding 5 seconds
rate(fraiseql_db_query_duration_seconds_sum[5m])
/ rate(fraiseql_db_query_duration_seconds_count[5m]) > 5

# Connection pool near capacity
fraiseql_db_connections_active / fraiseql_db_connections_total > 0.8

# Query timeout rate increasing
rate(fraiseql_errors_total{error_code="QUERY_TIMEOUT"}[5m]) > 0.1
```

### Structured Logs Examples

```json
{
  "timestamp": "2025-12-29T10:45:23.456Z",
  "level": "WARNING",
  "event": "database.slow_query",
  "message": "Query exceeded performance threshold",
  "context": {
    "query_duration_ms": 8500,
    "query_type": "SELECT",
    "table_name": "users",
    "threshold_ms": 5000,
    "user_id": "user_123"
  },
  "trace_id": "trace_abc123"
}
```

```json
{
  "timestamp": "2025-12-29T10:45:30.123Z",
  "level": "ERROR",
  "event": "database.query_timeout",
  "message": "Query exceeded timeout limit",
  "context": {
    "query_duration_ms": 30000,
    "timeout_ms": 30000,
    "query_type": "SELECT",
    "table_name": "orders",
    "user_id": "user_456"
  },
  "trace_id": "trace_def456"
}
```

---

## 🔍 Diagnostic Steps

### Step 1: Check Current Query Performance

**Via Prometheus**:

```promql
# Average query duration by query type
avg by (query_type) (
  rate(fraiseql_db_query_duration_seconds_sum[5m])
  / rate(fraiseql_db_query_duration_seconds_count[5m])
)

# Top 5 slowest tables
topk(5,
  sum by (table_name) (fraiseql_db_query_duration_seconds_sum)
)
```

**Via Structured Logs**:

```bash
# Find slow queries in last 5 minutes
jq -r 'select(.event == "database.slow_query") |
  "\(.timestamp) \(.context.table_name) \(.context.query_duration_ms)ms"' \
  /var/log/fraiseql/app.log | tail -50

# Find query timeouts
jq -r 'select(.event == "database.query_timeout") |
  "\(.timestamp) \(.context.table_name) \(.context.user_id)"' \
  /var/log/fraiseql/app.log | tail -50
```

### Step 2: Check Connection Pool Status

**Via Prometheus**:

```promql
# Active connections
fraiseql_db_connections_active

# Idle connections
fraiseql_db_connections_idle

# Total connections
fraiseql_db_connections_total

# Pool utilization percentage
(fraiseql_db_connections_active / fraiseql_db_connections_total) * 100
```

**Via Application Code**:

The repository exposes its psycopg pool, whose `get_stats()` counts connections and
waiting requests (from inside the running app, e.g. a resolver or an admin route):

```python
pool_stats = info.context["db"].get_pool().get_stats()
print(f"Open: {pool_stats['pool_size']}")
print(f"Idle: {pool_stats['pool_available']}")
print(f"Waiting for a connection: {pool_stats.get('requests_waiting', 0)}")
```

### Step 3: Identify Problematic Queries

**PostgreSQL - Find Long-Running Queries**:

```sql
SELECT
  pid,
  usename,
  application_name,
  state,
  query,
  now() - query_start AS duration
FROM pg_stat_activity
WHERE state != 'idle'
  AND query_start < now() - interval '5 seconds'
ORDER BY duration DESC
LIMIT 10;
```

**PostgreSQL - Check Table-Level Stats**:

```sql
SELECT
  schemaname,
  relname AS table_name,
  seq_scan,
  seq_tup_read,
  idx_scan,
  idx_tup_fetch,
  n_tup_ins + n_tup_upd + n_tup_del AS writes
FROM pg_stat_user_tables
ORDER BY seq_tup_read DESC
LIMIT 10;
```

**PostgreSQL - Missing Indexes**:

```sql
SELECT
  schemaname,
  tablename,
  seq_scan,
  seq_tup_read,
  idx_scan,
  seq_tup_read / seq_scan AS avg_seq_read
FROM pg_stat_user_tables
WHERE seq_scan > 0
  AND idx_scan = 0
ORDER BY seq_tup_read DESC
LIMIT 10;
```

### Step 4: Check Database Resource Usage

**PostgreSQL - Database Size**:

```sql
SELECT
  pg_size_pretty(pg_database_size(current_database())) AS db_size;
```

**PostgreSQL - Connection Count**:

```sql
SELECT count(*) AS total_connections
FROM pg_stat_activity;

SELECT
  state,
  count(*) AS count
FROM pg_stat_activity
GROUP BY state;
```

**PostgreSQL - Cache Hit Ratio** (should be > 95%):

```sql
SELECT
  sum(heap_blks_read) AS heap_read,
  sum(heap_blks_hit) AS heap_hit,
  sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) AS cache_hit_ratio
FROM pg_statio_user_tables;
```

---

## 🔧 Resolution Steps

### Immediate Actions (5 minutes)

#### 1. Verify Query Timeout Configuration

`query_timeout` (seconds, default 30) becomes a `SET LOCAL statement_timeout` on the
statements the repository runs through `db.run()` and on mutation functions
(`execute_function`); PostgreSQL cancels one that runs longer:

```python
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    query_timeout=60,  # For slow queries, temporarily increase from 30
)
app = create_fraiseql_app(config=config, types=[Order], queries=[orders])
```

**Environment Variable Override** (read when the app is built from a `FraiseQLConfig`):

```bash
# In production environment
export FRAISEQL_QUERY_TIMEOUT=60  # seconds
```

`find()`, `find_one()` and the other reads don't get it, so bound every statement
the app sends with a timeout on its database role as well; new pool connections
pick it up:

```sql
ALTER ROLE app_user SET statement_timeout = '30s';
```

#### 2. Kill Long-Running Queries (If Critical)

```sql
-- Find problematic query PID
SELECT pid, query
FROM pg_stat_activity
WHERE state != 'idle'
  AND query_start < now() - interval '30 seconds';

-- Kill specific query
SELECT pg_cancel_backend(<pid>);

-- Force terminate if cancel doesn't work
SELECT pg_terminate_backend(<pid>);
```

#### 3. Temporarily Increase Connection Pool Size

The pool opens at most `database_pool_size + database_max_overflow` connections:

```python
from fraiseql.fastapi import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    database_pool_size=30,  # Default: 20 (create_fraiseql_app uses 10 in development)
    database_max_overflow=10,  # Default: 10
)
```

**Environment Variables** (read when the app is built from a `FraiseQLConfig`):

```bash
export FRAISEQL_DATABASE_POOL_SIZE=30
export FRAISEQL_DATABASE_MAX_OVERFLOW=10
```

### Short-Term Fixes (15-30 minutes)

#### 1. Analyze and Optimize Slow Queries

**Enable Query Logging**:

```sql
-- PostgreSQL configuration
ALTER DATABASE your_db SET log_min_duration_statement = 1000;  -- Log queries > 1s
ALTER DATABASE your_db SET log_statement = 'all';
```

**Use EXPLAIN ANALYZE**:

```sql
-- For slow GraphQL query
EXPLAIN ANALYZE
SELECT ... FROM users WHERE ...;
```

**Common Issues**:

- Missing indexes → Add indexes
- Sequential scans → Add WHERE clause indexes
- Join order → Reorder joins
- N+1 queries → Use DataLoader pattern

#### 2. Add Missing Indexes

```sql
-- Example: Index on frequently filtered column
CREATE INDEX CONCURRENTLY idx_users_email ON users(email);

-- Example: Composite index for common WHERE clauses
CREATE INDEX CONCURRENTLY idx_orders_user_status
ON orders(user_id, status);

-- Example: Index for foreign key lookups
CREATE INDEX CONCURRENTLY idx_order_items_order_id
ON order_items(order_id);
```

**Note**: Use `CONCURRENTLY` to avoid locking the table.

#### 3. Optimize Connection Pool Settings

**Configuration Guidelines**:

```python
# Calculate optimal pool size
# Rule of thumb: pool_size = (available_connections / number_of_app_instances) * 0.8

# Example for PostgreSQL with max_connections=100, 2 app instances
pool_size = (100 / 2) * 0.8  # = 40 connections per instance, overflow included

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    database_pool_size=30,
    database_max_overflow=10,  # 30 + 10 = 40
    database_pool_timeout=30,  # seconds to wait for connection
    database_pool_recycle=3600,  # recycle connections after 1 hour
)
```

### Long-Term Solutions (1+ days)

#### 1. Implement Query Result Caching

Cache expensive reads with `fraiseql.caching` (`PostgresCache` + `ResultCache` +
`CachedRepository`, stored in a PostgreSQL UNLOGGED table): see
[Caching](../../performance/caching.md) for the setup and invalidation.

For reads that are expensive to compute rather than frequent, pre-compose them into
a `tv_` projection table instead.

#### 2. Use Database Read Replicas

fraiseql connects to one `database_url` and has no read/write routing. To offload
reads, run a separate deployment of the API pointed at a replica (or at a
connection pooler that routes to replicas), and send read-only traffic to it.

#### 3. Partition Large Tables

```sql
-- Example: Partition orders by created_at month
CREATE TABLE orders (
    id SERIAL,
    user_id INTEGER,
    created_at TIMESTAMP,
    ...
) PARTITION BY RANGE (created_at);

-- Create monthly partitions
CREATE TABLE orders_2025_01 PARTITION OF orders
FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');

CREATE TABLE orders_2025_02 PARTITION OF orders
FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
```

#### 4. Compose Related Rows in the View (N+1 Queries)

A fraiseql query reads one view; embed related rows in its `data` JSONB and the
whole tree comes back from a single SQL statement, however many orders there are:

```sql
CREATE VIEW v_order AS
SELECT
    o.id,
    jsonb_build_object(
        'id', o.id,
        'total', o.total,
        'created_at', o.created_at,
        'user', jsonb_build_object('id', u.id, 'name', u.name)
    ) AS data
FROM tb_order o
JOIN tb_user u ON u.pk_user = o.fk_user;
```

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.type
class OrderUser:
    id: ID
    name: str


@fraiseql.type(sql_source="v_order", jsonb_column="data")
class Order:
    id: ID
    total: float
    user: OrderUser


@fraiseql.query
async def orders(info, limit: int = 100) -> list[Order]:
    db = info.context["db"]
    return await db.find("v_order", limit=limit)
```

---

## 📊 Monitoring & Alerts

### Prometheus Alert Rules

```yaml
# alerts/database.yml
groups:
  - name: database_performance
    interval: 30s
    rules:
      - alert: DatabaseSlowQueries
        expr: |
          rate(fraiseql_db_query_duration_seconds_sum[5m])
          / rate(fraiseql_db_query_duration_seconds_count[5m]) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Database queries are slow (> 5s average)"
          description: "Average query duration is {{ $value }}s"

      - alert: DatabaseConnectionPoolExhausted
        expr: |
          fraiseql_db_connections_active / fraiseql_db_connections_total > 0.9
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Database connection pool is exhausted"
          description: "{{ $value | humanizePercentage }} of connections in use"

      - alert: DatabaseQueryTimeouts
        expr: |
          rate(fraiseql_errors_total{error_code="QUERY_TIMEOUT"}[5m]) > 0.1
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Database query timeouts increasing"
          description: "{{ $value }} timeouts/sec in last 5 minutes"

      - alert: DatabaseCacheHitRateLow
        expr: |
          (sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read))) < 0.95
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Database cache hit ratio is low (< 95%)"
          description: "Cache hit ratio: {{ $value | humanizePercentage }}"
```

### Grafana Dashboard Panels

**1. Query Duration by Type**:

```promql
avg by (query_type) (
  rate(fraiseql_db_query_duration_seconds_sum[5m])
  / rate(fraiseql_db_query_duration_seconds_count[5m])
)
```

**2. Connection Pool Utilization**:

```promql
fraiseql_db_connections_active
fraiseql_db_connections_idle
fraiseql_db_connections_total
```

**3. Slow Query Rate**:

```promql
rate(fraiseql_db_queries_total{query_duration_bucket="+Inf"}[5m])
```

**4. Query Timeout Rate**:

```promql
rate(fraiseql_errors_total{error_code="QUERY_TIMEOUT"}[5m])
```

---

## 🔍 Verification

After applying fixes, verify performance has improved:

### 1. Check Metrics

```promql
# Query duration should decrease
avg(rate(fraiseql_db_query_duration_seconds_sum[5m])
    / rate(fraiseql_db_query_duration_seconds_count[5m]))

# Connection pool utilization should decrease
fraiseql_db_connections_active / fraiseql_db_connections_total
```

### 2. Check Logs

```bash
# Verify no recent slow queries
jq -r 'select(.event == "database.slow_query")' /var/log/fraiseql/app.log | tail -10

# Verify no timeouts
jq -r 'select(.event == "database.query_timeout")' /var/log/fraiseql/app.log | tail -10
```

### 3. Synthetic Test

```bash
# Run load test
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ users { id name email } }"}'

# Check response time < 1 second
```

---

## 📝 Post-Incident Review

After resolving the incident:

1. **Document Root Cause**:
   - What caused the performance degradation?
   - Missing index? Poor query? Connection leak?

2. **Update Monitoring**:
   - Add alerts for similar patterns
   - Adjust thresholds based on normal load

3. **Implement Preventive Measures**:
   - Add missing indexes
   - Optimize slow queries
   - Tune connection pool settings

4. **Update Runbook**:
   - Add new diagnostic steps
   - Document solution for future reference

---

## 📚 Related Resources

- [PostgreSQL Performance Tuning](https://wiki.postgresql.org/wiki/Performance_Optimization)
- [Connection Pool Best Practices](../deployment.md#connection-pooling)
- [Query Optimization Guide](../../performance/performance-guide.md)
- [Monitoring Setup](../monitoring.md)
- [Health Checks](../health-checks.md)

---

## 🆘 Escalation

If issue persists after following this runbook:

1. **Gather Evidence**:
   - Prometheus metrics screenshot
   - Recent structured logs (last 15 minutes)
   - PostgreSQL query stats
   - Connection pool stats

2. **Escalate To**:
   - Database Administrator (for PostgreSQL tuning)
   - Platform Team (for infrastructure scaling)
   - Development Team (for query optimization)

3. **Emergency Contact**:
   - On-call DBA: [Contact info]
   - Platform On-call: [Contact info]
   - Engineering Manager: [Contact info]

---

**Version**: 1.0
**Last Tested**: 2025-12-29
**Next Review**: 2026-03-29
