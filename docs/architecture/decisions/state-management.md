---
title: FraiseQL State Management — Source of Truth and Result Caching
description: How FraiseQL keeps PostgreSQL as the single source of truth while caching query results with cascade invalidation.
keywords: ["caching", "consistency", "performance", "patterns", "postgresql"]
tags: ["documentation", "reference"]
---

# FraiseQL State Management — Source of Truth and Result Caching

**Status:** Stable
**Audience:** Application architects, backend engineers, DBAs

---

## Executive Summary

FraiseQL state management is built on one principle:

> **PostgreSQL is the single source of truth. Everything else is an optimization layer.**

There is no separate state store, no event bus, and no change-data-capture pipeline in
FraiseQL v1. Application state lives in your PostgreSQL tables (`tb_*`), is exposed through
read views (`v_*` / `tv_*`), and is mutated through PostgreSQL functions (`fn_*`). On top of
that, FraiseQL ships a real **result cache** (`src/fraiseql/caching/`) that caches the JSONB
results of view queries and invalidates them when the underlying data changes.

This document covers two concerns:

1. **The state model** — how PostgreSQL provides consistency for reads and writes.
2. **Result caching** — how FraiseQL caches query results and keeps them coherent with the
   database via TTL expiry and cascade invalidation.

---

## 1. The State Model

### 1.1 Source of truth

All durable state lives in PostgreSQL:

| Layer | Object | Role |
|-------|--------|------|
| Write side | `tb_*` tables | Normalized source of truth |
| Write logic | `fn_*` functions | Validation + writes (called by mutations) |
| Read side | `v_*` views | Logical views building a `data` JSONB column |
| Read side | `tv_*` projection tables | Pre-composed JSONB for heavy nested reads |

Queries read from `v_*` / `tv_*` views via `db.find(...)` / `db.find_one(...)`. Mutations
call `fn_*` functions via `db.execute_function(...)`. No business state is held in the Python
process — the schema is assembled in memory at startup, but the data is always PostgreSQL's.

### 1.2 Consistency for a single database

Within a single PostgreSQL instance, consistency is whatever transaction isolation your
database is configured for. A query started after a mutation commits sees that mutation's
effects:

```text
T0     Query: db.find("v_user")            sees A, B, C
T0+1ms Mutation: db.execute_function(
         "fn_create_user", {...})          commits user D
T0+10ms Query: db.find("v_user")           sees A, B, C, D
```

PostgreSQL is the arbiter. FraiseQL does not add its own consistency protocol on top of it.

### 1.3 Read replicas

If you route reads to PostgreSQL read replicas, you inherit PostgreSQL's streaming
replication semantics: writes go to the primary and become visible on replicas after a small
replication lag (typically well under a second). This is standard PostgreSQL operations, not a
FraiseQL feature; configure it through your connection routing and `DATABASE_URL`. See the
consistency model document linked at the end for the guarantees this provides.

---

## 2. Result Caching

### 2.1 What the cache stores

FraiseQL caches the **result of a view query** — the JSONB payload returned by
`db.find(...)` / `db.find_one(...)` — keyed by the view name, tenant, and query parameters.
The cache is an optimization: a cache miss simply re-runs the query against PostgreSQL, so the
database remains the source of truth at all times.

The public API lives in `fraiseql.caching`:

| Symbol | Purpose |
|--------|---------|
| `PostgresCache` | PostgreSQL-backed cache backend (UNLOGGED table) |
| `CacheBackend` | Protocol any backend implements (`get`/`set`/`delete`/`delete_pattern`) |
| `ResultCache` | Cache-aside engine (`get_or_set`, `invalidate`, `invalidate_pattern`, stats) |
| `CacheConfig` | TTL and behaviour configuration |
| `CacheStats` | Hit/miss/error counters and `hit_rate` |
| `CacheKeyBuilder` | Deterministic, tenant-isolated cache keys |
| `CachedRepository` | Drop-in repository wrapper that caches reads and invalidates on writes |
| `cached_query` | Decorator to cache an arbitrary async query function |
| `CascadeRule` | One source-domain → target-domain invalidation rule |
| `SchemaAnalyzer` | Derives cascade rules from your GraphQL schema |
| `setup_auto_cascade_rules` | Registers all derived cascade rules at startup |

### 2.2 The PostgreSQL cache backend

`PostgresCache` is the default backend. It stores cache entries in an `UNLOGGED` PostgreSQL
table, so writes skip the WAL and run at in-memory speeds, while the entries remain shared
across every application instance pointed at the same database. UNLOGGED tables are cleared on
crash/restart, which is acceptable for cache data that can be regenerated.

