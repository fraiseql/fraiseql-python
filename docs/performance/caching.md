# Result Caching

Comprehensive guide to FraiseQL's result caching system with PostgreSQL backend and optional domain-based automatic invalidation via `pg_fraiseql_cache` extension.

## Overview

FraiseQL provides a sophisticated caching system that stores query results in PostgreSQL UNLOGGED tables for:

- **Sub-millisecond cache hits** with automatic result caching
- **Zero Redis dependency** - uses existing PostgreSQL infrastructure
- **Multi-tenant security** - automatic tenant isolation in cache keys
- **Automatic invalidation** - TTL-based or domain-based (with extension)
- **Transparent integration** - minimal code changes required

**Performance Impact**:

| Scenario | Without Cache | With Cache | Speedup |
|----------|---------------|------------|---------|
| Simple query | 50-100ms | 0.5-2ms | **50-100x** |
| Complex aggregation | 200-500ms | 0.5-2ms | **200-500x** |
| Multi-tenant query | 100-300ms | 0.5-2ms | **100-300x** |

## Quick Start

### Basic Setup

```python
from fraiseql import create_fraiseql_app
from fraiseql.caching import PostgresCache, ResultCache, CachedRepository
from fraiseql.db import DatabasePool

# Initialize database pool
pool = DatabasePool("postgresql://user:pass@localhost/mydb")

# Create cache backend (PostgreSQL UNLOGGED table)
postgres_cache = PostgresCache(
    connection_pool=pool,
    table_name="fraiseql_cache",  # default
    auto_initialize=True
)

# Wrap with result cache (adds statistics tracking)
result_cache = ResultCache(backend=postgres_cache, default_ttl=300)

# Wrap repository with caching
from fraiseql.db import FraiseQLRepository

base_repo = FraiseQLRepository(
    pool=pool,
    context={"tenant_id": tenant_id}  # CRITICAL for multi-tenant!
)

cached_repo = CachedRepository(
    base_repository=base_repo,
    cache=result_cache
)

# Use cached repository - automatic caching!
# View name: "v_user" (singular, as defined in schema)
users = await cached_repo.find("v_user", mandatory_filters={"status": "active"})
```

### FastAPI Integration

```python
from fastapi import FastAPI, Request
from fraiseql.fastapi import create_fraiseql_app

app = FastAPI()

# Initialize cache at startup
@app.on_event("startup")
async def startup():
    app.state.cache = PostgresCache(pool)
    app.state.result_cache = ResultCache(
        backend=app.state.cache,
        default_ttl=300
    )

# Provide cached repository in GraphQL context
async def get_graphql_context(request: Request) -> dict:
    """Build complete GraphQL context with all required keys."""
    # Extract tenant and user from request state
    tenant_id = request.state.tenant_id
    user = request.state.user  # UserContext instance (or None)

    # Create repository with tenant context
    base_repo = FraiseQLRepository(
        pool=app.state.pool,
        context={
            "tenant_id": tenant_id,
            "user_id": user.user_id if user else None
        }
    )

    # Wrap with caching layer
    cached_db = CachedRepository(
        base_repository=base_repo,
        cache=app.state.result_cache
    )

    # Return complete context structure
    return {
        "request": request,          # FastAPI/Starlette request
        "db": cached_db,              # Repository with caching
        "tenant_id": tenant_id,       # Required for multi-tenancy
        "user": user                  # UserContext for auth decorators
    }

fraiseql_app = create_fraiseql_app(
    types=[User, Post, Product],
    context_getter=get_graphql_context
)

app.mount("/graphql", fraiseql_app)
```

## PostgreSQL Cache Backend

### UNLOGGED Tables

FraiseQL uses PostgreSQL UNLOGGED tables for maximum cache performance:

```sql
-- Automatically created by PostgresCache
CREATE UNLOGGED TABLE fraiseql_cache (
    cache_key TEXT PRIMARY KEY,
    cache_value JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX fraiseql_cache_expires_idx
    ON fraiseql_cache (expires_at);
```

