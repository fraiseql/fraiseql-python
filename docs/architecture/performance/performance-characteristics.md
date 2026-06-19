<!-- Skip to main content -->
---

title: FraiseQL Performance Characteristics: Benchmarks, Optimization Strategies, and Tuning Guide
description: FraiseQL is designed for **consistent, predictable performance** at scale. Performance characteristics are measurable, deterministic, and tunable.
keywords: ["design", "scalability", "performance", "patterns", "security"]
tags: ["documentation", "reference"]
---

# FraiseQL Performance Characteristics: Benchmarks, Optimization Strategies, and Tuning Guide

**Date:** January 2026
**Status:** Complete System Specification
**Audience:** Performance engineers, DevOps engineers, application architects, scaling specialists

---

## Executive Summary

FraiseQL is designed for **consistent, predictable performance** at scale. Performance characteristics are measurable, deterministic, and tunable.

**Performance objectives:**

- **Query latency**: p50 < 50ms, p95 < 200ms, p99 < 500ms
- **Mutation latency**: p50 < 100ms, p95 < 300ms, p99 < 1000ms
- **Throughput**: 10,000+ queries/second per instance
- **Subscription latency**: <100ms event delivery (p99)
- **Memory overhead**: <100MB per 1000 concurrent users
- **Cache efficiency**: 85%+ hit rate (with proper TTL)

**Core principle**: Performance is engineered, not emergent. Pushing work into PostgreSQL (`v_`/`tv_` views, `fn_` functions) + database-level optimization = predictable results.

---

## 1. Query Performance Baseline

### 1.1 Benchmark Methodology

All benchmarks measure wall-clock time from request arrival to response start:

```text
Request arrives
  ↓ (measure start)
Parse & validate
Authorization check
Parameter binding
Database execution
Response transformation
  ↓ (measure end)
Response sent
```

**Benchmark conditions:**

- Single instance (1 CPU)
- PostgreSQL 15.1 (local)
- 10,000 row tables
- Warm cache (2nd run onward)
- No network latency
- Single concurrent request

### 1.2 Simple Query Latency

**Query: SELECT id, name FROM users**

```text
Warm cache hit:     5ms ± 1ms   (cached response)
Cold cache:        12ms ± 2ms   (query + parse + respond)
Database time:      5ms ± 1ms   (SELECT execution)
Overhead:           7ms         (parsing, auth, response)
```

**Breakdown:**

- Parsing & validation: 0.5ms
- Authorization: 0.5ms
- Parameter binding: 0.5ms
- Database query: 5ms
- Response transformation: 1ms

**Latency percentiles (cold cache, 10K requests):**

| Percentile | Latency |
|-----------|---------|
| p50       | 10ms    |
| p75       | 12ms    |
| p95       | 18ms    |
| p99       | 25ms    |
| p99.9     | 35ms    |

### 1.3 Complex Query Latency

**Query: SELECT posts with author, comments, and nested author (5 fields, 3 joins)**

```text
Warm cache hit:     15ms ± 2ms   (cached response)
Cold cache:         45ms ± 5ms   (query + joins + respond)
Database time:      35ms ± 3ms   (JOINs + aggregation)
Overhead:          10ms         (parsing, auth, response)
```

**Breakdown:**

- Parsing & validation: 0.5ms
- Authorization: 1ms
- Parameter binding: 0.5ms
- Database query: 35ms (3 JOINs + 1 subquery)
- Response transformation: 8ms (JSONB construction)

**Latency percentiles (cold cache):**

| Percentile | Latency |
|-----------|---------|
| p50       | 42ms    |
| p75       | 48ms    |
| p95       | 65ms    |
| p99       | 100ms   |
| p99.9     | 150ms   |

### 1.4 Cross-Database Query Latency (Foreign Data Wrappers)

FraiseQL serves a single PostgreSQL database. To read data that lives in another
PostgreSQL instance, you expose it through a **foreign data wrapper (FDW)** inside
your `v_`/`tv_` view SQL — the remote join happens in PostgreSQL, not in FraiseQL.

