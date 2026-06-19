---
title: FraiseQL Reference
description: API, scalar, and operator references for FraiseQL v1.
keywords: ["decorators", "types", "scalars", "operators", "config", "cli"]
tags: ["documentation", "reference"]
---

# FraiseQL Reference

FraiseQL is a Python runtime GraphQL framework for PostgreSQL. You define types,
queries, and mutations with decorators; at app startup the schema is built in
memory and served over FastAPI. This section is the API and operator reference.

New here? Start with the [Quickstart](../getting-started/quickstart.md), or browse
the full [Documentation Home](../index.md).

---

## Decorators & API

| Document | Description |
|----------|-------------|
| [decorators.md](decorators.md) | `@fraiseql.type`, `@fraiseql.query`, `@fraiseql.mutation`, `@fraiseql.input`, `@fraiseql.success`/`@fraiseql.error`, and friends |
| [mutations-api.md](mutations-api.md) | Mutation result types and calling PostgreSQL `fn_` functions |
| [repositories.md](repositories.md) | The CQRS repository (`db.find`, `db.find_one`, `db.execute_function`) on `info.context["db"]` |

## Types & Scalars

| Document | Description |
|----------|-------------|
| [scalars.md](scalars.md) | The built-in and domain scalar library (`ID`, `UUID`, `DateTime`, `EmailAddress`, `JSON`, `LTree`, and many more) |

## Filtering Operators

All operators are PostgreSQL-specific and generated at runtime from your `WHERE`
input types.

| Document | Description |
|----------|-------------|
| [where-operators.md](where-operators.md) | The complete WHERE operator catalog (comparison, text/pattern, array, JSON) |
| [ltree-operators.md](ltree-operators.md) | `ltree` hierarchy operators (`ancestor_of`, `descendant_of`, `matches_lquery`, …) |
| [vector-operators.md](vector-operators.md) | pgvector distance operators (`cosine_distance`, `inner_product`, `hamming_distance`, …) |

## Conventions

| Document | Description |
|----------|-------------|
| [naming-patterns.md](naming-patterns.md) | Database naming conventions (`tb_`, `v_`, `tv_`, `fn_`, `pk_`/`fk_`, the trinity `pk_`/`id`/`identifier`) |
| [database.md](database.md) | Read views, table-backed views, and the `data` JSONB pattern |
| [terminology.md](terminology.md) | Glossary of FraiseQL terms |

## Configuration & CLI

| Document | Description |
|----------|-------------|
| [config.md](config.md) | `FraiseQLConfig`, `create_fraiseql_app(...)` kwargs, and `FRAISEQL_` environment variables |
| [cli.md](cli.md) | Command-line tooling for development workflows |
| [quick-reference.md](quick-reference.md) | One-page cheat sheet of common patterns |

---

## Using these references

A minimal v1 app ties the pieces together at startup:

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import ID


@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: str
    email: str


@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user")


app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users],
    production=False,  # enables the GraphQL playground
)
```

- **Schema authors** — reach for [decorators.md](decorators.md),
  [scalars.md](scalars.md), and [naming-patterns.md](naming-patterns.md).
- **Frontend developers** — bookmark [where-operators.md](where-operators.md)
  and [scalars.md](scalars.md) for query building and type serialization.
- **Operators / deployers** — see [config.md](config.md) and [cli.md](cli.md).

---

**Back to:** [Documentation Home](../index.md)
