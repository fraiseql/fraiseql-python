---
title: FraiseQL Python API Reference
description: API reference for the FraiseQL Python framework — the decorators, application factory, repository, scalars, and configuration you use to build a PostgreSQL GraphQL API at runtime.
keywords: ["fraiseql", "python", "graphql", "postgresql", "decorators", "api", "reference"]
tags: ["documentation", "reference"]
---

# FraiseQL Python API Reference

**Status**: Production-Ready · **Python**: 3.10+ · **Database**: PostgreSQL

In FraiseQL v1 the Python package **is** the SDK. You define your GraphQL API with
decorators on plain Python classes and functions; at application startup FraiseQL builds
the GraphQL schema **in memory** and serves it over FastAPI. There is no compile step, no
schema-export artifact, and no separate server binary — you run the FastAPI app with an
ASGI server such as `uvicorn`.

The runtime follows a CQRS split against PostgreSQL:

- **Reads** — `@fraiseql.query` resolvers call `db.find` / `db.find_one` against `v_` / `tv_`
  read views, whose `data` JSONB column is shaped to the requested GraphQL fields.
- **Writes** — `@fraiseql.mutation` resolvers call `fn_` PostgreSQL functions via
  `db.execute_function`; all write logic lives in the database.

> This page is a focused tour of the public Python surface. For exhaustive per-symbol
> tables, see the canonical references linked throughout (e.g.
> [Decorators](../../reference/decorators.md), [Scalars](../../reference/scalars.md),
> [Repositories](../../reference/repositories.md), [Config](../../reference/config.md)).

---

## Installation

```bash
# uv (recommended)
uv add fraiseql

# or pip
pip install fraiseql
```

FastAPI integration is included. The optional Rust extension (`fraiseql_rs`) accelerates
JSON transformation on the read path and loads automatically when present — it is not a
separate component you install or run.

---

## Import styles

The preferred style is **namespaced** — it avoids shadowing Python builtins like `type`
and `input`:

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import ID, EmailAddress
```

Direct-import aliases exist for every decorator. `fraiseql.type` and `fraiseql.input` are
only available via attribute access (they are intentionally *not* importable by name, to
prevent `from fraiseql import type`); their importable aliases are `fraise_type` and
`fraise_input`:

| Namespaced | Importable alias |
|------------|------------------|
| `@fraiseql.type` | `fraise_type` |
| `@fraiseql.input` | `fraise_input` |
| `@fraiseql.enum` | `fraise_enum` |
| `@fraiseql.interface` | `fraise_interface` |
| `@fraiseql.field` | `fraise_field` |
| `@fraiseql.query` | `query` |
| `@fraiseql.mutation` | `mutation` |
| `@fraiseql.subscription` | `subscription` |
| `@fraiseql.connection` | `connection` |
| `@fraiseql.success` / `@fraiseql.error` | `success` / `error` |

All of the above are exported from the top-level `fraiseql` package, alongside
`result`, `dataloader_field`, and `build_fraiseql_schema`.

---

## Decorators

### `@fraiseql.type`

Defines a GraphQL object type from a Python class. When bound to a `sql_source` view, the
type becomes queryable and filterable automatically.

```python
@fraiseql.type(
    sql_source: str | None = None,
    jsonb_column: str | None = "data",
    implements: list[type] | None = None,
    resolve_nested: bool = False,
    authorize_fields: list[str] | None = None,
)
```

| Parameter | Description |
|-----------|-------------|
| `sql_source` | Read view (`v_` / `tv_`) this type is bound to. |
| `jsonb_column` | JSONB column holding the type's data (default `"data"`). |
| `implements` | GraphQL interfaces this type implements. |
| `resolve_nested` | If `True`, resolve this type via a separate query to its `sql_source` when it appears as a nested field. Default `False` (assumes embedded JSONB). |
| `authorize_fields` | Field names gated by the configured operation `Authorizer` (no-op unless an authorizer is set). |

```python
import fraiseql
from fraiseql.types import ID, EmailAddress

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: EmailAddress
    created_at: str
```

### `@fraiseql.input`

Defines a GraphQL input object — the argument shape for queries and mutations.

```python
@fraiseql.input
class CreateUserInput:
    name: str
    email: EmailAddress
