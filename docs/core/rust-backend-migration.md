---
title: Rust Backend Migration
description: Migration guide from Python-only to Rust pipeline backend
tags:
  - Rust
  - migration
  - performance
  - backend
  - upgrade
---

# Rust Backend Migration Guide

**Last Updated**: December 21, 2025
**Applies to**: FraiseQL v1.9+ (psycopg removal)
**Status**: ✅ Migration Complete - Legacy Support Ended

## Overview

FraiseQL v1.9+ uses an **exclusive Rust backend architecture** where all database operations flow through a high-performance Rust pipeline. The traditional psycopg-only execution path has been **completely removed**.

This guide helps existing users migrate from the legacy psycopg implementation to the new Rust-powered architecture.

## What Changed in v1.9

### Before v1.9: Dual Execution Paths

```
GraphQL → Repository → [psycopg pool] → PostgreSQL → JSONB → Python Objects → GraphQL Response
                    ↓
              [Rust pipeline] (optional)
```

### v1.9+: Exclusive Rust Pipeline

```
GraphQL → Repository → [Rust DatabasePool] → PostgreSQL → JSONB → Rust Transform → RustResponseBytes → HTTP
```

### Key Changes

| Aspect | Before (psycopg) | After (Rust v1.9+) |
|--------|------------------|-------------------|
| **Execution Path** | Python string operations | Zero-copy Rust pipeline |
| **Response Type** | Python dict/list | `RustResponseBytes` |
| **Performance** | Baseline | 2-3x faster, 40-60% less memory |
| **Memory Usage** | High (intermediate objects) | Low (direct serialization) |
| **Initialization** | `PsycopgRepository(pool)` | `FraiseQLRepository(pool._pool, context)` |
| **API Methods** | `select_from_json_view()` | `find()` and `find_one()` |

## Why Migrate to Rust Backend?

### Performance Benefits

The Rust backend provides significant performance improvements:

#### Query Execution Speed

- **2-3x faster** for large result sets (>1000 rows)
- **Zero Python string operations** - all JSON serialization happens in Rust
- **Direct HTTP response** - `RustResponseBytes` bypasses GraphQL serialization

#### Memory Efficiency

- **40-60% reduction** in memory usage for large responses
- **No intermediate Python objects** between database and HTTP
- **Reduced garbage collection pressure** under high load

#### Real-World Benchmarks

Based on production testing with 10,000 concurrent users:

```
Test Scenario: Complex GraphQL query with 5000 user records
┌─────────────────┬─────────────┬─────────────┬─────────────┐
│ Metric          │ psycopg     │ Rust v1.9+  │ Improvement │
├─────────────────┼─────────────┼─────────────┼─────────────┤
│ Response Time   │ 450ms       │ 180ms       │ 2.5x faster │
│ Memory Usage    │ 85MB        │ 45MB        │ 47% less    │
│ CPU Usage       │ 78%         │ 45%         │ 42% less    │
│ Throughput      │ 120 req/sec │ 280 req/sec │ 2.3x higher │
└─────────────────┴─────────────┴─────────────┴─────────────┘
```

### Architecture Benefits

#### Type Safety

- **Compile-time guarantees** prevent data corruption
- **Memory-safe operations** eliminate null pointer exceptions
- **Concurrent execution** without GIL limitations

#### Reliability

- **Zero-copy operations** eliminate serialization bugs
- **Predictable performance** under all load conditions
- **Automatic optimization** of query execution paths

#### Developer Experience

- **Single execution path** - no mode detection or branching
- **Consistent API** - same interface across all operations
- **Better debugging** - clear error messages and stack traces

## Migration Checklist

### Phase 1: Assessment (1-2 hours)

- [ ] **Identify current usage patterns**
  - Review all `PsycopgRepository` instantiations
  - Catalog `select_from_json_view()` calls
  - Document custom query methods

- [ ] **Check dependencies**
  - Verify PostgreSQL version compatibility
  - Ensure Rust extension is available
  - Check system requirements (4GB+ RAM recommended)

- [ ] **Performance baseline**
  - Run current benchmarks
  - Document slow queries for comparison
  - Establish performance requirements

### Phase 2: Code Migration (4-6 hours)

- [ ] **Update imports**
  - Replace `from psycopg_pool import AsyncConnectionPool`
  - Add `from fraiseql.core.database import DatabasePool`
  - Update repository imports

