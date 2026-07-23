---
title: Performance Tuning Runbook
description: Operational procedures for diagnosing and optimizing FraiseQL query performance in production.
keywords: ["deployment", "scaling", "performance", "monitoring", "troubleshooting"]
tags: ["documentation", "reference"]
---

# Performance Tuning Runbook

**Status:** Production Ready
**Audience:** DevOps, Database Administrators, Performance Engineers
**Reading Time:** 30-40 minutes

Operational procedures for diagnosing and optimizing FraiseQL query performance in production.

FraiseQL v1 is a Python runtime GraphQL framework that serves a PostgreSQL database over
FastAPI. Queries read `v_`/`tv_` views, mutations call `fn_` PostgreSQL functions, and the
GraphQL schema is built in memory at application startup. Almost all performance work
therefore happens in two places: **your PostgreSQL database** (indexes, statistics, views)
and **the FastAPI app** (connection pool, caching). This runbook covers both.

---

## Overview

This runbook provides **diagnosis workflows** and **remediation steps** for common performance issues. Each section includes:

- **Symptoms** (what users see)
- **Diagnosis** (how to identify root cause)
- **Solutions** (how to fix it)
- **Prevention** (how to avoid in future)

---

## Quick Diagnosis Tree

```text
Is performance issue...

1. NEW: Slow since deployment?
   → Go to: AFTER SCHEMA CHANGE (below)

2. GRADUAL: Getting slower over time?
   → Go to: INDEX FRAGMENTATION or STATISTICS STALE

3. INTERMITTENT: Only sometimes slow?
   → Go to: CONNECTION POOL EXHAUSTION or DATABASE UNDER LOAD

4. SPECIFIC QUERY: One query is slow?
   → Go to: QUERY ANALYSIS

5. BROAD: Many queries slow?
   → Go to: DATABASE TUNING or NETWORK LATENCY
```

---

## 1. Query Performance Analysis

### Symptom: Single Query Takes > 1 Second

### Diagnosis Step 1: Enable Query Logging

FraiseQL is a Python/FastAPI application. Turn up Python logging to see the SQL it issues
against your views and functions. Set the logger level via standard Python logging (or the
`FRAISEQL_` environment, e.g. `FRAISEQL_DATABASE_ECHO=true` to echo SQL).

```python
# In your app entry point, before create_fraiseql_app(...)
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("fraiseql").setLevel(logging.DEBUG)
```

```bash
# Run the app with uvicorn and watch the logs
uvicorn app:app --host 0.0.0.0 --port 8000 2>&1 | grep -i "query\|select"
```

**Look for:**

- Query execution time
- The generated SQL against your `v_`/`tv_` views
- Database roundtrip time
- Result transformation time (JSONB shaping, done by the optional `fraiseql_rs` extension)

### Diagnosis Step 2: Get Query Plan from Database

Take the SQL FraiseQL logged (a `SELECT ... FROM v_...`) and run `EXPLAIN ANALYZE` against
PostgreSQL:

```sql
-- PostgreSQL
EXPLAIN ANALYZE
SELECT ... FROM v_user WHERE ...;
```

**Interpret output:**

- **Seq Scan** = Sequential scan (bad, table is too large)
- **Index Scan** = Using index (good)
- **Nested Loop** = Joining rows inefficiently (check indexes)
- **Hash Join** = Hash-based join (acceptable)

### Diagnosis Step 3: Check for Missing Indexes

```sql
-- Find tables without indexes
SELECT schemaname, tablename
FROM pg_tables
WHERE schemaname = 'public'
EXCEPT
SELECT schemaname, tablename
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename;

-- Check the most expensive queries (requires the pg_stat_statements extension)
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
WHERE mean_exec_time > 100
ORDER BY mean_exec_time DESC
LIMIT 5;

-- Example output: "SELECT ... FROM tb_user WHERE created_at >= ..."
-- → Need index on created_at
```

> Enable `pg_stat_statements` by adding it to `shared_preload_libraries` in
> `postgresql.conf` and running `CREATE EXTENSION pg_stat_statements;`.

### Solutions

**Solution 1: Add Missing Index**