```

### `@fraiseql.success` / `@fraiseql.error`

Define the success and error variants of a mutation result. `@fraiseql.success`
auto-injects `status: str`, `message: str | None`, and `updated_fields: list[str] | None`
when they are not already declared, so you only list your entity field(s).

```python
@fraiseql.success
class CreateUserSuccess:
    user: User                 # status / message / updated_fields injected automatically

@fraiseql.error
class CreateUserError:
    message: str
    code: str = "VALIDATION_ERROR"
```

`@fraiseql.result(success_cls, error_cls)` builds a combined result type if you prefer that
over a union return annotation.

### `@fraiseql.query`

Marks an async function as a root query resolver. Resolvers receive `info` and read from the
CQRS repository at `info.context["db"]`.

```python
@fraiseql.query                     # bare form
@fraiseql.query(authorizer=...)     # with an operation Authorizer
```

```python
@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user")

@fraiseql.query
async def user(info, id: ID) -> User | None:
    db = info.context["db"]
    return await db.find_one("v_user", id=id)
```

### `@fraiseql.mutation`

Marks an async function (or class) as a mutation. Resolvers call a `fn_` PostgreSQL function
via `db.execute_function` and return a success-or-error union.

```python
@fraiseql.mutation(
    function: str | None = None,
    schema: str | None = None,
    context_params: dict[str, str] | None = None,
    error_config: MutationErrorConfig | None = None,
    enable_cascade: bool = False,
    authorizer: Any | None = None,
)
```

```python
@fraiseql.mutation
async def create_user(
    info, input: CreateUserInput
) -> CreateUserSuccess | CreateUserError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_user", {"name": input.name, "email": input.email}
    )
    if not result.get("success"):
        return CreateUserError(message=result.get("message", "failed"))
    return CreateUserSuccess(user=User(**result["user"]))
```

### `@fraiseql.subscription`

Marks an **async generator** as a subscription resolver, streamed to clients over
GraphQL-over-WebSocket. The event source is your generator — it can be backed by PostgreSQL
`LISTEN/NOTIFY`, polling, or any async stream.

```python
from collections.abc import AsyncGenerator
from fraiseql.types import UUID

@fraiseql.subscription                  # or @fraiseql.subscription(authorizer=...)
async def task_updates(info, project_id: UUID) -> AsyncGenerator[Task, None]:
    async for task in watch_project_tasks(project_id):
        yield task
```

### `@fraiseql.field`

Defines a custom / computed field resolver on a `@fraiseql.type` (sync or async).

```python
@fraiseql.field(
    resolver: Callable[..., Any] | None = None,
    description: str | None = None,
    track_n1: bool = True,
)
```

```python
@fraiseql.type(sql_source="v_user")
class User:
    first_name: str
    last_name: str

    @fraiseql.field
    def full_name(self, info) -> str:
        return f"{self.first_name} {self.last_name}"
```

### `@fraiseql.dataloader_field`

Batches a field through a `DataLoader` to prevent N+1 queries.

```python
@fraiseql.dataloader_field(
    loader_class: type[DataLoader],
    *,
    key_field: str,
    description: str | None = None,
)
```

```python
@fraiseql.type(sql_source="v_post")
class Post:
    author_id: UUID

    @fraiseql.dataloader_field(UserDataLoader, key_field="author_id")
    async def author(self, info) -> User | None:
        ...  # resolution auto-generated from the loader
```

### `@fraiseql.connection`

Wraps a query into a Relay-style cursor-paginated `Connection[T]` resolver.

```python
@fraiseql.connection(
    node_type: type,
    view_name: str | None = None,
    default_page_size: int = 20,
    max_page_size: int = 100,
    include_total_count: bool = True,
    cursor_field: str = "id",
    jsonb_column: str | None = None,
)
```

See [Decorators reference](../../reference/decorators.md) for the full parameter tables and
additional examples.

---

## Application & schema

### `create_fraiseql_app`

The FastAPI application factory. All parameters are keyword-only.

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url: str | None = None,
    types: Sequence[type] = (),
    queries: Sequence[type] = (),
    mutations: Sequence[Callable] = (),
    config: FraiseQLConfig | None = None,
    auth: Auth0Config | AuthProvider | None = None,
    context_getter: Callable[[Request], Awaitable[dict]] | None = None,
    authorizer: Authorizer | None = None,
    authorization_cache: AuthorizationCacheConfig | None = None,
    production: bool = False,
    auto_discover: bool = False,
    lifespan: Callable | None = None,
    app: FastAPI | None = None,
    # connection pool
    connection_pool_size: int | None = None,
    connection_pool_max_overflow: int | None = None,
    connection_pool_timeout: float | None = None,
    connection_pool_recycle: int | None = None,
)
```

