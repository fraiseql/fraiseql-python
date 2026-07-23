# FraiseQL Performance Guide

🟡 **Production** - Performance expectations, methodology, and optimization guidance.


## Executive Summary

FraiseQL is a Python runtime GraphQL framework for PostgreSQL. It delivers fast response times for typical GraphQL queries by pushing data shaping into PostgreSQL (views return a `data` JSONB column) and serving that JSON over FastAPI. An optional Rust extension (`fraiseql_rs`) accelerates JSON transformation on the hot path — field selection, camelCase conversion, and `__typename` injection — so most queries avoid heavy Python string work.

This guide provides realistic performance expectations, methodology details, and guidance on when performance optimizations matter.

**Key Takeaways:**

- **Typical queries**: 5-25ms response time (including database)
- **Optimized queries**: 0.5-5ms response time (with caching and table views active)
- **Cache hit rates**: 85-95% in production applications with stable query patterns
- **Architecture**: PostgreSQL (`v_`/`tv_` views → `data` JSONB) → FastAPI, with optional `fraiseql_rs` JSON acceleration

---

## Performance Claims & Methodology

### Claim: "Fast typical-query latency"

**What this means**: FraiseQL keeps end-to-end latency low for typical workloads because PostgreSQL does the joins and JSON composition once (in a `v_`/`tv_` view), and FraiseQL streams the resulting `data` JSONB to the client with minimal transformation.

**Methodology**:

- **Test queries**: Simple user lookup, nested user+posts, filtered searches
- **Dataset**: 10k-100k records in PostgreSQL 15+
- **Hardware**: Standard cloud instances (4 CPU, 8GB RAM)
- **Measurement**: End-to-end response time including the database query

**Realistic expectations**:

- **Simple queries** (single view): a few milliseconds plus database time
- **Complex queries** (nested data via `tv_` projection views): comparable, because the view is pre-composed
- **Cached queries**: sub-millisecond when served from APQ and/or result cache
- **JSON transformation**: handled by `fraiseql_rs` when available (Python fallback otherwise)

**When this matters**: High-throughput APIs (>100 req/sec) where small latency improvements compound.

---

### Claim: "Sub-millisecond cached responses (0.5-2ms)"

**What this means**: Cached GraphQL queries return in roughly 0.5-2ms when the response is served from cache and JSON transformation is accelerated.

**Methodology**:

- **APQ (Automatic Persisted Queries)**: SHA-256 hash lookup; the persisted query is recognized without re-parsing the full document
- **Result cache** (`fraiseql.caching`): cached query results keyed by query + variables, optionally backed by PostgreSQL
- **JSON transformation**: database `data` JSONB → field-selected response, accelerated by `fraiseql_rs`
- **Measurement**: Time from GraphQL request to HTTP response (excluding network latency)

**Realistic expectations**:

- **Cache hit**: 0.5-2ms
- **Cache miss**: 5-25ms (includes the database query)
- **Cache hit rate**: 85-95% in production applications with stable queries

**Conditions**:

- PostgreSQL 15+ with proper indexing
- APQ enabled (`apq_mode="optional"` or `"required"`); PostgreSQL storage backend recommended for multi-instance deployments
- Result cache configured for the hot queries
- Query complexity within configured limits
- Response size modest (< ~50KB)

---

### Claim: "85-95% cache hit rates in production applications"

**What this means**: Well-designed applications with stable query shapes achieve 85-95% APQ hit rates.

**Methodology**:

- **Client configuration**: a GraphQL client with persisted queries enabled (e.g. Apollo Client)
- **Query patterns**: stable query structure (no dynamic field selection)
- **Cache TTL**: 1-24 hours depending on data-freshness requirements
- **Measurement**: cache hits / (cache hits + cache misses) over a 24-hour period

**Realistic expectations**:

- **Stable APIs**: 95%+ hit rate
- **Dynamic queries**: 80-90% hit rate
- **Admin interfaces**: 70-85% hit rate (more unique queries)

**Factors affecting hit rate**:

- Query stability (fewer unique queries = higher hit rate)
- Client-side query deduplication
- Cache TTL settings
- Query complexity (simple queries cache better)

---

### Claim: "0.05-0.5ms table view responses"

**What this means**: Table-backed projection views (`tv_*`) hold pre-composed `data` JSONB, so reads that would otherwise require multi-table JOINs become a single indexed lookup.

