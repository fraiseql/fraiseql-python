# Result Caching

How to cache query results with `fraiseql.caching`: a PostgreSQL-backed cache with
TTL expiry and explicit invalidation. The reference is the
[Caching Specification](../specs/caching.md); this page shows how to use it.

## Overview

`fraiseql.caching` stores results in a PostgreSQL `UNLOGGED` table:

- **No extra service**: the cache lives in the database you already run, and every
  application instance using that database shares it.
- **TTL expiry**: each entry has an `expires_at`; expired entries are never returned.
- **Explicit invalidation**: by key, by `*` pattern, or by view
  (`CachedRepository.invalidate_view`). `CachedRepository.execute_function` invalidates
  the views of the entity the SQL function writes.
- **Tenant isolation**: `CachedRepository` puts the repository context's `tenant_id`
  in every key.

It is opt-in, and you wire it yourself: `create_fraiseql_app` has no caching
setting, and there is no `FraiseQLConfig` setting or `FRAISEQL_CACHE_*` environment
variable for it. You build the cache in Python and hand a `CachedRepository` to your
resolvers as `info.context["db"]`.

What it doesn't do: it doesn't cache whole GraphQL responses (`CachedRepository`
caches each `find` / `find_one` call), class mutations (`@fraiseql.mutation class
...`) invalidate nothing, and the CASCADE rules of the `pg_fraiseql_cache` extension
don't invalidate its entries (see [pg_fraiseql_cache](#pg_fraiseql_cache-extension)).

The speed-up depends on how expensive the query behind an entry is: a hit is one
primary-key lookup in the cache table plus the transfer of the stored value.
Measure it on your own queries.

## Quick Start

### Standalone

```python
from psycopg_pool import AsyncConnectionPool

import fraiseql
from fraiseql.caching import CacheConfig, CachedRepository, PostgresCache, ResultCache
from fraiseql.db import FraiseQLRepository


@fraiseql.type(sql_source="v_user")  # a view with an id column and a data JSONB column
class User:
    id: int
    name: str
    status: str


pool = AsyncConnectionPool("postgresql://user:pass@localhost/mydb", open=False)
await pool.open()

# Backend: the UNLOGGED table fraiseql_cache, created on first use
postgres_cache = PostgresCache(pool)

# Get-or-set logic, TTLs and hit/miss statistics
result_cache = ResultCache(backend=postgres_cache, config=CacheConfig(default_ttl=300))

# The repository wrapper; tenant_id goes into every cache key
base_repo = FraiseQLRepository(pool, context={"tenant_id": "tenant-123"})
cached_repo = CachedRepository(base_repo, result_cache)

users = await cached_repo.find("v_user", "users", mandatory_filters={"status": "active"})
users = await cached_repo.find("v_user", "users", mandatory_filters={"status": "active"})  # hit

print(bytes(users))  # b'{"data":{"users":[{"__typename":"User","id":1,...}]}}'
print(result_cache.get_stats())  # CacheStats(hits=1, misses=1, errors=0)
```

`find` and `find_one` take the wrapped repository's arguments (`view_name`,
`field_name`, `info`, then `where`, `order_by`, `limit`, `offset`,
`mandatory_filters`...) and return what it returns: a `RustResponseBytes`. On a hit
it holds the same bytes as the response that was cached.

### FastAPI Integration

`create_fraiseql_app` opens the database pool; build the cache in a `lifespan`
(which runs once the pool is open) and return a `CachedRepository` as `db` from a
`context_getter`:

```python
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request

import fraiseql
from fraiseql.caching import CachedRepository, PostgresCache, ResultCache
from fraiseql.db import FraiseQLRepository
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.dependencies import get_db_pool


@fraiseql.type(sql_source="v_user")
class User:
    id: int
    name: str


@fraiseql.query
async def users(info) -> list[User]:
    return await info.context["db"].find("v_user", "users", info, cache_ttl=60)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    backend = PostgresCache(get_db_pool())
    await backend.initialize()  # create the table, detect pg_fraiseql_cache
    app.state.cache = ResultCache(backend)
    yield


async def context_getter(request: Request, user=None) -> dict:
    # The tenant comes from the authenticated user, never from a client argument
    tenant_id = user.metadata.get("tenant_id") if user else None
    repo = FraiseQLRepository(get_db_pool(), context={"tenant_id": tenant_id})
    return {"db": CachedRepository(repo, request.app.state.cache), "user": user}


app = create_fraiseql_app(
    database_url="postgresql://user:pass@localhost/mydb",
    types=[User],
    queries=[users],
    lifespan=lifespan,
    context_getter=context_getter,
)
```

