---

title: Caching Specification
description: Result caching in FraiseQL is a PostgreSQL-backed system that improves performance while maintaining data consistency through TTL expiry and CASCADE invalidation.
keywords: ["format", "compliance", "protocol", "specification", "standard"]
tags: ["documentation", "reference"]
---

# Caching Specification

**Version:** 1.0
**Status:** Draft
**Audience:** Database architects, schema designers, API developers, operations engineers

---

## 1. Overview

Caching in FraiseQL is a result-caching layer that improves performance while maintaining data consistency. It lives in `fraiseql.caching` and is built on three foundational principles:

1. **PostgreSQL-backed** — Cache entries are stored in a PostgreSQL `UNLOGGED` table (no WAL overhead), so the cache is shared across every FastAPI instance pointed at the same database.
2. **Tenant Isolation** — Cache keys include the tenant context, preventing cross-tenant data leakage.
3. **CASCADE Invalidation** — Cache invalidation rules are derived from the GraphQL schema at app startup, so mutations on a domain invalidate the caches of types that depend on it.

The public API (`from fraiseql.caching import ...`) provides:

- **`ResultCache`** — Query-result caching with `get_or_set`, TTL handling, and stats.
- **`CacheConfig`** — Dataclass configuring `enabled`, TTLs, error caching, and key prefix.
- **`CacheBackend`** — Protocol every backend implements (`get` / `set` / `delete` / `delete_pattern`).
- **`PostgresCache`** — Production backend using a PostgreSQL `UNLOGGED` table.
- **`CacheKeyBuilder`** — Deterministic, tenant-isolated cache-key generation.
- **`CachedRepository`** — A `FraiseQLRepository` wrapper that transparently caches `find`/`find_one` and invalidates on `execute_function`.
- **`cached_query`** — A decorator for caching arbitrary async query functions.
- **`CascadeRule`**, **`SchemaAnalyzer`**, **`setup_auto_cascade_rules`** — Automatic CASCADE-rule generation from the GraphQL schema.
- **`CacheStats`** — Hit / miss / error counters with a `hit_rate` property.

All of this runs at runtime inside your FastAPI app; there is no build step and no compiled artifact.

---

## 2. Query Result Caching

### 2.1 Overview

`ResultCache` stores the result of a query function in a backend, enabling subsecond response times for repeated reads.

**Key Characteristics:**

- Operates at the **repository / query-function level** (via `CachedRepository` or `cached_query`).
- **Deterministic cache keys** built from query name, tenant, filters, ordering, and pagination.
- **Tenant-isolated** — `tenant_id` is part of every key, so one tenant cannot read another's cached data.
- **Configurable backends** — `PostgresCache` for shared/production caching, or any object satisfying the `CacheBackend` protocol.
- **Optional error caching** — Controlled by `CacheConfig.cache_errors`.

### 2.2 Cache Key Generation

#### Structure

`CacheKeyBuilder.build_key(...)` joins its components with colons. The tenant id (when present) is the second component, immediately after the prefix:

```text
{prefix}:{tenant_id}:{query_name}:{filter parts...}:{order...}:{limit:N}:{offset:N}
```

**Components:**

- `prefix` — Default: `"fraiseql"` (`CacheConfig.key_prefix`), configurable per deployment.
- `tenant_id` — Included when present in the repository context (`info.context["tenant_id"]`).
- `query_name` — The view/query name (e.g. `v_user`); `find_one` appends `:one`.
- filter / order / pagination parts — Serialized deterministically (filters sorted by field, lists hashed) so the same logical query always maps to the same key.

#### Example

```text
fraiseql:org_550e8400-e29b-41d4:v_user:status:active:limit:20:offset:0
```

**Tenant Isolation Guarantee:**
Because `tenant_id` is part of the key, even an attacker who knows the key structure cannot retrieve another tenant's data: a request authenticated as tenant B produces tenant-B keys and only ever reads tenant-B entries.

### 2.3 Configuration

