# Caching Migration Guide

Quick guide for adding FraiseQL result caching to existing applications.

## For New Projects

If you're starting fresh, simply follow the [Result Caching Guide](caching.md).

## For Existing Projects

### Step 1: Add Cache Dependencies

No new dependencies required! FraiseQL caching uses your existing PostgreSQL database.

### Step 2: Initialize Cache

Add cache initialization to your application startup:

```python
from fastapi import FastAPI
from fraiseql.caching import PostgresCache, ResultCache

app = FastAPI()

@app.on_event("startup")
async def startup():
    # Reuse existing database pool
    pool = app.state.db_pool

    # Initialize cache backend (auto-creates UNLOGGED table)
    postgres_cache = PostgresCache(
        connection_pool=pool,
        table_name="fraiseql_cache",
        auto_initialize=True
    )

    # Wrap with result cache for statistics
    app.state.result_cache = ResultCache(
        backend=postgres_cache,
        default_ttl=300  # 5 minutes default
    )
```

### Step 3: Update Repository Creation

Wrap your existing repository with `CachedRepository`:

**Before**:

```python
def get_graphql_context(request: Request) -> dict:
    repo = FraiseQLRepository(
        pool=app.state.db_pool,
        context={"tenant_id": request.state.tenant_id}
    )

    return {
        "request": request,
        "db": repo,  # ← Direct repository
        "tenant_id": request.state.tenant_id
    }
```

**After**:

```python
from fraiseql.caching import CachedRepository

def get_graphql_context(request: Request) -> dict:
    base_repo = FraiseQLRepository(
        pool=app.state.db_pool,
        context={"tenant_id": request.state.tenant_id}  # REQUIRED!
    )

    # Wrap with caching
    cached_repo = CachedRepository(
        base_repository=base_repo,
        cache=app.state.result_cache
    )

    return {
        "request": request,
        "db": cached_repo,  # ← Cached repository
        "tenant_id": request.state.tenant_id
    }
```

### Step 4: Verify tenant_id in Context

**CRITICAL FOR MULTI-TENANT APPS**: Ensure `tenant_id` is always in repository context.

```python
# ✅ CORRECT: tenant_id in context
context={"tenant_id": request.state.tenant_id}

# ❌ WRONG: Missing tenant_id (security risk!)
context={}
```

**Why this matters**: Without `tenant_id`, all tenants share the same cache keys, leading to data leakage between tenants!

**Verify**:

```python
# Check that tenant_id is in context
assert base_repo.context.get("tenant_id") is not None, "tenant_id required!"
```

### Step 5: Add Cache Cleanup (Optional but Recommended)

Schedule periodic cleanup of expired entries:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job("interval", minutes=5)
async def cleanup_expired_cache():
    cache_backend = app.state.result_cache.backend
    cleaned = await cache_backend.cleanup_expired()
    if cleaned > 0:
        print(f"Cleaned {cleaned} expired cache entries")

@app.on_event("startup")
async def start_scheduler():
    scheduler.start()

@app.on_event("shutdown")
async def stop_scheduler():
    scheduler.shutdown()
```

## Migration for Non-Multi-Tenant Apps

If your app is single-tenant or doesn't use `tenant_id`:

```python
# Option 1: Use a constant tenant_id
context={"tenant_id": "single-tenant"}

# Option 2: Don't set tenant_id (cache keys won't include it)
context={}  # OK for single-tenant apps

# Option 3: Use another identifier (user_id, org_id, etc.)
context={"tenant_id": request.state.organization_id}
```

## Gradual Rollout Strategy

### Phase 1: Monitoring Only

Enable caching but bypass it initially to verify no issues:

```python
# All queries skip cache
users = await cached_repo.find("users", skip_cache=True)
```

Monitor logs for:

- Cache table created successfully
- No errors from cache operations
- Connection pool not exhausted

### Phase 2: Selective Caching

Enable caching for low-risk, read-heavy queries:

```python
# Cache rarely-changing data
countries = await cached_repo.find("countries", cache_ttl=3600)