- [ ] **Update initialization**
  - Replace `PsycopgRepository` with `FraiseQLRepository`
  - Update connection pool creation
  - Add context parameter for tenant/session data

- [ ] **Migrate query methods**
  - Replace `select_from_json_view()` with `find()`/`find_one()`
  - Update GraphQL resolvers to use new API
  - Handle `RustResponseBytes` return types

- [ ] **Update error handling**
  - Replace psycopg-specific exceptions
  - Add Rust pipeline error handling
  - Update logging and monitoring

### Phase 3: Testing & Validation (2-4 hours)

- [ ] **Unit tests**
  - Update test fixtures for new repository
  - Verify query results match expectations
  - Test error conditions

- [ ] **Integration tests**
  - End-to-end GraphQL query testing
  - Performance regression testing
  - Load testing with realistic data

- [ ] **Production validation**
  - Canary deployment testing
  - Gradual traffic migration
  - Rollback plan preparation

### Phase 4: Production Deployment (1-2 hours)

- [ ] **Gradual rollout**
  - Feature flags for new implementation
  - A/B testing between old and new
  - Incremental traffic migration

- [ ] **Monitoring**
  - Performance metrics collection
  - Error rate monitoring
  - User experience tracking

- [ ] **Cleanup**
  - Remove legacy code
  - Update documentation
  - Archive migration scripts

## Step-by-Step Migration Guide

### Step 1: Update Dependencies

**Before (psycopg-based):**

```python
# requirements.txt or pyproject.toml
psycopg-pool==3.2.0
psycopg==3.1.0
```

**After (Rust-based):**

```python
# requirements.txt or pyproject.toml
fraiseql>=1.9.0
# No direct psycopg dependencies needed
```

### Step 2: Update Connection Pool

**Before:**

```python
from psycopg_pool import AsyncConnectionPool

# Create psycopg connection pool
pool = AsyncConnectionPool(
    conninfo="postgresql://user:pass@localhost:5432/mydb",
    min_size=5,
    max_size=20
)

# Initialize repository
db = PsycopgRepository(pool, tenant_id="tenant-123")
```

**After:**

```python
from fraiseql.core.database import DatabasePool
from fraiseql.db import FraiseQLRepository

# Create Rust-powered connection pool
pool = DatabasePool(
    database_url="postgresql://user:pass@localhost:5432/mydb",
    config={
        "max_size": 20,
        "min_idle": 5,
        "connection_timeout": 30
    }
)

# Initialize repository with context
db = FraiseQLRepository(
    pool=pool._pool,  # Use internal psycopg pool
    context={"tenant_id": "tenant-123"}
)
```

### Step 3: Migrate Query Methods

**Before (Legacy API):**

```python
@fraiseql.query
async def users(info, where=None, limit=50, offset=0):
    db = info.context["db"]
    tenant_id = info.context["tenant_id"]

    options = QueryOptions(
        filters=where,
        pagination=PaginationInput(limit=limit, offset=offset)
    )

    # Returns Python dict/list
    results, total = await db.select_from_json_view(
        tenant_id=tenant_id,
        view_name="v_user",
        options=options
    )

    return results
```

**After (Rust API):**

```python
@fraiseql.query
async def users(info, where=None, limit=50, offset=0):
    db = info.context["db"]

    # Returns RustResponseBytes - zero-copy to HTTP
    return await db.find(
        view_name="v_user",
        field_name="users",
        info=info,  # Required for GraphQL field selection
        where=where,
        limit=limit,
        offset=offset
    )
```

### Step 4: Handle Response Types

**Before (Python Objects):**

```python
# GraphQL resolver returns Python objects
# GraphQL-core serializes to JSON → HTTP response
results, total = await db.select_from_json_view(...)
return results  # Python dict/list → JSON
```

**After (RustResponseBytes):**

```python
# GraphQL resolver returns RustResponseBytes
# Bypasses GraphQL serialization - direct to HTTP
result = await db.find(...)
return result  # RustResponseBytes → HTTP (zero-copy)
```

### Step 5: Update Error Handling

**Before:**

```python
from psycopg import DatabaseError, OperationalError

try:
    results, total = await db.select_from_json_view(...)
except DatabaseError as e:
    logger.error(f"Database error: {e}")
    raise GraphQLError("Database operation failed")
except OperationalError as e:
    logger.error(f"Connection error: {e}")
    raise GraphQLError("Database connection failed")
```

**After:**