**UNLOGGED Benefits**:

- **No WAL overhead** - writes are as fast as in-memory cache
- **Crash-safe** - table cleared on crash (acceptable for cache)
- **Shared access** - all app instances share same cache
- **Zero dependencies** - no Redis/Memcached required

**Trade-offs**:

- Data lost on PostgreSQL crash/restart (acceptable for cache)
- Not replicated to read replicas (primary-only)

### Extension Detection

PostgresCache automatically detects the `pg_fraiseql_cache` extension:

```python
# In an async function or startup handler
cache = PostgresCache(pool)
await cache._ensure_initialized()

if cache.has_domain_versioning:
    print(f"✓ pg_fraiseql_cache v{cache.extension_version} detected")
    print("  Domain-based invalidation enabled")
else:
    print("Using TTL-only caching (no extension)")
```

**Detection Logic**:

1. Query `pg_extension` table for `pg_fraiseql_cache`
2. If found: Enable domain-based invalidation features
3. If not found: Gracefully fall back to TTL-only caching
4. If error: Log warning and continue with TTL-only

## Configuration

### PostgresCache Options

```python
from fraiseql.caching import PostgresCache

cache = PostgresCache(
    connection_pool=pool,
    table_name="fraiseql_cache",  # Cache table name
    auto_initialize=True           # Auto-create table on first use
)
```

### ResultCache Options

```python
from fraiseql.caching import ResultCache

result_cache = ResultCache(
    backend=postgres_cache,
    default_ttl=300,              # Default TTL in seconds (5 min)
    enable_stats=True             # Track hit/miss statistics
)
```

### CachedRepository Options

```python
from fraiseql.caching import CachedRepository

cached_repo = CachedRepository(
    base_repository=base_repo,
    cache=result_cache
)

# Query with custom TTL
users = await cached_repo.find(
    "users",
    cache_ttl=600,
    mandatory_filters={"status": "active"},
)

# Skip cache for specific query
users = await cached_repo.find(
    "users",
    skip_cache=True,
    mandatory_filters={"status": "active"},
)
```

### Cache Cleanup

Set up periodic cleanup to remove expired entries:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize scheduler
    scheduler = AsyncIOScheduler()

    # Clean expired entries every 5 minutes
    @scheduler.scheduled_job("interval", minutes=5)
    async def cleanup_cache():
        cleaned = await app.state.postgres_cache.cleanup_expired()
        print(f"Cleaned {cleaned} expired cache entries")

    scheduler.start()
    yield
    # Shutdown: Stop scheduler
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
```

## Multi-Tenant Security

### Tenant Isolation in Cache Keys

**CRITICAL**: FraiseQL automatically includes `tenant_id` in cache keys to prevent cross-tenant data leakage.

```python
# tenant_id extracted from repository context
base_repo = FraiseQLRepository(
    pool=pool,
    context={"tenant_id": "tenant-123"}  # REQUIRED for multi-tenant!
)

cached_repo = CachedRepository(base_repo, result_cache)

# Automatically generates tenant-scoped cache key
users = await cached_repo.find("v_user", mandatory_filters={"status": "active"})
# Cache key: "fraiseql:tenant-123:users:status:active"
```

**Without tenant_id**:

```python
# 🚨 CRITICAL SECURITY VIOLATION - DO NOT USE IN PRODUCTION
# This example shows what happens when tenant_id is missing.
# Missing tenant_id causes CROSS-TENANT DATA LEAKAGE!

# ❌ WRONG: No tenant_id in context
base_repo = FraiseQLRepository(pool, context={})

cached_repo = CachedRepository(base_repo, result_cache)
users = await cached_repo.find("v_user", mandatory_filters={"status": "active"})
# Cache key: "fraiseql:users:status:active"
# ⚠️ This cache key is SHARED ACROSS ALL TENANTS - SECURITY VIOLATION!

