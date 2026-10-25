---
title: Performance Guide
description: Optimization strategies and performance best practices
tags:
  - performance
  - optimization
  - speed
  - efficiency
  - best-practices
---

# FraiseQL Performance Guide

🟡 **Production** - Performance expectations, methodology, and optimization guidance.

**📍 Navigation**: [← Main README](README.md) • [Performance Docs →](docs/performance/index.md) • [Benchmarks →](../../benchmarks/)

## Executive Summary

FraiseQL delivers **sub-10ms response times** for typical GraphQL queries through an exclusive Rust pipeline that eliminates Python string operations. This guide provides realistic performance expectations, methodology details, and guidance on when performance optimizations matter.

**Key Takeaways:**

- **Typical queries**: 5-25ms response time (including database)
- **Optimized queries**: 0.5-5ms response time (with all optimizations active)
- **Cache hit rates**: 85-95% in production applications
- **Speedup vs alternatives**: 2-4x faster than traditional GraphQL frameworks
- **Architecture**: PostgreSQL → Rust Pipeline → HTTP (zero Python string operations)

---

## Performance Claims & Methodology

### Claim: "2-4x faster than traditional GraphQL frameworks"

**What this means**: FraiseQL is 2-4x faster than frameworks like Strawberry, Hasura, or PostGraphile for typical workloads, with end-to-end optimizations including APQ caching, field projection, and exclusive Rust pipeline transformation.

**Methodology**:

- **Baseline comparison**: Measured against Strawberry GraphQL (Python ORM) and Hasura (PostgreSQL GraphQL)
- **Test queries**: Simple user lookup, nested user+posts, filtered searches
- **Dataset**: 10k-100k records in PostgreSQL 15
- **Hardware**: Standard cloud instances (4 CPU, 8GB RAM)
- **Measurement**: End-to-end response time including database queries

**Realistic expectations**:

- **Simple queries** (single table): 2-3x faster
- **Complex queries** (joins, aggregations): 3-4x faster
- **Cached queries**: 4-10x faster (due to APQ optimization)
- **All queries**: Use exclusive Rust pipeline (PostgreSQL → Rust → HTTP)

**When this matters**: High-throughput APIs (>100 req/sec) where small latency improvements compound.

---

### Claim: "Sub-millisecond cached responses (0.5-2ms)"

**What this means**: Cached GraphQL queries return in 0.5-2ms when all optimization layers are active.

**Methodology**:

- **APQ caching**: SHA-256 hash lookup with PostgreSQL storage backend
- **Rust pipeline**: Direct database JSONB → Rust transformation → HTTP response (no Python string operations)
- **Field projection**: Optional filtering of requested GraphQL fields
- **Measurement**: Time from GraphQL request to HTTP response (excluding network latency)

**Realistic expectations**:

- **Cache hit**: 0.5-2ms (Rust pipeline + APQ)
- **Cache miss**: 5-25ms (includes database query)
- **Cache hit rate**: 85-95% in production applications

**Conditions**:

- PostgreSQL 15+ with proper indexing
- APQ storage backend configured (PostgreSQL recommended)
- Query complexity score < 100
- Response size < 50KB
- Exclusive Rust pipeline active (automatic in v1.0.0+)

---

### Claim: "85-95% cache hit rates in production applications"

**What this means**: Well-designed applications achieve 85-95% APQ cache hit rates with the exclusive Rust pipeline.

**Methodology**:

- **Client configuration**: Apollo Client with persisted queries enabled
- **Query patterns**: Stable query structure (no dynamic field selection)
- **Cache TTL**: 1-24 hours depending on data freshness requirements
- **Measurement**: Cache hits / (cache hits + cache misses) over 24-hour period

**Realistic expectations**:

- **Stable APIs**: 95%+ hit rate
- **Dynamic queries**: 80-90% hit rate
- **Admin interfaces**: 70-85% hit rate (more unique queries)

**Factors affecting hit rate**:

- Query stability (fewer unique queries = higher hit rate)
- Client-side query deduplication
- Cache TTL settings
- Query complexity (simple queries cache better)
- Rust pipeline compatibility (automatic)

---

### Claim: "0.05-0.5ms table view responses"

**What this means**: Table views (`tv_*`) provide instant responses for complex queries, processed through the exclusive Rust pipeline.

**Methodology**:

- **Table views**: Denormalized tables with pre-computed data
- **Comparison**: Traditional JOIN queries vs table view lookups
- **Dataset**: 10k users with 50k posts (average 5 posts/user)
- **Measurement**: Database query time only (EXPLAIN ANALYZE)