**Methodology**:

- **Table views**: real tables holding pre-composed JSONB, refreshed by functions/triggers
- **Comparison**: traditional JOIN-at-query-time vs `tv_` lookup
- **Dataset**: 10k users with 50k posts (average 5 posts/user)
- **Measurement**: database query time only (`EXPLAIN ANALYZE`)

**Realistic expectations**:

- **`tv_` lookup**: 0.05-0.5ms (single indexed row read of pre-composed JSONB)
- **Traditional JOIN**: 5-50ms (depends on data size)
- **Speedup**: 10-100x faster for complex nested queries
- **JSON transformation**: camelCase conversion and `__typename` injection handled on the hot path (accelerated by `fraiseql_rs`)

**When this applies**:

- Read-heavy workloads with stable data relationships
- Queries with fixed nesting patterns
- Applications where data freshness can tolerate the `tv_` refresh cadence

---

## Typical vs Optimal Scenarios

### Typical Production Application (85th percentile)

**Response Times**:

- Simple queries: 1-5ms
- Complex queries: 5-25ms
- Cached queries: 0.5-2ms

**Configuration**:

```python
from fraiseql.fastapi import create_fraiseql_app

# Standard production setup
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User, Post],
    queries=[users, user],
    mutations=[create_user],
    production=True,
    connection_pool_size=20,
)
```

APQ and complexity limits are configured via `FraiseQLConfig` (or `FRAISEQL_` environment variables):

```python
from fraiseql.fastapi import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    apq_mode="optional",                 # accept persisted-query hashes
    apq_storage_backend="postgresql",    # share APQ across instances
    complexity_enabled=True,
    complexity_max_score=1000,
    cache_ttl=300,                       # result-cache TTL (seconds)
)
```

**Performance Characteristics**:

- Cache hit rate: 85-95%
- Database load: moderate (most queries cached)
- Memory usage: 200-500MB per instance
- CPU usage: 20-40% under normal load

### High-Performance Optimized Application (99th percentile)

**Response Times**:

- Simple queries: 0.5-2ms
- Complex queries: 2-10ms
- Cached queries: 0.2-1ms

**Configuration**:

```python
from fraiseql.fastapi import FraiseQLConfig

# Maximum performance setup
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    apq_mode="required",                 # only accept persisted queries
    apq_storage_backend="postgresql",
    complexity_enabled=True,
    complexity_max_score=500,            # reject expensive queries earlier
    cache_ttl=600,
)
```

**Performance Characteristics**:

- Cache hit rate: 95%+
- Database load: low (extensive caching, `tv_` projection views)
- Memory usage: 500MB-1GB per instance
- CPU usage: 10-30% under normal load

---

## Query Complexity Impact

### Complexity Scoring

FraiseQL calculates query complexity to reject expensive operations before they hit PostgreSQL. The scorer combines field count, nesting depth, list sizes, and per-field multipliers; it is controlled by `complexity_*` settings on `FraiseQLConfig`:

```python
from fraiseql.fastapi import FraiseQLConfig

config = FraiseQLConfig(
    complexity_enabled=True,
    complexity_max_score=1000,
    complexity_max_depth=10,
    complexity_default_list_size=10,
    complexity_field_multipliers={
        "search": 5,      # text search operations
        "aggregate": 10,  # COUNT, SUM, AVG operations
        "sort": 2,        # ORDER BY clauses
    },
)
```

### Performance by Complexity

| Complexity Score | Response Time | Use Case | Optimization Priority |
|------------------|---------------|----------|----------------------|
| 1-50 | 0.5-2ms | Simple lookups | Low |
| 51-200 | 2-10ms | Nested data | Medium |
| 201-500 | 10-50ms | Complex aggregations | High |
| 501-1000 | 50-200ms | Heavy computations | Critical |
| 1000+ | 200ms+ | Rejected | N/A |

### Optimization Strategies by Complexity

**Low Complexity (1-50)**:

- Focus on caching (APQ + result caching)
- Use `tv_` table views for instant responses

**Medium Complexity (51-200)**:

- `tv_` table views for nested relationships
- Index the columns your views filter and sort on
- Result caching via `fraiseql.caching`

**High Complexity (201-500)**:

- Materialized views or `tv_` projection tables for aggregations
- Pre-compute heavy aggregates in the view, refresh on a schedule
- Result caching with a short TTL
- Keep the JSONB payload in `tv_` rows lean

---

## When Performance Matters

### 🚀 Performance-Critical Scenarios

**Reach for the optimizations above when you need**:

1. **High-throughput APIs** (>500 req/sec per instance)
   - Small latency improvements compound significantly
   - 1ms saved = 500ms saved per 500 requests/second

2. **Real-time applications** (chat, gaming, live dashboards)
   - Low response times enable real-time UX
   - WebSocket subscriptions via `@fraiseql.subscription`

3. **Mobile applications** (limited bandwidth, battery)
   - APQ cuts request payload size for repeated queries
   - Faster responses improve mobile UX

4. **Aggregation-heavy reads**
   - Pre-compose nested data in `tv_` views instead of joining at query time
   - Runtime auto-aggregation derives `GROUP BY` SQL from the requested fields

### 📊 Performance-Neutral Scenarios

**FraiseQL works well without heavy tuning for**:

1. **CRUD applications** (admin panels, CMS)
   - Standard 5-25ms response times are acceptable
   - Developer productivity benefits outweigh raw performance

2. **Internal APIs** (company dashboards, tools)
   - Predictable performance with caching
   - Operational simplicity valuable

3. **Prototyping/MVPs**
   - Fast time-to-market
   - Good enough performance for early users

### ⚠️ Performance-Challenging Scenarios

**Consider specialized infrastructure when**:

1. **Ultra-low latency** (< 1ms required end-to-end)
   - Dedicated C/Rust services for extreme cases
   - In-memory stores for the hottest paths

2. **Massive scale** (> 10,000 req/sec)
   - Read replicas and horizontal scaling of the FastAPI app
   - PgBouncer in front of PostgreSQL

3. **Heavy analytical computations**
   - External compute (Spark, Ray) feeding a `tv_` table
   - Pre-aggregate into projection tables on a schedule

---

## Design Notes: Why PostgreSQL-First Is Fast

FraiseQL's performance comes from where the work happens, not from a runtime translation layer:

- **Composition in the database.** A read view (`v_`) builds the response shape with `jsonb_build_object(...)`, so the GraphQL response is essentially a single `data` JSONB column. No ORM hydration, no N+1 join walking in Python.
- **Projection tables for heavy reads.** A `tv_` table holds pre-composed JSONB, refreshed by functions/triggers. Expensive nested reads collapse to one indexed row lookup.
- **JSONB + GIN.** Filtering inside the JSONB payload is backed by PostgreSQL's native JSONB operators and GIN indexes (see Indexing below).
- **Minimal Python on the hot path.** Field selection, camelCase conversion, and `__typename` injection are applied to the JSONB before it goes out; `fraiseql_rs` accelerates this transformation when the extension is installed, with a pure-Python fallback otherwise.
- **Caching layers.** APQ avoids re-parsing persisted queries, and the `fraiseql.caching` result cache returns prior results without touching PostgreSQL.

There is no compile step and no separate query engine — the schema is assembled in memory at app startup and served by FastAPI.

---

## Caching

FraiseQL ships a PostgreSQL-backed result cache in `fraiseql.caching`. The public API:

| Object | Purpose |
|--------|---------|
| `PostgresCache` | Cache backend that stores results in a PostgreSQL table |
| `ResultCache` | Result-caching engine (`get_or_set`, key building, stats) |
| `CacheConfig` | TTL / prefix / error-caching settings for `ResultCache` |
| `CachedRepository` | Wraps the CQRS repository to cache `find`/`find_one` reads |
| `cached_query` | Decorator to cache a resolver's result |
| `CascadeRule` / `setup_auto_cascade_rules` | Invalidate dependent cache entries on writes |
| `SchemaAnalyzer` | Derives cascade rules from your schema |
| `CacheKeyBuilder`, `CacheStats`, `CacheBackend` | Key generation, hit/miss stats, backend protocol |

Minimal setup using the PostgreSQL backend and a result cache:

```python
from psycopg_pool import AsyncConnectionPool

from fraiseql.caching import (
    CachedRepository,
    CacheConfig,
    PostgresCache,
    ResultCache,
    cached_query,
)

pool = AsyncConnectionPool("postgresql://localhost/mydb")

backend = PostgresCache(connection_pool=pool, table_name="fraiseql_cache")
cache = ResultCache(backend, CacheConfig(default_ttl=300, max_ttl=3600))


@cached_query(cache, ttl=600)
async def expensive_report(info) -> list[Report]:
    db = info.context["db"]
    return await db.find("v_report")
```

