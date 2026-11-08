# Server-Side Cache Invalidation

> **Note**: This document describes server-side cache invalidation, not the [GraphQL Cascade](../features/graphql-cascade.md) client-side update feature.

FraiseQL's result cache (`fraiseql.caching`, see the
[Caching Specification](../specs/caching.md)) expires entries by TTL and deletes
them when you call `invalidate` / `invalidate_pattern`. It can also derive
**CASCADE rules** from your GraphQL schema ("when a `User` changes, cached `Post`s
are stale") and register them with the `pg_fraiseql_cache` PostgreSQL extension.
This page covers both, and what each one invalidates.

---

## What Invalidates What

| Mechanism | Invalidates |
|-----------|-------------|
| TTL (`CacheConfig.default_ttl`, `ttl=`) | Every entry, when it expires |
| `cache.invalidate(key)` / `cache.invalidate_pattern("prefix:*")` | The entries you name, when you call it |
| CASCADE rules (`setup_auto_cascade_rules`) | Nothing in `ResultCache`: they are stored in the `pg_fraiseql_cache` extension, whose domain versions only the RBAC permission cache (`fraiseql.enterprise.rbac`) checks |

So for cached query results: pick TTLs that match how stale the data may be, and
invalidate explicitly where your code writes.

---

## Invalidating After a Write

Key your entries so one pattern covers what a write makes stale, and invalidate
that pattern after the write:

```python
from contextlib import asynccontextmanager

import fraiseql
from fraiseql.caching import CacheConfig, PostgresCache, ResultCache
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.dependencies import get_db_pool

cache: ResultCache | None = None


@fraiseql.type(sql_source="v_user")
class User:
    id: int
    name: str


async def user_names(tenant_id: str) -> list[str]:
    async def load() -> list[str]:
        async with get_db_pool().connection() as conn:
            cur = await conn.execute("SELECT data->>'name' FROM v_user ORDER BY id")
            return [row[0] for row in await cur.fetchall()]

    return await cache.get_or_set(f"fraiseql:{tenant_id}:user:names", load, ttl=300)


@fraiseql.query
async def names(info) -> list[str]:
    return await user_names(str(info.context.get("tenant_id", "public")))


@fraiseql.mutation
async def rename_user(info, id: int, name: str) -> bool:
    db = info.context["db"]
    await db.execute_function("fn_rename_user", {"id": id, "name": name})
    tenant_id = str(info.context.get("tenant_id", "public"))
    await cache.invalidate_pattern(f"fraiseql:{tenant_id}:user:*")
    return True


@asynccontextmanager
async def lifespan(app):
    global cache
    cache = ResultCache(backend=PostgresCache(connection_pool=get_db_pool()), config=CacheConfig())
    yield


app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[names],
    mutations=[rename_user],
    lifespan=lifespan,  # runs once fraiseql has opened the pool
)
```

Writes that don't go through your code (another service, a migration, `psql`)
invalidate nothing: their entries stay until they expire.

---

## CASCADE Rules

### Relationship Detection

`SchemaAnalyzer` walks the schema's object types and makes one rule per field that
references another object type, from the referenced type to the referencing one:

```graphql
type User {
  id: ID!
  name: String!
}

type Post {
  id: ID!
  author: User!        # rule: user → post
  comments: [Comment!]!  # rule: comment → post (confidence 0.9, a list)
}

type Comment {
  id: ID!
  author: User!        # rule: user → comment
}
```

Type names become snake_case domains (`BlogPost` → `blog_post`). Self-references
(`parent: User` on `User`), `Query`, `Mutation`, `Subscription` and introspection
types are skipped. A field that only holds an id (`author_id: ID!`) isn't a
relationship.

```python
from fraiseql.caching import SchemaAnalyzer

analyzer = SchemaAnalyzer(app.state.graphql_schema)
for rule in analyzer.analyze_relationships():
    print(rule)                         # user → post
print(analyzer.get_domain_dependencies())  # {'post': {'user', 'comment'}, 'comment': {'user'}}
```

`SchemaAnalyzer(schema, type_to_domain_fn=..., exclude_types=...)` takes your own
type-to-domain mapping and types to leave out (the default excludes the root and
introspection types; a set you pass replaces it).

### Registering Rules at Startup

```python
from contextlib import asynccontextmanager

from fraiseql.caching import PostgresCache, setup_auto_cascade_rules
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.dependencies import get_db_pool


@asynccontextmanager
async def lifespan(app):
    backend = PostgresCache(connection_pool=get_db_pool())
    await backend.get_stats()  # first use: creates the cache table, detects the extension
    count = await setup_auto_cascade_rules(backend, app.state.graphql_schema, verbose=True)
    yield


app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User, Post, Comment],
    queries=[posts],
    lifespan=lifespan,
)
```

`verbose=True` logs the rules and the dependency graph on the
`fraiseql.caching.schema_analyzer` logger at `INFO`. Each rule goes to
`PostgresCache.register_cascade_rule(source_domain, target_domain, rule_type="invalidate")`,
which inserts it into the extension's `fraiseql_cache.cascade_rules` table. Call it
yourself for a rule the schema doesn't show:

```python
await backend.register_cascade_rule("user", "feed")
await backend.setup_table_trigger("tb_user", domain_name="user")  # the extension's trigger
await backend.clear_cascade_rules("user")
```

The backend detects the extension on its first use (a `get`, `set` or
`get_stats`), not when it's created: before that, and without the
`pg_fraiseql_cache` extension (`backend.has_domain_versioning` is `False`), these
methods log a warning and do nothing, and `setup_auto_cascade_rules`
still returns the number of rules it tried. The extension is a separate project:
see [PostgreSQL Extensions](../core/postgresql-extensions.md).

---

## Troubleshooting

**Stale data after a mutation**: the write didn't invalidate a pattern matching the
entries' keys. Print the keys (`SELECT cache_key FROM fraiseql_cache`) and the
pattern; `*` becomes SQL `LIKE`'s `%`, and `_` matches any one character.

**"CASCADE rules require pg_fraiseql_cache extension" warnings**: the extension
isn't installed in this database; the rules weren't registered.

**Too much invalidated**: the pattern is too broad (`fraiseql:*` clears every
entry); put the tenant and the domain in the key so the pattern can name them.

---

## See Also

- [Caching Specification](../specs/caching.md) - `ResultCache`, `PostgresCache`, keys and TTLs
- [Caching Guide](./caching.md) - General caching documentation
- [GraphQL Cascade](../features/graphql-cascade.md) - Client-side cache updates from mutations

---

**Last Updated**: 2026-10-25
**FraiseQL Version**: 1.31.0