```sql
-- Identify filter columns from EXPLAIN output
CREATE INDEX idx_user_created_at ON tb_user(created_at);

-- Verify the index is used
EXPLAIN SELECT * FROM tb_user WHERE created_at >= '2026-01-01';
-- Should show "Index Scan" not "Seq Scan"
```

**Concurrent index creation (doesn't lock the table):**

```sql
-- Build the index without blocking writes (recommended in production)
CREATE INDEX CONCURRENTLY idx_user_created_at ON tb_user(created_at);
```

Because read views build a `data` JSONB column, you often want indexes on the JSONB
expressions you filter on:

```sql
-- Index on a value extracted from the JSONB data column
CREATE INDEX idx_user_email
    ON tb_user ((data->>'email'));

-- GIN index for containment / key-existence queries on the whole JSONB document
CREATE INDEX idx_user_data_gin ON tb_user USING gin (data);
```

**Solution 2: Composite Indexes for Common Filter Combinations**

```sql
-- If queries often filter by both tenant and status:
CREATE INDEX idx_user_tenant_status ON tb_user(tenant_id, status);
-- Covers WHERE tenant_id = X AND status = 'active'

-- If queries filter by range, put the range column last:
CREATE INDEX idx_posts_user_date ON tb_post(fk_user, created_at);
-- Covers WHERE fk_user = X AND created_at >= Y
```

**Solution 3: Switch to a Table-Backed Projection View (`tv_*`)**

If indexing a logical `v_` view doesn't help (heavy aggregation or deep nested joins),
move to a **table-backed projection view** (`tv_`): a real table that holds the
pre-composed `data` JSONB, refreshed by your `fn_` functions or triggers. Reads then hit
a pre-built, indexable table instead of recomputing JSONB per request.

```python
import fraiseql
from fraiseql.types import ID

# Logical view: data JSONB computed per query (good for small/simple reads)
@fraiseql.type(sql_source="v_user_stats", jsonb_column="data")
class UserStats:
    id: ID
    post_count: int

# Table-backed projection view: data pre-composed and refreshed by fn_/triggers
@fraiseql.type(sql_source="tv_user_stats", jsonb_column="data")
class UserStatsFast:
    id: ID
    post_count: int  # Pre-computed in tv_user_stats, indexable
```

**Solution 4: Reduce Query Scope**

```graphql
# Before: fetching too much
query {
  users {  # Gets all 10M users!
    id
    name
    posts { id title }
  }
}

# After: add filters (WHERE operators are generated against the view)
query {
  users(where: { created_at: { gte: "2026-01-01" } }) {
    id
    name
    posts { id title }
  }
}
```

### Prevention

- [ ] Monitor slow queries via `pg_stat_statements` (alert if `mean_exec_time > 500ms`)
- [ ] Weekly index review: check for missing indexes on filtered columns / JSONB expressions
- [ ] Query profiling in staging: profile new queries with `EXPLAIN ANALYZE` before deploying
- [ ] Document expected performance: "Query X should run in < 100ms"

---

## 2. Database Connection Pool Issues

### Symptom: "Too Many Connections" or "Connection Timeout"

FraiseQL maintains an async connection pool inside the FastAPI app. The effective maximum
number of database connections is `connection_pool_size + connection_pool_max_overflow`.

### Diagnosis

```sql
-- Check active connections
SELECT COUNT(*) FROM pg_stat_activity;
SELECT setting FROM pg_settings WHERE name = 'max_connections';

-- Example: 100 max connections, 95 active → almost exhausted

-- Find slow / non-idle connections
SELECT pid, usename, state, query_start, query
FROM pg_stat_activity
WHERE state != 'idle'
ORDER BY query_start;
```

### Solutions

**Solution 1: Increase Pool Size**

Tune the pool through `create_fraiseql_app(...)` kwargs:

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://user:pass@localhost/mydb",
    types=[User],
    queries=[users, user],
    connection_pool_size=30,        # base connections held open
    connection_pool_max_overflow=20,  # extra connections under load
    connection_pool_timeout=30.0,   # seconds to wait for a free connection
    connection_pool_recycle=3600,   # seconds before recycling idle connections
)
```

Equivalently, via `FraiseQLConfig` (or the `FRAISEQL_` environment variables it reads):

```python
from fraiseql.fastapi import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    database_pool_size=30,
    database_max_overflow=20,
    database_pool_timeout=30,
    database_pool_recycle=3600,
)
```

```bash
# Or set them from the environment (FRAISEQL_ prefix, case-insensitive)
export FRAISEQL_DATABASE_POOL_SIZE=30
export FRAISEQL_DATABASE_MAX_OVERFLOW=20
export FRAISEQL_DATABASE_POOL_TIMEOUT=30
export FRAISEQL_DATABASE_POOL_RECYCLE=3600
```

**Sizing guidance:**

- Keep `pool_size + max_overflow` comfortably below PostgreSQL's `max_connections`
  (commonly 100-500, depending on the server).
- Account for **every** app instance/worker: total DB connections = per-instance pool max
  × number of instances. Three instances with `30 + 20` can open 150 connections.

**Solution 2: Add a Connection Pooler in Front of PostgreSQL**

```bash
# Use PgBouncer when many app instances would otherwise exhaust max_connections
sudo apt install pgbouncer
```

```ini
; /etc/pgbouncer/pgbouncer.ini
[databases]
mydb = host=localhost port=5432 dbname=mydb