| Parameter | Description |
|-----------|-------------|
| `database_url` | PostgreSQL connection URL. |
| `types` / `queries` / `mutations` | The decorated types and resolvers to register. |
| `config` | A full [`FraiseQLConfig`](#fraiseqlconfig); overrides individual kwargs. |
| `auth` | An `Auth0Config` or an `AuthProvider` instance. |
| `context_getter` | Async function building extra `info.context` from the request. |
| `authorizer` / `authorization_cache` | Global operation authorization and its optional decision cache. |
| `production` | `False` enables the GraphQL playground and introspection; `True` applies production hardening. |
| `app` | An existing FastAPI app to extend (mount FraiseQL inside a larger app). |

Returns a configured `FastAPI` instance. To add HTTP middleware, use standard FastAPI
(`app.add_middleware(...)`) on the returned app, or pass an existing `app=`.

### `build_fraiseql_schema`

Builds a `graphql-core` `GraphQLSchema` directly, without the FastAPI wrapper — useful for
testing or custom ASGI integration.

```python
from fraiseql import build_fraiseql_schema

schema = build_fraiseql_schema(
    query_types: list[type | Callable] | None = None,
    mutation_resolvers: list[type | Callable] | None = None,
    subscription_resolvers: list[Callable] | None = None,
    camel_case_fields: bool = True,
    authorizer: Authorizer | None = None,
    decision_cache: DecisionCache | None = None,
)
```

Both `create_fraiseql_app` and `build_fraiseql_schema` run at startup — the schema lives in
memory; there is no generated artifact.

---

## The repository (`info.context["db"]`)

Every resolver gets a `FraiseQLRepository` (from `fraiseql.db`) at `info.context["db"]`. It
is the CQRS data access object — reads via views, writes via functions.

| Method | Signature | Use |
|--------|-----------|-----|
| `find` | `await db.find(view_name, **kwargs)` | List rows from a `v_` / `tv_` view (filter with `where=`, `limit=`, `offset=`, `order_by=`). |
| `find_one` | `await db.find_one(view_name, id=..., **kwargs)` | Single row, or `None` if not found. |
| `execute_function` | `await db.execute_function(function_name, input_data)` | Call a `fn_` PostgreSQL function (passes `input_data` as JSONB); returns the function's result dict. |
| `count` | `await db.count(view_name, **kwargs)` | Integer count with the same `where=` semantics as `find`. |
| `aggregate` | `await db.aggregate(view_name, aggregations, **kwargs)` | Run multiple aggregate expressions in one query. |

```python
# Read with filtering
rows = await db.find("v_order", where={"status": {"eq": "active"}}, limit=20)

# Single record
one = await db.find_one("v_user", id=user_id)

# Count
total = await db.count("v_user", where={"status": {"eq": "active"}})

# Aggregate
stats = await db.aggregate(
    "v_order",
    aggregations={"revenue": "SUM(amount)", "orders": "COUNT(*)"},
    where={"status": {"eq": "completed"}},
)

# Write (mutation)
res = await db.execute_function("fn_create_user", {"name": "Ada", "email": "ada@x.io"})
```

Filtering uses FraiseQL's PostgreSQL WHERE operators (`eq`, `gt`, `contains`, `ilike`,
ltree, network, and pgvector operators). See
[WHERE operators](../../reference/where-operators.md),
[ltree operators](../../reference/ltree-operators.md), and
[vector operators](../../reference/vector-operators.md). For the full repository surface
(pagination, transactions, the legacy `CQRSRepository`), see
[Repositories](../../reference/repositories.md).

---

## Scalars

Domain scalars are importable from `fraiseql.types`:

```python
from fraiseql.types import ID, UUID, Date, DateTime, JSON, EmailAddress, URL, LTree
```

