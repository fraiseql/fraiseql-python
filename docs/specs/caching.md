---

title: Caching Specification
description: What fraiseql.caching provides - a PostgreSQL-backed result cache with TTL expiry and pattern invalidation - and what it doesn't.
keywords: ["format", "compliance", "protocol", "specification", "standard"]
tags: ["documentation", "reference"]
---

# Caching Specification

**Version:** 1.31
**Status:** Describes the code as it is
**Audience:** Database architects, schema designers, API developers, operations engineers

---

## 1. Overview

`fraiseql.caching` is a result cache you wire into your own code. Nothing in
`create_fraiseql_app` turns it on, and no `FraiseQLConfig` setting or environment
variable configures it: you build the cache in Python and call it.

```python
from fraiseql.caching import (
    CacheBackend,         # protocol: get / set / delete / delete_pattern
    CacheConfig,          # enabled, default_ttl, max_ttl, cache_errors, key_prefix
    CacheKeyBuilder,      # deterministic keys, tenant id second
    CacheStats,           # hits / misses / errors, hit_rate
    CachedRepository,     # FraiseQLRepository wrapper (see 2.6: doesn't cache find results today)
    CascadeRule,          # source_domain -> target_domain
    PostgresCache,        # backend: a PostgreSQL UNLOGGED table
    PostgresCacheError,
    ResultCache,          # get_or_set, invalidate, invalidate_pattern, stats
    SchemaAnalyzer,       # derives CascadeRules from a GraphQL schema
    cached_query,         # decorator over ResultCache.get_or_set
    setup_auto_cascade_rules,
)
```

What it gives you:

- **A shared cache**: `PostgresCache` stores entries in an `UNLOGGED` table, so every
  instance using the same database sees them.
- **TTL expiry**: each entry has an `expires_at`; expired entries are never returned.
- **Explicit invalidation**: by key, or by a `*` pattern.

What it doesn't do: it doesn't cache GraphQL responses, it doesn't invalidate
anything when a mutation runs, and the CASCADE rules it can derive from the schema
don't invalidate `ResultCache` entries (see [Section 4](#4-cascade-rules)).

---

## 2. Query Result Caching

### 2.1 `CacheConfig`

```python
from dataclasses import dataclass


@dataclass
class CacheConfig:
    enabled: bool = True       # False: get_or_set always runs the function
    default_ttl: int = 300     # seconds, when the call gives no ttl
    max_ttl: int = 3600        # every ttl is capped to this
    cache_errors: bool = False # see below
    key_prefix: str = "fraiseql"
```

`cache_errors` doesn't cache exceptions (a function that raises is never cached).
It decides what happens when the backend fails on a read: `False` runs the function
and returns its result without storing it; `True` runs it and still tries to store
the result.

### 2.2 `ResultCache`

```python
from psycopg_pool import AsyncConnectionPool

from fraiseql.caching import CacheConfig, PostgresCache, ResultCache

pool = AsyncConnectionPool("postgresql://localhost/mydb", open=False)
await pool.open()

cache = ResultCache(
    backend=PostgresCache(connection_pool=pool),
    config=CacheConfig(default_ttl=300, max_ttl=3600),
)


async def load_top_sellers() -> list[dict]:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT data FROM v_top_seller ORDER BY rank LIMIT 10")
        return [row[0] for row in await cur.fetchall()]


top = await cache.get_or_set("fraiseql:top_sellers", load_top_sellers, ttl=600)
```

`get_or_set(key, func, ttl=None)` returns the stored value when there is one, and
otherwise awaits `func()`, stores its result for `min(ttl or default_ttl, max_ttl)`
seconds and returns it. A result of `None` is stored but reads back as a miss, so
it's recomputed every time. Backend errors are logged (`fraiseql.caching.result_cache`,
`WARNING`), counted in `stats.errors`, and never raised.

The value must be JSON-serializable for `PostgresCache`: it's stored as JSONB and
read back as JSON. A value `json.dumps` can't encode (a `datetime`, a `UUID`, a
dataclass) isn't stored: the failure is logged and counted as an error, and the
next call runs the function again.

### 2.3 `cached_query`

```python
from fraiseql.caching import cached_query


@cached_query(cache, ttl=600)
async def top_sellers(region: str) -> list[dict]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT data FROM v_top_seller WHERE region = %s ORDER BY rank LIMIT 10", (region,)
        )
        return [row[0] for row in await cur.fetchall()]


await top_sellers(region="emea")                   # computed and stored
await top_sellers(region="emea")                   # from the cache
await top_sellers(region="emea", skip_cache=True)  # computed, not stored
```

The key is the function name followed by its positional arguments and its sorted
keyword arguments: `top_sellers:region:emea`. It has no prefix and no tenant id;
pass `key_func=` (called with the keyword arguments) to build your own, e.g. with a
tenant:

```python
@cached_query(cache, ttl=600, key_func=lambda tenant_id, region: f"fraiseql:{tenant_id}:top_sellers:{region}")
async def tenant_top_sellers(tenant_id: str, region: str) -> list[dict]: ...
```

### 2.4 Cache Keys (`CacheKeyBuilder`)

```python
from fraiseql.caching import CacheKeyBuilder

CacheKeyBuilder().build_key(
    "v_user",
    tenant_id="org_123",
    filters={"status": "active"},
    order_by=[("name", "asc")],
    limit=20,
    offset=0,
)
# 'fraiseql:org_123:v_user:status:active:order:name:asc:limit:20:offset:0'
```

The parts are joined with `:`: the prefix, the tenant id (when given), the query
name, each filter sorted by field (`field:value`, or `field:op:value` for an operator
dict), `order:field:direction`, `limit:N`, `offset:N`, then any extra keyword
arguments. A list of strings is sorted and joined with commas; another list becomes
an 8-character hash. `build_mutation_pattern("user")` returns `fraiseql:user:*`.

Put the tenant id in every key of tenant data: two tenants then never read each
other's entries. Nothing adds it for you outside `CachedRepository`.

### 2.5 Invalidation

```python
await cache.invalidate("fraiseql:top_sellers")           # one key
await cache.invalidate_pattern("fraiseql:org_123:*")      # every key of a tenant
```

`invalidate_pattern` turns `*` into SQL `LIKE`'s `%` (so `_` in a pattern also
matches any one character). Call them where your code writes, e.g. after the
mutation resolver's SQL function returns. Errors are logged, not raised.

### 2.6 `CachedRepository`

`CachedRepository(base_repository, cache)` wraps a `FraiseQLRepository`: `find` and
`find_one` take `skip_cache=False` and `cache_ttl=None`, build a key from the view
name, the repository context's `tenant_id` and the keyword arguments, and go through
`get_or_set`; `execute_function` invalidates afterwards; other methods are
delegated.

> **Known issue (1.31.0):** with `PostgresCache`, `find` / `find_one` never store
> anything. They return `RustResponseBytes`, which isn't JSON-serializable, so each
> call reads the database, logs `Cache set error ... not JSON serializable`, and
> counts a miss and an error. And `execute_function("fn_update_user", ...)`
> invalidates `fraiseql:user:*` and `fraiseql:users:*`, which never match the keys
> `find` builds (`fraiseql:<tenant>:v_user:...`). Cache the data your resolvers
> compute with `get_or_set` / `cached_query` instead.

### 2.7 Backends

A backend implements the `CacheBackend` protocol:

```python
from typing import Any, Protocol


class CacheBackend(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def delete(self, key: str) -> bool: ...
    async def delete_pattern(self, pattern: str) -> int: ...
```

**`PostgresCache(connection_pool, table_name="fraiseql_cache", auto_initialize=True)`**
creates its table on first use (whatever `auto_initialize` says):

```sql
CREATE UNLOGGED TABLE IF NOT EXISTS fraiseql_cache (
    cache_key TEXT PRIMARY KEY,
    cache_value JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS fraiseql_cache_expires_idx ON fraiseql_cache (expires_at);
```

An `UNLOGGED` table skips the write-ahead log: writes are cheaper, and PostgreSQL
empties the table after a crash, which a cache can afford. It isn't replicated to
standbys either.

Besides the protocol methods, it has `exists(key)`, `ping()`, `get_stats()` (
`total_entries`, `expired_entries`, `active_entries`, `table_size_bytes`),
`cleanup_expired()` (deletes the expired rows, returns how many) and `clear_all()`.
Expired rows aren't returned but stay in the table until `cleanup_expired()` runs;
schedule it:

```python
import asyncio


async def purge_cache(backend: PostgresCache) -> None:
    while True:
        await backend.cleanup_expired()
        await asyncio.sleep(600)
```

Any other object with the four protocol methods works as a backend, e.g. one on
Redis (`SET key value EX ttl`, `SCAN` + `DEL` for patterns).

### 2.8 Monitoring

```python
stats = cache.get_stats()            # CacheStats(hits=..., misses=..., errors=...)
print(f"hit rate: {stats.hit_rate:.1f}%")  # 0-100
cache.reset_stats()

print(await cache.backend.get_stats())  # PostgresCache: entries and table size
```

`CacheStats` counts this process's calls only. A growing `errors` count usually
means values that can't be stored (not JSON) or a backend that can't be reached.

```sql
-- Occupancy, from any instance
SELECT
    COUNT(*)                                    AS total_entries,
    COUNT(*) FILTER (WHERE expires_at <= NOW()) AS expired_entries,
    pg_size_pretty(pg_total_relation_size('fraiseql_cache')) AS table_size
FROM fraiseql_cache;
```