```python
from psycopg_pool import AsyncConnectionPool
from fraiseql.caching import PostgresCache, ResultCache, CacheConfig

pool = AsyncConnectionPool("postgresql://localhost/mydb")

backend = PostgresCache(pool, table_name="fraiseql_cache")
cache = ResultCache(backend, CacheConfig(default_ttl=300, max_ttl=3600))
```

Because the cache lives in PostgreSQL, every instance sees the same entries and the same
invalidations — there is no separate caching cluster to operate, and no cross-instance event
stream to coordinate.

### 2.3 Cache-aside pattern

`ResultCache.get_or_set` implements the cache-aside pattern: look up the key, and on a miss,
run the function, store the result, and return it.

```python
async def get_user_posts(cache: ResultCache, db, user_id):
    key = cache.key_builder.build_key("v_post", filters={"user_id": user_id})

    async def fetch():
        return await db.find("v_post", user_id=user_id)

    return await cache.get_or_set(key, fetch, ttl=300)
```

On a hit it returns the cached JSONB; on a miss it queries the `v_post` view and caches the
result. Hit/miss/error counters are tracked on `cache.get_stats()`.

### 2.4 Cache keys and tenant isolation

`CacheKeyBuilder` produces deterministic keys from the view name plus filters, ordering, and
pagination. Crucially, it folds the `tenant_id` into the key so one tenant can never read
another tenant's cached data:

```python
key = cache.key_builder.build_key(
    query_name="v_post",
    tenant_id=tenant_id,        # prevents cross-tenant cache poisoning
    filters={"status": "published"},
    limit=20,
)
```

`CachedRepository` does this automatically: it reads `tenant_id` from the repository context
and includes it in every key. Never cache before an authorization check — caching is keyed by
inputs, not by the caller's permissions, so authorization must run on every request.

### 2.5 TTL

`CacheConfig` controls time-to-live. `default_ttl` applies when a call does not specify one,
and `max_ttl` caps any per-call TTL. Choose TTL by how fresh the data must be and how
expensive the miss is:

```text
Slow-changing reference data    long TTL (e.g. 1 hour) — rarely re-queried
User-scoped data                short TTL (e.g. 5 minutes)
Frequently changing data        very short TTL (e.g. 10–30 seconds)
```

Even without explicit invalidation, TTL guarantees the cache is never stale for longer than
its lifetime — a hard backstop for correctness.

### 2.6 The cached repository

`CachedRepository` wraps a `FraiseQLRepository` so that reads are cached and writes invalidate
the affected entries automatically — no changes to your resolvers:

```python
from fraiseql.caching import CachedRepository, ResultCache, PostgresCache

cached_db = CachedRepository(base_repository=db, cache=ResultCache(PostgresCache(pool)))

# Reads go through the cache (tenant-isolated key, cache-aside)
posts = await cached_db.find("v_post", status="published")

# Per-call overrides
fresh = await cached_db.find("v_post", skip_cache=True)          # bypass cache
short = await cached_db.find("v_post", cache_ttl=30)             # custom TTL
```

When a mutation runs through the cached repository, it invalidates the affected entries:

```python
# Calls fn_update_post, then invalidates cached "post" (and "posts") entries
await cached_db.execute_function("fn_update_post", {"id": post_id, "title": "Updated"})
```

`execute_function` derives the affected view name from the function name and calls
`invalidate_pattern` for both the singular and plural forms, so reads of those views miss on
their next request and re-read fresh data from PostgreSQL.

### 2.7 Write path and invalidation

The write path is always: mutation resolver → `fn_*` function → cache invalidation.

```text
Mutation: fn_update_post(post_id=789)
    1. db.execute_function runs fn_update_post (write commits in PostgreSQL)
    2. Cache entries for the affected view(s) are invalidated
    3. Next read of those views misses → re-queries PostgreSQL → re-caches
```

Because the database commit happens first and invalidation second, a reader can at worst see a
slightly stale cache entry until invalidation completes or the TTL expires — never lost or
corrupted data. The source of truth is always correct.

---

## 3. Cascade Invalidation

A single mutation often affects more than one cached view. Updating a `User` should invalidate
cached `Post` results that embed that user's data. FraiseQL models this with **cascade rules**.

### 3.1 Cascade rules

A `CascadeRule` says "when the source domain changes, invalidate the target domain":

```python
from fraiseql.caching import CascadeRule

# When user data changes, invalidate post caches
rule = CascadeRule(source_domain="user", target_domain="post", rule_type="invalidate")
```

Rules are registered on a `PostgresCache` via `register_cascade_rule`. Cascade invalidation
requires the optional `pg_fraiseql_cache` PostgreSQL extension; if it is not installed,
`PostgresCache` falls back to TTL-only caching and skips cascade registration.

### 3.2 Automatic cascade rules from the schema