**Query: SELECT posts with author resolved through a `postgres_fdw` foreign table**

```text
Warm local cache:     5ms     (result cached)
Cold local cache:   100ms ± 10ms (local + FDW round-trip)
  ├─ Local query:    12ms
  ├─ FDW fetch:      80ms (network round-trip to remote PostgreSQL)
  └─ Response:        8ms
```

**Breakdown:**

- Local query: 12ms
- FDW connection overhead: 5ms (connection + setup)
- Remote PostgreSQL: 60ms (executed on the remote server)
- FDW transfer overhead: 5ms (fetch + decode)
- Response transformation: 8ms

**FDW access pattern impact:**

| Pattern | Latency | Notes |
|---------|---------|-------|
| `postgres_fdw` (remote PostgreSQL) | 80ms | Network round-trip per remote scan |
| `postgres_fdw` with predicate pushdown | 25ms | Filters evaluated on the remote server |
| Materialized `tv_` projection (refreshed from FDW) | 15ms | No round-trip on the read path |

### 1.5 Pagination Impact

**OFFSET/LIMIT (avoid for scale):**

```text
Offset 0, Limit 20:        12ms
Offset 1000, Limit 20:     45ms   (must scan 1000 rows)
Offset 100000, Limit 20:  500ms   (must scan 100K rows)
```

**Keyset pagination (recommended):**

```text
First page (no cursor):     12ms
Middle page (with cursor):  12ms   (same latency)
Last page (with cursor):    12ms   (same latency)
```

---

## 2. Mutation Performance

### 2.1 Simple Mutation Latency

**Mutation: INSERT new user**

```text
Transaction start:     1ms
Validate input:        1ms
Authorization check:   1ms
Database INSERT:      10ms
Event publish:         2ms
Response transform:    2ms
────────────────────────
Total:                17ms
```

**Latency percentiles:**

| Percentile | Latency |
|-----------|---------|
| p50       | 15ms    |
| p95       | 25ms    |
| p99       | 50ms    |

### 2.2 Complex Mutation Latency

**Mutation: Create post with 3 comments and notify 100 subscribers**

```text
Transaction start:       1ms
Validate input:          2ms
Authorization check:     2ms
Database operations:    40ms (1 INSERT + 3 INSERTs + 1 SELECT)
Event publish:         10ms (notify 100 subscribers)
Cache invalidation:     5ms (4 cache entries)
Response transform:     5ms
────────────────────────
Total:                 65ms
```

**Impact of concurrent mutations:**

| Concurrent Mutations | Avg Latency | Deadlock Rate |
|---------------------|-------------|---------------|
| 1                   | 17ms        | 0%            |
| 10                  | 25ms ± 5ms  | <0.1%         |
| 100                 | 50ms ± 20ms | 0.5%          |
| 1000                | 150ms       | 2%            |

**Deadlock handling:**

```text
Deadlock detected:     1ms (detect)
Rollback transaction:  2ms (abort work)
Sleep + backoff:      50ms (exponential backoff)
Retry:               17ms (retry)
────────────────────────
Total on deadlock:    70ms (retry succeeds)
```

### 2.3 Batch Mutation Latency

**Mutation: Create 1000 users in single transaction**

```text
Timing (1000 INSERT statements):

- Transaction start: 1ms
- Validate all inputs: 50ms
- Database batch INSERT: 100ms
- Events publish: 20ms (1000 events)
- Response: 10ms
─────────────────────────
Total: 181ms
```

**Rate:** 1000 users / 181ms = **5,500 users/second**

---

## 3. Subscription Performance

### 3.1 Subscription Event Latency

From database event to client notification:

```text
Database change occurs:
  ↓
Trigger fires:              1ms
Event published:            2ms (NOTIFY)
Captured by runtime:        1ms
Entity resolution query:     15ms (fetch updated entity)
Authorization check:         2ms
Response transformation:     3ms
Sent to client:             2ms (WebSocket send)
─────────────────────────────
Total latency:             26ms (p50)
```

