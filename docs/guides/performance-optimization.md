---
title: Performance & Optimization Guide
description: Comprehensive guide to optimizing FraiseQL performance for production systems.
keywords: ["debugging", "implementation", "best-practices", "deployment", "performance", "tutorial"]
tags: ["documentation", "reference"]
---

# Performance & Optimization Guide

**Status:** ✅ Production Ready
**Audience:** Backend engineers, DevOps, database administrators
**Reading Time:** 40-50 minutes

Comprehensive guide to optimizing FraiseQL performance for production systems. FraiseQL is a
Python runtime GraphQL framework for PostgreSQL served over FastAPI: queries read from `v_`/`tv_`
views, mutations call `fn_` PostgreSQL functions, and an optional Rust extension (`fraiseql_rs`)
accelerates JSON transformation on the hot path. Tuning is therefore mostly PostgreSQL tuning
plus a few framework knobs.

---

## Table of Contents

1. [Query Optimization](#query-optimization)
2. [Database Optimization](#database-optimization)
3. [Caching Strategies](#caching-strategies)
4. [Connection Pooling](#connection-pooling)
5. [Monitoring & Profiling](#monitoring--profiling)
6. [Scaling Strategies](#scaling-strategies)
7. [Common Bottlenecks](#common-bottlenecks--solutions)

---

## Query Optimization

### 1. Avoid N+1 Query Problem

❌ **Bad: per-field resolver fan-out**

```graphql
query GetUsers {
  users {
    id
    name
    # If posts are resolved with a separate per-user query, this becomes
    # 1 query for users + N queries for posts (one per user)
    posts {
      id
      title
    }
  }
}
```

Result: 101 queries (1 for users + 100 for individual user's posts)

✅ **Good: posts already nested in the view's JSONB**

```graphql
query GetUsers {
  users {
    id
    name
    posts {  # Composed in the v_user view's data JSONB — single read
      id
      title
    }
  }
}
```

Result: 1-2 queries total

The two main ways to avoid N+1 in FraiseQL:

- **Compose nested data in the view.** Build child objects directly into the parent view's
  `data` JSONB with `jsonb_build_object` / `jsonb_agg`, so a single read returns the full tree.
- **Use `@fraiseql.dataloader_field`** for computed/cross-aggregate fields that cannot be
  pre-composed — it batches the field across all parents in one round trip.

### 2. Pagination for Large Result Sets

❌ **Bad: Fetch all records**

```graphql
query AllPosts {
  posts {  # Returns 1,000,000 records!
    id
    title
    content
  }
}
```

✅ **Good: Paginate with limit/offset or cursor**

```graphql
query PostsPaginated($first: Int!, $after: String) {
  posts(first: $first, after: $after) {
    edges {
      cursor
      node { id title }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

### 3. Request Only Needed Fields

❌ **Bad: Over-fetching**

```graphql
query GetUser {
  user(id: "123") {
    id
    email
    full_name
    phone
    address
    payment_methods
    all_orders { id amount date }  # Fetch everything
    all_reviews { id rating text }
  }
}
```

✅ **Good: Specific fields**

```graphql
query GetUser {
  user(id: "123") {
    id
    email
    full_name
    recent_orders(limit: 5) {
      id
      amount
    }
  }
}
```

FraiseQL's `fraiseql_rs` extension performs field selection on the view's `data` JSONB at
runtime, so requesting fewer fields means less JSON is transformed and serialized.

### 4. Use Database Indexes

```sql
-- ✅ Good: Indexes on common filters
CREATE INDEX idx_user_email ON tb_user(email);
CREATE INDEX idx_order_date ON tb_order(created_at);
CREATE INDEX idx_user_status ON tb_user(status);

-- For complex queries:
CREATE INDEX idx_orders_user_date ON tb_order(fk_user, created_at);

-- For full-text search:
CREATE INDEX idx_content_search ON tb_document USING GIN(to_tsvector('english', content));

-- For filtering inside a view's data JSONB:
CREATE INDEX idx_user_data ON tb_user USING GIN(data jsonb_path_ops);
```

**Index Selection:**

- Filter columns: Yes (WHERE clause)
- Join columns: Yes (ON clause)
- Order columns: Yes (ORDER BY)
- Covering index: Include other columns for "index-only" scans

### 5. Explain Query Plans

```sql
EXPLAIN ANALYZE
SELECT u.id, u.email, COUNT(o.id)
FROM tb_user u
LEFT JOIN tb_order o ON u.pk_user = o.fk_user
WHERE u.status = 'active'
GROUP BY u.id, u.email
ORDER BY u.email;

-- Output shows:
-- - Sequential Scan vs Index Scan
-- - Rows filtered
-- - Actual runtime
-- - Inefficiencies (full table scans, etc.)
```

---

## Database Optimization

### 1. Connection Pooling

FraiseQL uses a psycopg async connection pool. Size it through `create_fraiseql_app` kwargs
(or the equivalent `FraiseQLConfig` fields / `FRAISEQL_*` env vars):

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    connection_pool_size=10,          # connections per app instance
    connection_pool_max_overflow=10,  # burst capacity above the base size
    connection_pool_timeout=5.0,      # seconds to wait for a free connection
    connection_pool_recycle=1800,     # recycle a connection after 30 min
)

# For 100 concurrent users:
# Pool size = 10-20 (not 100!)
# Each connection can handle multiple queries sequentially
```

### 2. Query Result Caching

FraiseQL ships a PostgreSQL-backed result cache in `fraiseql.caching`. Wrap the repository with
`CachedRepository`; query results are cached and invalidated via cascade rules derived from your
schema. See the [Caching Strategies](#caching-strategies) section below for the full setup.

```python
from fraiseql.caching import (
    PostgresCache,
    ResultCache,
    CacheConfig,
    CachedRepository,
)

# Build a result cache over the PostgreSQL UNLOGGED cache table
backend = PostgresCache(connection_pool=pool)
await backend.initialize()
cache = ResultCache(backend, CacheConfig(default_ttl=300))  # 5 minutes

# Wrap the repository — find()/find_one() now read through the cache
cached_repo = CachedRepository(base_repository=repo, cache=cache)

# Per-query control is available on the call itself
await cached_repo.find("v_user", skip_cache=False, cache_ttl=600)
```

### 3. Materialized Views for Aggregations

```sql
-- Pre-compute expensive aggregations
CREATE MATERIALIZED VIEW user_stats AS
SELECT
  fk_user,
  COUNT(*) as total_orders,
  SUM(amount) as total_spent,
  AVG(amount) as avg_order_value,
  MAX(created_at) as last_order_date
FROM tb_order
GROUP BY fk_user;

-- Refresh hourly
SELECT cron.schedule('refresh_user_stats', '0 * * * *',
  'REFRESH MATERIALIZED VIEW CONCURRENTLY user_stats');

-- Query materialized view (fast)
SELECT * FROM user_stats WHERE fk_user = $1;
```

For nested reads, the same idea applies to `tv_` projection views — real tables holding
pre-composed `data` JSONB, refreshed by `fn_` functions or triggers.

### 4. Partitioning Large Tables

```sql
-- Time-based partitioning for time-series data
CREATE TABLE tb_event (
  event_date DATE NOT NULL,
  pk_event BIGSERIAL,
  fk_user BIGINT,
  event_type VARCHAR(50),
  PRIMARY KEY (event_date, pk_event)
) PARTITION BY RANGE (event_date);

-- Create partitions
CREATE TABLE tb_event_2024_01 PARTITION OF tb_event
  FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE TABLE tb_event_2024_02 PARTITION OF tb_event
  FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

-- Queries automatically scan only relevant partitions
SELECT * FROM tb_event
WHERE event_date BETWEEN '2024-01-15' AND '2024-01-20';
-- Only queries tb_event_2024_01 partition
```

### 5. Denormalization When Needed

```sql
-- Denormalized user_stats table avoids expensive joins
CREATE TABLE tb_user_stats (
  fk_user BIGINT PRIMARY KEY,
  email VARCHAR(255),
  full_name VARCHAR(255),
  total_orders INT,
  total_spent DECIMAL(12, 2),
  last_order_date DATE,
  updated_at TIMESTAMP
);

-- Update on order changes
CREATE TRIGGER order_update_stats
AFTER INSERT OR UPDATE ON tb_order
FOR EACH ROW
EXECUTE FUNCTION fn_update_user_stats(NEW.fk_user);
```

---

## Caching Strategies

FraiseQL's result cache lives in `fraiseql.caching`. It is **PostgreSQL-backed** — results are
stored in an UNLOGGED cache table (no extra infrastructure) and invalidated automatically through
cascade rules derived from your GraphQL schema relationships.

### 1. Cache Layers

```text
┌─────────────────┐
│   Client Cache  │  (your GraphQL client / browser)
└────────┬────────┘
         ↓
┌─────────────────┐
│ ResultCache     │  (CachedRepository wrapping the CQRS repo)
└────────┬────────┘
         ↓
┌─────────────────┐
│ PostgresCache   │  (UNLOGGED fraiseql_cache table, shared across instances)
└────────┬────────┘
         ↓
┌─────────────────┐
│   Database      │  (v_/tv_ views — slowest path)
└─────────────────┘
```

### 2. Setting Up the Result Cache

```python
from fraiseql.caching import PostgresCache, ResultCache, CacheConfig, CachedRepository

# 1. PostgreSQL-backed backend (shared by all app instances)
backend = PostgresCache(connection_pool=pool, table_name="fraiseql_cache")
await backend.initialize()  # creates the UNLOGGED table + expiry index

# 2. Result cache with TTL policy
cache = ResultCache(
    backend,
    CacheConfig(
        enabled=True,
        default_ttl=300,   # 5 minutes
        max_ttl=3600,      # 1 hour ceiling
        key_prefix="fraiseql",
    ),
)

# 3. Wrap the repository — reads now go through the cache
cached_repo = CachedRepository(base_repository=repo, cache=cache)
```

### 3. Automatic Cascade Invalidation

Instead of hand-written invalidation, let FraiseQL derive invalidation rules from your schema:

```python
from fraiseql.caching import setup_auto_cascade_rules

# During app startup, analyze the schema and register CASCADE rules
# so writes to a parent automatically invalidate dependent cached reads.
n_rules = await setup_auto_cascade_rules(backend, app.schema, verbose=True)
```

You can also declare rules explicitly with `CascadeRule`, or bypass/override the cache per call
via `find(..., skip_cache=True)` / `find(..., cache_ttl=600)`.

### 4. Caching a Single Resolver

For a one-off expensive resolver, `cached_query` memoizes the result on a cache instance:

```python
from fraiseql.caching import cached_query

@cached_query(cache, ttl=300)
async def expensive_user_stats(info, user_id: ID) -> UserStats:
    db = info.context["db"]
    return await db.find_one("v_user_stats", id=user_id)
```

---

## Connection Pooling

### Configuration

Configure the pool in code via `create_fraiseql_app` kwargs, or with `FRAISEQL_*` environment
variables / a `FraiseQLConfig` instance:

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    connection_pool_size=20,          # base connections
    connection_pool_max_overflow=10,  # burst above the base size
    connection_pool_timeout=10.0,     # seconds to wait for a connection
    connection_pool_recycle=1800,     # recycle connections after 30 min
)
```

Equivalent environment variables (consumed by `FraiseQLConfig`):

```bash
FRAISEQL_DATABASE_URL=postgresql://localhost/mydb
FRAISEQL_DATABASE_POOL_SIZE=20
FRAISEQL_DATABASE_POOL_TIMEOUT=10
FRAISEQL_DATABASE_POOL_RECYCLE=1800
```

### Tuning

```text
Pool Size Formula:
  = ((core_count × 2) + effective_spindle_count)
  = ((8 cores × 2) + 1) = 17 connections

Concurrency = Pool Size × Average Query Time
  = 20 connections × 50ms = 1000 concurrent requests
```

### Monitoring

```sql
-- Check pool usage
SELECT count(*) FROM pg_stat_activity;
-- Should be <= pool_size (20)

-- Identify slow/idle connections
SELECT pid, usename, state, query, query_start
FROM pg_stat_activity
WHERE state = 'idle'
  AND query_start < NOW() - INTERVAL '15 minutes';
```

---

## Monitoring & Profiling

### Query Performance Metrics

```python
import time

import fraiseql

# Instrument a resolver with timing
@fraiseql.query
async def posts(info, limit: int = 50) -> list[Post]:
    start = time.time()

    db = info.context["db"]
    results = await db.find("v_post", limit=limit)

    duration = time.time() - start
    log_metric("query.duration", duration, tags={"query": "posts"})

    return results
```

### Slow Query Log

```sql
-- Enable slow query logging
ALTER SYSTEM SET log_min_duration_statement = 100;  -- Log queries > 100ms
SELECT pg_reload_conf();

-- View slow queries
SELECT * FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 20;
```

### APM Integration (DataDog/New Relic)

```python
from datadog_api_client.v1.api.metrics_api import MetricsApi
from datadog_api_client.v1.model.metrics_payload import MetricsPayload
from datadog_api_client.v1.model.series import Series

# Report query metrics
metrics_api.submit_metrics(
    body=MetricsPayload(
        series=[
            Series(
                metric="fraiseql.query.duration",
                points=[[int(time.time()), query_duration_ms]],
                tags=["query:posts", "endpoint:graphql"],
            )
        ]
    )
)
```

---

## Scaling Strategies

### Vertical Scaling (More Powerful Hardware)

✅ **When:**

- Single database is bottleneck
- Cost-effective up to ~200GB data
- Complex queries needing more CPU/RAM

### Horizontal Scaling (Multiple Servers)

Run several copies of the FastAPI app (for example `uvicorn app:app` behind a process manager
or in multiple containers) behind a load balancer, all sharing one PostgreSQL database:

```text
┌──────────────────────────────────────┐
│        Load Balancer (nginx)         │
└──────────────┬───────────────────────┘
               │
    ┌──────────┼──────────┐
    ↓          ↓          ↓
┌─────────┐┌─────────┐┌─────────┐
│ FastAPI ││ FastAPI ││ FastAPI │
│ (uvicorn)│(uvicorn)│(uvicorn)│
└────┬────┘└────┬────┘└────┬────┘
     │          │          │
     └──────────┼──────────┘
                ↓
        ┌──────────────┐
        │ PostgreSQL   │
        │ (Shared DB)  │
        └──────────────┘
```

### Read Replicas

```text
-- Primary for writes
PRIMARY (writes)
  ↓ (replication)
REPLICA 1 (reads)
REPLICA 2 (reads)
REPLICA 3 (reads)
```

FraiseQL's CQRS split maps naturally onto read replicas: mutations call `fn_` functions and must
hit the primary, while `@query` reads of `v_`/`tv_` views can target a replica. A common pattern
is to run a read-only app instance whose `database_url` points at a replica (queries only), and a
write instance pointed at the primary, fronted by your load balancer or router:

```python
from fraiseql.fastapi import create_fraiseql_app

# Read-only instance — queries served from a replica
read_app = create_fraiseql_app(
    database_url="postgresql://postgres_replica/mydb",
    types=[User],
    queries=[users, user],
)

# Write instance — mutations served from the primary
write_app = create_fraiseql_app(
    database_url="postgresql://postgres_primary/mydb",
    types=[User],
    mutations=[create_user],
)
```

### Citus for Sharding

```sql
-- Distribute table across nodes
SELECT create_distributed_table('tb_order', 'fk_user');

-- Queries automatically sharded
SELECT * FROM tb_order WHERE fk_user = $1;  -- Single shard
SELECT * FROM tb_order;  -- All shards (parallel)
```

---

## Common Bottlenecks & Solutions

| Symptom | Cause | Solution |
|---------|-------|----------|
| High CPU | Complex queries, missing indexes | Add indexes, optimize queries |
| High Memory | Large result sets | Paginate, limit results |
| Slow responses | N+1 queries | Use nested queries, batch requests |
| Connection errors | Pool exhausted | Increase pool size, optimize query time |
| Disk I/O | No indexes on filters | Create indexes |
| Network latency | Geographic distance | Use CDN, edge servers |
| Cache misses | Low TTL | Increase TTL for stable data |

---

## Performance Benchmarking

### Benchmark Suite

```typescript
import Benchmark from 'benchmark';

const suite = new Benchmark.Suite;

suite
  .add('Simple query (1KB result)', () => {
    return client.query(GET_USER);
  })
  .add('Complex query (100KB result)', () => {
    return client.query(GET_POSTS_WITH_COMMENTS);
  })
  .add('Aggregation query', () => {
    return client.query(GET_STATS);
  })
  .on('complete', function() {
    console.log('Fastest is ' + this.filter('fastest').map('name'));
  })
  .run({ async: true });
```

### Load Testing

```bash
# Using Apache Bench against the running FastAPI app
ab -n 10000 -c 100 http://localhost:8000/graphql

# Results:
# Requests per second: 500
# 95th percentile latency: 200ms
# Max latency: 1000ms
```

---

## Best Practices Checklist

- [ ] Indexes on all filter/join/sort columns
- [ ] Query result pagination for large datasets
- [ ] Nested queries instead of N+1
- [ ] Connection pooling configured
- [ ] Slow query logging enabled
- [ ] Cache strategies implemented
- [ ] Read replicas for heavy read workloads
- [ ] Monitoring/alerting in place
- [ ] Load testing before production
- [ ] Database statistics up-to-date (`ANALYZE`)

---

## See Also

**Related Guides:**

- [Schema Design Best Practices](./schema-design-best-practices.md)
- [Production Deployment](./production-deployment.md)
- [Observability & Monitoring](./observability.md)

**Production Patterns:**

- [Analytics Platform](../patterns/analytics-olap-platform.md) - Optimize for aggregations
- [SaaS Multi-Tenant](../patterns/saas-multi-tenant.md) - Row-level security performance