# Skip cache for frequently-changing data
orders = await cached_repo.find("orders", skip_cache=True)
```

### Phase 3: Full Rollout

Once confident, enable caching by default:

```python
# Caching automatic (no skip_cache flag)
users = await cached_repo.find("users")
products = await cached_repo.find("products", mandatory_filters={"status": "active"})
```

## Verification Checklist

After migration, verify:

### 1. Cache Table Created

```sql
-- Check cache table exists
SELECT COUNT(*) FROM fraiseql_cache;

-- Check cache table is UNLOGGED
SELECT relpersistence
FROM pg_class
WHERE relname = 'fraiseql_cache';
-- Should return 'u' (unlogged)
```

### 2. Cache Keys Include tenant_id

```python
from fraiseql.caching import CacheKeyBuilder

key_builder = CacheKeyBuilder()
cache_key = key_builder.build_key(
    query_name="users",
    tenant_id=repo.context.get("tenant_id"),
    filters={"status": "active"}
)

print(cache_key)
# Should include tenant_id: "fraiseql:tenant-123:users:status:active"
```

### 3. Cache Hits Working

```python
# First query (cache miss)
result1 = await cached_repo.find("users", mandatory_filters={"status": "active"})

# Second query (cache hit)
result2 = await cached_repo.find("users", mandatory_filters={"status": "active"})

# Results should be identical
assert result1 == result2
```

### 4. Cache Statistics

```python
stats = await app.state.result_cache.get_stats()
print(f"Cache hit rate: {stats['hit_rate']:.1%}")
print(f"Total entries: {stats['total_entries']}")
print(f"Hits: {stats['hits']}, Misses: {stats['misses']}")
```

## Troubleshooting Migration Issues

### Issue: "tenant_id missing from context"

**Symptom**: Cache keys don't include tenant_id

**Fix**:

```python
# Ensure tenant middleware runs BEFORE GraphQL
@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    request.state.tenant_id = await resolve_tenant(request)
    return await call_next(request)

# Then use in repository context
context={"tenant_id": request.state.tenant_id}
```

### Issue: "Cache table not found"

**Symptom**: `PostgresCacheError: relation "fraiseql_cache" does not exist`

**Fix**:

```python
# Ensure auto_initialize=True
cache = PostgresCache(
    connection_pool=pool,
    auto_initialize=True  # ← Must be True
)

# Or create manually
await cache._ensure_initialized()
```

### Issue: "Connection pool exhausted"

**Symptom**: "Connection pool is full" errors after enabling cache

**Fix**:

```python
# Option 1: Increase pool size
pool = DatabasePool(db_url, min_size=20, max_size=40)

# Option 2: Use separate pool for cache
cache_pool = DatabasePool(db_url, min_size=5, max_size=10)
cache = PostgresCache(cache_pool)
```

### Issue: "Stale data in cache"

**Symptom**: Cache returns old data after mutations

**Fix**:

```python
# Ensure mutations use cached_repo (auto-invalidates)
await cached_repo.execute_function("update_user", {"id": user_id, ...})

# Or manually invalidate
from fraiseql.caching import CacheKeyBuilder
key_builder = CacheKeyBuilder()
pattern = key_builder.build_mutation_pattern("user")
await result_cache.invalidate_pattern(pattern)
```

## Performance Expectations

After migration, expect:

| Metric | Before Cache | After Cache | Improvement |
|--------|--------------|-------------|-------------|
| Simple query | 50-100ms | 0.5-2ms | **50-100x faster** |
| Complex query | 200-500ms | 0.5-2ms | **200-500x faster** |
| Cache hit rate | N/A | 70-95% | (after warm-up) |
| Database load | 100% | 5-30% | **Significant reduction** |

## Next Steps

- [Full Caching Guide](caching.md) - Comprehensive caching documentation
- [Multi-Tenancy](../advanced/multi-tenancy.md) - Tenant isolation patterns
- [Monitoring](../production/monitoring.md) - Track cache performance
- [Security](../production/security.md) - Cache security best practices