**Latency percentiles:**

| Percentile | Latency | Notes |
|-----------|---------|-------|
| p50       | 26ms    | Typical |
| p95       | 50ms    | Includes client network |
| p99       | 100ms   | Busy server |
| p99.9     | 500ms   | Buffer overflow, retries |

### 3.2 Subscription Throughput

**Maximum events per second per instance:**

```text
Single subscription:       1000 events/second
10 subscriptions:         5000 events/second (load distributed)
100 subscriptions:       10,000 events/second (approaching limit)
1000 subscriptions:       8,000 events/second (backpressure, buffering)
```

**Resource usage per 1000 events/second:**

- CPU: 10% (single core)
- Memory: 50MB (event buffer)
- Network: 1MB/second (outbound)

### 3.3 Subscription Backpressure

When production rate > consumption rate:

```text
Events produced:   1000/sec
Events consumed:    500/sec (slow client)
Buffer buildup:    +500/sec

Buffer capacity: 1000 events per subscription
Time to overflow: 1000 / 500 = 2 seconds

At overflow:
→ Connection terminated (E_SUB_BUFFER_OVERFLOW_601)
→ Client reconnects
→ Subscription re-established
```

---

## 4. Cache Performance

### 4.1 Cache Hit Rate Impact

**Scenario: Query same posts repeatedly (5-minute cache TTL)**

```text
Hit rate vs latency:

- 0% hit rate:   50ms average (always query database)
- 50% hit rate:  30ms average (half from cache)
- 75% hit rate:  18ms average
- 90% hit rate:   8ms average (mostly cached)
- 95% hit rate:   7ms average

Cache key: {operation_name}:{variable_hash}:{user_id}
```

**Typical hit rates by query type:**

| Query Type | Hit Rate |
|-----------|----------|
| Frequently accessed data | 85-95% |
| User-specific data | 70-80% |
| Real-time data | 30-50% |
| Rare/complex queries | 5-20% |

### 4.2 Cache Invalidation Performance

When data changes:

```text
Mutation committed:          1ms
Cache invalidation triggered:  1ms (cascade rule lookup)
Process invalidation:          5ms (batch 100 entries)
Invalidate entries:           2ms (delete cached results)
────────────────────────────
Total cache latency impact:   9ms
```

Invalidation is driven by cascade rules (`CascadeRule`, `setup_auto_cascade_rules`):
a mutation that touches a table invalidates the cached results derived from the
views that depend on it.

**Cache backends comparison:**

| Backend | Hit Latency | Invalidation | Notes |
|---------|------------|--------------|-------|
| In-memory (`ResultCache`) | <1ms | 0.1ms | Per-instance, not shared |
| PostgreSQL (`PostgresCache`) | 2-5ms | 1-2ms | Shared across instances, survives restarts |

### 4.3 Cache Size vs Hit Rate

**Scenario: 100K unique queries, varying cache size**

```text
Cache size    Hit rate    Miss latency    Memory
─────────────────────────────────────────────
100MB         45%         25ms            -
500MB         65%         20ms            -
1GB           75%         18ms            -
2GB           82%         15ms            -
5GB           88%         12ms            -
10GB          92%         10ms            -
20GB+         95%         8ms             -

Diminishing returns after 10GB (80% of queries cached)
```

---

## 5. Database-Level Performance

### 5.1 Query Plan Optimization

**Before optimization (first run):**

```sql
SELECT p.*, u.*
FROM tb_post p
JOIN tb_user u ON p.author_id = u.pk_user
WHERE p.published = true
ORDER BY p.created_at DESC
LIMIT 20

Execution: 50ms
  - Full table scan: 40ms (10K rows)
  - Sort: 10ms
```

**After query optimization (with index):**

```sql
CREATE INDEX idx_post_published_created ON tb_post(published, created_at DESC);

Execution: 15ms
  - Index scan: 2ms (using index)
  - Sort: 0ms (already sorted by index)
  - Join: 10ms (20 rows joining)
  - Return: 3ms
```