[pgbouncer]
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 25
```

**Solution 3: Kill Slow/Idle Connections**

```sql
-- Kill connections idle > 5 minutes
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle'
AND query_start < now() - interval '5 minutes';

-- Set a server-side idle timeout instead of killing manually
ALTER DATABASE mydb SET idle_in_transaction_session_timeout = '60s';
```

**Solution 4: Set Connection and Query Timeouts**

`connection_pool_timeout` bounds how long FraiseQL waits for a free pool slot. Bound the
query itself in PostgreSQL with `statement_timeout`:

```sql
-- Abort any statement running longer than 30 seconds (per role or per database)
ALTER ROLE fraiseql_user SET statement_timeout = '30s';
```

### Prevention

- [ ] Monitor pool usage: alert at 80% capacity
- [ ] Size `pool_size + max_overflow` against `max_connections` and instance count
- [ ] Regular connection review (weekly)
- [ ] Implement statement timeouts
- [ ] Close subscriptions on disconnect

---

## 3. Index Fragmentation

### Symptom: Query Was Fast, Now Slow (Same Data Size)

### Diagnosis

```sql
-- Find unused indexes (candidates for removal) and large indexes
SELECT schemaname, tablename, indexrelname, idx_scan,
       pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
WHERE idx_scan = 0
ORDER BY pg_relation_size(indexrelid) DESC;

-- Estimate table/index bloat (requires the pgstattuple extension)
CREATE EXTENSION IF NOT EXISTS pgstattuple;
SELECT * FROM pgstattuple('idx_user_created_at');
```

### Solutions

**Solution 1: Reindex**

```sql
-- Reindex a single index (takes a lock)
REINDEX INDEX idx_user_created_at;

-- Reindex an entire table (rebuilds all its indexes)
REINDEX TABLE tb_user;

-- Concurrent reindex (no exclusive lock, PostgreSQL 12+)
REINDEX INDEX CONCURRENTLY idx_user_created_at;
```

**Solution 2: VACUUM to Reclaim Dead Tuples**

```sql
-- Reclaim space and update visibility map (does not lock for normal VACUUM)
VACUUM (ANALYZE) tb_user;

-- VACUUM FULL rewrites the table compactly but takes an exclusive lock
VACUUM FULL tb_user;
```

**Solution 3: Regular Maintenance Schedule**

```bash
# Weekly concurrent reindex of a hot table (PostgreSQL 12+)
0 2 * * 0 psql -d "$DATABASE_URL" -c "REINDEX TABLE CONCURRENTLY tb_user;"

