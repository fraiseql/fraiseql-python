---
title: Rust Transform Pipeline (v1.9+)
description: Understand the v1.9 Rust JSON-transform architecture and adapt your resolvers to RustResponseBytes
tags:
  - Rust
  - performance
  - backend
  - architecture
---

# Rust Transform Pipeline (v1.9+)

## Overview

FraiseQL v1 has a clear two-layer execution model for reads:

1. **Database query layer — psycopg.** Every SQL query against PostgreSQL runs through
   [psycopg 3](https://www.psycopg.org/) and its async connection pool
   (`psycopg_pool.AsyncConnectionPool`). psycopg is a **required, first-class dependency** —
   it is the only PostgreSQL driver FraiseQL uses, and it is not optional, deprecated, or
   removed.
2. **JSON transform / response layer — Rust (`fraiseql._fraiseql_rs`).** After psycopg returns
   the raw JSONB rows, FraiseQL hands them to a bundled Rust extension that performs field
   projection, `camelCase` conversion, `__typename` injection, and direct UTF-8 byte encoding.
   The result is a `RustResponseBytes` object that is written straight to the HTTP response,
   bypassing `graphql-core` serialization.

This guide explains the v1.9 architecture and shows how to write resolvers that use the
Rust-transform path (`db.find` / `db.find_one`).

## What Changed in v1.9

The change in v1.9 is **not** about the database driver — psycopg is still the driver and
still required. What changed is the **JSON-transform / response path**: it became
**Rust-exclusive, with no Python-serialization fallback**.

Before v1.9, the JSON transformation could fall back to a Python serialization path. As of
v1.9+, the Rust extension is bundled and mandatory: it is built with maturin as
`fraiseql._fraiseql_rs` and loaded by `src/fraiseql/core/rust_pipeline.py`. If the extension
is missing, FraiseQL raises an error asking you to reinstall — there is no Python fallback.

### Execution flow (v1.9+)

```
GraphQL request
   → @query resolver calls db.find(...) / db.find_one(...)
      → psycopg AsyncConnectionPool executes SQL against PostgreSQL
         → PostgreSQL returns JSONB rows
            → Rust transform (field projection, camelCase, __typename, UTF-8 bytes)
               → RustResponseBytes
                  → written directly to the HTTP response (no graphql-core serialization)
```

### Key points

| Aspect | Detail |
|--------|--------|
| **Database driver** | psycopg 3 (`psycopg[pool]`) — required, unchanged |
| **Connection pool** | `psycopg_pool.AsyncConnectionPool` |
| **Repository** | `FraiseQLRepository(pool, context)` |
| **JSON transform** | Rust extension `fraiseql._fraiseql_rs` — bundled, mandatory, no fallback |
| **Read return type** | `RustResponseBytes` (from `db.find` / `db.find_one`) |
| **Response handling** | `RustResponseBytes` is written directly to HTTP (zero-copy bytes) |

## Why the Rust Transform Path

Moving JSON transformation out of Python and into the bundled Rust extension keeps the hot
read path off the Python interpreter once psycopg has fetched the rows.

### Performance characteristics

- **JSON serialization happens in Rust**, not in Python — no intermediate Python dict/list
  objects are built for the response body.
- **Direct HTTP response** — `RustResponseBytes` is encoded once and written to the socket,
  bypassing `graphql-core` serialization.
- **Lower garbage-collection pressure** — fewer transient Python objects per request under
  load.

The exact speedup depends on payload size and query shape; benefits are most visible on large
result sets and deeply-nested GraphQL selections. The figures below are **illustrative
examples** from a single internal benchmark, not guarantees — measure your own workload.

```
Example benchmark — complex GraphQL query returning ~5,000 records
┌─────────────────┬─────────────┬─────────────┬──────────────────┐
│ Metric          │ Python JSON │ Rust v1.9+  │ Example delta    │
├─────────────────┼─────────────┼─────────────┼──────────────────┤
│ Response Time   │ 450ms       │ 180ms       │ ~2.5x faster     │
│ Memory Usage    │ 85MB        │ 45MB        │ ~47% less        │
│ Throughput      │ 120 req/sec │ 280 req/sec │ ~2.3x higher     │
└─────────────────┴─────────────┴─────────────┴──────────────────┘
```

### Architecture benefits

- **Single read path** — `db.find` / `db.find_one` always use the Rust transform, so there is
  no mode detection or branching in your resolvers.
- **Consistent return type** — reads return `RustResponseBytes` everywhere.
- **Clear failure mode** — if the Rust extension is missing, FraiseQL fails loudly at import
  time rather than silently degrading.

## Setting Up the Pool and Repository

In almost all applications you do **not** build the pool yourself.
`create_fraiseql_app(...)` creates the psycopg `AsyncConnectionPool` for you and wires a
`FraiseQLRepository` into each request's GraphQL context as `info.context["db"]`.

### The normal path: `create_fraiseql_app`

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import ID


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str


@fraiseql.query
async def users(info, limit: int = 50, offset: int = 0) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user", field_name="users", info=info, limit=limit, offset=offset)


app = create_fraiseql_app(
    database_url="postgresql://user:pass@localhost:5432/mydb",
    types=[User],
    queries=[users],
    production=False,  # False enables the GraphQL playground
    connection_pool_size=20,
)
```

`create_fraiseql_app` accepts pool-tuning kwargs: `connection_pool_size`,
`connection_pool_max_overflow`, `connection_pool_timeout`, and `connection_pool_recycle`.

### The manual path: building the pool yourself

If you are embedding FraiseQL outside the standard app factory (custom context, tests, or
scripts), build the psycopg pool and the repository directly. The repository takes the
psycopg `AsyncConnectionPool` and an optional context dict.

```python
from fraiseql.fastapi import create_db_pool
from fraiseql.db import FraiseQLRepository

# create_db_pool returns a psycopg_pool.AsyncConnectionPool, configured for FraiseQL
pool = await create_db_pool("postgresql://user:pass@localhost:5432/mydb")

db = FraiseQLRepository(
    pool,
    context={"tenant_id": "tenant-123"},  # optional: flows into RLS session GUCs
)
```

`FraiseQLRepository.__init__(self, pool: AsyncConnectionPool, context: dict | None = None)`
takes the psycopg pool directly — there is no separate "Rust pool" wrapper.

## Writing Read Resolvers

Read resolvers call `db.find` (lists) or `db.find_one` (single record). Both return
`RustResponseBytes`; you return that value straight from the resolver and FraiseQL sends it to
the HTTP response.

### List query

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.type(sql_source="v_product", jsonb_column="data")
class Product:
    id: ID
    name: str
    price: float


@fraiseql.query
async def products(info, limit: int = 20, offset: int = 0) -> list[Product]:
    db = info.context["db"]
    return await db.find(
        "v_product",
        field_name="products",
        info=info,  # drives field selection / projection
        limit=limit,
        offset=offset,
    )
```

### Single-record query

```python
@fraiseql.query
async def user(info, id: ID) -> User | None:
    db = info.context["db"]
    # find_one returns RustResponseBytes for a hit, or None when no row matches
    return await db.find_one("v_user", field_name="user", info=info, id=id)
```

### Filtered query

`db.find` accepts a `where` dict (and filter kwargs) plus `order_by`. The Rust transform still
handles the response.

```python
@fraiseql.query
async def search_orders(
    info,
    customer_id: ID | None = None,
    status: str | None = None,
    date_from: str | None = None,
) -> list["Order"]:
    db = info.context["db"]

    where: dict[str, object] = {}
    if customer_id:
        where["customer_id"] = customer_id
    if status:
        where["status"] = status
    if date_from:
        where["created_at"] = {"gte": date_from}

    return await db.find(
        "v_order",
        field_name="orders",
        info=info,
        where=where,
        order_by=[{"field": "created_at", "direction": "DESC"}],
    )
```

## Handling `RustResponseBytes`

`db.find` and `db.find_one` return `RustResponseBytes`, defined in
`fraiseql.core.rust_pipeline`. It wraps a finished UTF-8 byte buffer of the GraphQL response
body. The point of the type is that it is **already serialized** — return it directly and let
FraiseQL stream it to the client.

Do **not** decode-and-re-encode it in your resolver; that throws away the whole benefit:

```python
import json

# Correct: return RustResponseBytes unchanged
@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user", field_name="users", info=info)


# Incorrect: round-tripping through Python JSON defeats the Rust transform
@fraiseql.query
async def users_bad(info) -> list[User]:
    db = info.context["db"]
    result = await db.find("v_user", field_name="users", info=info)
    return json.loads(bytes(result).decode())  # don't do this
```

Always pass `info` to `find` / `find_one` so the Rust transform knows which fields the client
requested. If `info` is omitted, FraiseQL tries to recover it from
`info.context["graphql_info"]`, but passing it explicitly is clearest.

## Mutations

Mutations are unchanged by the Rust-transform work. They call PostgreSQL functions through the
same psycopg-backed repository:

```python
@fraiseql.input
class CreateUserInput:
    name: str
    email: str


@fraiseql.success
class CreateUserSuccess:
    user: User


@fraiseql.error
class CreateUserError:
    message: str
    code: str = "VALIDATION_ERROR"


@fraiseql.mutation
async def create_user(info, input: CreateUserInput) -> CreateUserSuccess | CreateUserError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_user",
        {"name": input.name, "email": input.email},
    )
    if not result.get("success"):
        return CreateUserError(message=result.get("message", "failed"))
    return CreateUserSuccess(user=User(**result["user"]))
```

## Testing

### Resolver-level tests

Reads return `RustResponseBytes`, so unit tests assert on the type or decode the bytes for
inspection. A real psycopg pool (or a test fixture that builds one) is required because the
query still runs through psycopg.

```python
import pytest
from fraiseql.fastapi import create_db_pool
from fraiseql.db import FraiseQLRepository
from fraiseql.core.rust_pipeline import RustResponseBytes


@pytest.fixture
async def db(postgres_url: str) -> FraiseQLRepository:
    pool = await create_db_pool(postgres_url)
    return FraiseQLRepository(pool, context={"tenant_id": "test"})


@pytest.mark.asyncio
async def test_user_query(db: FraiseQLRepository) -> None:
    result = await db.find("v_user", field_name="users", info=None, status="active")
    assert isinstance(result, RustResponseBytes)
```

### End-to-end GraphQL tests

End-to-end tests hit the FastAPI `/graphql` endpoint and assert on the JSON body, exactly as
before — the Rust transform is transparent to the HTTP contract.

```python
def test_user_query(client) -> None:
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

    assert response.status_code == 200
    data = response.json()["data"]
    assert "users" in data
    assert len(data["users"]) <= 10
```

## Troubleshooting

### "fraiseql Rust extension is not available"

```
ImportError: fraiseql Rust extension is not available.
Please reinstall fraiseql: pip install --force-reinstall fraiseql
```

The Rust transform is bundled with FraiseQL as `fraiseql._fraiseql_rs`. If the wheel was built
without it (or a source install failed to compile), reinstall a prebuilt wheel:

```bash
pip install --force-reinstall fraiseql
```

If you build from source, ensure a Rust toolchain and maturin are available, then rebuild.

### "Connection pool exhausted"

This is a psycopg pool limit, not a Rust issue. Raise the pool size or fix connection leaks:

```python
app = create_fraiseql_app(
    database_url=DATABASE_URL,
    types=[...],
    queries=[...],
    connection_pool_size=50,
    connection_pool_max_overflow=10,
)
```

Also confirm connections are released (use context managers for explicit transactions) and
prefer `find_one` for single-record lookups to avoid over-fetching.

### "Expected Iterable but got RustResponseBytes"

This means a resolver tried to treat `RustResponseBytes` as a plain Python list. Return it
unchanged from the resolver and pass `info` so the transform produces the correct shape:

```python
@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user", field_name="users", info=info)  # return as-is
```

### Schema and migration tools

The Rust transform works with any standard PostgreSQL schema — your `v_` / `tv_` read views
and JSONB structures are unchanged. Migration tools (Alembic and friends) operate on the
database directly and need no changes:

```sql
-- Confirm your read views exist
SELECT table_name FROM information_schema.views
WHERE table_name LIKE 'v_%';
```

## FAQ

**Q: Is psycopg still required?**
A: Yes. psycopg 3 (`psycopg[pool]`) is the PostgreSQL driver and a required dependency. The
Rust extension transforms the JSON response after psycopg has fetched the rows; it does not
replace psycopg.

**Q: Is the Rust extension optional?**
A: No. It is bundled as `fraiseql._fraiseql_rs` and mandatory for the read path. There is no
Python-serialization fallback; a missing extension raises at import time.

**Q: Do I need to change my database schema?**
A: No. The Rust transform works with existing PostgreSQL views and JSONB structures.

**Q: Do I have to build the connection pool myself?**
A: No. `create_fraiseql_app` builds the psycopg pool and wires `FraiseQLRepository` into
`info.context["db"]`. Build the pool manually only for custom embedding or tests.

**Q: When will I see the biggest performance benefit?**
A: On large result sets and deeply-nested GraphQL selections, where moving JSON serialization
out of Python matters most. Measure your own workload.

## Additional Resources

- **[Database API Documentation](database-api.md)** — repository and read/write API reference
- **[Rust Pipeline Integration](rust-pipeline-integration.md)** — how the transform integrates
- **[Performance Optimization Guide](../performance/rust-pipeline-optimization.md)** — tuning
- **[Troubleshooting Guide](../guides/troubleshooting.md)** — common issues and solutions