# ✅ CORRECT: Always include tenant_id
base_repo = FraiseQLRepository(
    pool,
    context={"tenant_id": tenant_id}  # REQUIRED for multi-tenant apps
)
cached_repo = CachedRepository(base_repo, result_cache)
users = await cached_repo.find("v_user", mandatory_filters={"status": "active"})
# Cache key: "fraiseql:tenant_123:users:status:active"  ✅ Isolated per tenant
```

### Cache Key Structure

```
fraiseql:{tenant_id}:{view_name}:{filters}:{order_by}:{limit}:{offset}
         ^^^^^^^^^^^^
         Tenant isolation (CRITICAL!)
```

**Examples**:

```
# Tenant A
fraiseql:tenant-a:users:status:active:limit:10

# Tenant B (different key, even with same filters)
fraiseql:tenant-b:users:status:active:limit:10

# Without tenant isolation (INSECURE)
fraiseql:users:status:active:limit:10  ← ALL TENANTS SHARE THIS KEY!
```

### Tenant Context Middleware

Ensure tenant_id is always set:

```python
from fastapi import Request, HTTPException

@app.middleware("http")
async def tenant_context_middleware(request: Request, call_next):
    # Extract tenant from subdomain, JWT, or header
    tenant_id = await resolve_tenant_id(request)

    if not tenant_id:
        raise HTTPException(400, "Tenant not identified")

    # Store in request state
    request.state.tenant_id = tenant_id

    # Set in PostgreSQL session for RLS
    async with pool.connection() as conn:
        await conn.execute(
            "SET LOCAL app.current_tenant_id = $1",
            tenant_id
        )

    response = await call_next(request)
    return response
```

## Domain-Based Invalidation

### Overview

The `pg_fraiseql_cache` extension provides automatic domain-based cache invalidation beyond simple TTL expiry:

**Without Extension** (TTL-only):

```python
# Cache entry valid for 5 minutes, even if data changes
users = await cached_repo.find("v_user", cache_ttl=300)
# ❌ If user data changes, cache remains stale until TTL expires
```

**With Extension** (Domain-based):

```python
# Cache automatically invalidated when 'user' domain data changes
users = await cached_repo.find("v_user", cache_ttl=300)
# ✅ If user data changes, cache immediately invalidated (via triggers)
```

### How It Works

1. **Domain Versioning**: Each domain (e.g., "user", "post") has a version counter
2. **Version Tracking**: Cache entries store domain versions they depend on
3. **Automatic Triggers**: PostgreSQL triggers increment domain versions on INSERT/UPDATE/DELETE
4. **Validation**: On cache hit, compare cached versions vs current versions
5. **Invalidation**: If versions mismatch, invalidate cache and refetch

```
┌──────────────────────────────────────────────────────────────┐
│                    Cache Entry Structure                      │
├──────────────────────────────────────────────────────────────┤
│ {                                                            │
│   "result": [...query results...],                          │
│   "versions": {                                              │
│     "user": 42,    ← Domain versions at cache time          │
│     "post": 15                                               │
│   },                                                         │
│   "cached_at": "2025-10-11T10:00:00Z"                       │
│ }                                                            │
└──────────────────────────────────────────────────────────────┘

On cache hit:
1. Get current versions: user=43, post=15
2. Compare: user changed (42→43), post unchanged (15=15)
3. Invalidate cache (user data changed)
4. Refetch with current data
```

### Installation

```bash
# Install pg_fraiseql_cache extension
psql -d mydb -c "CREATE EXTENSION pg_fraiseql_cache;"
```

FraiseQL automatically detects the extension and enables domain-based features.

### Cache Value Metadata

When `pg_fraiseql_cache` is detected, cache values are wrapped with metadata:

```python
# Without extension (backward compatible)
cache_value = [...query results...]