# Daily vacuum + analyze of heavily modified tables
0 3 * * * psql -d "$DATABASE_URL" -c "VACUUM (ANALYZE) tb_user; VACUUM (ANALYZE) tb_post;"
```

### Prevention

- [ ] Schedule periodic concurrent reindexing of hot tables
- [ ] Monitor index bloat with `pgstattuple` (alert if > 20% bloat)
- [ ] Use concurrent indexing operations to avoid downtime
- [ ] Rely on autovacuum, and run manual `ANALYZE` after large bulk loads

---

## 4. Stale Database Statistics

### Symptom: Query Planner Chooses Wrong Index or Seq Scan

### Diagnosis

```sql
-- Check when statistics were last updated and autovacuum/analyze ran
SELECT schemaname, tablename, last_vacuum, last_autovacuum,
       last_analyze, last_autoanalyze, n_dead_tup
FROM pg_stat_user_tables
ORDER BY last_analyze NULLS FIRST;

-- If last_analyze / last_autoanalyze is very old → update statistics
```

### Solutions

**Solution 1: Update Statistics (ANALYZE)**

```sql
ANALYZE tb_user;
ANALYZE;  -- All tables in the current database
```

**Solution 2: Autovacuum Configuration**

```sql
-- Check autovacuum settings
SELECT name, setting FROM pg_settings WHERE name LIKE 'autovacuum%';

-- Make autovacuum more aggressive globally
ALTER SYSTEM SET autovacuum_naptime = '30s';  -- Default 60s
SELECT pg_reload_conf();

-- Or tune a single high-churn table
ALTER TABLE tb_post SET (autovacuum_analyze_scale_factor = 0.02);
```

**Solution 3: Schedule Regular ANALYZE**

```bash
# Hourly analysis of heavily modified tables
0 * * * * psql -d "$DATABASE_URL" -c "ANALYZE tb_user; ANALYZE tb_post;"

# Daily full-database analysis
0 2 * * * psql -d "$DATABASE_URL" -c "ANALYZE;"
```

### Prevention

- [ ] Keep autovacuum enabled (it is on by default)
- [ ] Schedule regular `ANALYZE`: daily for OLTP, hourly for heavily modified tables
- [ ] Monitor `last_analyze` / `last_autoanalyze` timestamps
- [ ] Alert if statistics are > 24 hours old on a busy table

---

## 5. Slow Aggregation Queries

### Symptom: GROUP BY or COUNT(DISTINCT) Queries Taking > 10 Seconds

FraiseQL supports **runtime auto-aggregation**: when a GraphQL query selects aggregate
fields on a view-backed type, FraiseQL derives `GROUP BY` + aggregate SQL automatically
(allowed functions: `SUM`, `AVG`, `COUNT`, `MIN`, `MAX`, `ARRAY_AGG`, `STRING_AGG`,
`BOOL_AND`, `BOOL_OR`, `JSON_AGG`, `JSONB_AGG`). That derived SQL still runs against your
PostgreSQL views, so the tuning below applies. Functions outside the allowlist (e.g.
`STDDEV`, `VARIANCE`) must be written by hand in the view SQL.

### Diagnosis

```sql
-- Identify aggregation queries (requires pg_stat_statements)
SELECT query, mean_exec_time
FROM pg_stat_statements
WHERE query ILIKE '%count%' OR query ILIKE '%group by%'
ORDER BY mean_exec_time DESC
LIMIT 5;

-- Check whether they use indexes
EXPLAIN ANALYZE SELECT COUNT(DISTINCT fk_user) FROM tb_post;
-- Look for "Seq Scan" (bad) vs "Index Only Scan" (good)
```

### Solutions

**Solution 1: Add Index for the Aggregation Column**

```sql
-- For: COUNT(DISTINCT fk_user)
CREATE INDEX idx_post_user ON tb_post(fk_user);

-- For: GROUP BY status
CREATE INDEX idx_order_status ON tb_order(status);

-- For: multiple GROUP BY columns
CREATE INDEX idx_user_org_status ON tb_user(fk_organization, status);
```

**Solution 2: Pre-Compute with a Table-Backed Projection View**

Move the aggregation out of the request path. Compute it into a `tv_` table refreshed by a
`fn_` function or trigger, and expose the `tv_` as the read source:

```python
import fraiseql
from fraiseql.types import ID, DateTime