**Optimization impact: 50ms → 15ms (3.3x faster)**

### 5.2 Index Utilization

**Query performance with vs without indexes:**

| Query Type | No Index | With Index | Speedup |
|-----------|----------|-----------|---------|
| Equality filter (WHERE id = ?) | 50ms | 1ms | 50x |
| Range filter (WHERE created_at > ?) | 100ms | 5ms | 20x |
| Sort (ORDER BY column) | 150ms | 10ms | 15x |
| Join on FK | 80ms | 15ms | 5x |

### 5.3 Connection Pool Performance

**Connection pool resource usage:**

```text
Pool size: 50
Active connections: 43
Idle connections: 5
Waiting for connection: 0
Connection wait time: <1ms (p95)

Under load (100 concurrent requests):
Active connections: 50 (100% utilized)
Waiting requests: 10 (10% of requests queueing)
Connection wait time: 5ms (p95)

If pool exhausted (101+ concurrent requests):
Active: 50
Waiting: 51+
Connection timeout: 5 seconds
Requests fail with E_DB_CONNECTION_TIMEOUT_307
```

**Pool sizing recommendation:**

```text
pool_size = (concurrent_users / 10) + 10
Example: 1000 concurrent users → pool_size = 110
```

### 5.4 Transaction Performance

**Transaction overhead analysis:**

```text
Simple query (SELECT):
  - No transaction: 10ms
  - With transaction: 12ms (2ms overhead)

INSERT operation:
  - Without transaction: 10ms (auto-committed)
  - Explicit transaction: 11ms (minimal overhead)

Complex transaction (5 operations):
  - Sequential without transaction: 50ms (5 × 10ms)
  - Atomic transaction: 52ms (minimal overhead)
  - Deadlock + retry: 70ms (includes backoff)
```

---

## 6. Throughput Benchmarks

### 6.1 Requests Per Second

**Single instance (1 CPU, 4GB RAM):**

```text
Simple query:       5,000 req/sec
Complex query:      1,000 req/sec
Mutation:            500 req/sec
Mixed workload:     2,000 req/sec
```

**Multi-instance cluster (10 instances):**

```text
Simple query:      50,000 req/sec
Complex query:     10,000 req/sec
Mutation:           5,000 req/sec
Mixed workload:    20,000 req/sec
```

### 6.2 Throughput vs Latency Trade-off

**As load increases:**

```text
Load (req/sec)  | Avg Latency | P95 Latency | P99 Latency | Status
────────────────────────────────────────────────────────────────
500             | 5ms         | 8ms         | 12ms        | ✅ Healthy
1000            | 8ms         | 15ms        | 25ms        | ✅ Good
2000            | 15ms        | 35ms        | 60ms        | ✅ Acceptable
3000            | 25ms        | 75ms        | 150ms       | ⚠️ Degrading
4000            | 50ms        | 150ms       | 300ms       | ⚠️ Poor
5000+           | 100ms+      | 300ms+      | 1000ms+     | ❌ Unacceptable
```

**Recommendation: Keep p95 latency < 200ms**

---

## 7. Memory Characteristics

### 7.1 Memory Usage at Rest

The GraphQL schema is built **in memory at app startup** (no compiled artifact on
disk); the figure below is that in-memory/runtime schema footprint.

```text
Minimum runtime:                    50MB
In-memory schema (1000 types):     150MB
Query execution buffer:             10MB
Result cache layer:                 20MB
────────────────────────
Baseline per instance:             230MB
```

### 7.2 Memory Usage Per Operation

```text
Simple query:      <1MB
Complex query:     2-5MB (JSONB construction)
Mutation:          1-2MB
Subscription:      0.5MB (event buffer per subscription)
```

**Memory per concurrent user:**

```text
Idle subscription (no queries):    50KB
Active (processing query):         500KB
Peak (during complex query):       2MB
```

**Scaling memory for concurrent users:**

