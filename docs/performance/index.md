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

FraiseQL uses a Rust extension, shipped inside the `fraiseql` package, for JSON
operations. `db.find` / `db.find_one` and class mutations call it; applications don't
need to. On its own:

```python
from fraiseql import fraiseql_rs

# snake_case keys to camelCase, without loading the JSON into Python objects
print(fraiseql_rs.transform_json('{"user_name": "John", "email_address": "john@example.com"}'))
# {"userName":"John","emailAddress":"john@example.com"}
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
from fraiseql.types import ID


@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: str


@fraiseql.query
async def users(info, limit: int = 100) -> list[User]:
    # Reads the view's data column; Rust builds the response
    return await info.context["db"].find("v_user", "users", info, limit=limit)
```

**Best Practices**:

- Use views for read operations
- Create indexes on frequently queried columns
- Use materialized views for expensive aggregations

### 3. Efficient N+1 Query Prevention

The first defence is the view itself: compose related data into the parent's
`data` column (a `jsonb_agg` of a user's posts in `v_user`), so one query answers the
whole tree. For fields that can't be composed in the view, FraiseQL has DataLoader
integration (`@fraiseql.dataloader_field` with a `DataLoader` subclass from
`fraiseql.optimization.dataloader`); see
[Avoid N+1 Query Problem](../guides/performance-optimization.md#1-avoid-n1-query-problem).

### 4. Query Complexity Analysis

Prevent expensive queries with complexity limits:

```python
from fraiseql.fastapi import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    max_query_depth=10,          # QUERY_TOO_DEEP past 10 levels
    complexity_max_score=1000,   # QUERY_TOO_COMPLEX over 1000
)
```

Both are checked before the query runs; no limit is on by default.

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

Configure the pool size of the app's connection pool:

```python
from fraiseql.fastapi import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    database_pool_size=20,  # Adjust based on load
    database_max_overflow=10,
)
```

`create_fraiseql_app(config=config, ...)` opens the pool; `connection_pool_size=` and
`connection_pool_max_overflow=` on `create_fraiseql_app` set the same values.

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
@fraiseql.query
async def users_page(info, limit: int = 100, offset: int = 0) -> list[User]:
    return await info.context["db"].find(
        "v_user", "usersPage", info, limit=limit, offset=offset, order_by=[{"id": "ASC"}]
    )
```

For cursor pagination, `@fraiseql.connection` pages a view with `first` / `after`
(see [`paginate()`](../reference/database.md#paginate)).

## Monitoring

### Query Performance

Monitor query execution time:

Time the SQL in PostgreSQL itself, where every statement FraiseQL sends shows up:

```sql
-- Log every statement slower than 100 ms
ALTER SYSTEM SET log_min_duration_statement = '100ms';
SELECT pg_reload_conf();
```

or read `pg_stat_statements` (`fraiseql.monitoring.init_query_stats` reads it for
you).

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
