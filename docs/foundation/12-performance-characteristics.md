---
title: "2.7: Performance Characteristics"
description: "FraiseQL v1 performance comes from pushing work into PostgreSQL (views, indexes, the query planner), an optional Rust JSON pipeline, connection pooling, and caching — all at runtime."
keywords: ["query-execution", "postgresql", "graphql", "performance", "runtime", "architecture"]
tags: ["documentation", "reference"]
---

# 2.7: Performance Characteristics

## Overview

FraiseQL v1 is a **Python runtime GraphQL framework for PostgreSQL**. There is no
compile step: the GraphQL schema is built in memory at application **startup** and
served over FastAPI. Performance therefore comes from a small set of runtime levers:

1. **Pushing work into PostgreSQL** — read views (`v_`/`tv_`) shape data with
   `jsonb_build_object(...)`, indexes keep lookups fast, and the query planner does
   the heavy lifting.
2. **The optional Rust extension (`fraiseql_rs`)** — accelerates JSON transformation
   and field selection on the hot path. It is a runtime accelerator, not a separate
   engine or data plane.
3. **Connection pooling** — reuse warm PostgreSQL connections instead of paying
   connect cost per request.
4. **Caching / Automatic Persisted Queries (APQ)** — avoid recomputing identical work.

This section explains FraiseQL's runtime performance model, typical latency/throughput
behaviour, and how design choices enable consistent, predictable performance.

### Performance Philosophy

```text
Traditional GraphQL Server (per request):
Query → Parse → Validate → Resolve (N+1) → Execute SQL → Format → Response

FraiseQL (per request):
Query → Parse → Validate → Resolve against v_/tv_ view → Execute one SQL → Shape JSON → Response

Key differences:
- The schema is built once at app startup (in memory), not on every request.
- Reads hit a single PostgreSQL view that already contains a shaped `data` JSONB column,
  avoiding the classic GraphQL N+1 resolver fan-out.
- The Rust `fraiseql_rs` pipeline shapes the JSONB down to the requested fields quickly.
```

The work that matters happens in PostgreSQL and in the JSON-shaping step, both at runtime.

---

## Performance Model

### Latency Breakdown

For a typical FraiseQL query, latency is distributed across these phases:

```text
Total Latency: ~27ms (example simple query)
├─ Network (round-trip): 2ms
├─ Server overhead: 3ms
│  ├─ Schema lookup: ~0.01ms (in-memory hash lookup)
│  ├─ Parameter binding: ~0.5ms (validation + SQL binding)
│  ├─ Authorization check: ~0.5ms (pre-execution rules)
│  └─ Response shaping: ~2ms (JSONB → requested fields, fraiseql_rs)
├─ Database: 20ms
│  ├─ Query planning: ~0.1ms (cached plan)
│  ├─ Execution: ~15ms (actual data fetch)
│  └─ Lock wait: ~3ms (if contention)
└─ Client-side parsing: 2ms
```

### Latency Tiers

| Query Complexity | Latency (P50) | Latency (P99) | Throughput |
|------------------|---------------|---------------|-----------|
| **Simple** (single row, 1-2 fields) | 2-5ms | 10ms | 200+ req/sec |
| **Medium** (single row, 5-10 fields, 1-2 relationships) | 10-20ms | 50ms | 100+ req/sec |
| **Complex** (10-100 rows, 3-4 nesting levels, filtering) | 30-100ms | 300ms | 20-50 req/sec |
| **Analytical** (1K-10K rows, aggregations) | 200ms-1s | 2-3s | 5-10 req/sec |

These figures are illustrative; always benchmark against your own schema and data.

### Real-World Baselines

Measured on a 4-core 8GB server with PostgreSQL on the same machine:

```text
Single Row Fetch (user by id):
- Latency: 3-4ms
- Throughput: 250+ req/sec
- Database time: 1-2ms
- Server overhead: 1-2ms

List with Pagination (100 items):
- Latency: 15-25ms
- Throughput: 50-70 req/sec
- Database time: 12-20ms
- Server overhead: 2-5ms

Nested Read (user + posts + comments via a tv_ view):
- Latency: 40-60ms
- Throughput: 20-30 req/sec
- Database time: 35-50ms
- Server overhead: 3-10ms

Analytical (1K rows with aggregation):
- Latency: 500-800ms
- Throughput: 2-3 req/sec
- Database time: 480-750ms
- Server overhead: 20-100ms
```

---

## Throughput Characteristics

### Request/Second Capacity

On a single server (4-core, 8GB RAM, dedicated PostgreSQL):