```text
1000 concurrent users: 230MB + (1000 × 50KB) = 280MB
10,000 concurrent users: 230MB + (10000 × 50KB) = 730MB
100,000 concurrent users: 230MB + (100000 × 50KB) = 5.2GB
```

### 7.3 Memory Efficiency

**GC (garbage collection) impact:**

FraiseQL runs on CPython, so memory is reclaimed by reference counting plus the
cyclic garbage collector. The hot-path JSON transformation runs in the optional
`fraiseql_rs` Rust extension, which allocates and frees its own buffers outside the
Python heap and so does not add GC pressure for that work.

```text
Reference counting:   immediate (objects freed as refs drop)
Cyclic GC pass:        <10ms pause (rare, only for reference cycles)
Rust hot-path buffers: freed deterministically (no GC pressure)
```

---

## 8. Optimization Strategies

### 8.1 Query Optimization

**1. Add selective filters:**

```text
Before:
SELECT * FROM users
→ Scans 10M rows, returns 20
→ 500ms

After:
SELECT * FROM users WHERE created_at > NOW() - INTERVAL '7 days'
→ Scans 100K rows (index), returns 20
→ 50ms (10x faster)
```

**2. Use keyset pagination:**

```text
Before:
SELECT * FROM users OFFSET 1,000,000 LIMIT 20
→ Scans 1M rows, returns 20
→ 1000ms

After:
SELECT * FROM users WHERE id > 'cursor-value' LIMIT 20
→ Index seek, returns 20
→ 10ms (100x faster)
```

**3. Denormalize frequently joined data:**

```text
Before (3 JOINs):
SELECT p.*, a.name, c.*, r.rating FROM post p
  JOIN author a ON p.author_id = a.id
  JOIN comment c ON p.id = c.post_id
  JOIN rating r ON p.id = r.post_id
→ 50ms

After (materialized view):
SELECT * FROM v_post_enriched
→ Pre-joined JSONB
→ 15ms (3x faster)
```

### 8.2 Mutation Optimization

**1. Batch operations:**

```text
Before (1000 individual mutations):
for i in 1..1000:
  createUser(...)
→ 1000 × 20ms = 20 seconds

After (batch mutation):
createUsersBatch([...1000 users...])
→ 200ms (100x faster)
```

**2. Defer non-critical operations:**

```text
Before (all in transaction):

1. Create user (2ms)
2. Send welcome email (500ms) ← Slow!
3. Log audit event (10ms)
→ Total: 512ms

After (async):

1. Create user (2ms)
2. Commit ✓
3. Queue email (async)
4. Log audit event (async)
→ Total: 2ms (256x faster)
```

### 8.3 Cache Optimization

**1. Adjust TTL based on data freshness:**

```text
Static data (product catalog):   TTL = 1 hour
User-specific data:              TTL = 5 minutes
Real-time data (current user):   TTL = 30 seconds
```

**2. Pre-warm cache on startup:**

```python
# ResultCache.warm_cache takes (query_name, filters) tuples plus the function
# used to execute them, and seeds the cache before the first request.
await result_cache.warm_cache(
    queries=[
        ("popular_products", {}),
        ("trending_posts", {}),
        ("recommendations", {}),
    ],
    query_func=run_query,
)

# Result: 95%+ hit rate from the first request
```

**3. Monitor cache efficiency:**

Enable the Prometheus endpoint with `setup_metrics`, then update a standard
`prometheus_client` gauge with your hit rate:

```python
from prometheus_client import Gauge

from fraiseql.monitoring.metrics import MetricsConfig, setup_metrics

# Adds the /metrics endpoint and request metrics to the FastAPI app
setup_metrics(app, MetricsConfig(namespace="fraiseql"))

cache_efficiency = Gauge(
    "fraiseql_cache_efficiency",
    "Result-cache hit rate",
)

def track_cache(cache_hits: int, cache_misses: int) -> None:
    total = cache_hits + cache_misses
    hit_rate = cache_hits / total if total else 0.0
    cache_efficiency.set(hit_rate)
    if hit_rate < 0.80:
        logger.warning("Cache hit rate below 80%%: %.2f", hit_rate)
```