#### CacheConfig Dataclass

`CacheConfig` is the real dataclass exported from `fraiseql.caching`:

```python
from dataclasses import dataclass


@dataclass
class CacheConfig:
    """Configuration for result caching."""

    enabled: bool = True
    default_ttl: int = 300  # 5 minutes
    max_ttl: int = 3600     # 1 hour
    cache_errors: bool = False
    key_prefix: str = "fraiseql"
```

#### Usage

`CacheConfig` configures a `ResultCache`; it is **not** a `create_fraiseql_app` kwarg. Build the cache explicitly and wire it into your repository (see [Section 2.5](#25-repository-integration)):

```python
from fraiseql.caching import CacheConfig, ResultCache, PostgresCache

cache_config = CacheConfig(
    enabled=True,
    default_ttl=300,     # 5 minutes for normal queries
    max_ttl=3600,        # Never cache longer than 1 hour
    cache_errors=False,  # Don't cache errors
    key_prefix="fraiseql",
)

backend = PostgresCache(connection_pool=pool)
cache = ResultCache(backend=backend, config=cache_config)
```

### 2.4 Cache Backends

A cache backend is any object implementing the `CacheBackend` protocol:

```python
from typing import Any, Protocol


class CacheBackend(Protocol):
    """Protocol for cache backends."""

    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def delete(self, key: str) -> bool: ...
    async def delete_pattern(self, pattern: str) -> int: ...
```

#### 2.4.1 PostgreSQL Backend (`PostgresCache`)

**Location:** `fraiseql.caching.PostgresCache`

**Characteristics:**

- Persists cache to PostgreSQL using an **UNLOGGED table** (no WAL overhead).
- **Best for:** Multi-instance deployments — the cache is shared across every FastAPI process on the same database.
- **Persistence:** Survives process restarts; UNLOGGED tables are cleared on a database crash (acceptable for a cache).
- **Optional domain versioning:** If the `pg_fraiseql_cache` extension is installed, `PostgresCache` uses domain versions for CASCADE invalidation; otherwise it falls back to TTL-only caching.

**Construction:**

```python
from psycopg_pool import AsyncConnectionPool

from fraiseql.caching import PostgresCache

pool = AsyncConnectionPool("postgresql://user:pass@db/mydb")

backend = PostgresCache(
    connection_pool=pool,
    table_name="fraiseql_cache",  # default
    auto_initialize=True,         # create the table on first use
)
```

**Table Structure** (created automatically by `PostgresCache` on first use):

```sql
CREATE UNLOGGED TABLE IF NOT EXISTS fraiseql_cache (
    cache_key TEXT PRIMARY KEY,
    cache_value JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS fraiseql_cache_expires_idx
    ON fraiseql_cache (expires_at);
```

**UNLOGGED Table Tradeoff:**

- **Pros:** Much faster writes than a regular table (no WAL writes).
- **Cons:** Data lost on a database crash (acceptable for cache data that can be regenerated).
- **Use case:** Perfect for caches where data loss is not catastrophic.

**Cleanup:** `PostgresCache` exposes `cleanup_expired()` (delete entries past `expires_at`) and `clear_all()`. Call `cleanup_expired()` periodically from a background task:

```sql
-- Equivalent of PostgresCache.cleanup_expired()
DELETE FROM fraiseql_cache
WHERE expires_at < NOW();
```

**Other methods:** `get_stats()` (row counts and size), `exists(key)`, `ping()`, plus CASCADE management (`register_cascade_rule`, `clear_cascade_rules`, `setup_table_trigger`) covered in [Section 4](#4-cascade-invalidation).

#### 2.4.2 Custom Backend

Any class satisfying the `CacheBackend` protocol can be used. For example, a Redis-backed implementation:

```python
import json
from typing import Any


class RedisCacheBackend:
    """Example: Redis cache backend implementing the CacheBackend protocol."""

    def __init__(self, redis_client, default_ttl: int = 300) -> None:
        self.redis = redis_client
        self.default_ttl = default_ttl

    async def get(self, key: str) -> Any | None:
        value = await self.redis.get(key)
        return json.loads(value) if value else None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        await self.redis.setex(key, ttl, json.dumps(value))

    async def delete(self, key: str) -> bool:
        return bool(await self.redis.delete(key))

    async def delete_pattern(self, pattern: str) -> int:
        keys = [k async for k in self.redis.scan_iter(match=pattern)]
        return await self.redis.delete(*keys) if keys else 0
```

**Usage:**

```python
import redis.asyncio as redis

from fraiseql.caching import CacheConfig, ResultCache

redis_client = redis.from_url("redis://localhost:6379/0")
backend = RedisCacheBackend(redis_client, default_ttl=300)
cache = ResultCache(backend=backend, config=CacheConfig())
```

### 2.5 Repository Integration

`CachedRepository` wraps a `FraiseQLRepository`, transparently caching reads and invalidating on writes.

```python
from fraiseql.caching import CachedRepository, ResultCache, PostgresCache, CacheConfig

backend = PostgresCache(connection_pool=pool)
cache = ResultCache(backend=backend, config=CacheConfig(default_ttl=300))

# `base_repo` is the FraiseQLRepository from info.context["db"]
cached_repo = CachedRepository(base_repository=base_repo, cache=cache)

# Reads are cached (per-call opt-out + custom TTL available):
rows = await cached_repo.find("v_user", status="active")
row = await cached_repo.find_one("v_user", id=user_id, cache_ttl=600)
fresh = await cached_repo.find("v_user", skip_cache=True)

# Writes invalidate related cache entries automatically:
await cached_repo.execute_function("fn_update_user", {"id": user_id, "name": name})
```

`find`/`find_one` accept `skip_cache: bool = False` and `cache_ttl: int | None = None`. `execute_function` derives the affected table from the function name (e.g. `fn_update_user` → `user`/`users`) and invalidates the matching key pattern. Any method not overridden is delegated to the underlying repository.

### 2.6 Caching Arbitrary Query Functions

For query functions outside the repository, use the `cached_query` decorator:

```python
from fraiseql.caching import cached_query, ResultCache, CacheConfig

cache = ResultCache(backend=backend, config=CacheConfig())


@cached_query(cache, ttl=600)
async def top_sellers(region: str) -> list[dict]:
    db = ...  # your FraiseQLRepository
    return await db.find("v_top_sellers", region=region)


# Bypass the cache for a single call:
fresh = await top_sellers(region="emea", skip_cache=True)
```

The decorator auto-generates a key from the function name and arguments, or you can pass `key_func=...` for a custom key.

### 2.7 Cache Invalidation Strategies

#### 2.7.1 Time-Based (TTL) Invalidation

**How it works:** Each cache entry is written with a TTL; `expires_at` is set to `NOW() + ttl`. `ResultCache.get_or_set` clamps the requested TTL to `min(ttl or default_ttl, max_ttl)`. Reads only return entries where `expires_at > NOW()`.

You can vary TTL per query based on how expensive or volatile it is:

```python
def choose_ttl(query_cost: int, config: CacheConfig) -> int:
    """Cheaper / more stable queries can be cached longer."""
    if query_cost < 10:
        return min(config.default_ttl * 2, config.max_ttl)  # up to 600s
    if query_cost < 50:
        return config.default_ttl                            # 300s
    if query_cost < 200:
        return config.default_ttl // 2                       # 150s
    return 30  # expensive queries cached briefly


ttl = choose_ttl(query_cost=5, config=cache.config)
await cached_repo.find("v_report", cache_ttl=ttl)
```

#### 2.7.2 Manual Invalidation

Invalidate through the `ResultCache` instance:

```python
# Invalidate a specific key
await cache.invalidate("fraiseql:org_123:v_user:one:id:550e8400")

# Pattern-based invalidation (all entries for a query/tenant)
await cache.invalidate_pattern("fraiseql:org_123:v_user:*")
```

`invalidate` / `invalidate_pattern` delegate to the backend's `delete` / `delete_pattern`. `CacheKeyBuilder.build_mutation_pattern(table_name)` produces a `"{prefix}:{table_name}:*"` pattern for write-side invalidation.

#### 2.7.3 CASCADE Invalidation (Automatic)

Mutations on one domain can invalidate the caches of types that depend on it. CASCADE rules are derived from the GraphQL schema at startup — see [Section 4](#4-cascade-invalidation).

### 2.8 Multi-Tenant Cache Isolation

#### Security Guarantee

`CacheKeyBuilder` places `tenant_id` immediately after the prefix:

```text
{prefix}:{tenant_id}:{query_name}:...
          ^^^^^^^^^^^
          Cannot retrieve another tenant's data
```

`CachedRepository` reads `tenant_id` from the repository context (`self._base.context.get("tenant_id")`), which FraiseQL populates from `info.context["tenant_id"]`. Because tenant context flows from the authenticated request, a request as tenant B can only ever build — and therefore read — tenant-B keys.

**Proof of Isolation:**

```python
# Two tenants, same logical query → different keys → isolated entries
org_a_key = "fraiseql:org_a:v_user:status:active"
org_b_key = "fraiseql:org_b:v_user:status:active"

assert await cache.backend.get(org_a_key) != await cache.backend.get(org_b_key)
```

#### Multi-Tenant Deployment Pattern

Always source `tenant_id` from the authenticated context, never from client arguments:

```python
import fraiseql


@fraiseql.query
async def users(info) -> list[User]:
    """List users — automatically tenant-scoped via the repository context."""
    db = info.context["db"]  # a CachedRepository in production
    # tenant_id is read from info.context and baked into the cache key
    return await db.find("v_user")
```

### 2.9 Performance Characteristics

#### PostgreSQL Backend

| Operation | Notes |
|-----------|-------|
| Cache Hit | Single indexed `SELECT` on `cache_key` filtered by `expires_at` |
| Cache Miss | Same lookup returns nothing; the wrapped query runs, then one `UPSERT` |
| Cleanup | `cleanup_expired()` deletes rows past `expires_at`; run from a background task |

UNLOGGED tables avoid WAL writes, keeping cache writes cheap. Because the table is shared, every FastAPI instance benefits from a warm cache populated by any instance.

### 2.10 Cache Monitoring & Metrics

`ResultCache` tracks hits, misses, and errors:

```python
stats = cache.get_stats()        # CacheStats
print(stats.hits, stats.misses, stats.errors)
print(f"hit rate: {stats.hit_rate:.1f}%")  # 0–100
cache.reset_stats()
```

`PostgresCache.get_stats()` returns backend-level counts (e.g. total/expired entries, size) you can export to Prometheus or OpenTelemetry.

#### Example Monitoring Query

```sql
-- PostgreSQL: live cache occupancy
SELECT
    COUNT(*)                                    AS total_entries,
    COUNT(*) FILTER (WHERE expires_at <= NOW()) AS expired_entries,
    pg_size_pretty(pg_total_relation_size('fraiseql_cache')) AS table_size
FROM fraiseql_cache;
```

#### Monitoring Dashboard Recommendations

1. **Cache Hit Rate** — Track `CacheStats.hit_rate`; target > 80% for normal queries.
2. **Expired Backlog** — Ensure `cleanup_expired()` keeps expired rows low.
3. **Table Size** — Alert if `fraiseql_cache` grows unbounded.
4. **Error Rate** — Watch `CacheStats.errors`; backend errors degrade to direct execution.

---

## 3. Field Selection

FraiseQL shapes each response to exactly the fields the client requested (Rust handles field selection on the hot path). The cache stores the result of a given query/filter combination; field selection is applied when shaping the response, so requesting fewer fields returns a subset of the cached data without a separate cache tier.

There is no separate "APQ response cache" tier in v1 — `ResultCache` is the single result-caching layer, and persisted queries reuse it.

---

## 4. CASCADE Invalidation

### 4.1 Automatic Rule Generation

When a GraphQL type references another type (e.g. `Post.author -> User`), a change to `User` should invalidate cached `Post` entries. `SchemaAnalyzer` walks the GraphQL schema and emits these relationships as `CascadeRule`s.

```python
from dataclasses import dataclass


@dataclass
class CascadeRule:
    """A CASCADE invalidation rule."""

    source_domain: str   # domain that triggers invalidation when it changes
    target_domain: str   # domain whose caches should be invalidated
    rule_type: str = "invalidate"
    confidence: float = 1.0
```

### 4.2 Setup at Startup

`setup_auto_cascade_rules` analyzes the schema and registers every rule on a `PostgresCache`:

```python
from fraiseql.caching import setup_auto_cascade_rules


@app.on_event("startup")
async def configure_cache_cascade() -> None:
    # `cache` is a PostgresCache; `schema` is the GraphQL schema
    registered = await setup_auto_cascade_rules(cache, schema, verbose=True)
    logger.info("Registered %d CASCADE rules", registered)
```

For finer control, drive `SchemaAnalyzer` directly:

```python
from fraiseql.caching import SchemaAnalyzer

analyzer = SchemaAnalyzer(schema)
rules = analyzer.analyze_relationships()          # list[CascadeRule]
deps = analyzer.get_domain_dependencies()         # {domain: {dependencies}}

for rule in rules:
    await cache.register_cascade_rule(
        source_domain=rule.source_domain,
        target_domain=rule.target_domain,
        rule_type=rule.rule_type,
    )
```

### 4.3 Example: Detected Relationships

Given:

```graphql
type Post {
  id: ID!
  title: String!
  author: User!        # relationship detected
  comments: [Comment!]!
}

type User {
  id: ID!
  name: String!
}

type Comment {
  id: ID!
  content: String!
  author: User!
}
```

`SchemaAnalyzer` produces rules such as:

- `user → post` (when a user changes, invalidate posts)
- `post → comment` (when a post changes, invalidate comments)
- `user → comment` (when a user changes, invalidate comments)

Self-references (e.g. `parent: User` on `User`) are skipped, and list relationships are registered with slightly lower confidence than scalar ones.

### 4.4 Database-Level Invalidation (PostgreSQL)

CASCADE invalidation is most effective when the database itself signals domain changes. `PostgresCache.setup_table_trigger(...)` installs triggers, and the optional `pg_fraiseql_cache` extension maintains per-tenant domain versions so cache entries can be validated against the current domain version. When the extension is absent, FraiseQL falls back to TTL-only caching plus explicit pattern invalidation.

If you prefer to manage triggers yourself, write to your own invalidation log from a `fn_` function or trigger and have a background task drain it into `cache.invalidate_pattern(...)` calls. Always route writes through `fn_` PostgreSQL functions (called via `db.execute_function`) so invalidation has a single chokepoint.

---

## 5. Configuration in Production

The cache is constructed in code, not in a config file. Use environment variables to choose TTLs and the database, then build the `PostgresCache` + `ResultCache` during app startup.

### 5.1 Development Configuration

```python
from fraiseql.caching import CacheConfig, ResultCache, PostgresCache

# Local development: short TTL, errors cached for debugging
cache_config = CacheConfig(
    enabled=True,
    default_ttl=60,     # 1 minute (frequent changes)
    cache_errors=True,  # cache errors while debugging
)
backend = PostgresCache(connection_pool=dev_pool)
cache = ResultCache(backend=backend, config=cache_config)
```

### 5.2 Staging Configuration

```python
import os

from fraiseql.caching import CacheConfig, ResultCache, PostgresCache
from psycopg_pool import AsyncConnectionPool

cache_config = CacheConfig(
    enabled=True,
    default_ttl=300,     # 5 minutes
    cache_errors=False,  # don't cache errors in staging
)
pool = AsyncConnectionPool(os.environ["STAGING_DB_URL"])
cache = ResultCache(backend=PostgresCache(pool), config=cache_config)
```

### 5.3 Production Configuration

```python
import os

from fraiseql.caching import CacheConfig, ResultCache, PostgresCache
from psycopg_pool import AsyncConnectionPool

cache_config = CacheConfig(
    enabled=True,
    default_ttl=600,     # 10 minutes (conservative)
    max_ttl=3600,        # never cache longer than 1 hour
    cache_errors=False,
    key_prefix="fraiseql",
)
pool = AsyncConnectionPool(os.environ["PROD_DB_URL"])
cache = ResultCache(backend=PostgresCache(pool), config=cache_config)
```

### 5.4 Environment Variables

Drive the values above from your own `FRAISEQL_`-prefixed environment variables (FraiseQL configuration uses the `FRAISEQL_` prefix via `FraiseQLConfig`):

```bash
# Development
FRAISEQL_CACHE_ENABLED=true
FRAISEQL_CACHE_TTL=60

# Staging
FRAISEQL_CACHE_ENABLED=true
FRAISEQL_CACHE_TTL=300
FRAISEQL_CACHE_DB_URL=postgresql://...

# Production
FRAISEQL_CACHE_ENABLED=true
FRAISEQL_CACHE_TTL=600
FRAISEQL_CACHE_MAX_TTL=3600
FRAISEQL_CACHE_DB_URL=postgresql://...
```

Read these in your startup code and pass them into `CacheConfig` / `PostgresCache`.

---

## 6. Best Practices

### 6.1 Cache Strategy Decision Tree

```text
Is data frequently queried?
├─ YES: Cache it
│   ├─ Is data frequently modified?
│   │   ├─ YES: Shorter TTL (60-300 seconds)
│   │   └─ NO: Longer TTL (300-3600 seconds)
│   └─ End: Use caching
└─ NO: Don't cache
    └─ Monitor to ensure cache isn't wasted
```

### 6.2 TTL Guidelines

| Data Type | Update Frequency | Recommended TTL | Example |
|-----------|------------------|-----------------|---------|
| User Profile | Hours | 600-1800s | User account settings |
| Product Catalog | Days | 3600s (capped by max_ttl) | E-commerce products |
| Real-time Data | Seconds | 30-60s | Stock prices, weather |
| Derived Data | Minutes | 300-600s | Rankings, aggregates |
| Reference Data | Never | 3600s (max_ttl) | Countries, currencies |

`CacheConfig.max_ttl` (default 3600s) caps every entry, so set it deliberately for very-long-lived data.

### 6.3 Per-Query TTL

```python
# Cheap, stable queries → long TTL; expensive/volatile → short TTL
await cached_repo.find("v_country", cache_ttl=3600)   # reference data
await cached_repo.find("v_dashboard", cache_ttl=60)   # expensive aggregate
```

### 6.4 Monitoring Checklist

- [ ] `CacheStats.hit_rate` > 80% for normal workload
- [ ] `cleanup_expired()` keeping the expired backlog small
- [ ] `fraiseql_cache` table size stable (not growing unbounded)
- [ ] TTLs match data volatility
- [ ] CASCADE / invalidation patterns matching mutations
- [ ] Tenant isolation verified in testing

---

## 7. Troubleshooting

### 7.1 Low Cache Hit Rate

**Symptoms:** `CacheStats.hit_rate` < 60%

**Causes:**

1. Filters changing between requests (same view, different filters → different keys)
2. TTL too short — entries expiring too quickly
3. Wrong query/table name in invalidation patterns

**Solutions:**

1. Normalize filter inputs before querying
2. Increase `default_ttl` (and `max_ttl` if it is clamping you)
3. Review the patterns passed to `invalidate_pattern` and the table names derived by `execute_function`

### 7.2 Cache Growth

**Symptoms:** `fraiseql_cache` table grows unbounded

**Causes:**

1. `cleanup_expired()` not running
2. TTLs too long — entries not expiring
3. High cardinality in query filters (unbounded set of keys)

**Solutions:**

1. Schedule `cleanup_expired()` from a background task
2. Decrease `default_ttl` / `max_ttl`
3. Reduce filter cardinality or cache at a coarser granularity

### 7.3 Stale Data in Cache

**Symptoms:** Old data served even after updates

**Causes:**

1. Invalidation patterns not matching the mutation's table
2. CASCADE rules not registered at startup
3. Database update bypassed the `fn_` mutation path

**Solutions:**

1. Review the `invalidate_pattern` / `build_mutation_pattern` table names
2. Call `setup_auto_cascade_rules(cache, schema)` at startup
3. Ensure all writes go through `fn_` functions invoked via `db.execute_function`

---

## 8. Security Considerations

### 8.1 Tenant Isolation

**Guaranteed:** Cache keys include `tenant_id` immediately after the prefix.
**Verify:** Always source `tenant_id` from the authenticated context.

```python
import fraiseql


@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    # CORRECT: tenant_id comes from info.context (set from the auth token),
    # which the CachedRepository folds into the cache key.
    return await db.find("v_user")

    # WRONG: never trust a client-supplied tenant_id for cache scoping.
```

### 8.2 Error Caching

**Warning:** Caching error responses can leak information.

```python
from fraiseql.caching import CacheConfig

# Cache errors only in development
cache_config = CacheConfig(
    cache_errors=(os.getenv("ENVIRONMENT") == "development"),
)
```

### 8.3 Sensitive Data

**Best Practice:** Don't cache PII or sensitive data. Expose only the public-facing fields in your read views and cache those.

```python
import fraiseql


# Prefer caching a public-profile view over a full user record:
@fraiseql.query
async def user_profile(info, id: ID) -> UserProfile:
    """Returns only public profile fields from v_user_profile."""
    db = info.context["db"]
    return await db.find_one("v_user_profile", id=id)
```

---

## 9. Performance Example

### 9.1 Real-World Pattern

**Setup:**

- A high-read `v_user` view queried with a small set of common filters
- `PostgresCache` (UNLOGGED table) shared across multiple FastAPI instances
- `default_ttl = 300` (5 minutes)

**Outcome:**

- Repeated reads of the same filter combination hit the cache (`CacheStats.hits` climbs).
- A write through `fn_update_user` invalidates the matching `v_user`/`v_users` patterns, so the next read repopulates the entry.
- Because the table is shared, a cache warmed by one instance serves every other instance.

Measure your own workload with `cache.get_stats()` and the SQL occupancy query in [Section 2.10](#210-cache-monitoring--metrics) before tuning TTLs.

---

## 10. Related Specifications

- **docs/specs/persisted-queries.md** — Persisted queries (reuse this caching layer)
- **docs/guides/monitoring.md** — Cache metrics and observability
- **docs/guides/production-deployment.md** — Cache configuration in production
- **docs/architecture/core/execution-model.md** — Where caching fits in query execution

---

## Glossary

| Term | Definition |
|------|-----------|
| **Cache Hit** | Requested data found in cache |
| **Cache Miss** | Requested data not in cache, retrieved from the database |
| **TTL (Time-To-Live)** | How long a cache entry remains valid (`expires_at`) |
| **Tenant Isolation** | Guarantee that one tenant cannot access another's cached data |
| **Invalidation** | Removing cache entries (by key or pattern) so they are recomputed |
| **CASCADE** | Automatic invalidation of dependent domains' caches when a domain changes |
| **CascadeRule** | A `source_domain → target_domain` invalidation relationship derived from the schema |
| **UNLOGGED Table** | PostgreSQL table without write-ahead logging (faster writes, lost on crash) |
| **Domain Versioning** | Optional `pg_fraiseql_cache` mechanism that validates entries against per-tenant domain versions |