# With extension
cache_value = {
    "result": [...query results...],
    "versions": {
        "user": 42,
        "post": 15,
        "product": 8
    },
    "cached_at": "2025-10-11T10:00:00Z"
}
```

**Automatic Unwrapping**: `PostgresCache.get()` automatically unwraps metadata:

```python
# Returns just the result, metadata handled internally
result = await cache.get("cache_key")
# result = [...query results...]  (unwrapped)

# Access metadata explicitly
result, versions = await cache.get_with_metadata("cache_key")
# result = [...query results...]
# versions = {"user": 42, "post": 15}
```

### Mutation Invalidation

Cache automatically invalidated on mutations:

```python
# Create a new user (mutation)
await cached_repo.execute_function("create_user", {
    "name": "Alice",
    "email": "alice@example.com"
})

# Automatically invalidates:
# - fraiseql:{tenant_id}:user:*
# - fraiseql:{tenant_id}:users:*  (plural form)

# Next query fetches fresh data
users = await cached_repo.find("users")
# Cache miss → fetch from database → re-cache with new version
```

## Usage Patterns

### Pattern 1: Repository-Level Caching

Automatic caching for all queries through repository:

```python
from fraiseql.caching import CachedRepository

cached_repo = CachedRepository(base_repo, result_cache)

# All find() calls automatically cached
# Note: View name is "v_user" (singular, as defined in schema)
users = await cached_repo.find("v_user", mandatory_filters={"status": "active"})  # Returns list
user = await cached_repo.find_one("v_user", mandatory_filters={"id": user_id})   # Returns single item

# Mutations automatically invalidate related cache
await cached_repo.execute_function("create_user", user_data)
```

### Pattern 2: Explicit Cache Control

Manual cache management for fine-grained control:

```python
from fraiseql.caching import CacheKeyBuilder

key_builder = CacheKeyBuilder()

# Build cache key
cache_key = key_builder.build_key(
    query_name="active_users",
    tenant_id=tenant_id,
    filters={"status": "active"},
    limit=10
)

# Check cache
cached_result = await result_cache.get(cache_key)
if cached_result:
    return cached_result

# Fetch from database
result = await base_repo.find("v_user", limit=10, mandatory_filters={"status": "active"})

# Cache result
await result_cache.set(cache_key, result, ttl=300)
```

### Pattern 3: Decorator-Based Caching

Cache individual resolver functions:

```python
import fraiseql
from fraiseql.caching import cache_result

@fraiseql.query
@cache_result(ttl=600, key_prefix="top_products")
async def get_top_products(
    info,
    category: str,
    limit: int = 10
) -> list[Product]:
    """Get top products by category (cached)."""
    tenant_id = info.context["tenant_id"]
    db = info.context["db"]

    return await db.find(
        "products",
        order_by=[("sales_count", "DESC")],
        limit=limit,
        mandatory_filters={"category": category, "status": "published"},
    )
```

### Pattern 4: Conditional Caching

Cache based on query characteristics:

```python
async def smart_find(view_name: str, **kwargs):
    """Cache only if query is expensive."""

    # Don't cache simple lookups by ID
    if "id" in kwargs and len(kwargs) == 1:
        return await base_repo.find_one(view_name, **kwargs)

    # Cache complex queries
    if len(kwargs) > 2 or "order_by" in kwargs:
        return await cached_repo.find(view_name, cache_ttl=300, **kwargs)

    # Default: no cache
    return await base_repo.find(view_name, **kwargs)
```

## Cache Key Strategy

### Key Components

```python
from fraiseql.caching import CacheKeyBuilder

key_builder = CacheKeyBuilder(prefix="fraiseql")

cache_key = key_builder.build_key(
    query_name="users",
    tenant_id="tenant-123",      # Tenant isolation
    filters={"status": "active", "role": "admin"},
    order_by=[("created_at", "DESC")],
    limit=10,
    offset=0
)