What `context_getter` returns is merged over fraiseql's default context, so keys you
don't return (`loader_registry`, `config`...) keep their defaults. Pass `info` to
`find`: the key then covers the GraphQL selection, so `{ users { id } }` and
`{ users { id name } }` get separate entries.

## PostgreSQL Cache Backend

### UNLOGGED Tables

`PostgresCache` creates this table (and index) on its first operation:

```sql
CREATE UNLOGGED TABLE IF NOT EXISTS fraiseql_cache (
    cache_key TEXT PRIMARY KEY,
    cache_value JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS fraiseql_cache_expires_idx ON fraiseql_cache (expires_at);
```

An `UNLOGGED` table skips the write-ahead log, so writes are cheaper than in a
regular table. The trade-offs:

- PostgreSQL empties the table after a crash (not after a clean restart), which a
  cache can afford.
- It isn't replicated to standbys: use the primary's pool for the cache.

### Extension Detection

`PostgresCache` detects the `pg_fraiseql_cache` extension on its first operation,
whichever it is (`ping()` included), or on `initialize()`:

```python
cache = PostgresCache(pool)
await cache.initialize()  # or: await cache.ping()

if cache.has_domain_versioning:
    print(f"pg_fraiseql_cache {cache.extension_version} detected")
else:
    print("pg_fraiseql_cache not installed")
```

It reads `extversion` from `pg_extension`. If the query fails (permissions, say), it
logs a warning and sets `has_domain_versioning` to `False`.

## Configuration

### PostgresCache Options

```python
from fraiseql.caching import PostgresCache

cache = PostgresCache(
    connection_pool=pool,          # a psycopg_pool.AsyncConnectionPool
    table_name="fraiseql_cache",   # may be schema-qualified: "app.fraiseql_cache"
    auto_initialize=True,          # the first operation creates the table if missing
)
```

With `auto_initialize=False` no operation creates the table: create it yourself (the
SQL above), or call `await cache.initialize()` once, which always creates it.
Operations on a missing table raise `PostgresCacheError`, which `ResultCache` logs and
counts as an error.

### ResultCache Options

```python
from fraiseql.caching import CacheConfig, ResultCache

result_cache = ResultCache(
    backend=postgres_cache,
    config=CacheConfig(
        enabled=True,          # False: get_or_set always runs the function
        default_ttl=300,       # seconds, when a call gives no TTL
        max_ttl=3600,          # every TTL is capped to this
        cache_errors=False,    # on a backend read error, don't try to store the result
        key_prefix="fraiseql",
    ),
)
```

Statistics are always kept (`result_cache.get_stats()`); there is no switch for them.
The configuration is a plain dataclass: `result_cache.config.default_ttl = 600`
changes the default for later calls.

There is no environment variable for any of this. Read your own and pass them in:

```python
import os

config = CacheConfig(
    enabled=os.environ.get("APP_CACHE_ENABLED", "true") == "true",
    default_ttl=int(os.environ.get("APP_CACHE_TTL", "300")),
)
```

### CachedRepository Options

```python
from fraiseql.caching import CachedRepository

cached_repo = CachedRepository(base_repository=base_repo, cache=result_cache)

# Custom TTL for this call (still capped to max_ttl)
users = await cached_repo.find(
    "v_user", "users", cache_ttl=600, mandatory_filters={"status": "active"}
)

# Bypass the cache: read the view, store nothing
users = await cached_repo.find(
    "v_user", "users", skip_cache=True, mandatory_filters={"status": "active"}
)
```

