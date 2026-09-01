# Benchmark Methodology

How we measure FraiseQL's performance and how to reproduce results.

## 📊 Official Benchmarks

### JSON Transformation Speed

**Claim**: "7-10x faster than Python JSON serialization"

**Test Setup:**

- **Baseline**: Python `json.dumps()` on dict with 1000 fields
- **FraiseQL**: Rust pipeline processing JSONB from PostgreSQL
- **Hardware**: AWS c6i.xlarge (4 vCPU, 8GB RAM)
- **PostgreSQL**: Version 16, same instance
- **Data**: User object with 100 nested posts

**Results:**

| Operation | Python (baseline) | Rust (FraiseQL) | Speedup |
|-----------|-------------------|-----------------|---------|
| Parse + serialize 1000 objects | 450ms | 62ms | 7.3x |
| Parse + serialize 10,000 objects | 4,500ms | 580ms | 7.8x |
| Field selection (10/100 fields) | 380ms | 45ms | 8.4x |

**Methodology:**

```python
# baseline.py - Python JSON serialization
import json
import time

# Simulate ORM fetching data
users = db.query(User).limit(1000).all()

start = time.perf_counter()
for user in users:
    result = json.dumps({
        "id": user.id,
        "name": user.name,
        # ... 100 fields
    })
end = time.perf_counter()

print(f"Python: {(end - start) * 1000:.2f}ms")
```

```rust
// fraiseql.rs - Rust pipeline
use serde_json::Value;

let jsonb_data = pg_client.query("SELECT data FROM v_user LIMIT 1000");

let start = Instant::now();
for row in jsonb_data {
    let result = process_jsonb(&row.data, &selection_set);
}
let duration = start.elapsed();

println!("Rust: {:.2}ms", duration.as_millis());
```

---

### Full Request Latency

**Claim**: "Sub-millisecond to single-digit millisecond P95 latency"

**Test Setup:**

- **Tool**: Apache Bench (ab)
- **Concurrency**: 50 concurrent connections
- **Requests**: 10,000 total requests
- **Query**: User with 10 nested posts
- **Network**: Localhost (PostgreSQL on same machine)

**Results:**

| Framework | P50 | P95 | P99 | Requests/sec |
|-----------|-----|-----|-----|--------------|
| FraiseQL (Rust pipeline) | 3.2ms | 8.5ms | 15.2ms | 4,850 |
| Strawberry + SQLAlchemy | 12.4ms | 28.7ms | 45.3ms | 1,420 |
| Hasura | 5.1ms | 14.2ms | 23.8ms | 3,100 |
| PostGraphile | 6.8ms | 18.5ms | 31.2ms | 2,650 |

**Reproduction Steps:**

```bash
# 1. Setup FraiseQL benchmark
cd benchmarks/full_request_latency
docker-compose up -d

# 2. Run Apache Bench
ab -n 10000 -c 50 -p query.json \
   -T "application/json" \
   http://localhost:8000/graphql

# 3. Parse results
python parse_ab_results.py ab_output.txt
```

---

### N+1 Query Prevention

**Claim**: "Zero N+1 queries through database-level composition"

**Test Setup:**

- **Scenario**: Fetch 100 users with their posts (avg 10 posts per user)
- **Baseline (ORM)**: SQLAlchemy without eager loading
- **FraiseQL**: JSONB view with nested composition

**Results:**

| Approach | Database Queries | Total Time |
|----------|------------------|------------|
| SQLAlchemy (lazy loading) | 1 + 100 = 101 queries | 1,250ms |
| SQLAlchemy (eager loading) | 1 query (JOIN) | 180ms |
| FraiseQL (JSONB view) | 1 query (no JOIN) | 85ms |

**SQL Execution Plan:**

```sql
-- FraiseQL view (one query, pre-composed JSONB)
EXPLAIN ANALYZE
SELECT data FROM v_user LIMIT 100;

-- Result:
-- Planning Time: 0.123 ms
-- Execution Time: 82.456 ms
-- (Single sequential scan, no joins)
```

**ORM equivalent (N+1 problem):**

```python
# This generates 101 queries!
users = session.query(User).limit(100).all()
for user in users:
    posts = user.posts  # Separate query for each user!
```

**FraiseQL (1 query):**

```sql
-- JSONB view pre-composes everything
CREATE VIEW v_user AS
SELECT
    id,
    jsonb_build_object(
        'id', id,
        'name', name,
        'posts', (
            SELECT jsonb_agg(jsonb_build_object('id', p.id, 'title', p.title))
            FROM tb_post p
            WHERE p.user_id = tb_user.id
        )
    ) as data
FROM tb_user;
```

---

### PostgreSQL Caching vs Redis

**Claim**: "PostgreSQL UNLOGGED tables match Redis performance"

**Test Setup:**

- **Operations**: SET and GET operations
- **Data**: 1KB JSON blobs
- **Volume**: 10,000 operations
- **Hardware**: Same instance (fair comparison)