# Result: "fraiseql:tenant-123:users:role:admin:status:active:order:created_at:DESC:limit:10:offset:0"
```

### Key Normalization

Keys are deterministic and order-independent:

```python
# These produce the same key
key1 = key_builder.build_key(
    "users",
    tenant_id="t1",
    filters={"status": "active", "role": "admin"}
)

key2 = key_builder.build_key(
    "users",
    tenant_id="t1",
    filters={"role": "admin", "status": "active"}  # Different order
)

assert key1 == key2  # True - filters sorted alphabetically
```

### Filter Serialization

Complex filter values are properly serialized:

```python
# UUID
filters={"user_id": UUID("...")}
# → user_id:00000000-0000-0000-0000-000000000000

# Date/DateTime
filters={"created_after": datetime(2025, 1, 1)}
# → created_after:2025-01-01T00:00:00

# List (sorted)
filters={"status__in": ["active", "pending"]}
# → status__in:active,pending

# Complex list (hashed for brevity)
filters={"ids": [UUID(...), UUID(...)]}
# → ids:a1b2c3d4  (MD5 hash prefix)

# Boolean
filters={"is_active": True}
# → is_active:true

# None
filters={"deleted_at": None}
# → deleted_at:null
```

### Pattern-Based Invalidation

Invalidate multiple related keys at once:

```python
# Invalidate all user queries for a tenant
pattern = key_builder.build_mutation_pattern("user")
# Result: "fraiseql:user:*"

await result_cache.invalidate_pattern(pattern)
# Deletes: fraiseql:tenant-a:user:*, fraiseql:tenant-b:user:*, etc.
```

## Monitoring & Metrics

### Cache Statistics

Track cache performance:

```python
# Get cache statistics
stats = await result_cache.get_stats()
print(f"Hit rate: {stats['hit_rate']:.1%}")
print(f"Hits: {stats['hits']}, Misses: {stats['misses']}")
print(f"Total entries: {stats['total_entries']}")
print(f"Expired entries: {stats['expired_entries']}")
print(f"Table size: {stats['table_size_bytes'] / 1024 / 1024:.2f} MB")
```

### PostgreSQL Monitoring

```sql
-- Check cache table size
SELECT
    pg_size_pretty(pg_total_relation_size('fraiseql_cache')) as total_size,
    pg_size_pretty(pg_relation_size('fraiseql_cache')) as table_size,
    pg_size_pretty(pg_indexes_size('fraiseql_cache')) as index_size;

-- Count cache entries
SELECT
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW()) as active_entries,
    COUNT(*) FILTER (WHERE expires_at <= NOW()) as expired_entries
FROM fraiseql_cache;

-- Find most common cache keys
SELECT
    substring(cache_key, 1, 50) as key_prefix,
    COUNT(*) as count
FROM fraiseql_cache
GROUP BY substring(cache_key, 1, 50)
ORDER BY count DESC
LIMIT 20;

-- Monitor cache churn
SELECT
    date_trunc('hour', expires_at) as hour,
    COUNT(*) as entries_expiring
FROM fraiseql_cache
WHERE expires_at > NOW()
GROUP BY hour
ORDER BY hour;
```

### Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge

# Cache hit/miss counters
cache_hits = Counter(
    'fraiseql_cache_hits_total',
    'Total cache hits',
    ['tenant_id', 'view_name']
)

cache_misses = Counter(
    'fraiseql_cache_misses_total',
    'Total cache misses',
    ['tenant_id', 'view_name']
)

# Cache operation duration
cache_get_duration = Histogram(
    'fraiseql_cache_get_duration_seconds',
    'Cache get operation duration',
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]
)

# Cache size
cache_size = Gauge(
    'fraiseql_cache_entries_total',
    'Total cache entries'
)

# Instrument cache operations
@cache_get_duration.time()
async def get_cached(key: str):
    result = await cache.get(key)
    if result:
        cache_hits.labels(tenant_id, view_name).inc()
    else:
        cache_misses.labels(tenant_id, view_name).inc()
    return result
```

### Logging