`find_one` takes the same two options. A `find_one` that finds nothing (`None`)
isn't cached.

### Cache Cleanup

Expired rows aren't returned, but they stay in the table until
`cleanup_expired()` deletes them (it returns how many). Nothing runs it for you;
start a task in your lifespan:

```python
import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from fraiseql.caching import PostgresCache, ResultCache
from fraiseql.fastapi.dependencies import get_db_pool


async def purge_expired(backend: PostgresCache, every: float = 300) -> None:
    while True:
        await backend.cleanup_expired()
        await asyncio.sleep(every)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    backend = PostgresCache(get_db_pool())
    app.state.cache = ResultCache(backend)
    cleanup = asyncio.create_task(purge_expired(backend))
    yield
    cleanup.cancel()
```

## Multi-Tenant Security

### Tenant Isolation in Cache Keys

`CachedRepository` reads `tenant_id` from the wrapped repository's context and puts
it second in every key:

```python
base_repo = FraiseQLRepository(pool, context={"tenant_id": "tenant-123"})
cached_repo = CachedRepository(base_repo, result_cache)

await cached_repo.find("v_user", "users", mandatory_filters={"status": "active"})
# key: fraiseql:tenant-123:v_user:q:fa9e468b99987da0
```

Without a `tenant_id` in the context, the key has no tenant part
(`fraiseql:v_user:q:<hash>`), and every caller with the same arguments shares the
entry. In a multi-tenant application that means one tenant can be served another
tenant's cached rows, even when row-level security filters the view on
`app.tenant_id`: a hit doesn't query the view. Always build the repository with the
tenant id, taken from the authenticated context, never from a client argument:

```python
# Correct: one entry per tenant
base_repo = FraiseQLRepository(pool, context={"tenant_id": tenant_id})

# Wrong in a multi-tenant application: one entry for every tenant
base_repo = FraiseQLRepository(pool, context={})
```

The same `tenant_id` also sets the `app.tenant_id` session variable when the
repository queries the database.

### Cache Key Structure

```text
<prefix>:<tenant_id>:<view>:q:<hash>       find
<prefix>:<tenant_id>:<view>:one:q:<hash>   find_one
<prefix>:<view>:q:<hash>                   find, no tenant_id in the context
```

`<prefix>` is `CacheConfig.key_prefix` (`fraiseql`). The hash covers `field_name`,
the keyword arguments (`where`, `order_by`, `limit`, `mandatory_filters`...) and, with
`info`, the GraphQL selection (fields, aliases, fragments, variables).