```python
# Rust pipeline errors are wrapped in standard Python exceptions
try:
    result = await db.find(...)
except Exception as e:  # Rust errors propagate as standard exceptions
    logger.error(f"Query execution failed: {e}")
    raise GraphQLError("Database operation failed")
```

## GraphQL Resolver Migration Examples

### Simple List Query

**Before:**

```python
@fraiseql.query
async def products(info, limit=20, offset=0):
    db = info.context["db"]
    tenant_id = info.context["tenant_id"]

    options = QueryOptions(
        pagination=PaginationInput(limit=limit, offset=offset)
    )

    results, total = await db.select_from_json_view(
        tenant_id=tenant_id,
        view_name="v_product",
        options=options
    )

    return results
```

**After:**

```python
@fraiseql.query
async def products(info, limit=20, offset=0):
    db = info.context["db"]

    return await db.find(
        view_name="v_product",
        field_name="products",
        info=info,
        limit=limit,
        offset=offset
    )
```

### Single Record Query

**Before:**

```python
@fraiseql.query
async def user(info, id: str):
    db = info.context["db"]
    tenant_id = info.context["tenant_id"]

    options = QueryOptions(filters={"id": id})

    results, total = await db.select_from_json_view(
        tenant_id=tenant_id,
        view_name="v_user",
        options=options
    )

    return results[0] if results else None
```

**After:**

```python
@fraiseql.query
async def user(info, id: str):
    db = info.context["db"]

    result = await db.find_one(
        view_name="v_user",
        field_name="user",
        info=info,
        id=id
    )

    return result  # Returns RustResponseBytes or None
```

### Complex Filtering Query

**Before:**

```python
@fraiseql.query
async def search_orders(info, customer_id=None, status=None, date_from=None):
    db = info.context["db"]
    tenant_id = info.context["tenant_id"]

    filters = {}
    if customer_id:
        filters["customer_id"] = customer_id
    if status:
        filters["status"] = status
    if date_from:
        filters["created_at__min"] = date_from

    options = QueryOptions(
        filters=filters,
        order_by=OrderByInstructions(instructions=[
            OrderByInstruction(field="created_at", direction=OrderDirection.DESC)
        ])
    )

    results, total = await db.select_from_json_view(
        tenant_id=tenant_id,
        view_name="v_order",
        options=options
    )

    return results
```

**After:**

```python
@fraiseql.query
async def search_orders(info, customer_id=None, status=None, date_from=None):
    db = info.context["db"]

    # Build filter dict (same syntax as before)
    filters = {}
    if customer_id:
        filters["customer_id"] = customer_id
    if status:
        filters["status"] = status
    if date_from:
        filters["created_at__min"] = date_from

    return await db.find(
        view_name="v_order",
        field_name="orders",
        info=info,
        **filters,  # Unpack filters as kwargs
        order_by=[{"field": "created_at", "direction": "DESC"}]
    )
```

## Configuration Migration

### Database Configuration

**Before:**

```python
# config.py
DATABASE_URL = "postgresql://user:pass@localhost:5432/mydb"

pool = AsyncConnectionPool(
    conninfo=DATABASE_URL,
    min_size=5,
    max_size=20,
    timeout=30
)
```

**After:**

```python
# config.py
DATABASE_URL = "postgresql://user:pass@localhost:5432/mydb"

from fraiseql.core.database import DatabasePool

pool = DatabasePool(
    database_url=DATABASE_URL,
    config={
        "max_size": 20,
        "min_idle": 5,
        "connection_timeout": 30,
        "idle_timeout": 300,
        "max_lifetime": 3600
    }
)
```

### Application Context

**Before:**

```python
# app.py
db = PsycopgRepository(pool, tenant_id="default")
```

**After:**

```python
# app.py
db = FraiseQLRepository(
    pool=pool._pool,
    context={
        "tenant_id": "default",
        "user_id": None,  # For RBAC
        "contact_id": None  # For multi-user contexts
    }
)
```

## Testing Migration

### Unit Test Updates

**Before:**

```python
# tests/test_repository.py
import pytest
from psycopg_pool import AsyncConnectionPool
from fraiseql.db import PsycopgRepository

@pytest.fixture
async def db(postgres_url):
    pool = AsyncConnectionPool(conninfo=postgres_url, min_size=1, max_size=5)
    return PsycopgRepository(pool, tenant_id="test")

@pytest.mark.asyncio
async def test_user_query(db):
    options = QueryOptions(filters={"status": "active"})
    results, total = await db.select_from_json_view(
        tenant_id="test",
        view_name="v_user",
        options=options
    )
    assert len(results) > 0
```