```python
import logging

# Enable cache logging
logging.getLogger("fraiseql.caching").setLevel(logging.INFO)

# Logs include:
# - Extension detection: "✓ Detected pg_fraiseql_cache v1.0.0"
# - Cache initialization: "PostgreSQL cache table 'fraiseql_cache' initialized"
# - Cleanup operations: "Cleaned 145 expired cache entries"
# - Errors: "Failed to get cache key 'fraiseql:...' ..."
```

## Best Practices

### 1. Always Set tenant_id

```python
# ✅ CORRECT: tenant_id in context
repo = FraiseQLRepository(
    pool,
    context={"tenant_id": tenant_id}
)

# ❌ WRONG: Missing tenant_id (security issue!)
repo = FraiseQLRepository(pool, context={})
```

### 2. Choose Appropriate TTLs

```python
# Frequently changing data (short TTL)
recent_orders = await cached_repo.find(
    "orders",
    cache_ttl=60,
    where={"created_at": {"gte": today}},
)

# Rarely changing data (long TTL)
categories = await cached_repo.find(
    "categories",
    cache_ttl=3600,
    mandatory_filters={"status": "active"},
)

# Static data (very long TTL)
countries = await cached_repo.find(
    "countries",
    cache_ttl=86400  # 24 hours
)
```

### 3. Use skip_cache for Real-Time Data

```python
# Admin dashboard: always fresh data
admin_stats = await cached_repo.find(
    "admin_stats",
    skip_cache=True  # Never cache
)

# User-facing: can cache
user_stats = await cached_repo.find(
    "user_stats",
    cache_ttl=300,
    mandatory_filters={"user_id": user_id},
)
```

### 4. Invalidate on Mutations

```python
# Manual invalidation
await cached_repo.execute_function("create_product", product_data)

# Or explicit
await result_cache.invalidate_pattern(
    key_builder.build_mutation_pattern("product")
)
```

### 5. Monitor Cache Health

```python
# Scheduled health check
async def check_cache_health():
    stats = await postgres_cache.get_stats()

    # Alert if too many expired entries (cleanup not working)
    if stats["expired_entries"] > 10000:
        logger.warning(f"High expired entry count: {stats['expired_entries']}")

    # Alert if cache table too large (increase cleanup frequency)
    if stats["table_size_bytes"] > 1_000_000_000:  # 1GB
        logger.warning(f"Cache table large: {stats['table_size_bytes']} bytes")

    # Alert if hit rate too low (TTLs too short or invalidation too aggressive)
    hit_rate = stats["hits"] / (stats["hits"] + stats["misses"])
    if hit_rate < 0.5:
        logger.warning(f"Low cache hit rate: {hit_rate:.1%}")
```

### 6. Vacuum UNLOGGED Tables

```sql
-- Schedule regular VACUUM for UNLOGGED table
-- (autovacuum works, but explicit VACUUM recommended)
VACUUM ANALYZE fraiseql_cache;
```

### 7. Partition Large Caches

For very high-traffic applications:

```sql
-- Partition by tenant_id prefix
CREATE UNLOGGED TABLE fraiseql_cache (
    cache_key TEXT NOT NULL,
    cache_value JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
) PARTITION BY HASH (cache_key);

CREATE TABLE fraiseql_cache_0 PARTITION OF fraiseql_cache
    FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE fraiseql_cache_1 PARTITION OF fraiseql_cache
    FOR VALUES WITH (MODULUS 4, REMAINDER 1);
CREATE TABLE fraiseql_cache_2 PARTITION OF fraiseql_cache
    FOR VALUES WITH (MODULUS 4, REMAINDER 2);
CREATE TABLE fraiseql_cache_3 PARTITION OF fraiseql_cache
    FOR VALUES WITH (MODULUS 4, REMAINDER 3);
```

## Troubleshooting

### Low Cache Hit Rate

**Symptom**: < 70% hit rate, frequent cache misses

**Causes**:

1. TTLs too short
2. High query diversity (many unique queries)
3. Aggressive invalidation
4. Missing tenant_id (keys not reused)

**Solutions**:

```python
# Increase TTLs
result_cache.default_ttl = 600  # 10 minutes

# Check key diversity
stats = await postgres_cache.get_stats()
print(f"Total entries: {stats['total_entries']}")
# If > 100,000: Consider query normalization

# Verify tenant_id in keys
cache_key = key_builder.build_key("users", tenant_id=tenant_id, ...)
print(cache_key)  # Should include tenant_id
```

### Stale Data

**Symptom**: Cached data doesn't reflect recent changes

**Causes**:

1. TTL too long
2. Mutations not invalidating cache
3. Extension not installed (no domain-based invalidation)

**Solutions**:

```python
# Check extension
if not cache.has_domain_versioning:
    print("⚠️ pg_fraiseql_cache not installed - using TTL-only")
    # Install extension or reduce TTLs

# Manual invalidation after mutation
await result_cache.invalidate_pattern(
    key_builder.build_mutation_pattern("user")
)

# Reduce TTL for frequently changing data
cache_ttl = 30  # 30 seconds
```

### High Memory Usage

**Symptom**: PostgreSQL memory usage growing

**Causes**:

1. Cache table too large
2. Expired entries not cleaned
3. Too many cached large results

**Solutions**:

```sql
-- Check table size
SELECT pg_size_pretty(pg_total_relation_size('fraiseql_cache'));

-- Manual cleanup
DELETE FROM fraiseql_cache WHERE expires_at <= NOW();
VACUUM fraiseql_cache;
```

```python
# Increase cleanup frequency
@scheduler.scheduled_job("interval", minutes=1)  # Every minute
async def cleanup_cache():
    await postgres_cache.cleanup_expired()

# Limit cache value size
if len(json.dumps(result)) > 100_000:  # > 100KB
    # Don't cache large results
    return result
```

### Connection Pool Exhaustion

**Symptom**: "Connection pool is full" errors

**Cause**: Cache operations holding connections too long

**Solution**:

```python
# Use separate pool for cache
cache_pool = DatabasePool(
    db_url,
    min_size=5,
    max_size=10  # Smaller than main pool
)

cache = PostgresCache(cache_pool)
```

### Cache Table Corruption

**Symptom**: Unexpected errors, constraint violations

**Solution**:

```sql
-- Drop and recreate cache table (safe - it's just cache)
DROP TABLE IF EXISTS fraiseql_cache CASCADE;

-- Recreate automatically on next use
-- Or manually:
CREATE UNLOGGED TABLE fraiseql_cache (
    cache_key TEXT PRIMARY KEY,
    cache_value JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX fraiseql_cache_expires_idx
    ON fraiseql_cache (expires_at);
```

### Extension Not Detected

**Symptom**: `has_domain_versioning` is False despite extension installed

**Causes**:

1. Extension not installed in correct database
2. Permissions issue
3. Extension name mismatch

**Solutions**:

```sql
-- Verify extension installed
SELECT * FROM pg_extension WHERE extname = 'pg_fraiseql_cache';

-- Install if missing
CREATE EXTENSION pg_fraiseql_cache;

-- Check permissions
GRANT USAGE ON SCHEMA fraiseql_cache TO app_user;
```

```python
# Check detection (in async function)
async def check_cache_extension():
    cache = PostgresCache(pool)
    await cache._ensure_initialized()

    print(f"Extension detected: {cache.has_domain_versioning}")
    print(f"Extension version: {cache.extension_version}")
```

## Next Steps

- [Performance Optimization](index.md) - Full performance stack (Rust, APQ, TurboRouter)
- [Multi-Tenancy](../advanced/multi-tenancy.md) - Tenant-aware caching patterns
- [Monitoring](../production/monitoring.md) - Production monitoring setup
- [Security](../production/security.md) - Cache security best practices