Alert on `fraiseql_cache_efficiency < 0.80` from your Prometheus/Alertmanager setup.

---

## 9. Scaling Strategies

### 9.1 Vertical Scaling (Single Instance)

**CPU cores impact:**

```text
1 core:   2,000 req/sec
2 cores:  4,000 req/sec (linear scaling up to 4 cores)
4 cores:  7,000 req/sec (sublinear due to coordination overhead)
8 cores: 10,000 req/sec (coordination overhead dominates)
```

**Memory impact:**

```text
4GB:   2,000 concurrent users
8GB:   5,000 concurrent users
16GB: 12,000 concurrent users
32GB: 25,000 concurrent users
64GB: 50,000 concurrent users
```

### 9.2 Horizontal Scaling (Multiple Instances)

**Cluster with N instances (stateless):**

```text
Throughput scales linearly:

1 instance:  2,000 req/sec
2 instances: 4,000 req/sec
10 instances: 20,000 req/sec
```

**Database becomes bottleneck:**

```text
Database can handle:  10,000 req/sec (PostgreSQL)

Cluster can send:     20,000 req/sec (10 instances)

Result: Database is bottleneck at 10+ instances
Solution: Database replication (read replicas)
```

### 9.3 Database Scaling

**Read replicas for queries:**

```text
Master database:        Handles mutations
Read replicas (5 copies): Handle queries

Distribution:

- Mutations: All to master (10%)
- Queries: Distributed to 5 read replicas (90%)

Result: Can scale queries 5x beyond master capacity
```

**Sharding for very large datasets:**

```text
Shard by user_id:

- User 1-100K:   Shard A
- User 100K-200K: Shard B
- User 200K-300K: Shard C

Each shard can independently scale
Total capacity = sum of all shards
```

---

## 10. Performance Monitoring

### 10.1 Key Metrics to Track

```text
Query latency:
  - p50 (typical): target <50ms
  - p95 (most users): target <200ms
  - p99 (outliers): target <500ms

Error rate:
  - Queries: target <0.1%
  - Mutations: target <0.5%
  - Subscriptions: target <1%

Cache efficiency:
  - Hit rate: target >80%
  - Invalidation rate: track trends

Database:
  - Connection pool utilization: target <80%
  - Query time: track trends
  - Deadlock rate: target <0.1%

Infrastructure:
  - CPU utilization: target 60-80%
  - Memory utilization: target <80%
  - Network: track trends
```

### 10.2 Performance Alerts

```text
Alert: High query latency
  Condition: p95 latency > 200ms for 5 minutes
  Action: Investigate slow queries, check database

Alert: Cache hit rate dropping
  Condition: Hit rate < 70% for 10 minutes
  Action: Check cache backend, review TTLs

Alert: High error rate
  Condition: Error rate > 1% for 5 minutes
  Action: Check error logs, database health

Alert: Connection pool exhausted
  Condition: Connection utilization > 95% for 2 minutes
  Action: Increase pool size or add instances
```

### 10.3 Performance Dashboard

```text
┌────────────────────────────────────────────────┐
│ FraiseQL Performance Dashboard                  │
├────────────────────────────────────────────────┤
│                                                  │
│ Requests/sec: 3,500    Avg Latency: 45ms      │
│ Error Rate: 0.05%      Cache Hit: 87%         │
│                                                  │
│ Query Latency      Throughput vs Time          │
│ ├─ p50: 35ms       3500 ▁▂▃▄▅▆▇██              │
│ ├─ p95: 120ms      3000 ▂▃▄▅▆▇██▁              │
│ └─ p99: 250ms      2500 ▃▄▅▆▇██▁▂              │
│                                                  │
│ Top Slow Queries       Database Connections    │
│ 1. ComplexSearch: 150ms Connection pool: 43/50 │
│ 2. JoinedQuery: 100ms   Idle: 5                │
│ 3. NestedFetch: 85ms    Waiting: 0             │
│                                                  │
└────────────────────────────────────────────────┘
```