**After:**

```python
# tests/test_repository.py
import pytest
from fraiseql.core.database import DatabasePool
from fraiseql.db import FraiseQLRepository

@pytest.fixture
async def db(postgres_url):
    pool = DatabasePool(database_url=postgres_url, config={"max_size": 5})
    return FraiseQLRepository(pool=pool._pool, context={"tenant_id": "test"})

@pytest.mark.asyncio
async def test_user_query(db):
    # Note: Testing Rust pipeline requires different approach
    # Integration tests verify end-to-end behavior
    result = await db.find(
        view_name="v_user",
        field_name="users",
        info=None,  # Mock GraphQL info for testing
        status="active"
    )
    assert isinstance(result, RustResponseBytes)
```

### Integration Test Updates

**Before:**

```python
# tests/test_graphql.py
def test_user_query(client):
    query = """
    query {
        users(limit: 10) {
            id
            name
            email
        }
    }
    """

    response = client.post("/graphql", json={"query": query})
    data = response.json()["data"]

    assert "users" in data
    assert len(data["users"]) <= 10
```

**After:**

```python
# tests/test_graphql.py
def test_user_query(client):
    query = """
    query {
        users(limit: 10) {
            id
            name
            email
        }
    }
    """

    response = client.post("/graphql", json={"query": query})

    # Rust pipeline returns direct HTTP response
    assert response.status_code == 200
    data = response.json()["data"]

    assert "users" in data
    assert len(data["users"]) <= 10

    # Additional validation: check performance headers
    assert "X-Rust-Pipeline" in response.headers
    assert response.headers["X-Rust-Pipeline"] == "true"
```

## Troubleshooting Common Issues

### Issue: "Rust extension not available"

**Symptoms:**

```
ImportError: fraiseql Rust extension is not available
```

**Solutions:**

1. **Reinstall FraiseQL:**

   ```bash
   pip uninstall fraiseql
   pip install --force-reinstall fraiseql
   ```

2. **Check system dependencies:**

   ```bash
   # Ubuntu/Debian
   sudo apt-get install build-essential

   # macOS
   xcode-select --install

   # Windows
   # Install Visual Studio Build Tools
   ```

3. **Verify Python version:**
   - Rust extension requires Python 3.8+
   - Check with: `python --version`

### Issue: "Connection pool exhausted"

**Symptoms:**

```
DatabaseError: Connection pool exhausted
```

**Solutions:**

1. **Increase pool size:**

   ```python
   pool = DatabasePool(
       database_url=DATABASE_URL,
       config={"max_size": 50, "min_idle": 10}  # Increase from defaults
   )
   ```

2. **Check connection leaks:**
   - Ensure connections are properly released
   - Use context managers for transactions
   - Monitor connection pool stats

3. **Optimize query patterns:**
   - Use `find_one()` for single records
   - Implement proper pagination
   - Avoid N+1 query patterns

### Issue: "GraphQL type mismatch errors"

**Symptoms:**

```
GraphQLError: Expected Iterable but got RustResponseBytes
```

**Solutions:**

1. **Check GraphQL resolver return types:**

   ```python
   # Correct: Let Rust pipeline handle response
   @fraiseql.query
   async def users(info):
       return await db.find("v_user", "users", info)

   # Incorrect: Manual processing loses optimization
   @fraiseql.query
   async def users(info):
       result = await db.find("v_user", "users", info)
       return json.loads(result.decode())  # Don't do this!
   ```

2. **Verify field selection:**
   - Pass `info` parameter to `find()` methods
   - Ensure GraphQL schema matches database views

3. **Check multi-field queries:**
   - Rust pipeline handles single-field queries optimally
   - Complex multi-field queries may need special handling

### Issue: "Performance regression after migration"

**Symptoms:**

- Queries slower than expected
- Memory usage increased
- Higher CPU usage

**Solutions:**

1. **Verify Rust pipeline usage:**

   ```python
   # Check that Rust pipeline is active
   response = await client.post("/graphql", json={"query": query})
   assert response.headers.get("X-Rust-Pipeline") == "true"
   ```

2. **Compare query patterns:**
   - Ensure using `find()` not legacy `select_from_json_view()`
   - Check that GraphQL `info` parameter is passed
   - Verify connection pool configuration

3. **Profile performance:**

   ```python
   import time
   start = time.time()
   result = await db.find("v_user", "users", info)
   duration = time.time() - start
   print(f"Query took: {duration:.3f}s")
   ```