To cache repository reads transparently, wrap the repository with `CachedRepository`. To keep cached data fresh, register `CascadeRule`s (or call `setup_auto_cascade_rules`) so that a write through a `fn_` mutation invalidates the cache entries it affects.

---

## Hardware & Configuration Impact

### Recommended Hardware

**Development**:

- 2-4 CPU cores
- 4-8GB RAM
- Standard SSD storage

**Production (per instance)**:

- 4-8 CPU cores
- 8-16GB RAM
- Fast SSD storage
- Storage for the result cache / APQ table in PostgreSQL

### PostgreSQL Configuration

```sql
-- Recommended starting points for FraiseQL (tune per workload)
shared_buffers = 256MB           -- ~25% of RAM
effective_cache_size = 1GB       -- ~75% of RAM
work_mem = 16MB                  -- per-operation sort/hash memory
max_connections = 100            -- size with the connection pool in mind
statement_timeout = 5000         -- prevent runaway queries (ms)
```

### Indexing

Index the columns your `v_`/`tv_` views filter, join, and sort on. For JSONB filtering, use GIN indexes:

```sql
-- B-tree on the public id used for WHERE id = $1
CREATE INDEX idx_v_user_id ON tb_user (id);

-- GIN index on the JSONB data column for containment / key lookups
CREATE INDEX idx_v_user_data ON tb_user USING gin (data jsonb_path_ops);

-- Expression index on a frequently filtered JSONB key
CREATE INDEX idx_v_user_email ON tb_user ((data ->> 'email'));
```

Use `jsonb_path_ops` GIN indexes for `@>` containment queries; use a default GIN index when you also need key-existence operators. Expression indexes on extracted scalars (`data ->> 'key'`) are best when you filter on a single field.

### Connection Pooling

`create_fraiseql_app` accepts pool settings directly:

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users],
    connection_pool_size=20,         # base connections
    connection_pool_max_overflow=10, # burst capacity
    connection_pool_timeout=5.0,     # seconds to wait for a connection
    connection_pool_recycle=3600,    # recycle idle connections (seconds)
)
```

The same values map to `FraiseQLConfig` fields (`database_pool_size`, `database_max_overflow`, `database_pool_timeout`, `database_pool_recycle`) if you build the config explicitly. Keep the pool size well under PostgreSQL's `max_connections`, and put PgBouncer in front when running many app instances.

---

## Monitoring & Troubleshooting

### Key Metrics to Monitor

1. **Response Time Percentiles** (p50, p95, p99)
2. **Cache Hit Rate** (APQ + result cache; target: >85%)
3. **Database Connection Pool Utilization** (<80%)
4. **Query Complexity Distribution**
5. **Memory Usage Trends**

### Common Performance Issues

**Slow Queries (50-200ms)** — inspect the underlying view with `EXPLAIN ANALYZE` and check for missing indexes:

```sql
-- Inspect the plan for a slow read view
EXPLAIN (ANALYZE, BUFFERS)
SELECT data FROM v_user WHERE id = '...';

-- Look for tables/views lacking useful statistics or indexes
SELECT schemaname, tablename, attname, n_distinct, correlation
FROM pg_stats
WHERE schemaname = 'public' AND tablename LIKE 'tb_%';
```

If a `v_` view does expensive JOINs at query time, consider promoting it to a `tv_` projection table refreshed by triggers.

**Low Cache Hit Rate (<80%)**:

- Review query patterns for stability (persist queries client-side)
- Increase cache TTL where data freshness allows
- Implement query deduplication on the client

**High Memory Usage**:

- Reduce complexity limits (`complexity_max_score` / `complexity_max_depth`)
- Implement pagination on large result sets
- Trim the JSONB payload composed by your views

---

## Related Documentation

- [APQ Caching Guide](./apq-optimization-guide.md) - Automatic Persisted Queries optimization
- [Caching Guide](./caching.md) - Application-level caching strategies

---

*Performance Guide - PostgreSQL-first runtime architecture with optional `fraiseql_rs` JSON acceleration*