Keys you build yourself (with `ResultCache.get_or_set` or `cached_query`) get a tenant
only if you put one in them; see [Cache Key Strategy](#cache-key-strategy).

## Invalidation

### Writes Through the Repository

`execute_function(name, input)` and `execute_function_with_context(...)` on a
`CachedRepository` run the SQL function, then invalidate the entries of the entity
it writes, for every tenant. `fn_update_user` (or `update_user`,
`app.fn_update_user`) invalidates the views `user`, `users`, `v_user`, `v_users`,
`tv_user` and `tv_users`, in any schema; a multi-word entity (`fn_create_blog_post`)
also those of its last word (`post`).

```python
await cached_repo.execute_function("fn_update_user", {"id": 1, "name": "Alicia"})

# Cache miss: reads the view again and stores the new result
users = await cached_repo.find("v_user", "users", mandatory_filters={"status": "active"})
```

A function-based mutation that calls `execute_function` on `info.context["db"]`
goes through this path:

```python
@fraiseql.mutation
async def rename_user(info, id: int, name: str) -> bool:
    await info.context["db"].execute_function("fn_update_user", {"id": id, "name": name})
    return True
```

### Class Mutations and Other Writes

A class mutation (`@fraiseql.mutation class UpdateUser`) calls its SQL function
without going through the repository, so it invalidates nothing; nor does a write
made with raw SQL, by another service, or by a trigger. Rely on the TTL, or
invalidate from your code after the write:

```python
await cached_repo.invalidate_view("v_user")                     # every tenant
await cached_repo.invalidate_view("v_user", all_tenants=False)  # the context's tenant only
await cached_repo.invalidate_for_function("fn_update_user")     # what execute_function does
```

### By Key or Pattern

`ResultCache` deletes one key, or every key matching a pattern:

```python
await result_cache.invalidate("fraiseql:top_sellers")       # one key
await result_cache.invalidate_pattern("fraiseql:tenant-123:*")  # every key of a tenant
```

A pattern's `*` becomes SQL `LIKE`'s `%`, so a `_` in a pattern also matches any one
character. Both methods log errors instead of raising them.

## pg_fraiseql_cache Extension

`pg_fraiseql_cache` is a separate PostgreSQL extension (see
[PostgreSQL Extensions](../core/postgresql-extensions.md)) that keeps per-tenant
domain version counters, bumped by triggers, and CASCADE rules between domains.
FraiseQL doesn't install it:

```bash
psql -d mydb -c "CREATE EXTENSION pg_fraiseql_cache;"
```

When it is installed (`has_domain_versioning` is `True`), `PostgresCache` offers:

- `get_domain_versions(tenant_id, domains)`: the current versions, e.g.
  `{"user": 42}` (`{}` without the extension).
- `set(key, value, ttl, versions={...})`: stores `{"result": value, "versions": ...,
  "cached_at": ...}`. Without the extension, or without `versions`, the value is
  stored as is.
- `get(key)` returns the `result` part of such an entry;
  `get_with_metadata(key)` returns `(result, versions)` (`versions` is `None` for a
  plain entry).
- `setup_table_trigger(table, domain_name=None, tenant_column="tenant_id")`: calls the
  extension's `fraiseql_cache.setup_table_invalidation`.
- `register_cascade_rule(source, target)` and `setup_auto_cascade_rules(cache, schema)`
  (rules derived from the GraphQL schema by `SchemaAnalyzer`; see the
  [specification](../specs/caching.md#4-cascade-rules)).

Without the extension, `setup_table_trigger` and `register_cascade_rule` log a
warning and do nothing; `register_cascade_rule` returns `False`, and
`setup_auto_cascade_rules` returns `0`, the number of rules it actually registered.

`ResultCache`, `cached_query` and `CachedRepository` never pass `versions` and never
compare them: with or without the extension, their entries are invalidated only by
TTL and by the invalidation calls above. If you want version-checked entries, you
call `set(..., versions=...)`, `get_with_metadata` and `get_domain_versions` on the
`PostgresCache` yourself.

## Usage Patterns

### Pattern 1: Repository-Level Caching

Every `find` / `find_one` through the wrapper is cached; writes through
`execute_function` invalidate:

```python
cached_repo = CachedRepository(base_repo, result_cache)

users = await cached_repo.find("v_user", "users", mandatory_filters={"status": "active"})
user = await cached_repo.find_one("v_user", "user", where={"id": {"eq": user_id}})

await cached_repo.execute_function("fn_update_user", {"id": user_id, "name": "Alicia"})
```

### Pattern 2: Explicit Cache Control

`get_or_set(key, func, ttl=None)` returns the stored value, or awaits `func()`,
stores its result and returns it. The value must be JSON-serializable: a value
`json.dumps` can't encode (a `datetime`, a `UUID`, a dataclass) isn't stored, and the
failure is logged and counted in `stats.errors`.

```python
key = result_cache.key_builder.build_key("active_users", tenant_id=tenant_id, limit=10)
# 'fraiseql:tenant-123:active_users:limit:10'


async def load_active_users() -> list[dict]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT data FROM v_user WHERE tenant_id = %s AND status = 'active'"
            " ORDER BY id LIMIT 10",
            (tenant_id,),
        )
        return [row[0] for row in await cur.fetchall()]


active_users = await result_cache.get_or_set(key, load_active_users, ttl=300)
```

`ResultCache` has no separate `get` / `set`; for those, call the backend
(`result_cache.backend.get(key)`, `.set(key, value, ttl)`).

### Pattern 3: Decorator-Based Caching

`cached_query(cache, ttl=None, key_func=None)` wraps an async function in
`get_or_set`:

```python
from fraiseql.caching import cached_query


@cached_query(result_cache, ttl=600)
async def user_names(status: str) -> list[str]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT data->>'name' FROM v_user WHERE status = %s ORDER BY id", (status,)
        )
        return [row[0] for row in await cur.fetchall()]


await user_names(status="active")                   # computed and stored
await user_names(status="active")                   # from the cache
await user_names(status="active", skip_cache=True)  # computed, not stored
```

The default key is the function name followed by its positional arguments and its
sorted keyword arguments (`user_names:status:active`): no prefix and no tenant. Pass
`key_func` (called with the keyword arguments) to build your own:

```python
@cached_query(
    result_cache,
    ttl=600,
    key_func=lambda tenant_id, status: f"fraiseql:{tenant_id}:user_names:{status}",
)
async def tenant_user_names(tenant_id: str, status: str) -> list[str]: ...
```

Don't put `cached_query` on a GraphQL resolver: its default key would include the
`info` object's text, and `find` returns `RustResponseBytes`, which isn't JSON. Use
`CachedRepository` in resolvers.

### Pattern 4: Conditional Caching

Choose per call with `skip_cache` and `cache_ttl`:

```python
async def find_users(repo: CachedRepository, info, **kwargs):
    # Lookups by id are cheap: don't cache them
    if "id" in kwargs.get("where", {}):
        return await repo.find("v_user", "users", info, skip_cache=True, **kwargs)
    return await repo.find("v_user", "users", info, cache_ttl=300, **kwargs)
```

## Cache Key Strategy

### Key Components

`CacheKeyBuilder` builds the keys of `ResultCache.key_builder`. Use it for keys you
build yourself:

```python
from fraiseql.caching import CacheKeyBuilder

key_builder = CacheKeyBuilder(prefix="fraiseql")

key_builder.build_key(
    "v_user",
    tenant_id="tenant-123",
    filters={"status": "active", "role": "admin"},
    order_by=[("created_at", "desc")],
    limit=10,
    offset=0,
)
# 'fraiseql:tenant-123:v_user:role:admin:status:active:order:created_at:desc:limit:10:offset:0'
```

The parts are joined with `:`: the prefix, the tenant id (when given), the query
name, each filter sorted by field, `order:field:direction`, `limit:N`, `offset:N`,
then any extra keyword arguments. Pass `order_by` as `(field, direction)` tuples.

### Key Normalization

Filters are sorted by field, so their order doesn't matter:

```python
key1 = key_builder.build_key("v_user", tenant_id="t1", filters={"status": "active", "role": "admin"})
key2 = key_builder.build_key("v_user", tenant_id="t1", filters={"role": "admin", "status": "active"})

assert key1 == key2
```

### Filter Serialization

```python
filters={"user_id": UUID("00000000-0000-0000-0000-000000000000")}
# → user_id:00000000-0000-0000-0000-000000000000

filters={"created_after": datetime(2025, 1, 1)}
# → created_after:2025-01-01T00:00:00

filters={"age": {"gte": 18, "lt": 65}}          # operator dict, sorted by operator
# → age:gte:18:lt:65

filters={"status": {"in": ["pending", "active"]}}  # list of strings: sorted, joined
# → status:in:active,pending

filters={"ids": [UUID(int=1), UUID(int=2)]}      # other list: 8-character MD5 prefix
# → ids:5ce60e84

filters={"is_active": True}
# → is_active:true

filters={"deleted_at": None}
# → deleted_at:null
```

### Pattern-Based Invalidation

`build_mutation_pattern(name)` returns `<prefix>:<name>:*`:

```python
key_builder.build_mutation_pattern("v_user")
# 'fraiseql:v_user:*'
```

That pattern matches only keys without a tenant part. It doesn't match
`fraiseql:tenant-a:v_user:...`. For `CachedRepository` entries, call
`invalidate_view("v_user")`; for keys you built with a tenant, pass your own
pattern:

```python
await result_cache.invalidate_pattern("fraiseql:*:v_user:*")       # every tenant
await result_cache.invalidate_pattern(f"fraiseql:{tenant_id}:*")  # one tenant, every view
```

## Monitoring & Metrics

### Cache Statistics

`ResultCache.get_stats()` (not async) returns this process's counters;
`PostgresCache.get_stats()` (async) describes the table, shared by every instance:

```python
stats = result_cache.get_stats()  # CacheStats(hits=..., misses=..., errors=...)
print(f"Hit rate: {stats.hit_rate:.1f}%")  # 0-100
print(f"Hits: {stats.hits}, Misses: {stats.misses}, Errors: {stats.errors}")
result_cache.reset_stats()

table = await postgres_cache.get_stats()
print(f"Total entries: {table['total_entries']}")
print(f"Expired entries: {table['expired_entries']}")
print(f"Active entries: {table['active_entries']}")
print(f"Table size: {table['table_size_bytes'] / 1024 / 1024:.2f} MB")
```

A growing `errors` count usually means values that can't be stored (not JSON) or a
backend that can't be reached.

### PostgreSQL Monitoring

```sql
-- Cache table size
SELECT
    pg_size_pretty(pg_total_relation_size('fraiseql_cache')) AS total_size,
    pg_size_pretty(pg_relation_size('fraiseql_cache'))       AS table_size,
    pg_size_pretty(pg_indexes_size('fraiseql_cache'))        AS index_size;

-- Entries
SELECT
    COUNT(*)                                    AS total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW())  AS active_entries,
    COUNT(*) FILTER (WHERE expires_at <= NOW()) AS expired_entries
FROM fraiseql_cache;

-- Entries per tenant and view (CachedRepository keys)
SELECT
    split_part(cache_key, ':q:', 1) AS key_prefix,
    COUNT(*)                        AS entries
FROM fraiseql_cache
GROUP BY key_prefix
ORDER BY entries DESC
LIMIT 20;

-- Entries expiring per hour
SELECT
    date_trunc('hour', expires_at) AS hour,
    COUNT(*)                       AS entries_expiring
FROM fraiseql_cache
WHERE expires_at > NOW()
GROUP BY hour
ORDER BY hour;
```

### Prometheus Metrics

FraiseQL exports no metric for this cache. You can publish the counters with
`prometheus_client`:

```python
from prometheus_client import Gauge

cache_hits = Gauge("app_result_cache_hits", "ResultCache hits in this process")
cache_misses = Gauge("app_result_cache_misses", "ResultCache misses in this process")
cache_errors = Gauge("app_result_cache_errors", "ResultCache backend errors in this process")
cache_entries = Gauge("app_result_cache_entries", "Unexpired rows in the cache table")

cache_hits.set_function(lambda: result_cache.get_stats().hits)
cache_misses.set_function(lambda: result_cache.get_stats().misses)
cache_errors.set_function(lambda: result_cache.get_stats().errors)


async def update_cache_gauges() -> None:  # call it periodically, e.g. from purge_expired
    stats = await postgres_cache.get_stats()
    cache_entries.set(stats["active_entries"])
```

### Logging

```python
import logging

logging.getLogger("fraiseql.caching").setLevel(logging.INFO)
```

The loggers are `fraiseql.caching.postgres_cache` and `fraiseql.caching.result_cache`.
At `INFO` you see, for example:

- `pg_fraiseql_cache not installed, using TTL-only caching` or
  `✓ Detected pg_fraiseql_cache v1.0.0`
- `PostgreSQL cache table 'fraiseql_cache' initialized`
- `Cleaned 145 expired cache entries`
- `Invalidated 3 cache keys matching: fraiseql:*:v_user:*` (one line per pattern:
  an `execute_function` call writes several)

At `WARNING`: `Cache get error for key ...` and `Cache set error for key ...` (the
call still returns the function's result). At `ERROR`: `Failed to get cache key
'...': ...` and the other backend failures.

## Best Practices

### 1. Always Set tenant_id

```python
# Correct: tenant_id in the repository context
repo = FraiseQLRepository(pool, context={"tenant_id": tenant_id})

# Wrong in a multi-tenant application: entries shared by every tenant
repo = FraiseQLRepository(pool, context={})
```

### 2. Choose Appropriate TTLs

| Data | Changes | TTL |
|------|---------|-----|
| Reference data (countries, currencies) | Rarely | up to `max_ttl` |
| Catalogs, profiles | Hours | 600-1800 s |
| Aggregates, rankings | Minutes | 60-300 s |
| Real-time data | Seconds | don't cache, or 5-30 s |

```python
recent_orders = await cached_repo.find("v_order", "orders", cache_ttl=60)
categories = await cached_repo.find("v_category", "categories", cache_ttl=1800)
```

`max_ttl` (3600 by default) caps every TTL: raise it in `CacheConfig` for data that
may live longer than an hour.

### 3. Use skip_cache for Real-Time Data

```python
admin_stats = await cached_repo.find("v_admin_stats", "adminStats", skip_cache=True)
```

### 4. Invalidate on Writes

Write through `cached_repo.execute_function(...)`, or call `invalidate_view` after a
write the cache doesn't see (class mutations included).

### 5. Monitor Cache Health

```python
import logging

logger = logging.getLogger(__name__)


async def check_cache_health() -> None:
    table = await postgres_cache.get_stats()

    # Many expired rows: cleanup_expired isn't running often enough
    if table["expired_entries"] > 10_000:
        logger.warning("High expired entry count: %s", table["expired_entries"])

    # Large table: keys with unbounded cardinality, or large values
    if table["table_size_bytes"] > 1_000_000_000:
        logger.warning("Cache table large: %s bytes", table["table_size_bytes"])

    # Low hit rate (this process): TTLs too short, or keys that never repeat
    stats = result_cache.get_stats()
    if stats.total > 1000 and stats.hit_rate < 50:
        logger.warning("Low cache hit rate: %.1f%%", stats.hit_rate)
```

### 6. Vacuum the Cache Table

Autovacuum covers `UNLOGGED` tables. After a large `cleanup_expired()` you can run:

```sql
VACUUM ANALYZE fraiseql_cache;
```

### 7. Partition Large Caches

`PostgresCache` uses an existing table as is, so you can create a hash-partitioned one
yourself. The parent keeps the primary key (`set` relies on `ON CONFLICT
(cache_key)`), and each partition is created `UNLOGGED` (PostgreSQL doesn't make a
partition unlogged because its parent is, and PostgreSQL 17 rejects `UNLOGGED` on a
partitioned table):

```sql
CREATE TABLE fraiseql_cache (
    cache_key TEXT PRIMARY KEY,
    cache_value JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
) PARTITION BY HASH (cache_key);

CREATE UNLOGGED TABLE fraiseql_cache_0 PARTITION OF fraiseql_cache
    FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE UNLOGGED TABLE fraiseql_cache_1 PARTITION OF fraiseql_cache
    FOR VALUES WITH (MODULUS 4, REMAINDER 1);
CREATE UNLOGGED TABLE fraiseql_cache_2 PARTITION OF fraiseql_cache
    FOR VALUES WITH (MODULUS 4, REMAINDER 2);
CREATE UNLOGGED TABLE fraiseql_cache_3 PARTITION OF fraiseql_cache
    FOR VALUES WITH (MODULUS 4, REMAINDER 3);

CREATE INDEX fraiseql_cache_expires_idx ON fraiseql_cache (expires_at);
```

On a partitioned table, `PostgresCache.get_stats()` reports `table_size_bytes` as 0
(the parent has no storage of its own); sum the partitions' sizes instead.

## Troubleshooting

### Low Cache Hit Rate

**Symptom**: `result_cache.get_stats().hit_rate` is low.

**Causes**:

1. TTLs too short.
2. Keys that differ between calls that should share one: different arguments,
   selections or variables give different keys.
3. Invalidation after every write of a frequently written entity.

**Solutions**:

```python
# Longer default TTL (still capped to max_ttl)
result_cache.config.default_ttl = 600

# Key cardinality: many entries for few views means keys that rarely repeat
table = await postgres_cache.get_stats()
print(f"Total entries: {table['total_entries']}")
```

Inspect the keys themselves with the "entries per tenant and view" query above.

### Stale Data

**Symptom**: cached data doesn't reflect recent changes.

**Causes**:

1. The write didn't go through `CachedRepository.execute_function` (a class
   mutation, raw SQL, another service).
2. The function name doesn't name the view's entity (`fn_rename_member` writing
   `v_user`).
3. TTL too long.

**Solutions**:

```python
# Invalidate after the write
await cached_repo.invalidate_view("v_user")

# Or a shorter TTL for frequently changing data
users = await cached_repo.find("v_user", "users", info, cache_ttl=30)
```

The `pg_fraiseql_cache` extension doesn't help here: `CachedRepository` doesn't check
domain versions.

### Nothing Is Cached

**Symptom**: `stats.misses` and `stats.errors` grow together, with `Cache set
error` warnings.

**Cause**: values that aren't JSON-serializable, passed to `get_or_set` or
`cached_query`. Return dicts, lists, strings and numbers (convert `datetime` and
`UUID` to strings). `CachedRepository` stores `RustResponseBytes` for you.

### Cache Table Growing

**Symptom**: the cache table keeps growing.

**Causes**:

1. `cleanup_expired()` isn't running.
2. Keys with unbounded cardinality (one per user input).
3. Large cached results.

**Solutions**:

```sql
-- Table size
SELECT pg_size_pretty(pg_total_relation_size('fraiseql_cache'));

-- Manual cleanup
DELETE FROM fraiseql_cache WHERE expires_at <= NOW();
VACUUM fraiseql_cache;
```

Run `cleanup_expired()` more often (the `every` argument of `purge_expired` above),
and use `skip_cache=True` for queries whose results are large or never repeat.

### Connection Pool Exhaustion

**Symptom**: `PoolTimeout` errors, or requests waiting for a connection.

**Cause**: every cache operation borrows a connection from the pool, on top of the
connections the queries use.

**Solution**: give the cache its own, smaller pool:

```python
from psycopg_pool import AsyncConnectionPool

cache_pool = AsyncConnectionPool(db_url, min_size=1, max_size=5, open=False)
await cache_pool.open()

cache = PostgresCache(cache_pool)
```

### Cache Table Corruption

**Symptom**: unexpected errors from the cache table.

**Solution**: drop it (it only holds cache entries). `PostgresCache` recreates it on
its next first operation (a new process, or `await cache.initialize()`):

```sql
DROP TABLE IF EXISTS fraiseql_cache;

-- Or recreate it yourself:
CREATE UNLOGGED TABLE IF NOT EXISTS fraiseql_cache (
    cache_key TEXT PRIMARY KEY,
    cache_value JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS fraiseql_cache_expires_idx ON fraiseql_cache (expires_at);
```

A running `PostgresCache` creates its table only once: after a drop, its operations
fail (logged, counted as errors) until the table exists again.

### Extension Not Detected

**Symptom**: `has_domain_versioning` is `False` although the extension is installed.

**Causes**:

1. The extension is installed in another database.
2. Detection hasn't run yet: it runs on the first operation, or `initialize()`.
3. The detection query failed (a warning `Failed to detect pg_fraiseql_cache
   extension` is logged).

**Solutions**:

```sql
-- Is it installed in this database?
SELECT extname, extversion FROM pg_extension WHERE extname = 'pg_fraiseql_cache';
```

```python
async def check_cache_extension(pool) -> None:
    cache = PostgresCache(pool)
    await cache.ping()  # runs the first-use setup, detection included

    print(f"Extension detected: {cache.has_domain_versioning}")
    print(f"Extension version: {cache.extension_version}")
```

## Next Steps

- [Caching Specification](../specs/caching.md) - Reference for `fraiseql.caching`
- [Performance Optimization](index.md) - Full performance stack (Rust, APQ, TurboRouter)
- [Multi-Tenancy](../advanced/multi-tenancy.md) - Tenant-aware caching patterns
- [Monitoring](../production/monitoring.md) - Production monitoring setup
- [Security](../production/security.md) - Cache security best practices
