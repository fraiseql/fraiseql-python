---
title: Benchmarking Guide
description: Complete guide to benchmarking FraiseQL performance with practical examples
tags:
  - benchmarking
  - performance
  - testing
  - optimization
  - metrics
---

# Benchmarking Guide

Complete guide to measuring and optimizing FraiseQL application performance.

## Overview

This guide provides practical tools and techniques for benchmarking your FraiseQL application, identifying bottlenecks, and measuring improvements.

---

## Quick Benchmark Script

```python
"""
Complete FraiseQL benchmarking script.

Requirements:
- pip install "fraiseql<2" psycopg asyncio timeit
"""

import asyncio
import time
from statistics import mean, median, stdev
from typing import List
from psycopg_pool import AsyncConnectionPool
import fraiseql

# Configure your application
DATABASE_URL = "postgresql://localhost/mydb"
ITERATIONS = 100


class BenchmarkResult:
    """Benchmark result with statistics."""

    def __init__(self, name: str, times: List[float]):
        self.name = name
        self.times = times
        self.mean = mean(times)
        self.median = median(times)
        self.min = min(times)
        self.max = max(times)
        self.stdev = stdev(times) if len(times) > 1 else 0
        self.p95 = sorted(times)[int(len(times) * 0.95)]
        self.p99 = sorted(times)[int(len(times) * 0.99)]

    def __str__(self):
        return f"""
{self.name}:
  Mean:   {self.mean * 1000:.2f}ms
  Median: {self.median * 1000:.2f}ms
  P95:    {self.p95 * 1000:.2f}ms
  P99:    {self.p99 * 1000:.2f}ms
  Min:    {self.min * 1000:.2f}ms
  Max:    {self.max * 1000:.2f}ms
  StdDev: {self.stdev * 1000:.2f}ms
"""


async def benchmark_query(pool: AsyncConnectionPool, query: str, iterations: int = ITERATIONS) -> List[float]:
    """Benchmark a GraphQL query."""
    times = []

    for _ in range(iterations):
        start = time.perf_counter()
        async with pool.connection() as conn:
            result = await conn.execute(query)
            rows = await result.fetchall()
        end = time.perf_counter()
        times.append(end - start)

    return times


async def benchmark_simple_query(pool: AsyncConnectionPool) -> BenchmarkResult:
    """Benchmark simple query (10 fields, 100 rows)."""
    query = """
        SELECT id, name, email, created_at, status,
               role, avatar_url, bio, updated_at, last_login
        FROM users
        LIMIT 100;
    """
    times = await benchmark_query(pool, query)
    return BenchmarkResult("Simple Query (10 fields, 100 rows)", times)


async def benchmark_nested_query(pool: AsyncConnectionPool) -> BenchmarkResult:
    """Benchmark nested query with relationships."""
    query = """
        SELECT
            u.id, u.name, u.email,
            jsonb_agg(
                jsonb_build_object(
                    'id', p.id,
                    'title', p.title,
                    'content', p.content
                )
            ) as posts
        FROM users u
        LEFT JOIN posts p ON p.user_id = u.id
        GROUP BY u.id, u.name, u.email
        LIMIT 50;
    """
    times = await benchmark_query(pool, query)
    return BenchmarkResult("Nested Query (User + Posts)", times)


async def benchmark_large_result(pool: AsyncConnectionPool) -> BenchmarkResult:
    """Benchmark large result set (1000 rows)."""
    query = """
        SELECT id, name, email, status, created_at
        FROM users
        LIMIT 1000;
    """
    times = await benchmark_query(pool, query)
    return BenchmarkResult("Large Result (1000 rows)", times)


async def benchmark_aggregation(pool: AsyncConnectionPool) -> BenchmarkResult:
    """Benchmark aggregation query."""
    query = """
        SELECT
            status,
            COUNT(*) as count,
            AVG(EXTRACT(EPOCH FROM (NOW() - created_at))) as avg_age_seconds
        FROM users
        GROUP BY status;
    """
    times = await benchmark_query(pool, query)
    return BenchmarkResult("Aggregation Query", times)


async def run_benchmarks():
    """Run all benchmarks."""
    print("FraiseQL Performance Benchmarks")
    print("=" * 60)
    print(f"Iterations: {ITERATIONS}")
    print(f"Database: {DATABASE_URL}")
    print("=" * 60)
    print()

    # Create connection pool
    pool = AsyncConnectionPool(
        conninfo=DATABASE_URL,
        min_size=5,
        max_size=20
    )

    try:
        # Run benchmarks
        results = []
        results.append(await benchmark_simple_query(pool))
        results.append(await benchmark_nested_query(pool))
        results.append(await benchmark_large_result(pool))
        results.append(await benchmark_aggregation(pool))

        # Print results
        for result in results:
            print(result)

        # Summary
        print("=" * 60)
        print("Summary:")
        print(f"  Total queries: {ITERATIONS * len(results)}")
        print(f"  Average query time: {mean([r.mean for r in results]) * 1000:.2f}ms")
        print("=" * 60)

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run_benchmarks())
```