---

## 3. What Isn't Cached

- **GraphQL responses**: no layer caches them. APQ (`apq_cache_responses=True`) can
  store responses of persisted queries; see [Persisted Queries](persisted-queries.md).
- **Mutations**: nothing invalidates on its own when a mutation runs.

---

## 4. CASCADE Rules

`SchemaAnalyzer(schema).analyze_relationships()` returns a `CascadeRule` per object
field that references another object type: for `Post.author: User`, the rule
`user → post` ("when a user changes, posts are stale"). Type names become snake_case
domains; self-references and `Query` / `Mutation` / `Subscription` are skipped; a
list field gets `confidence=0.9`, others `1.0`.

```python
from fraiseql.caching import SchemaAnalyzer, setup_auto_cascade_rules

rules = SchemaAnalyzer(schema).analyze_relationships()  # [CascadeRule('user', 'post', ...)]
await setup_auto_cascade_rules(postgres_cache, schema)
```

`setup_auto_cascade_rules(cache, schema, verbose=False)` passes each rule to
`PostgresCache.register_cascade_rule`, which stores it in the
`fraiseql_cache.cascade_rules` table of the `pg_fraiseql_cache` PostgreSQL extension
(a separate project; see [PostgreSQL Extensions](../core/postgresql-extensions.md)).
Without the extension, `register_cascade_rule` logs a warning and does nothing, and
`setup_auto_cascade_rules` still returns the number of rules.

Even with the extension, `ResultCache`, `cached_query` and `CachedRepository` don't
check domain versions: the rules invalidate none of their entries. Only the RBAC
permission cache (`fraiseql.enterprise.rbac`) reads them. For query results, rely on
TTLs and on `invalidate` / `invalidate_pattern` where you write.

---

## 5. Configuration

There is no cache setting in `FraiseQLConfig` and no `FRAISEQL_CACHE_*` variable
for this cache. (`FraiseQLConfig.cache_ttl`, read from `FRAISEQL_CACHE_TTL`, is
deprecated and has no effect.) Read your own settings and pass them in:

```python
import os

from fraiseql.caching import CacheConfig, PostgresCache, ResultCache

cache = ResultCache(
    backend=PostgresCache(connection_pool=pool),
    config=CacheConfig(
        enabled=os.environ.get("APP_CACHE_ENABLED", "true") == "true",
        default_ttl=int(os.environ.get("APP_CACHE_TTL", "300")),
        max_ttl=int(os.environ.get("APP_CACHE_MAX_TTL", "3600")),
    ),
)
```

### 5.1 TTL Guidelines

| Data | Changes | TTL |
|------|---------|-----|
| Reference data (countries, currencies) | Rarely | up to `max_ttl` |
| Catalogs, profiles | Hours | 600-1800 s |
| Aggregates, rankings | Minutes | 60-300 s |
| Real-time data | Seconds | don't cache, or 5-30 s |

Raise `max_ttl` for data that may live longer than an hour: it caps every TTL.

---

## 6. Troubleshooting

**Nothing is cached** (`stats.misses` grows, `stats.errors` too): the values aren't
JSON-serializable (look for `Cache set error` warnings), or they're `CachedRepository`
reads (see [2.6](#26-cachedrepository)). Cache JSON data (dicts, lists, strings,
numbers).

**Low hit rate**: keys differ between calls that should share one (argument order
doesn't matter for keyword arguments, but values do: normalize them), or the TTL
is short.

**Stale data after a write**: nothing invalidates automatically; call
`invalidate_pattern` with a pattern that matches the keys you built.

**Table growing**: `cleanup_expired()` isn't running, or keys have unbounded
cardinality (one per user input).

---

## 7. Security

- **Tenant isolation** depends on the keys: put the tenant id (from the
  authenticated context, never from a client argument) in every key of tenant
  data. `CacheKeyBuilder.build_key(tenant_id=...)` puts it second.
- **Sensitive data**: entries are plain JSONB in a table every role with access to
  it can read. Don't cache what that role shouldn't see.

---

## Glossary

| Term | Definition |
|------|-----------|
| **Cache Hit** | `get_or_set` found a stored, unexpired value |
| **Cache Miss** | No value (or `None`): the function ran |
| **TTL** | Seconds an entry stays valid (`expires_at`) |
| **Invalidation** | Deleting entries by key or `*` pattern |
| **CascadeRule** | A `source_domain → target_domain` relationship derived from the schema, used by the `pg_fraiseql_cache` extension |
| **UNLOGGED Table** | A PostgreSQL table without write-ahead logging: faster writes, emptied after a crash |