# Aggregation is pre-computed in tv_user_stats and refreshed on a schedule;
# reads no longer run COUNT/GROUP BY on every request.
@fraiseql.type(sql_source="tv_user_stats", jsonb_column="data")
class UserStats:
    id: ID
    post_count: int   # pre-computed
    updated_at: DateTime
```

You can implement the same idea with a PostgreSQL **materialized view** refreshed
periodically:

```sql
CREATE MATERIALIZED VIEW mv_user_post_counts AS
SELECT fk_user, COUNT(*) AS post_count
FROM tb_post
GROUP BY fk_user;

-- Refresh without blocking readers (requires a unique index on the MV)
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_user_post_counts;
```

**Solution 3: Partition Large Tables**

```sql
-- Partition the post table by date
CREATE TABLE tb_post_2026_01 PARTITION OF tb_post
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

-- Aggregation on a single monthly partition is much faster (partition pruning)
SELECT COUNT(*) FROM tb_post WHERE created_at >= '2026-01-01'
                              AND created_at <  '2026-02-01';
```

### Prevention

- [ ] Profile `GROUP BY` queries before deploying
- [ ] Create indexes on aggregation columns
- [ ] Use `tv_` projection tables or materialized views for heavy aggregations
- [ ] Monitor query time: alert if > 5 seconds

---

## 6. N+1 Query Problem

### Symptom: Many Small Queries Instead of One Large Query

### Diagnosis

Turn up FraiseQL's Python logging and count the SQL statements issued for a single request.

```python
import logging
logging.getLogger("fraiseql").setLevel(logging.DEBUG)
```

```bash
# Run the request, capture the app logs, then count SELECTs
uvicorn app:app 2>&1 | tee logs.txt
grep -c -i "select" logs.txt
# ~101 statements for 100 parents → N+1 problem
```

### Solutions

**Solution 1: Compose the Nested Data Inside the View**

The most reliable fix is to build the nested data directly into the `data` JSONB of a
`v_`/`tv_` view using `jsonb_build_object` / `jsonb_agg`, so one read returns everything:

```sql
-- v_user_with_posts: posts embedded in the user's data JSONB (one query, no N+1)
CREATE VIEW v_user_with_posts AS
SELECT
    u.id,
    jsonb_build_object(
        'id', u.id,
        'name', u.data->>'name',
        'posts', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('id', p.id, 'title', p.data->>'title'))
            FROM tb_post p
            WHERE p.fk_user = u.pk_user
        ), '[]'::jsonb)
    ) AS data
FROM tb_user u;
```

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user_with_posts", jsonb_column="data")
class UserWithPosts:
    id: ID
    name: str
    posts: list["Post"]  # fetched in the view definition, no per-row query
```

**Solution 2: Batch a Field with a DataLoader**

For computed/related fields resolved in Python, batch them with `@fraiseql.dataloader_field`
to collapse N lookups into one:

```python
import fraiseql

@fraiseql.dataloader_field
async def author(post: "Post", info) -> "User":
    # Loaded in a single batched query for all posts in the result set.
    ...
```

**Solution 3: Flatten the Query Structure**

If deep nesting is unavoidable on a slow path, split it into separate queries the client
joins client-side:

```graphql
query { users { id } }
query { posts { id userId } }
query { comments { id postId } }
```

### Prevention

- [ ] Monitor query count per request: alert if > 10 queries per request
- [ ] Load test with large datasets (1000+ records)
- [ ] Prefer view-composed nested data over per-field resolvers on hot paths
- [ ] Use `@fraiseql.dataloader_field` for Python-resolved relations
- [ ] Test queries with `EXPLAIN ANALYZE` to see the execution plan

---

## 7. Network Latency Issues

### Symptom: Queries Slow Even Though Database is Fast

### Diagnosis

```bash
# Measure latency to the database host
ping -c 10 database-host
# Normal: 1-10ms; High: > 50ms indicates a network issue

# Measure end-to-end database response time
time psql -h database-host -d mydb -c "SELECT COUNT(*) FROM tb_user;"

# Inspect the network path
traceroute database-host
# Look for high latency at any hop
```