---

## GraphQL-Specific Benchmarks

### Benchmark GraphQL Queries

```python
"""Benchmark GraphQL query execution."""

import asyncio
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
import time

GRAPHQL_URL = "http://localhost:8000/graphql"


async def benchmark_graphql():
    """Benchmark GraphQL queries."""
    transport = AIOHTTPTransport(url=GRAPHQL_URL)

    async with Client(transport=transport, fetch_schema_from_transport=True) as session:
        # Simple query
        query = gql("""
            query {
              users(limit: 100) {
                id
                name
                email
              }
            }
        """)

        times = []
        for _ in range(100):
            start = time.perf_counter()
            result = await session.execute(query)
            end = time.perf_counter()
            times.append(end - start)

        print(f"GraphQL Query Performance:")
        print(f"  Mean: {mean(times) * 1000:.2f}ms")
        print(f"  P95:  {sorted(times)[95] * 1000:.2f}ms")


asyncio.run(benchmark_graphql())
```

---

## Load Testing with Locust

### Installation

```bash
pip install locust
```

### Locust Test Script

```python
"""
locustfile.py - Load testing for FraiseQL GraphQL API

Run: locust -f locustfile.py --host=http://localhost:8000
"""

from locust import HttpUser, task, between
import json


class FraiseQLUser(HttpUser):
    """Simulates GraphQL API user."""

    wait_time = between(1, 3)

    @task(3)
    def query_users(self):
        """Query users list (most common operation)."""
        query = """
            query {
              users(limit: 20) {
                id
                name
                email
              }
            }
        """
        self.client.post(
            "/graphql",
            json={"query": query},
            headers={"Content-Type": "application/json"}
        )

    @task(2)
    def query_user_with_posts(self):
        """Query user with nested posts."""
        query = """
            query {
              user(id: "550e8400-e29b-41d4-a716-446655440000") {
                id
                name
                email
                posts {
                  id
                  title
                }
              }
            }
        """
        self.client.post(
            "/graphql",
            json={"query": query},
            headers={"Content-Type": "application/json"}
        )

    @task(1)
    def mutation_create_post(self):
        """Create post mutation."""
        mutation = """
            mutation {
              createPost(input: {
                title: "Test Post"
                content: "Load test content"
              }) {
                status
                message
                entity {
                  id
                  title
                }
              }
            }
        """
        self.client.post(
            "/graphql",
            json={"query": mutation},
            headers={"Content-Type": "application/json"}
        )
```

### Run Load Test

```bash
# Start with 10 users, ramp up to 100
locust -f locustfile.py --host=http://localhost:8000 \
       --users 100 --spawn-rate 10

# Headless mode (no web UI)
locust -f locustfile.py --host=http://localhost:8000 \
       --users 100 --spawn-rate 10 --headless \
       --run-time 5m --html report.html
```

---

## Database Query Analysis

### EXPLAIN ANALYZE

```python
"""Analyze query execution plans."""

import asyncio
from psycopg_pool import AsyncConnectionPool


async def analyze_query(pool: AsyncConnectionPool, query: str):
    """Run EXPLAIN ANALYZE on query."""
    async with pool.connection() as conn:
        explain_query = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"
        result = await conn.execute(explain_query)
        plan = await result.fetchone()

        # Parse execution plan
        plan_data = plan[0][0]
        execution_time = plan_data['Execution Time']
        planning_time = plan_data['Planning Time']

        print(f"Query: {query[:50]}...")
        print(f"  Planning Time: {planning_time:.2f}ms")
        print(f"  Execution Time: {execution_time:.2f}ms")
        print(f"  Total Time: {planning_time + execution_time:.2f}ms")

        return plan_data


# Example usage
DATABASE_URL = "postgresql://localhost/mydb"
pool = AsyncConnectionPool(conninfo=DATABASE_URL)

query = "SELECT * FROM users WHERE status = 'active' LIMIT 100"
asyncio.run(analyze_query(pool, query))
```