Commonly used scalars include `ID`, `UUID`, `Date`, `DateTime`, `Time`, `JSON`,
`EmailAddress`, `URL`, `LTree`, `IpAddress`, `Money`, `Percentage`, `Duration`,
`DateRange`, `PhoneNumber`, `PostalCode`, `Color`, `Slug`, `Markdown`, `HTML`,
`Coordinate`, `Latitude`, and `Longitude`. Many more domain scalars (financial,
geographic, transport, identifiers) are exported. The casing shown is the real class name;
the module is lowercase `fraiseql.types`.

See the complete list in [Scalars reference](../../reference/scalars.md).

---

## Configuration

`FraiseQLConfig` (a pydantic settings model, from `fraiseql.fastapi`) centralizes
configuration. Every field can be set from an environment variable with the `FRAISEQL_`
prefix (e.g. `FRAISEQL_DATABASE_URL`, `FRAISEQL_AUTH_PROVIDER`).

```python
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    environment="production",
    auth_provider="auth0",
    auth0_domain="myapp.auth0.com",
    auth0_api_identifier="https://api.myapp.com",
)
app = create_fraiseql_app(config=config, types=[User], queries=[users])
```

Representative fields:

| Field | Default | Purpose |
|-------|---------|---------|
| `database_url` | — | PostgreSQL connection URL. |
| `environment` | `"development"` | `development` / `production` / `testing`. |
| `auth_provider` | `"none"` | `"auth0"`, `"custom"`, or `"none"`. |
| `auth0_domain` / `auth0_api_identifier` | `None` | Auth0 tenant + API audience. |
| `auth0_algorithms` | `["RS256"]` | Accepted JWT algorithms. |
| `dev_auth_username` / `dev_auth_password` | `None` | Development login credentials. |
| `enable_playground` | `True` | Serve the GraphQL playground. |
| `query_timeout` | `30` | Per-query statement timeout (seconds). |
| `database_pool_size` | `20` | Connection pool size. |
| `cors_enabled` / `cors_origins` | `False` / `[]` | CORS configuration. |

See [Config reference](../../reference/config.md) for every field and its environment
variable.

---

## End-to-end example

A complete, minimal application — type, query, mutation, app, server:

```python
# app.py
import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import ID, EmailAddress


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: EmailAddress


@fraiseql.input
class CreateUserInput:
    name: str
    email: EmailAddress


@fraiseql.success
class CreateUserSuccess:
    user: User


@fraiseql.error
class CreateUserError:
    message: str
    code: str = "VALIDATION_ERROR"


@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user")


@fraiseql.query
async def user(info, id: ID) -> User | None:
    db = info.context["db"]
    return await db.find_one("v_user", id=id)


@fraiseql.mutation
async def create_user(
    info, input: CreateUserInput
) -> CreateUserSuccess | CreateUserError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_user", {"name": input.name, "email": input.email}
    )
    if not result.get("success"):
        return CreateUserError(message=result.get("message", "failed"))
    return CreateUserSuccess(user=User(**result["user"]))


app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    production=False,  # enables the GraphQL playground
)
```

The matching PostgreSQL schema follows the naming conventions: a `v_user` read view exposing
an `id` (UUID) and a `data` JSONB column, and an `fn_create_user` function that performs the
write and returns a result.

```sql
CREATE VIEW v_user AS
SELECT
    u.id,
    jsonb_build_object(
        'id', u.id,
        'name', u.name,
        'email', u.email
    ) AS data
FROM tb_user u;
```

Run it with any ASGI server:

```bash
uvicorn app:app --reload
```

The GraphQL endpoint is served at `/graphql`, with the playground available in
non-production mode.

---

## See also

- [Decorators reference](../../reference/decorators.md) — full decorator parameter tables.
- [Repositories reference](../../reference/repositories.md) — `FraiseQLRepository` and `CQRSRepository`.
- [Mutations API](../../reference/mutations-api.md) — mutation patterns and result types.
- [Scalars reference](../../reference/scalars.md) — all built-in scalars.
- [WHERE operators](../../reference/where-operators.md) — filtering operators for `find` / `count`.
- [Config reference](../../reference/config.md) — `FraiseQLConfig` fields and `FRAISEQL_` env vars.
- [Naming patterns](../../reference/naming-patterns.md) — `tb_` / `v_` / `tv_` / `fn_` conventions.
- [Authentication](../authentication/README.md) — auth providers and setup.