### Solutions

**Solution 1: Reduce Network Roundtrips**

Compose related data in the view (see Section 6) so a request makes one roundtrip instead
of several. Inside views, prefer a single joined `SELECT` over multiple subqueries:

```sql
-- One roundtrip: join user and posts in the view's SELECT
SELECT u.id,
       jsonb_build_object('user', u.data, 'posts', jsonb_agg(p.data)) AS data
FROM tb_user u
LEFT JOIN tb_post p ON p.fk_user = u.pk_user
WHERE u.id = $1
GROUP BY u.id, u.data;
```

**Solution 2: Co-locate the Pooler / Database with the App**

```bash
# Deploy PgBouncer on the same host (or same AZ) as the FastAPI app
# to cut per-connection roundtrip overhead.
```

**Solution 3: Cache Frequently Accessed Data**

Use FraiseQL's PostgreSQL-backed result cache (see Section 9) for read-heavy, slow-changing
data. Also deploy the database in the same availability zone as the application.

### Prevention

- [ ] Monitor network latency: alert if > 50ms
- [ ] Deploy database close to the application (same AZ)
- [ ] Use connection pooling
- [ ] Compose nested data in views to reduce roundtrips

---

## 8. Memory Leaks or Growing Memory Usage

### Symptom: Memory Usage Increases Over Time, Never Returns

### Diagnosis

```bash
# Find the uvicorn / app process and watch resident memory
ps aux | grep uvicorn
top -p <app_pid>          # watch RES (resident set size) — should be stable

# Check for open file handles (growing → handle leak)
lsof -p <app_pid> | wc -l
```

```sql
-- Check for unclosed database connections from the app role
SELECT count(*) FROM pg_stat_activity WHERE usename = 'fraiseql_user';
-- Should stay near the configured pool size, not grow unbounded
```

### Solutions

**Solution 1: Ensure Resources Are Released**

The CQRS repository borrows pool connections per request and returns them automatically.
For long-lived async generators (subscriptions), make sure the generator is closed:

```python
# Subscriptions are async generators; ensure cleanup on disconnect
@fraiseql.subscription
async def task_updates(info, project_id):
    try:
        async for task in watch_project_tasks(project_id):
            yield task
    finally:
        # release any external resources you opened in the generator
        ...
```

**Solution 2: Bound Concurrency and Query Cost**

Limit query depth/complexity and request load through `FraiseQLConfig` rather than
unbounded execution:

```python
from fraiseql.fastapi import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    complexity_enabled=True,
    complexity_max_depth=10,
    complexity_max_score=1000,
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=60,
    execution_timeout_ms=30000,
)
```

**Solution 3: Profile and Recycle**

```bash
# Profile a Python process with a sampling profiler such as py-spy
py-spy top --pid <app_pid>

# As a stop-gap, recycle workers periodically (uvicorn/gunicorn)
gunicorn app:app -k uvicorn.workers.UvicornWorker --max-requests 10000 --max-requests-jitter 1000
```

### Prevention

- [ ] Monitor memory: alert if growth > 10%/day
- [ ] Recycle workers periodically (`--max-requests`)
- [ ] Ensure subscription generators clean up on disconnect
- [ ] Set complexity, rate-limit, and execution timeouts

---

## 9. Query Caching Effectiveness

### Symptom: Query Results Seem Stale or Caching Not Working

FraiseQL ships a PostgreSQL-backed result cache in `fraiseql.caching`. The key pieces:

- `PostgresCache` — a cache backend stored in an `UNLOGGED` PostgreSQL table (shared across
  app instances, fast, cleared on crash — acceptable for cache data).
- `ResultCache` + `CacheConfig` — the cache itself and its settings (`enabled`,
  `default_ttl`, `max_ttl`, `cache_errors`, `key_prefix`). `CacheStats` exposes `hits`,
  `misses`, and `hit_rate`.
- `CachedRepository` — wraps the CQRS repository so `db.find(...)` is cached transparently
  (with per-tenant key isolation), accepting `skip_cache=` and `cache_ttl=` per call.