| Workload Profile | Req/Sec | Avg Latency | Connection Pool Usage |
|------------------|---------|-------------|----------------------|
| **Light** (mostly simple reads) | 200-500 | 5-10ms | 5-10 connections |
| **Moderate** (mix of reads/writes) | 100-200 | 20-40ms | 15-25 connections |
| **Heavy** (complex reads, frequent writes) | 50-100 | 40-80ms | 30-50 connections |
| **Burst** (temporary spike, 10x load) | 20-50 | 200-500ms | 50+ connections (degradation) |

### Scaling Model

FraiseQL scales **linearly with servers up to PostgreSQL I/O saturation**:

```text
Throughput vs Instance Count (PostgreSQL on dedicated machine)
─────────────────────────────────────────────────────────────

1 server:   200 req/sec   Database has headroom
2 servers:  350 req/sec   Still scales
4 servers:  600 req/sec   Still scales
8 servers:  900 req/sec   Still scales
16 servers: 1000 req/sec  Database at ~95% CPU (saturation point)
```

**Key insight**: Your throughput is limited by PostgreSQL, not by the FraiseQL Python
processes. Once you saturate the database, optimize there.

---

## Query Complexity and Performance Impact

### Common Query Patterns and Performance

Because reads resolve against a single `v_`/`tv_` view per type, most queries map to
one SQL statement. The patterns below show how shape affects cost.

**Pattern 1: Simple Single-Row Query**

```graphql
query {
  user(id: "…") {
    id
    name
    email
  }
}
```

- Execution plan: single indexed SELECT on the view (`WHERE id = $1`)
- Latency: 2-5ms
- Database queries: 1

**Pattern 2: List with Pagination**

```graphql
query {
  users(limit: 50, offset: 0) {
    id
    name
    email
  }
}
```

- Execution plan: SELECT with LIMIT/OFFSET on the view
- Latency: 10-20ms
- Database queries: 1

**Pattern 3: Nested Read via a Projection View**

```graphql
query {
  user(id: "…") {
    id
    name
    posts {
      id
      title
      createdAt
    }
  }
}
```

- Execution plan: resolved from a `tv_` projection view that already nests `posts`
  inside the `data` JSONB, so it stays a single read
- Latency: 15-30ms
- Database queries: 1 (no per-post fan-out)

**Pattern 4: Deeply Nested (use a projection view)**

```graphql
query {
  user(id: "…") {
    posts {
      comments {
        author {
          profile {
            bio
          }
        }
      }
    }
  }
}
```

- Without a purpose-built view this is the classic N+1 risk.
- **Fix**: model the nested shape in a `tv_` view so the whole tree comes back in one
  read, then let `fraiseql_rs` shape it down to the requested fields.

---

## Caching Strategy

### Result Caching and APQ

FraiseQL supports result caching and **Automatic Persisted Queries (APQ)** so repeated
work is not recomputed:

- **APQ** lets clients send a query hash instead of the full document, cutting parse and
  network overhead for hot queries.
- **Result caching** stores a response keyed by the query plus its parameters, with a TTL.

### Cache Coherency

When data is modified, dependent cached entries are invalidated so stale reads are not
served:

```text
Cache key: hash(query + params)
Example:   hash("user(id) { id name }" + {id: …})

When a mutation writes to the underlying table (via an fn_ function),
entries that read from that table are invalidated, and future queries recompute.
```

### Cache Hit Rates

Typical deployment cache statistics:

| Query Type | Cache Hit Rate | Time Saved |
|------------|----------------|-----------|
| Repeated read queries | 60-80% | 20-30ms per hit |
| Dashboard queries | 70-90% | 50-100ms per hit |
| User profile queries | 40-60% | 10-20ms per hit |
| Analytical queries | 20-40% | 200-500ms per hit |

### Enabling Caching