### pg_stat_statements

```sql
-- Enable pg_stat_statements extension
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- View slowest queries
SELECT
    query,
    calls,
    total_exec_time / 1000.0 as total_seconds,
    mean_exec_time as avg_ms,
    max_exec_time as max_ms
FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat_statements%'
ORDER BY total_exec_time DESC
LIMIT 20;

-- Reset statistics
SELECT pg_stat_statements_reset();
```

---

## Continuous Monitoring

### Prometheus Metrics

```python
"""Export Prometheus metrics."""

from prometheus_client import Counter, Histogram, generate_latest
from fastapi import FastAPI

app = FastAPI()

# Define metrics
graphql_requests = Counter('graphql_requests_total', 'Total GraphQL requests')
graphql_duration = Histogram('graphql_duration_seconds', 'GraphQL query duration')
database_queries = Counter('database_queries_total', 'Total database queries')


@app.middleware("http")
async def metrics_middleware(request, call_next):
    """Collect metrics for each request."""
    if request.url.path == "/graphql":
        graphql_requests.inc()

        with graphql_duration.time():
            response = await call_next(request)

        return response

    return await call_next(request)


@app.get("/metrics")
async def metrics():
    """Expose Prometheus metrics."""
    return generate_latest()
```

---

## Performance Checklist

### Before Optimization

- [ ] Run baseline benchmarks (simple, nested, large queries)
- [ ] Identify slowest queries using pg_stat_statements
- [ ] Profile application with cProfile/py-spy
- [ ] Check database connection pool utilization
- [ ] Measure end-to-end latency with real user traffic

### During Optimization

- [ ] Add indexes for slow queries
- [ ] Optimize N+1 queries with JOINs or data loader
- [ ] Enable Rust pipeline for JSON transformation
- [ ] Configure connection pooling (min/max sizes)
- [ ] Add caching for frequently accessed data

### After Optimization

- [ ] Re-run benchmarks to measure improvement
- [ ] Validate P95/P99 latency targets met
- [ ] Load test with expected peak traffic
- [ ] Monitor metrics in production for 24 hours
- [ ] Document baseline and improved performance

---

## Performance Targets

**Recommended Targets** (P95):

- Simple queries (< 10 fields): **< 10ms**
- Nested queries (1-2 levels): **< 50ms**
- Large result sets (1000 rows): **< 100ms**
- Mutations: **< 20ms**

**Production Benchmarks** (FraiseQL v1.9+):

- JSON transformation overhead: **< 0.1ms** (Rust pipeline)
- Connection pool acquisition: **< 1ms**
- GraphQL parsing: **< 5ms**
- Total overhead (non-DB time): **< 10ms**

---

## Tools

**Benchmarking**:

- [Locust](https://locust.io/) - Load testing
- [Artillery](https://artillery.io/) - Load testing with scenarios
- [k6](https://k6.io/) - JavaScript load testing

**Profiling**:

- [py-spy](https://github.com/benfred/py-spy) - Python profiler
- [cProfile](https://docs.python.org/3/library/profile.html) - Built-in profiler
- [memory_profiler](https://pypi.org/project/memory-profiler/) - Memory usage

**Monitoring**:

- [Prometheus](https://prometheus.io/) - Metrics collection
- [Grafana](https://grafana.com/) - Metrics visualization
- [pg_stat_statements](https://www.postgresql.org/docs/current/pgstatstatements.html) - PostgreSQL query stats

---

## See Also

- [Performance Guide](index.md) - Overview and optimization strategies
- [Rust Pipeline Architecture](../core/rust-pipeline-integration.md) - 7-10x JSON speedup
- [Monitoring](../production/monitoring.md) - Production monitoring
- [Observability](../production/observability.md) - Distributed tracing