- `CascadeRule` + `SchemaAnalyzer` + `setup_auto_cascade_rules` — derive invalidation rules
  from your GraphQL schema so changing one type invalidates dependent caches.
- `cached_query` — a decorator for caching the result of an individual resolver.

### Diagnosis

```python
# Inspect cache statistics from a ResultCache instance
print(result_cache.stats.hits, result_cache.stats.misses, result_cache.stats.hit_rate)
```

```python
# Turn on cache logging
import logging
logging.getLogger("fraiseql.caching").setLevel(logging.DEBUG)
# Then run the same query twice and look for "Cache hit" vs "Cache miss"
```

### Solutions

**Solution 1: Enable Query Caching**

```python
from fraiseql.caching import PostgresCache, ResultCache, CacheConfig, CachedRepository

# Backend: an UNLOGGED PostgreSQL table shared across instances
backend = PostgresCache(connection_pool=pool, table_name="fraiseql_cache")

# Cache with a 5-minute default TTL
cache = ResultCache(backend, CacheConfig(enabled=True, default_ttl=300, max_ttl=3600))

# Wrap the repository so reads are cached transparently
cached_repo = CachedRepository(base_repository=repo, cache=cache)
```

**Solution 2: Invalidate the Cache on Writes (Cascade Rules)**

```python
from fraiseql.caching import setup_auto_cascade_rules

# Analyze the schema and register CASCADE invalidation rules so that, e.g.,
# changing a User invalidates cached Posts that reference it.
await setup_auto_cascade_rules(schema=schema, cache=cache)
```

```python
from fraiseql.caching import CascadeRule

# Or declare a rule explicitly: when "user" changes, invalidate "post" caches.
rule = CascadeRule(source_domain="user", target_domain="post")
```

**Solution 3: Tune TTL Per Read or Bypass When Needed**

`CachedRepository.find` accepts a per-call TTL and a cache bypass:

```python
# Slow-changing reference data: cache longer
users = await cached_repo.find("v_user", cache_ttl=900)

# Volatile data (e.g. inventory): bypass the cache for a fresh read
levels = await cached_repo.find("v_inventory_level", skip_cache=True)
```

> The optional `fraiseql_rs` extension accelerates JSONB transformation on the read path;
> it complements, but does not replace, the result cache above.

### Prevention

- [ ] Monitor cache effectiveness via `CacheStats.hit_rate` (alert if hit rate < 30%)
- [ ] Set an appropriate TTL per data type (`cache_ttl` / `CacheConfig`)
- [ ] Register cascade invalidation rules so mutations don't serve stale reads
- [ ] Profile cache performance against an expected hit rate

---

## 10. Production Response Checklist

**When a performance issue is reported:**

1. **Immediately:**
   - [ ] Check application logs for exceptions
   - [ ] Verify database connectivity and pool health
   - [ ] Check if it's a known issue

2. **Within 5 minutes:**
   - [ ] Identify affected queries (`pg_stat_statements`, app logs)
   - [ ] Check request rate: normal load?
   - [ ] Run `EXPLAIN ANALYZE` on the slow view query
   - [ ] Check for missing indexes

3. **Within 15 minutes:**
   - [ ] Apply temporary mitigation (cache, statement timeout, index)
   - [ ] Monitor for improvement
   - [ ] Communicate status to the team

4. **Later:**
   - [ ] Root cause analysis
   - [ ] Implement permanent fix (index, view rewrite, projection table, cache rule)
   - [ ] Deploy to staging first
   - [ ] Gradual rollout to production
   - [ ] Document in the runbook

---

## See Also

**Related Guides:**

- **[Schema Design Best Practices](../guides/schema-design-best-practices.md)** — Designing for performance
- **[Common Gotchas](../guides/common-gotchas.md)** — Avoid performance pitfalls
- **[Monitoring & Observability](../guides/monitoring.md)** — Setting up performance metrics
- **[View Selection Guide](../architecture/database/view-selection-guide.md)** — Choosing `v_` vs `tv_` for performance

**Operations:**

- **[Observability & Monitoring](./observability.md)** — Runtime performance monitoring