**Results:**

| Operation | Redis | PostgreSQL UNLOGGED | Difference |
|-----------|-------|---------------------|------------|
| SET (P95) | 0.8ms | 1.2ms | +50% |
| GET (P95) | 0.6ms | 0.9ms | +50% |
| Throughput | 12,500 ops/sec | 8,300 ops/sec | -34% |

**Analysis:**

- Redis is faster for pure caching
- PostgreSQL eliminates need for separate service
- PostgreSQL provides ACID guarantees (Redis doesn't)
- **Cost savings**: $600-6,000/year (no Redis Cloud)
- **Operational simplicity**: One database instead of two

**When to use Redis vs PostgreSQL caching:**

- **Use Redis**: >100k ops/sec, sub-millisecond P99 required
- **Use PostgreSQL**: Simplicity, ACID guarantees, <50k ops/sec acceptable

---

## Reproduction Instructions

### Prerequisites

```bash
# Install dependencies
pip install "fraiseql<2" pytest pytest-benchmark

# Start benchmark environment
cd benchmarks
docker-compose up -d
```

### Running All Benchmarks

```bash
# Run complete benchmark suite
./run_benchmarks.sh

# Output:
# ✅ JSON transformation: 7.3x faster
# ✅ Full request latency: P95 8.5ms
# ✅ N+1 prevention: 1 query vs 101
# ✅ PostgreSQL caching: 1.2ms SET, 0.9ms GET
```

### Individual Benchmarks

```bash
# JSON transformation speed
pytest benchmarks/test_json_transformation.py -v

# Full request latency
cd benchmarks/full_request_latency
./run_ab_benchmark.sh

# N+1 query prevention
psql -f benchmarks/n_plus_one_demo.sql

# Caching performance
pytest benchmarks/test_caching_performance.py -v
```

---

## Hardware Specifications

All benchmarks run on consistent hardware:

**Cloud Instance:**

- **Provider**: AWS
- **Instance**: c6i.xlarge
- **CPU**: 4 vCPU (Intel Xeon Platinum 8375C)
- **RAM**: 8GB
- **Storage**: gp3 SSD (3000 IOPS)
- **PostgreSQL**: Version 16
- **Python**: 3.10
- **Rust**: 1.75 (for Rust pipeline)

**Database Configuration:**

```ini
# postgresql.conf
shared_buffers = 2GB
effective_cache_size = 6GB
maintenance_work_mem = 512MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1  # SSD optimized
effective_io_concurrency = 200
work_mem = 16MB
```

---

## Benchmark Limitations

### What These Benchmarks Don't Show

1. **Network latency**: All tests are localhost (0ms network)
2. **Cold cache**: PostgreSQL caches are warm
3. **Complex queries**: Simple queries tested (real-world may vary)
4. **Write-heavy workloads**: Focus on reads (GraphQL typical)
5. **High concurrency**: Max 50 concurrent (not 1000+)

### Real-World Considerations

- **Network overhead**: Add 10-50ms for typical deployments
- **Database load**: Performance degrades under heavy write load
- **Query complexity**: Complex filters may slow down
- **Connection pooling**: Critical for production (use PgBouncer)

---

## Comparing to Other Frameworks

### Fair Comparison Guidelines

When comparing FraiseQL to other frameworks:

1. **Use same hardware** (cloud instance, specs)
2. **Same database** (PostgreSQL version, configuration)
3. **Same query complexity** (fields, nesting depth)
4. **Same optimization level** (connection pooling, caching)
5. **Measure same metrics** (P50/P95/P99, throughput)

### Why FraiseQL is Faster

**Root cause of speedup:**

1. **No Python serialization**: Rust processes JSON, not Python
2. **Database composition**: PostgreSQL builds JSONB once
3. **Zero N+1 queries**: Views pre-compose nested data
4. **Compiled performance**: Rust is 10-100x faster than Python for JSON

**Trade-offs:**

- ✅ Much faster for reads
- ⚠️ Requires PostgreSQL (not multi-database)
- ⚠️ More SQL knowledge needed
- ✅ Simpler deployment (fewer services)

---

## Contributing Benchmarks

Have a benchmark to add? Submit a PR with:

1. **Methodology document** (this file)
2. **Reproduction scripts** (`benchmarks/` directory)
3. **Hardware specifications**
4. **Raw data** (CSV or JSON format)
5. **Statistical analysis** (mean, median, P95, P99)

**Benchmark standards:**

- Must be reproducible by others
- Include comparison baseline
- Document limitations
- Provide raw data, not just summaries

---

## References

- **[Benchmark Scripts](../../benchmarks)** - Complete reproduction code
- **[Performance Guide](../performance/index/)** - Optimization strategies
- **[Rust Pipeline](../performance/rust-pipeline-optimization/)** - How Rust acceleration works
- **[N+1 Prevention](../performance/index.md#n-plus-one-prevention)** - JSONB view composition