You rarely write cascade rules by hand. `SchemaAnalyzer` walks your GraphQL schema and derives
a rule for every relationship field — `Post.author -> User` produces `user → post`,
`Comment.author -> User` produces `user → comment`, and so on. `setup_auto_cascade_rules`
analyzes the schema and registers all derived rules in one call:

```python
from fraiseql.caching import setup_auto_cascade_rules

# Run once at application startup (e.g. from a FastAPI lifespan handler)
async def configure_cache_cascades():
    count = await setup_auto_cascade_rules(cache, app.schema, verbose=True)
    logger.info("Registered %d cascade rules", count)
```

The analyzer reports each rule as `source_domain → target_domain` and builds a domain
dependency graph (for example `comment` depends on `{user, post}`), giving you zero-config
cache coherence that follows your real type relationships.

### 3.3 How a cascade fires

```text
Mutation: fn_update_user(user_id=456)
    1. fn_update_user commits in PostgreSQL
    2. "user" domain marked changed
    3. Cascade rules fire:
         user → post      → invalidate cached posts that embed this user
         user → comment   → invalidate cached comments that embed this user
    4. Next reads of those views miss → re-query PostgreSQL → re-cache
```

---

## 4. Layered Caching Thinking

The classic L1/L2 layering still applies, expressed through this API rather than a bespoke
multi-tier cache:

- **PostgreSQL as the shared cache layer.** `PostgresCache` (an UNLOGGED table) is fast and
  shared across all instances, filling the role a separate cache cluster would otherwise play
  — with no extra infrastructure.
- **Per-call read-through.** `ResultCache.get_or_set` (and `CachedRepository`) is the
  read-through tier: every read checks the cache first and only touches the underlying view on
  a miss.
- **PostgreSQL views/projection tables as the durable backing store.** `v_*` views and `tv_*`
  projection tables are the permanent state; `tv_*` tables additionally pre-compose heavy
  JSONB so even a cache miss is cheap.

If you need an additional in-process or external tier, implement the `CacheBackend` protocol
(`get` / `set` / `delete` / `delete_pattern`) and pass it to `ResultCache`. The cache-aside,
TTL, and cascade behaviour come for free regardless of backend.

---

## 5. Decorator-Based Caching

For caching an arbitrary async query function (outside the repository), use `cached_query`:

```python
from fraiseql.caching import cached_query, ResultCache, PostgresCache

cache = ResultCache(PostgresCache(pool))

@cached_query(cache, ttl=60)
async def trending_posts(limit: int = 20):
    return await db.find("v_post", order_by=[("score", "desc")], limit=limit)

# Bypass on demand
fresh = await trending_posts(limit=20, skip_cache=True)
```

The decorator builds a key from the function name and arguments (or a `key_func` you provide)
and runs the same cache-aside path as `ResultCache.get_or_set`.

---

## 6. Monitoring

`ResultCache.get_stats()` returns a `CacheStats` with `hits`, `misses`, `errors`, `total`, and
a computed `hit_rate`. `PostgresCache.get_stats()` exposes backend-level statistics (entry
counts, expiry). Watch:

- **Hit rate** — aim high; a sustained low hit rate suggests TTLs are too short or keys are too
  granular.
- **Invalidation activity** — a spike alongside writes is expected; a constant churn may mean
  cascade rules are too broad.
- **Errors** — cache errors are logged and degrade gracefully to a direct database read, so the
  request still succeeds; investigate the trend, not individual misses.

---

## 7. Best Practices

**Do**

- Treat PostgreSQL as the source of truth — the cache is always optional for correctness.
- Always include `tenant_id` in cache keys (`CacheKeyBuilder` / `CachedRepository` do this).
- Set a TTL on every cached query as a correctness backstop, even with cascade rules.
- Let `setup_auto_cascade_rules` derive cascade rules from your schema; add manual
  `CascadeRule`s only for relationships the schema can't express.
- Run authorization on every request, before serving from cache.

**Don't**

- Rely on the cache for correctness — it is an optimization, not a state store.
- Cache without a TTL.
- Cache a value before checking the caller's permissions.
- Invent an external event pipeline for invalidation — invalidation is driven by mutations
  going through `fn_*` functions and the cascade rules above.

---

## See Also

- [Anti-Patterns](./anti-patterns.md) — state and caching mistakes to avoid.
- [Consistency Model](../reliability/consistency-model.md) — the guarantees PostgreSQL provides.
- [tv_ Table Pattern](../database/tv-table-pattern.md) — pre-composed projection tables for heavy reads.
- [View Selection Guide](../database/view-selection-guide.md) — choosing between `v_` and `tv_` sources.
- [Performance Characteristics](../../foundation/12-performance-characteristics.md) — latency and throughput context.
- [Result Caching Guide](../../performance/caching.md) — full configuration and the `pg_fraiseql_cache` extension.
