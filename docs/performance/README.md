---

title: Performance Overview
description: Index to FraiseQL v1 performance guides — PostgreSQL tuning, caching, connection pooling, the optional Rust JSON pipeline, and APQ.
keywords: ["performance"]
tags: ["documentation", "reference"]
---

# Performance Tuning Guide

**Status**: Production Ready
**Last Updated**: 2026-06-19

FraiseQL v1 is a Python runtime GraphQL framework for PostgreSQL, served over
FastAPI. The schema is built in memory at app startup — there is no build or
compile step. Performance work therefore lives in three places:

1. **PostgreSQL** — your `v_`/`tv_` views, indexes, and `fn_` functions do the
   heavy lifting. Most latency wins come from good view and index design.
2. **The runtime** — psycopg connection pooling, query-result caching, and the
   optional `fraiseql_rs` Rust extension that accelerates JSON transformation on
   the hot path.
3. **The GraphQL surface** — Automatic Persisted Queries (APQ), field selection,
   pagination, and N+1 prevention.

This page is an index. Pick a guide below based on what you want to tune.

## Where to Start

| You want to… | Read |
|---|---|
| Get a broad tour of every performance feature | [Performance Guide](./performance-guide.md) |
| Speed up reads with query-result caching | [Caching](./caching.md) |
| Tune the PostgreSQL connection pool | [Connection Pool Tuning](./connection-pool-tuning.md) |
| Cut parsing/transport cost on hot queries | [APQ Optimization Guide](./apq-optimization-guide.md) |
| Understand the Rust JSON pipeline | [Rust Pipeline Optimization](./rust-pipeline-optimization.md) |
| Measure before/after changes | [Benchmarking Guide](./benchmarking-guide.md) |

## Performance Levers in v1

| Lever | What it does | Where to tune it |
|---|---|---|
| **PostgreSQL views + indexes** | Pre-compose nested data as JSONB in `v_`/`tv_` views; index filtered columns | Your database schema |
| **Query-result caching** | PostgreSQL-backed `ResultCache` with cascade invalidation | [Caching](./caching.md) |
| **Connection pooling** | psycopg pool reuses connections; tunable size/overflow/timeout/recycle | [Connection Pool Tuning](./connection-pool-tuning.md) |
| **`fraiseql_rs` JSON pipeline** | 7-10x faster JSON transform / field selection vs pure Python | [Rust Pipeline Optimization](./rust-pipeline-optimization.md) |
| **APQ** | Persist queries by hash so clients send a short ID, not the full query text | [APQ Optimization Guide](./apq-optimization-guide.md) |

## Quick Start