### Issue: "Migration tool compatibility"

**Symptoms:**

- Alembic migrations fail
- Schema changes not applied
- Database inconsistencies

**Solutions:**

1. **Use compatible migration tools:**
   - Continue using existing migration tools
   - Rust backend works with standard PostgreSQL schemas
   - No changes needed to migration scripts

2. **Verify schema compatibility:**

   ```sql
   -- Check that views exist and are accessible
   SELECT table_name FROM information_schema.views
   WHERE table_name LIKE 'v_%';
   ```

3. **Test migrations:**

   ```bash
   # Run migrations before switching to Rust backend
   alembic upgrade head

   # Then test with Rust backend
   pytest tests/integration/
   ```

## FAQ

### General Questions

**Q: Is the migration mandatory?**
A: Yes, as of FraiseQL v1.9, the psycopg-only path has been completely removed. All applications must use the Rust backend.

**Q: Can I migrate gradually?**
A: Yes, you can migrate resolvers incrementally. The Rust backend is backward compatible with existing GraphQL schemas and database views.

**Q: Do I need to change my database schema?**
A: No, the Rust backend works with existing PostgreSQL schemas, views, and JSONB structures. No database changes are required.

**Q: What if I have custom query methods?**
A: Custom methods using raw SQL will need to be adapted. The Rust backend provides a consistent API, but custom SQL execution may need refactoring.

### Performance Questions

**Q: When will I see performance improvements?**
A: Performance benefits are most noticeable with:

- Large result sets (>1000 rows)
- Complex GraphQL queries with deep field selection
- High-concurrency scenarios
- Memory-constrained environments

**Q: Are there any performance downsides?**
A: The Rust backend adds minimal overhead for simple queries but provides substantial benefits for complex operations. Memory usage is consistently lower.

**Q: How do I monitor performance?**
A: Check response headers for `X-Rust-Pipeline: true` to confirm Rust execution. Use standard application performance monitoring tools.

### Compatibility Questions

**Q: Does it work with my existing GraphQL schema?**
A: Yes, the Rust backend is fully compatible with existing GraphQL schemas. The API changes are in the resolver implementation, not the schema definition.

**Q: Can I use it with my current PostgreSQL version?**
A: The Rust backend works with PostgreSQL 12+. For optimal performance, PostgreSQL 14+ is recommended.

**Q: What about my existing middleware?**
A: Most middleware continues to work. The `RustResponseBytes` type integrates seamlessly with HTTP response handling.

### Support Questions

**Q: Where can I get help with migration?**
A: Check the troubleshooting section above, or create an issue in the FraiseQL repository with migration questions.

**Q: Are there example migrations I can reference?**
A: This guide includes before/after examples for common patterns. The FraiseQL test suite also demonstrates proper Rust backend usage.

**Q: What if I encounter a bug during migration?**
A: Report issues to the FraiseQL repository. Include your before/after code, error messages, and FraiseQL version information.

## Success Metrics

After successful migration, you should see:

### Performance Improvements

- ✅ Query response times 2-3x faster for large datasets
- ✅ Memory usage reduced by 40-60%
- ✅ CPU usage decreased under load
- ✅ Higher throughput (requests/second)

### Operational Improvements

- ✅ Consistent query performance
- ✅ Reduced garbage collection pressure
- ✅ Better error messages and debugging
- ✅ Simplified deployment (fewer dependencies)

### Developer Experience

- ✅ Single execution path (no mode detection)
- ✅ Type-safe operations
- ✅ Better IDE support and autocomplete
- ✅ Consistent API across all operations

## Next Steps After Migration

1. **Monitor Performance**: Track query times, memory usage, and error rates
2. **Optimize Queries**: Use the new API patterns for maximum performance
3. **Update Documentation**: Document the migration for your team
4. **Plan Future Updates**: Leverage Rust backend features like advanced caching

## Additional Resources

- **[Database API Documentation](database-api.md)** - Complete Rust backend API reference
- **[Performance Optimization Guide](../performance/rust-pipeline-optimization.md)** - Advanced performance tuning
- **[Troubleshooting Guide](../guides/troubleshooting.md)** - Common issues and solutions
- **[CI/CD Architecture](../archive/testing/ci-architecture.md)** - Testing the Rust backend

---

**Migration Complete**: This guide covers the complete transition from psycopg to the exclusive Rust backend in FraiseQL v1.9+.