**Realistic expectations**:

- **Table view lookup**: 0.05-0.5ms
- **Traditional JOIN**: 5-50ms (depends on data size)
- **Speedup**: 10-100x faster for complex nested queries
- **Rust pipeline**: Automatic camelCase transformation and __typename injection

**When this applies**:

- Read-heavy workloads with stable data relationships
- Queries with fixed nesting patterns
- Applications where data freshness is less critical than speed

---

## Typical vs Optimal Scenarios

### Typical Production Application (85th percentile)

**Response Times**:

- Simple queries: 1-5ms
- Complex queries: 5-25ms
- Cached queries: 0.5-2ms

**Configuration**:

```python
# Standard production setup
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    apq_storage_backend="postgresql",  # APQ is on by default (apq_mode="optional")
    complexity_max_score=1000,
)
```

**Performance Characteristics**:

- Cache hit rate: 85-95%
- Database load: Moderate (most queries cached)
- Memory usage: 200-500MB per instance
- CPU usage: 20-40% under normal load

### High-Performance Optimized Application (99th percentile)

**Response Times**:

- Simple queries: 0.5-2ms
- Complex queries: 2-10ms
- Cached queries: 0.2-1ms

**Configuration**:

```python
# Maximum performance setup
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    apq_storage_backend="postgresql",  # APQ is on by default (apq_mode="optional")
    complexity_max_score=500,
)
```

**Performance Characteristics**:

- Cache hit rate: 95%+
- Database load: Low (extensive caching)
- Memory usage: 500MB-1GB per instance
- CPU usage: 10-30% under normal load

---

## Query Complexity Impact

### Complexity Scoring

FraiseQL calculates query complexity to prevent expensive operations:

```python
# Complexity calculation
complexity = field_count + (list_size * nested_fields) + multipliers

# Example multipliers
field_multipliers = {
    "search": 5,      # Text search operations
    "aggregate": 10,  # COUNT, SUM, AVG operations
    "sort": 2,        # ORDER BY clauses
}
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
- Field projection for reduced data transfer
- Table views for instant responses

**Medium Complexity (51-200)**:

- Table views for nested relationships
- Database indexing optimization
- Query result caching
- Field projection optimization

**High Complexity (201-500)**:

- Materialized views for aggregations
- Background computation
- Result caching with short TTL
- Minimize JSONB size in table views

---

## CASCADE Selection Optimization

### Overview

CASCADE data can add significant payload size to mutation responses. Use selective requesting to optimize performance.

### Payload Size Comparison

| Selection | Typical Size | Use Case |
|-----------|-------------|----------|
| No CASCADE | 200-500 bytes | Display-only mutations |
| Metadata only | 300-600 bytes | Need count info only |
| Invalidations only | 400-800 bytes | Cache clearing only |
| Full CASCADE | 1,500-5,000 bytes | Complete cache sync |

### Best Practices

**1. Request Only What You Need**

```graphql
# ❌ Bad: Request everything when you only need count
cascade {
  updated { __typename id operation entity }
  deleted { __typename id }
  invalidations { queryName strategy scope }
  metadata { timestamp affectedCount }
}

# ✅ Good: Request only metadata
cascade {
  metadata { affectedCount }
}
```

**2. Use Conditional CASCADE with Directives**

```graphql
mutation CreatePost($input: CreatePostInput!, $needCascade: Boolean!) {
  createPost(input: $input) {
    ... on CreatePostSuccess {
      post { id title }
      cascade @include(if: $needCascade) {
        updated { __typename id entity }
      }
    }
  }
}
```

**3. Profile Your Queries**

Use GraphQL query complexity analysis to understand CASCADE impact:

```javascript
// Measure response size
const response = await client.mutate({ mutation: CREATE_POST });
console.log('Response size:', JSON.stringify(response).length);

// Compare with and without CASCADE
```

**4. Mobile-Specific Optimizations**

For mobile clients, avoid CASCADE on:

- Background sync operations
- Bulk operations
- Low-priority mutations

Request CASCADE only on user-initiated, UI-critical mutations.

### Performance Monitoring

Track CASCADE payload sizes in production:

```python
from prometheus_client import Histogram

cascade_payload_size = Histogram(
    'graphql_cascade_payload_bytes',
    'CASCADE payload size in bytes',
    buckets=[100, 500, 1000, 5000, 10000, 50000]
)
```

Alert on large payloads:

```yaml
- alert: LargeCascadePayloads
  expr: histogram_quantile(0.95, cascade_payload_bytes) > 10000
  for: 5m
