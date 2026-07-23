---
title: Connection Pool Tuning Guide
description: Connection pooling is essential for GraphQL API performance. A properly tuned connection pool can improve throughput by 2-3x and reduce latency variance.
keywords: []
tags: ["documentation", "reference"]
---

# Connection Pool Tuning Guide

**Framework**: FraiseQL (Python, FastAPI) over psycopg's async connection pool
**Impact**: Critical for production performance

## Overview

Connection pooling is essential for GraphQL API performance. A properly tuned connection pool can improve throughput by 2-3x and reduce latency variance.

FraiseQL uses [psycopg](https://www.psycopg.org/psycopg3/)'s `AsyncConnectionPool` to manage PostgreSQL connections. The pool is created once at application startup and shared across every GraphQL request, so connections are reused instead of being opened and closed per request.

## How FraiseQL Configures the Pool

You configure the pool through `create_fraiseql_app(...)` keyword arguments:

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    connection_pool_size=20,        # base connections
    connection_pool_max_overflow=10,  # extra connections under burst load
    connection_pool_timeout=30.0,   # seconds to wait for a free connection
    connection_pool_recycle=3600,   # seconds before an idle connection is recycled
)
```

These kwargs map onto fields of `FraiseQLConfig`, which can also be set directly or via `FRAISEQL_`-prefixed environment variables:

| `create_fraiseql_app` kwarg | `FraiseQLConfig` field | Environment variable | Default |
|-----------------------------|------------------------|----------------------|---------|
| `connection_pool_size` | `database_pool_size` | `FRAISEQL_DATABASE_POOL_SIZE` | 20 (10 in dev) |
| `connection_pool_max_overflow` | `database_max_overflow` | `FRAISEQL_DATABASE_MAX_OVERFLOW` | 10 |
| `connection_pool_timeout` | `database_pool_timeout` | `FRAISEQL_DATABASE_POOL_TIMEOUT` | 30 |
| `connection_pool_recycle` | `database_pool_recycle` | `FRAISEQL_DATABASE_POOL_RECYCLE` | 3600 |

Internally, the psycopg pool's `max_size` is `database_pool_size + database_max_overflow`. The pool keeps a small number of connections warm and grows up to `max_size` under load.

### Configuring via `FraiseQLConfig`

```python
from fraiseql import FraiseQLConfig
from fraiseql.fastapi import create_fraiseql_app

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    database_pool_size=20,
    database_max_overflow=10,
    database_pool_timeout=30,
    database_pool_recycle=3600,
)

app = create_fraiseql_app(types=[User], config=config)
```

### Configuring via environment variables

```bash
export FRAISEQL_DATABASE_POOL_SIZE=20
export FRAISEQL_DATABASE_MAX_OVERFLOW=10
export FRAISEQL_DATABASE_POOL_TIMEOUT=30
export FRAISEQL_DATABASE_POOL_RECYCLE=3600
```

## Current Configuration

### Default Settings

| Setting | Value | Notes |
|---------|-------|-------|
| **Pool size** | 20 (10 in dev) | Base connections kept available |
| **Max overflow** | 10 | Extra connections allowed under burst load |
| **Max connections** | `pool_size + max_overflow` | Effective psycopg `max_size` |
| **Acquire timeout** | 30s | Wait time for a free connection before erroring |
| **Recycle** | 3600s | Idle connections recycled after 1 hour |
| **Initialization** | Eager warm-up | A few connections opened at startup |

### What This Means

```text
Behavior:

1. App startup opens a small number of warm connections
2. The pool grows toward max_size (pool_size + max_overflow) as needed
3. Requests acquire a connection, run their query, and return it
4. Idle connections are recycled after database_pool_recycle seconds
```

## Tuning by Workload

### Small Applications (Development, Low Traffic)

**Characteristics**:

- < 100 requests/hour
- < 10 concurrent connections needed
- Single server deployment

**Configuration**:

```python
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    connection_pool_size=5,          # small pool is sufficient
    connection_pool_max_overflow=2,
)
```

**Expected Metrics**:

- Pool utilization: 20-40%
- Connection reuse: High
- Latency: < 50ms p95

### Medium Applications (Staging, Moderate Traffic)

**Characteristics**:

- 1K-10K requests/hour
- 10-50 concurrent connections
- Single or dual server

**Configuration** (Recommended):

```python
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    connection_pool_size=20,         # default 10 in dev is often too small
    connection_pool_max_overflow=10,
)
```

**Expected Metrics**:

- Pool utilization: 40-70%
- Connection reuse: High
- Latency: < 100ms p95

### Large Applications (Production)

**Characteristics**:

- 100K+ requests/hour
- 50-200 concurrent connections
- Multiple servers (load balanced)

**Configuration**:

```python
import os