Caching and APQ are configured through the application, not a config file. Use
`create_fraiseql_app(...)` kwargs, a `FraiseQLConfig` instance, or `FRAISEQL_*`
environment variables:

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    production=True,  # production mode disables the playground and tightens defaults
)
```

```bash
# Equivalent toggles via environment variables
export FRAISEQL_DATABASE_URL="postgresql://localhost/mydb"
export FRAISEQL_PRODUCTION=true
```

See [Performance Optimization](../guides/performance-optimization.md) for the full set of
caching and APQ options.

---

## Database Optimization

This is where most FraiseQL performance work happens: the database does the heavy lifting.

### Index Strategy

Proper indexes are **critical** for FraiseQL performance:

```sql
-- Write table (source of truth) with internal BIGINT primary key
CREATE TABLE tb_post (
    pk_post BIGSERIAL PRIMARY KEY,   -- internal, never exposed
    id      UUID NOT NULL DEFAULT gen_random_uuid(),  -- public GraphQL id
    fk_user BIGINT NOT NULL,         -- internal foreign key
    status  TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Public id lookups (how queries filter: WHERE id = $1)
CREATE UNIQUE INDEX idx_post_id ON tb_post(id);

-- Foreign keys (for relationship queries / view joins)
CREATE INDEX idx_post_author ON tb_post(fk_user);

-- Frequently filtered fields
CREATE INDEX idx_post_status ON tb_post(status);
CREATE INDEX idx_post_created ON tb_post(created_at DESC);

-- Composite indexes for common access patterns
CREATE INDEX idx_post_author_status ON tb_post(fk_user, status);
CREATE INDEX idx_post_user_date ON tb_post(fk_user, created_at DESC);
```

**Performance impact:**

- Sequential scan: 500-5000ms for filtered queries
- Index scan: 5-50ms for filtered queries
- Index overhead: ~1ms per INSERT (acceptable)

### Query Planning

Always analyze PostgreSQL query plans for the views your queries hit:

```sql
EXPLAIN ANALYZE
SELECT data FROM v_post
WHERE id = $1;
```

Good plans have:

- Index Scan (not Sequential Scan)
- Correct join conditions
- Proper sort method (indexed)
- Reasonable row estimates (within ~10x of actual)

### Connection Pooling

FraiseQL reuses PostgreSQL connections from a pool. Tune the pool through application
configuration — `create_fraiseql_app(...)` kwargs, `FraiseQLConfig`, or `FRAISEQL_*`
environment variables — not a standalone config file:

```bash
# Pool sizing via environment variables
export FRAISEQL_DATABASE_POOL_MIN=10
export FRAISEQL_DATABASE_POOL_MAX=50
```

**Guidelines:**

- Light workload: min=5, max=20
- Moderate workload: min=10, max=50
- Heavy workload: min=20, max=100

A pool that is too small queues requests; one that is too large can overwhelm
PostgreSQL. Size `pool_max` against your database's connection limit and core count.

---

## Monitoring and Profiling

### Key Metrics to Track

```text
1. Latency Percentiles
   - P50 (median): ~20ms is good
   - P95: ~100ms is acceptable
   - P99: ~500ms is concerning

2. Throughput
   - Requests per second
   - Successful vs error rate
   - Queue depth

3. Database
   - Query time (should be ~80% of total latency)
   - Connection pool utilization
   - Slow query log hits

4. Application
   - Memory usage
   - Event-loop / worker saturation
```

If database time is *not* the dominant slice, look at your views, indexes, or the
JSON-shaping path before adding servers.

### Load Testing

Use `wrk` or Apache Bench against the GraphQL endpoint to establish a baseline:

```bash
# 4 threads, 10 concurrent connections, 30 seconds
wrk -t 4 -c 10 -d 30s \
  -s post_query.lua \
  http://localhost:8000/graphql

# Example output:
# Running 30s test @ http://localhost:8000/graphql
#   4 threads and 10 connections
#   Latency     25.3ms   18.2ms  156.2ms   85.42%
#   Req/Sec    123.2     35.4     250      72.19%
# 14856 requests in 30.09s, 123.5MB read
```

Run the app with a production ASGI server (for example `uvicorn app:app`) when
benchmarking so results reflect real deployment conditions.

---

## Scaling Patterns

### Pattern 1: Vertical Scaling (Single Server)

Add more CPU/RAM to a single server:

```text
2-core → 4-core:    +50-70% throughput
4-core → 8-core:    +30-50% throughput (diminishing returns)
8GB RAM → 16GB RAM: +20-30% (more headroom for caching)
```

**When to use**: up to ~1000 req/sec.

### Pattern 2: Horizontal Scaling (Multiple App Servers)

Run more FraiseQL app instances behind a load balancer:

```text
1 server:   200 req/sec
2 servers:  350 req/sec (~75% of linear)
4 servers:  600 req/sec (~75% of linear)
8 servers:  900 req/sec (~70% of linear)
```

Scaling efficiency drops once PostgreSQL becomes the bottleneck (often around 8 servers).

### Pattern 3: Read Replicas

Use PostgreSQL read replicas for read-heavy workloads:

```text
Primary DB (writes):    200 req/sec
+ 2 Read Replicas:      400 req/sec
+ 4 Read Replicas:      800 req/sec
```

**Gotcha:** replicas have replication lag (typically 10-100ms), so very recent writes
may not yet be visible.

### Pattern 4: Caching Layer

Layer caching in front of hot reads:

```text
Without cache:  200 req/sec
+ cache:        500+ req/sec (hit-rate dependent)
```

**Note**: cache coherency becomes harder at scale — rely on FraiseQL's invalidation and
keep TTLs conservative for data that changes often.

---

## Performance Anti-Patterns

### Anti-Pattern 1: N+1 Reads

```graphql
# Risky: a generic resolver that fetches each user's posts separately
query {
  users {
    id
    posts {   # one query per user if not modeled in the view
      id
      title
    }
  }
}
```

**Fix**: model the nested shape in a `tv_` projection view so the tree returns in one
read, or compose it inside the `v_` view's `data` JSONB with `jsonb_build_object(...)`.

```sql
-- The view already nests posts inside the user's data JSONB
SELECT
    u.id,
    jsonb_build_object(
        'id',    u.id,
        'name',  u.name,
        'posts', (
            SELECT jsonb_agg(jsonb_build_object('id', p.id, 'title', p.title))
            FROM tb_post p
            WHERE p.fk_user = u.pk_user
        )
    ) AS data
FROM tb_user u;
```

Performance impact:

- N+1 version: 100 users × 10ms each ≈ 1000ms
- Single shaped read: one ~20ms query

### Anti-Pattern 2: Over-Fetching

Requesting every field forces PostgreSQL to return the full `data` JSONB and makes the
JSON-shaping step do more work.

```graphql
# Wasteful: pulls the entire data JSONB per row
query { users { id name email bio avatarUrl preferences metadata } }

# Lean: request only what you render — fraiseql_rs shapes down to these fields
query { users { id name } }
```

Performance impact:

- Wide selection: 100 users × ~5KB ≈ 500KB network + ~100ms
- Lean selection: 100 users × ~100B ≈ 10KB network + ~5ms

### Anti-Pattern 3: Unbounded Lists

```graphql
# Risky: no limit on the result set
query {
  posts {   # could return millions of rows
    id
    title
  }
}
```

**Fix**: enforce pagination limits.

```graphql
query {
  posts(limit: 50, offset: 0) {
    id
    title
  }
}
```

Performance impact:

- Unbounded: 1,000,000 rows × 50 bytes ≈ 50MB + 5000ms
- With a limit: 50 rows × 50 bytes ≈ 2.5KB + 5ms

### Anti-Pattern 4: Missing Indexes

```sql
-- Slow: frequently filtered field has no index (sequential scan: 500-5000ms)
SELECT data FROM v_post WHERE status = 'PUBLISHED';

-- Fast: index the underlying column (index scan: 5-50ms)
CREATE INDEX idx_post_status ON tb_post(status);
```

---

## Performance Tuning Checklist

- [ ] **Indexes**: all frequently filtered columns (including public `id`) are indexed
- [ ] **Views**: nested reads modeled in `v_`/`tv_` views instead of resolver fan-out
- [ ] **Query plans**: verified with `EXPLAIN ANALYZE`
- [ ] **Caching / APQ**: enabled with appropriate TTL where it helps
- [ ] **Connection pool**: sized for the workload and the database's connection limit
- [ ] **Monitoring**: latency, throughput, and pool metrics collected
- [ ] **Load testing**: a baseline established with `wrk`/`ab`
- [ ] **N+1 detection**: identified and fixed in the view layer
- [ ] **Field projection**: clients request only the fields they render
- [ ] **Pagination**: maximum limits enforced
- [ ] **Database**: on dedicated hardware, low-latency network (<5ms) to the app

---

## Related Topics

- [2.2: Database-Centric Architecture](03-database-centric-architecture.md) — why work
  lives in PostgreSQL views and functions
- [2.4: Design Principles](04-design-principles.md) — the runtime, database-first model
- [2.6: Type System](09-type-system.md) — type safety and how types map to views
- [Performance Optimization Guide](../guides/performance-optimization.md) — concrete
  caching, APQ, and tuning options
- [tv_ Table Pattern](../architecture/database/tv-table-pattern.md) — projection views
  for fast nested reads

---

## Summary

FraiseQL v1's performance model is built on **runtime execution backed by PostgreSQL**:

- **No compile step** — the schema is built in memory at app startup and served over
  FastAPI; there is no compiled artifact.
- **Database does the work** — read views shape data, indexes keep lookups fast, and the
  query planner optimizes execution.
- **Rust JSON pipeline** — `fraiseql_rs` shapes JSONB down to requested fields quickly on
  the hot path.
- **Pooling and caching** — connection pooling and caching/APQ avoid repeated cost.
- **Latency**: 2-100ms typical (database-bound).
- **Throughput**: 200+ req/sec per server, scaling roughly linearly until PostgreSQL
  saturates.

The key insight: **your performance ceiling is PostgreSQL, not FraiseQL.** Once you hit
database saturation, optimize there — indexes, query plans, well-shaped views, and
replication — rather than adding more app servers.