```

---

## When Performance Matters

### 🚀 Performance-Critical Scenarios

**Choose FraiseQL when you need**:

1. **High-throughput APIs** (>500 req/sec per instance)
   - Small latency improvements compound significantly
   - 1ms saved = 500ms saved per 500 requests/second

2. **Real-time applications** (chat, gaming, live dashboards)
   - Sub-10ms response times enable real-time UX
   - WebSocket connections with frequent GraphQL subscriptions

3. **Mobile applications** (limited bandwidth, battery)
   - 70% bandwidth reduction with APQ
   - Faster responses improve mobile UX

4. **Microservices orchestration**
   - Single database reduces network hops
   - Faster aggregation of data from multiple services

5. **Cost optimization**
   - Save $300-3,000/month vs Redis + Sentry
   - Fewer services to manage and monitor

### 📊 Performance-Neutral Scenarios

**FraiseQL works well for**:

1. **CRUD applications** (admin panels, CMS)
   - Standard 5-25ms response times acceptable
   - Developer productivity benefits outweigh raw performance

2. **Internal APIs** (company dashboards, tools)
   - Predictable performance with caching
   - Operational simplicity valuable

3. **Prototyping/MVPs**
   - Fast time-to-market (1-2 weeks)
   - Good enough performance for early users

### ⚠️ Performance-Challenging Scenarios

**Consider alternatives when**:

1. **Ultra-low latency** (< 1ms required)
   - Custom C/Rust services for extreme performance
   - Specialized databases (Redis, ClickHouse)

2. **Massive scale** (> 10,000 req/sec)
   - Distributed databases (CockroachDB, Yugabyte)
   - Service mesh architectures

3. **Complex computations**
   - External compute services (Spark, Ray)
   - Specialized databases for analytics

---

## Baseline Comparisons

### Framework Comparison (Real Measurements)

| Framework | Simple Query | Complex Query | Setup Time | Maintenance |
|-----------|-------------|---------------|------------|-------------|
| **FraiseQL** | **5-15ms** | **15-50ms** | **1-2 weeks** | **Low** |
| Strawberry + SQLAlchemy | 50-100ms | 200-400ms | 2-4 weeks | Medium |
| Hasura | 25-75ms | 150-300ms | 1 week | Low |
| PostGraphile | 50-100ms | 200-400ms | 2-3 weeks | Medium |

**Test conditions**:

- PostgreSQL 15, 10k records
- Standard cloud instance (4 CPU, 8GB RAM)
- Connection pooling enabled
- Proper indexing

### Database-Only Comparison

| Approach | Response Time | Development Time | Flexibility |
|----------|---------------|------------------|-------------|
| **FraiseQL (Database-first)** | **5-25ms** | **1-2 weeks** | **High** |
| Stored Procedures | 5-15ms | 3-6 weeks | Low |
| ORM (SQLAlchemy) | 25-100ms | 1-2 weeks | High |
| Raw SQL | 5-50ms | 2-4 weeks | Medium |

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
- 10-100GB storage for APQ cache

### PostgreSQL Configuration

```sql
-- Recommended for FraiseQL
shared_buffers = 256MB          -- 25% of RAM
effective_cache_size = 1GB       -- 75% of RAM
work_mem = 16MB                  -- Per-connection sort memory
max_connections = 100            -- Connection pool size
statement_timeout = 5000         -- Prevent long queries
```

### Connection Pooling

```python
# Recommended settings
config = FraiseQLConfig(
    database_pool_size=20,        # 20% of max_connections
    database_max_overflow=10,     # Burst capacity
    database_pool_timeout=5.0,    # Fail fast
)
```

---

## Monitoring & Troubleshooting

### Key Metrics to Monitor

1. **Response Time Percentiles** (p50, p95, p99)
2. **APQ Cache Hit Rate** (target: >85%)
3. **Database Connection Pool Utilization** (<80%)
4. **Query Complexity Distribution**
5. **Memory Usage Trends**

### Common Performance Issues

**Slow Queries (50-200ms)**:

```sql
-- Check for missing indexes
SELECT schemaname, tablename, attname, n_distinct, correlation
FROM pg_stats
WHERE schemaname = 'public' AND tablename LIKE 'v_%';
```

**Low Cache Hit Rate (<80%)**:

- Review query patterns for stability
- Increase cache TTL
- Implement query deduplication

**High Memory Usage**:

- Reduce complexity limits
- Implement pagination
- Monitor for memory leaks

---

*Performance Guide - Exclusive Rust Pipeline Architecture*
*Last updated: October 2025*