# Scale the base pool with CPU cores, leave headroom in overflow
cores = os.cpu_count() or 4

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    connection_pool_size=50 + cores,
    connection_pool_max_overflow=20,
    connection_pool_timeout=60.0,
)
```

**Expected Metrics**:

- Pool utilization: 50-80%
- Connection reuse: High
- Latency: < 150ms p95
- Queueing: < 10ms p95

## Tuning for Concurrency

### Rule of Thumb

```text
max_connections = pool_size + max_overflow ≈ (core_count × 2) + effective_spindle_count

For typical cloud VMs:

- 2 cores:  5 connections
- 4 cores:  10 connections (dev default)
- 8 cores:  20 connections (prod default)
- 16 cores: 35 connections
- 32 cores: 65 connections
```

### Rationale

Each connection:

- Occupies ~1-2 MB of database memory
- Requires a PostgreSQL backend process (~5-10 MB)
- Handles one query at a time

Too small a pool → Requests queue, latency increases
Too large a pool → Wasted memory, database may struggle

### Stay under PostgreSQL `max_connections`

The total connections opened across all FraiseQL instances must stay comfortably below PostgreSQL's `max_connections` (default 100). Reserve headroom for superuser sessions, migrations, and other clients.

```sql
-- Check the server limit
SHOW max_connections;

-- Reserve some connections for superusers
SHOW superuser_reserved_connections;
```

If you run `N` application instances, then `N × (pool_size + max_overflow)` must be less than `max_connections - superuser_reserved_connections`. When that ceiling is too low for your fleet, put a connection pooler (PgBouncer) in front of PostgreSQL instead of raising `max_connections` indefinitely.

## Monitoring Pool Health

### Health Signals

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Utilization | 40-70% | 70-90% | >90% |
| Waiting Requests | 0 | 1-5 | >5 |
| Idle Connections | >0 | = 0 | - |
| Acquisition Time | < 1ms | 1-10ms | > 10ms |

### Diagnose with `pg_stat_activity`

PostgreSQL exposes live connection state in `pg_stat_activity`. Use it to see how many backends your application is actually holding and what they are doing.

```sql
-- Count connections per state for your application
SELECT state, count(*)
FROM pg_stat_activity
WHERE datname = 'mydb'
GROUP BY state
ORDER BY count(*) DESC;
```

```sql
-- Find long-running or idle-in-transaction connections
SELECT pid, state, wait_event_type, wait_event,
       now() - state_change AS time_in_state,
       left(query, 80) AS query
FROM pg_stat_activity
WHERE datname = 'mydb'
  AND state <> 'idle'
ORDER BY time_in_state DESC;
```

If you see many `idle in transaction` connections, an application code path is holding a connection without committing — that starves the pool. If `active` connections are pinned at `max_size` while requests queue, the pool is too small for the load.

### Application-side monitoring

The psycopg `AsyncConnectionPool` exposes runtime statistics. The FraiseQL app holds a single shared pool; you can read its stats for dashboards:

```python
from fraiseql.fastapi.dependencies import get_db_pool

pool = get_db_pool()
stats = pool.get_stats()  # psycopg pool statistics dict

# Useful keys include:
#   pool_size              - connections currently in the pool
#   pool_available         - idle connections ready to hand out
#   requests_waiting       - requests queued for a connection
#   requests_wait_ms       - cumulative time spent waiting
print(stats)
```

Export these into Prometheus, structured logs, or your APM of choice. A persistently non-zero `requests_waiting` is the clearest signal that the pool is undersized.

## Optimization Techniques

### 1. Keep connections warm

FraiseQL keeps a small number of connections open at startup so the first requests do not pay a cold-start penalty. For latency-sensitive services, raise the base `connection_pool_size` so the pool rarely has to open new connections under load.

**Benefit**: Eliminates cold-start latency spikes.

### 2. Recycle idle connections

`connection_pool_recycle` (default 3600s) caps how long an idle connection lives before it is replaced. This guards against connections that have been silently dropped by the database, a firewall, or PgBouncer.

```python
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    connection_pool_recycle=300,  # recycle idle connections every 5 minutes
)
```

**Benefit**: Avoids using connections the server has already closed.

### 3. Share one pool across the whole app

FraiseQL creates exactly one pool per application and shares it across all GraphQL requests. Do not create additional pools or open ad-hoc connections per request — that defeats pooling and exhausts PostgreSQL backends.

```python
# ✅ GOOD - one app, one shared pool
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    connection_pool_size=20,
)

