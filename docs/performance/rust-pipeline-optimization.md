# Rust Pipeline Performance Optimization

How to get the best performance from FraiseQL's Rust pipeline.

## Performance Characteristics

The Rust pipeline is **already optimized** and provides 0.5-5ms response times out of the box. However, you can improve end-to-end performance with these strategies.

## 1. Optimize Database Queries (Biggest Impact)

The Rust pipeline is fast (< 1ms), but database queries can take 1-100ms+ depending on complexity.

### Use Table Views (tv_*)

Pre-compute denormalized data in the database:

```sql
-- Slow: Compute JSONB on every query
SELECT jsonb_build_object(
    'id', u.id,
    'first_name', u.first_name,
    'posts', (SELECT jsonb_agg(...) FROM posts WHERE user_id = u.id)
) FROM tb_user u;
-- Takes: 10-50ms for complex queries

-- Fast: Pre-computed data in table view
SELECT * FROM tv_user WHERE id = $1;
-- Takes: 0.5-2ms (just index lookup!)
```

**Impact**: 5-50x faster database queries

### Index Properly

```sql
-- Index JSONB paths used in WHERE clauses
CREATE INDEX idx_user_email ON tv_user ((data->>'email'));

-- Index foreign keys
CREATE INDEX idx_post_user_id ON tb_post (fk_user);
```

## 2. Enable Field Projection

Let Rust filter only requested fields:

```graphql
# Client requests only these fields:
query {
  users {
    id
    firstName
  }
}
```

Rust pipeline will extract only `id` and `firstName` from the full JSONB, ignoring other fields.

**Configuration:** none. Field projection always happens; there is no `field_projection`
setting (`FraiseQLConfig` ignores it).

**Impact**: 20-40% faster transformation for large objects with many fields

## 3. Use Automatic Persisted Queries (APQ)

APQ is on by default (`apq_mode="optional"`). Pick where persisted queries are stored:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    apq_storage_backend="postgresql",  # or "memory" (the default)
)
```

**Benefits:**

- 85-95% cache hit rate in production
- Eliminates GraphQL parsing overhead
- Reduces bandwidth (send hash instead of full query)

**Impact**: 5-20ms saved per query

## 4. Minimize JSONB Size

Smaller JSONB = faster Rust transformation:

### Don't Include Unnecessary Data

```sql
-- ❌ Bad: Include everything
SELECT jsonb_build_object(
    'id', id,
    'first_name', first_name,
    'email', email,
    'bio', bio,  -- 1MB+ text field!
    'preferences', preferences,  -- Large JSON
    ...
) FROM tb_user;

-- ✅ Good: Only include what GraphQL needs
SELECT jsonb_build_object(
    'id', id,
    'first_name', first_name,
    'email', email
) FROM tb_user;
```

**Impact**: 2-5x faster for large objects

### Use Separate Queries for Large Fields

```graphql
# Main query: small fields
query {
  users {
    id
    firstName
  }
}

# Separate query when needed: large fields
query {
  user(id: "123") {
    bio
    preferences
  }
}
```

## 5. Batch Queries with DataLoader (if needed)

For N+1 query problems, use the DataLoader pattern: subclass
`fraiseql.optimization.dataloader.DataLoader` and implement `batch_load`, which gets
every key requested in the same tick and returns the values in the order of the keys.

```python
import asyncio

from psycopg.sql import SQL

from fraiseql.db import DatabaseQuery
from fraiseql.optimization.dataloader import DataLoader


class UserLoader(DataLoader[str, dict]):
    def __init__(self, db) -> None:
        super().__init__()
        self.db = db

    async def batch_load(self, user_ids: list[str]) -> list[dict | None]:
        rows = await self.db.run(DatabaseQuery(
            SQL("SELECT id::text AS id, data FROM v_user WHERE id = ANY(%(ids)s::uuid[])"),
            {"ids": user_ids},
        ))
        by_id = {row["id"]: row["data"] for row in rows}
        return [by_id.get(user_id) for user_id in user_ids]


user_loader = UserLoader(db)

# Batches multiple user lookups into a single query
users = await asyncio.gather(*[user_loader.load(user_id) for user_id in user_ids])
```

## 6. Monitor Rust Performance

FraiseQL exports no Rust-specific metrics. Time the requests with the Prometheus
metrics of `setup_metrics` (`fraiseql_http_request_duration_seconds`,
`fraiseql_response_time_seconds`), or the `extensions.execution.time_ms` of a
response outside production (see `include_execution_metadata`).

Typical Rust transformation times, for comparison with your own measurements:

- Simple objects: 0.1-0.5ms
- Complex nested: 0.5-2ms
- Large arrays: 1-5ms

**If higher:** Check the JSONB size of the rows and how many fields the query selects

## 7. PostgreSQL Configuration

Optimize PostgreSQL for JSONB queries:

```sql
-- postgresql.conf
shared_buffers = 4GB          -- 25% of RAM
effective_cache_size = 12GB   -- 75% of RAM
work_mem = 64MB               -- For complex queries
```

## Performance Checklist

- [ ] Use table views (tv_*) for complex queries
- [ ] Index JSONB paths used in WHERE clauses
- [ ] Enable field projection (default: enabled)
- [ ] Enable APQ for production
- [ ] Minimize JSONB size (only include needed fields)
- [ ] Use DataLoader for N+1 queries
- [ ] Monitor Rust pipeline metrics
- [ ] Optimize PostgreSQL configuration

## Benchmarking

Measure end-to-end performance:

```python
import time

start = time.time()
result = await repo.find("v_user")
duration = time.time() - start
print(f"Total time: {duration*1000:.2f}ms")
```

**Target times:**

- Simple query: < 5ms
- Complex query with joins: < 25ms
- With APQ cache hit: < 2ms

## Advanced: Custom Rust Transformations

For very specialized needs, you can extend fraiseql-rs. See [Contributing Guide](../../CONTRIBUTING.md).