Performance-relevant settings are passed to `create_fraiseql_app(...)` (or set
via `FraiseQLConfig` / `FRAISEQL_` environment variables). There is no config
file and no separate server binary — you run the FastAPI app with `uvicorn`.

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    production=True,                 # disables the playground, tightens errors
    connection_pool_size=20,         # → FraiseQLConfig.database_pool_size
    connection_pool_max_overflow=10, # → FraiseQLConfig.database_pool_max_overflow
    connection_pool_timeout=30,      # → FraiseQLConfig.database_pool_timeout
    connection_pool_recycle=1800,    # → FraiseQLConfig.database_pool_recycle
)
```

```bash
# Run it
uvicorn app:app --host 0.0.0.0 --port 8000
```

## By Use Case

### Development / Testing

- A small pool is plenty: `connection_pool_size=5`.
- Leave caching off while you iterate on schema and views.
- Use `production=False` to keep the GraphQL playground available.

### Staging / Pre-Production

- Raise the pool toward your expected concurrency (`connection_pool_size=20`).
- Run a load test and watch pool utilization (see
  [Connection Pool Tuning](./connection-pool-tuning.md)).
- Turn on query-result caching for hot read paths and validate invalidation
  behaviour (see [Caching](./caching.md)).

### Production / Scale

- Size the pool from your worker/CPU count and database `max_connections`.
- Enable caching with cascade invalidation rules for expensive reads.
- Register hot queries with APQ to drop request payload size and parse cost.
- Keep the `fraiseql_rs` extension installed for the fast JSON path.

## Tuning Checklist

### Database

- [ ] `v_`/`tv_` views pre-compose nested data as a `data` JSONB column
- [ ] Indexes exist on every filtered/joined column (and on `id`)
- [ ] Heavy nested reads use `tv_` projection tables refreshed by functions/triggers
- [ ] `EXPLAIN ANALYZE` confirms index usage on your hottest queries

### Runtime

- [ ] Connection pool sized for your concurrency, not left at the default
- [ ] Query-result caching enabled for expensive, cache-friendly reads
- [ ] Cascade invalidation rules cover the tables behind cached views
- [ ] `fraiseql_rs` installed (verify the fast JSON path is active)

### GraphQL Surface

- [ ] APQ enabled for repeated client queries
- [ ] Clients select only the fields they need (field selection is pushed down)
- [ ] Large result sets are paginated
- [ ] N+1 fields use `@fraiseql.dataloader_field`

## Diagnosing Slow Queries

1. **Find the slow SQL.** PostgreSQL `pg_stat_statements` shows the worst
   offenders:

   ```sql
   SELECT query, calls, mean_exec_time
   FROM pg_stat_statements
   WHERE mean_exec_time > 100
   ORDER BY mean_exec_time DESC
   LIMIT 20;
   ```

2. **Check the plan.** Run `EXPLAIN ANALYZE` on the underlying view query and
   confirm indexes are used instead of sequential scans:

   ```sql
   EXPLAIN ANALYZE
   SELECT data FROM v_user WHERE id = '...'::uuid;
   ```

3. **Check the pool.** Connection saturation shows up as latency variance under
   load. See [Connection Pool Tuning](./connection-pool-tuning.md) for sizing,
   monitoring, and exhaustion symptoms.

4. **Check the cache.** If a hot read is uncached or invalidating too
   aggressively, the [Caching](./caching.md) guide covers `ResultCache`,
   `CacheConfig`, and cascade rules.

## All Performance Guides

- [Performance Guide](./performance-guide.md) — broad tour of v1 performance features
- [Caching](./caching.md) — PostgreSQL-backed query-result caching and cascade invalidation
- [Caching Migration](./caching-migration.md) — moving to the caching API
- [Server Cache Invalidation](./server-cache-invalidation.md) — invalidation patterns
- [Connection Pool Tuning](./connection-pool-tuning.md) — psycopg pool sizing and monitoring
- [Rust Pipeline Optimization](./rust-pipeline-optimization.md) — the optional `fraiseql_rs` JSON path
- [Benchmarking Guide](./benchmarking-guide.md) — how to measure FraiseQL performance
- [APQ Assessment](./apq-assessment.md) — when Automatic Persisted Queries help
- [APQ Optimization Guide](./apq-optimization-guide.md) — configuring and tuning APQ
- [Coordinate Performance Guide](./coordinate-performance-guide.md) — tuning coordinate/geo queries
- [Index](./index.md) — performance section landing page

## External Resources

- [PostgreSQL Performance Optimization](https://wiki.postgresql.org/wiki/Performance_Optimization) — database tuning
- [PostgreSQL Performance Tips](https://www.postgresql.org/docs/current/performance-tips.html) — query planning
- [GraphQL Best Practices](https://graphql.org/learn/best-practices/) — query design

## FAQ

**Q: Is there a build/compile step to optimize?**
A: No. FraiseQL v1 builds its schema in memory at app startup. All optimization
is runtime: PostgreSQL views/indexes, caching, the connection pool, the
`fraiseql_rs` JSON path, and APQ.

**Q: What does the Rust extension do?**
A: `fraiseql_rs` accelerates JSON transformation and field selection on the hot
path (roughly 7-10x faster than pure Python for that step). It is an optional
acceleration, not a separate architecture. See
[Rust Pipeline Optimization](./rust-pipeline-optimization.md).

**Q: How do I tune the connection pool?**
A: Pass `connection_pool_size`, `connection_pool_max_overflow`,
`connection_pool_timeout`, and `connection_pool_recycle` to
`create_fraiseql_app(...)` (they map to `FraiseQLConfig.database_pool_*`). Size
the pool for your concurrency; see
[Connection Pool Tuning](./connection-pool-tuning.md).

**Q: Where does caching live?**
A: It is PostgreSQL-backed query-result caching (`ResultCache`, `CacheConfig`,
cascade invalidation). See [Caching](./caching.md).

**Q: My queries are slow — where do I look first?**
A: Start in PostgreSQL: `pg_stat_statements` and `EXPLAIN ANALYZE` on the
underlying view. Most latency comes from view/index design, not from FraiseQL.

---

**Next**: Pick a guide based on what you're tuning:

- **Reads slow?** Start with the [Performance Guide](./performance-guide.md) and your view indexes
- **High concurrency?** Read [Connection Pool Tuning](./connection-pool-tuning.md)
- **Repeated expensive reads?** Read [Caching](./caching.md)
- **Lots of repeat client queries?** Read the [APQ Optimization Guide](./apq-optimization-guide.md)