# ❌ BAD - opening a fresh connection per request bypasses the pool
# import psycopg
# async def handler():
#     conn = await psycopg.AsyncConnection.connect("postgresql://localhost/mydb")
#     ...
```

### 4. Reduce how long each query holds a connection

A connection is held for the duration of a query. Faster queries return connections sooner, so the same pool serves more traffic.

- Push field selection into the `v_`/`tv_` view `data` JSONB so only requested fields are read.
- Add indexes that support your `WHERE` clauses and joins.
- Avoid `idle in transaction` by keeping transactions short.

**Benefit**: Higher effective throughput from the same pool size.

## Using PgBouncer

When you run many application instances, raising each pool's size eventually exhausts PostgreSQL's `max_connections`. [PgBouncer](https://www.pgbouncer.org/) sits between FraiseQL and PostgreSQL and multiplexes many client connections onto a small set of server connections.

Recommended setup:

- Run PgBouncer in **transaction pooling** mode for GraphQL workloads (a server connection is assigned per transaction, not per client session).
- Point `database_url` at PgBouncer's listen address instead of PostgreSQL directly.
- Keep FraiseQL's `connection_pool_size` modest per instance, since PgBouncer absorbs the burst.

```ini
# pgbouncer.ini
[databases]
mydb = host=127.0.0.1 port=5432 dbname=mydb

[pgbouncer]
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 25
```

```python
# Point FraiseQL at PgBouncer (default port 6432)
app = create_fraiseql_app(
    database_url="postgresql://localhost:6432/mydb",
    types=[User],
    connection_pool_size=10,
)
```

In transaction pooling mode, avoid features that require session state across statements (for example, server-side prepared statements that outlive a transaction). psycopg's defaults work well behind PgBouncer for FraiseQL's per-transaction CQRS access pattern.

## Troubleshooting

### Problem: "Too many connections" Error

**Symptom**: PostgreSQL rejects connections with `FATAL: sorry, too many clients already`, or pool acquisition times out.

**Cause**: The combined pool size across all instances exceeds PostgreSQL `max_connections`, or the pool is too small for the load.

**Solutions**:

1. **Right-size the pool** for a single instance:

   ```python
   app = create_fraiseql_app(
       database_url="postgresql://localhost/mydb",
       types=[User],
       connection_pool_size=30,
       connection_pool_max_overflow=10,
   )
   ```

2. **Reduce query latency** (slow queries hold connections longer):

   ```text
   Add database indexes
   Optimize WHERE clauses
   Keep field selection inside view JSONB
   ```

3. **Add PgBouncer** so many instances share a small set of server connections (see above), rather than raising `max_connections` without limit.

### Problem: High Latency with Low CPU Usage

**Symptom**: p95 latency > 100ms even with low CPU.

**Cause**: Connections are the bottleneck — requests are queuing for a free connection.

**Solution**: Check whether requests are waiting on the pool and whether backends are pinned:

```sql
SELECT state, count(*)
FROM pg_stat_activity
WHERE datname = 'mydb'
GROUP BY state;
```

If `active` is pinned at `max_size` and your app reports non-zero `requests_waiting`, increase `connection_pool_size` (and/or `connection_pool_max_overflow`).

### Problem: Connections Stuck "idle in transaction"

**Symptom**: `pg_stat_activity` shows many `idle in transaction` backends and the pool drains.

**Cause**: A code path opens a transaction and does not commit or roll back promptly.

**Solution**: Ensure repository calls are awaited and transactions are short. FraiseQL's repository commits per operation; custom `fn_` calls and manual transactions must complete promptly so connections return to the pool.

```sql
-- Find the offenders
SELECT pid, now() - state_change AS idle_for, left(query, 80) AS query
FROM pg_stat_activity
WHERE datname = 'mydb' AND state = 'idle in transaction'
ORDER BY idle_for DESC;
```

## Production Checklist

- [ ] Pool size configured based on core count and instance count
- [ ] `pool_size + max_overflow × instance_count` stays under PostgreSQL `max_connections`
- [ ] PgBouncer (transaction pooling) used when running many instances
- [ ] Connection recycle interval appropriate for your network/firewall
- [ ] `pg_stat_activity` and pool stats monitored / alerted on
- [ ] Load testing confirms the pool is adequate
- [ ] Alerts configured for pool exhaustion and `idle in transaction`

## Next Steps

1. **Measure your workload**: Watch `pg_stat_activity` and psycopg pool stats under real traffic.
2. **Profile queries**: Identify slow queries that hold connections too long.
3. **Optimize**: Push field selection into view JSONB and add indexes.
4. **Re-tune**: Adjust `connection_pool_size` / `connection_pool_max_overflow` based on metrics.
5. **Scale out**: Add PgBouncer before raising PostgreSQL `max_connections`.

## Related Documentation

- [Performance Guide](./performance-guide.md) - End-to-end performance tuning
- [Caching](./caching.md) - PostgreSQL-backed result caching
- [Request Flow](../architecture/request-flow.md) - How a request acquires a connection

---

**Last Updated**: 2026-06-19
**Framework**: FraiseQL over psycopg `AsyncConnectionPool`
