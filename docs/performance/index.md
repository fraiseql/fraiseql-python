# FraiseQL Performance Guide

FraiseQL is designed for high performance with PostgreSQL-native optimizations and Rust-powered JSON processing.

## Overview

FraiseQL achieves exceptional performance through:

- **Rust JSON Pipeline**: Fast JSON transformation and response building
- **PostgreSQL Views**: Optimized read-path with materialized views
- **Efficient SQL Generation**: Smart query planning and execution
- **Connection Pooling**: Optimal database connection management
- **Caching Layer**: Optional pg_fraiseql_cache extension

## Performance Features

### 1. Rust-Powered JSON Processing

FraiseQL uses a Rust extension for JSON operations:

```python
from fraiseql_rs import build_graphql_response, transform_json

# Fast JSON transformation
result = transform_json(data, transform_func)
```

**Performance Benchmarks** (fraiseql_rs v0.2.0):

| Test Case | Data Size | Python Time | Rust Time | Speedup |
|-----------|-----------|-------------|-----------|---------|
| Simple (10 fields) | 0.23 KB | 0.055 ms | 0.006 ms | **9.1x** |
| Medium (42 fields) | 1.07 KB | 0.122 ms | 0.016 ms | **7.7x** |
| Nested (User + 15 posts) | 7.39 KB | 0.915 ms | 0.094 ms | **9.7x** |
| Large (100 fields, deep) | 32.51 KB | 2.157 ms | 0.453 ms | **4.8x** |

**Benefits**:

- **7-10x faster JSON processing** vs pure Python (measured benchmarks)
- **2-4x faster end-to-end queries** including database time
- Zero-copy transformations where possible
- Efficient camelCase conversion
- Negligible transformation overhead (< 0.1ms for most queries)

### 2. PostgreSQL View Optimization

Read queries use PostgreSQL views for optimal performance:

```python
import fraiseql

@fraiseql.query
def get_users(info: Info) -> list[User]:
    # Automatically uses optimized view
    return info.context.repo.find("users_view")
```

**Best Practices**:

- Use views for read operations
- Create indexes on frequently queried columns
- Use materialized views for expensive aggregations

### 3. Efficient N+1 Query Prevention

FraiseQL includes DataLoader integration:

```python
from fraiseql import dataloader

@field
@dataloader
async def posts(user: User, info: Info) -> list[Post]:
    # Automatically batched
    return await info.context["db"].find("posts_view", mandatory_filters={"user_id": user.id})
```

### 4. Query Complexity Analysis

Prevent expensive queries with complexity limits:

```python
from fraiseql import ComplexityConfig

config = ComplexityConfig(
    max_complexity=1000,
    max_depth=10
)
```

## Performance Benchmarks

**Latest Results** (2025-10-17, fraiseql v0.11.5 with fraiseql_rs v0.2.0):

### Transformation Performance

- **Rust vs Python**: 7-10x faster JSON transformation
- **End-to-end queries**: 2-4x faster including database time
- **Transformation overhead**: < 0.1ms (negligible)

### Typical Query Performance

- **Simple Query**: < 1ms (with Rust pipeline)
- **Complex Query with Joins**: < 5ms
- **Nested relationships**: < 10ms (pre-composed in views)
- **Mutation**: < 10ms
- **Bulk Operations**: ~1ms per record

### APQ + TurboRouter Performance Stack

- **Base GraphQL**: 100ms average response
- **+ APQ**: 20-80ms faster (eliminates parsing)
- **+ TurboRouter**: Additional 2-3x speedup (bypasses GraphQL entirely)
- **Total**: Up to 6-9x faster for registered queries

See `benchmarks/benchmark-results.md` for detailed performance tests and reproducibility instructions.

## Optimization Tips

### 1. Database Indexes

Create indexes for frequently filtered columns:

```sql
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_posts_user_id ON posts(user_id);
```

### 2. Connection Pooling

Configure optimal pool size:

```python
from fraiseql import FraiseQLRepository

repo = FraiseQLRepository(
    pool,
    pool_size=20,  # Adjust based on load
    max_overflow=10
)
```

### 3. Caching

Enable the pg_fraiseql_cache extension:

```sql
CREATE EXTENSION IF NOT EXISTS pg_fraiseql_cache;
```

### 4. Field Selection

Only select needed fields:

```graphql
query {
  users {
    id
    name
    # Don't select unnecessary fields
  }
}
```

### 5. Pagination

Always paginate large result sets:

```python
import fraiseql

@connection
def users(
    info: Info,
    first: int = 100
) -> Connection[User]:
    return info.context.repo.find("users_view", limit=first)
```

## Monitoring

### Query Performance

Monitor query execution time:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
# Logs all SQL queries with timing
```

### Metrics

Track key metrics:

- Query execution time
- Database connection pool utilization
- Cache hit rate
- GraphQL complexity scores

## Troubleshooting

### Slow Queries

1. Check EXPLAIN ANALYZE output
2. Verify indexes exist
3. Review query complexity
4. Check connection pool status

### High Memory Usage

1. Reduce result set size with pagination
2. Limit query depth
3. Review DataLoader batch sizes
4. Check for N+1 queries

### Database Connection Issues

1. Review pool configuration
2. Check connection timeouts
3. Verify max_connections in PostgreSQL
4. Monitor connection lifecycle

## Advanced Topics

### Custom Rust Extensions

For maximum performance, write custom Rust functions:

```rust
use pyo3::prelude::*;

#[pyfunction]
fn custom_transform(data: &PyAny) -> PyResult<String> {
    // Your high-performance logic
    Ok(result)
}
```

### Query Planning

Understand PostgreSQL query plans:

```sql
EXPLAIN ANALYZE
SELECT * FROM users_view WHERE email = 'user@example.com';
```

## Further Reading

- [PostgreSQL Performance Tips](https://www.postgresql.org/docs/current/performance-tips.html)
- [GraphQL Query Complexity](https://github.com/slicknode/graphql-query-complexity)
- FraiseQL Benchmarks: `benchmarks/README.md`

---

For questions about performance optimization, open a GitHub discussion.