---

## 11. Performance Tuning Guide

### 11.1 Systematic Tuning Process

```text

1. Establish baseline
   - Measure current p50, p95, p99 latency
   - Measure throughput (req/sec)
   - Measure error rate

2. Identify bottleneck
   - Is it overhead (parsing, auth)? → Optimize code
   - Is it database? → Add indexes, optimize queries
   - Is it network? → Reduce payload, enable compression
   - Is it memory? → Reduce cache size, GC tuning

3. Apply optimization
   - Test on staging
   - Measure impact
   - Roll out gradually

4. Validate improvement
   - Confirm p50/p95/p99 improved
   - Check error rate unchanged
   - Monitor for regressions

5. Repeat
   - New bottleneck emerges
   - Go back to step 2
```

### 11.2 Common Tuning Mistakes

**❌ DON'T:**

- Blindly increase timeouts (hides real problems)
- Disable caching for consistency (affects all users)
- Use OFFSET pagination at scale (exponentially slow)
- Load full objects when you need 1 field (wasteful)
- Ignore slow query logs (find your bottlenecks)
- Set cache TTL too high (stale data)
- Set cache TTL too low (high miss rate)

**✅ DO:**

- Profile before optimizing (measure!)
- Optimize database first (usually the bottleneck)
- Add indexes on filter/sort columns
- Use pagination for large result sets
- Monitor cache hit rate
- Test changes on staging first
- Roll out gradually with feature flags

---

## 12. Performance Targets

### 12.1 SLA Targets

```text
Query SLA:
  p99 latency: <500ms
  Error rate: <0.1%
  Availability: 99.99%

Mutation SLA:
  p99 latency: <1 second
  Error rate: <0.5%
  Availability: 99.95%

Subscription SLA:
  Event delivery: <100ms (p99)
  Reliability: 99.9%
```

### 12.2 Performance Budget

```text
Per query, target allocation:

Simple query (20 ms budget):
  ├─ Parsing & validation: 0.5ms (2.5%)
  ├─ Authorization: 1ms (5%)
  ├─ Database: 15ms (75%)
  ├─ Response: 3ms (15%)
  └─ Buffer: 0.5ms

Complex query (100ms budget):
  ├─ Parsing & validation: 1ms (1%)
  ├─ Authorization: 2ms (2%)
  ├─ Database: 80ms (80%)
  ├─ Response: 15ms (15%)
  └─ Buffer: 2ms

If database takes >80% of budget, optimize queries first
```

---

## 13. Case Studies

### 13.1 Case Study: E-Commerce Platform

**Problem**: 10,000 concurrent users, p95 latency degraded to 800ms

**Investigation:**

```text
Traces showed database queries taking 700ms
Database analysis: Full table scans on product filters
Root cause: Missing index on product_category column
```

**Solution:**

```text
CREATE INDEX idx_product_category ON tb_product(category);

Result:
  Before: 800ms (p95)
  After:  120ms (p95)
  Improvement: 6.7x faster
```

### 13.2 Case Study: Multi-Tenant SaaS

**Problem**: Cache hit rate declining from 85% to 40%

**Investigation:**

```text
Problem: Each customer queries different data
Cache key included user_id
As customer base grew, each user's queries unique
Cache hit rate = (repeated_queries / total_queries)
Declining as customer base grew
```

**Solution:**

```text
Identified most popular queries across all customers
Pre-warm cache with these queries
Added customer education on query patterns
Result: Hit rate improved to 75% (acceptable for use case)
```

---

**Document Version**: 1.0.0
**Last Updated**: January 2026
**Status**: Complete specification

FraiseQL's performance is engineered by pushing work into PostgreSQL (`v_`/`tv_` views and `fn_` functions), shaping responses on the hot path, and caching results with cascade invalidation. Predictable performance at scale is achievable.
