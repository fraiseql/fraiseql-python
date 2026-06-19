---
title: FraiseQL
description: A Python GraphQL framework that turns PostgreSQL views and functions into a typed GraphQL API at runtime.
tags:
  - overview
  - introduction
  - graphql
  - postgresql
  - fastapi
---

# FraiseQL

**A Python GraphQL framework for PostgreSQL.** Define your types and operations
with decorators, point them at PostgreSQL views and functions, and FraiseQL serves
a typed GraphQL API over FastAPI — no build step, no code generation.

PostgreSQL returns JSONB. An integrated Rust pipeline (`fraiseql_rs`) transforms it
into GraphQL responses with minimal Python overhead. You write Python; the hot path
runs in Rust.

```python
# A complete GraphQL API
import fraiseql
from fraiseql.fastapi import create_fraiseql_app

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    """A user in the system."""
    id: int
    name: str
    email: str

@fraiseql.query
async def users(info) -> list[User]:
    """Get all users."""
    db = info.context["db"]
    return await db.find("v_user")

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users],
)
```

Run it with any ASGI server (`uvicorn app:app`) and open `/graphql`.

---

## Why FraiseQL

- **Database-first.** Your PostgreSQL views and functions are the source of truth.
  Types map to views; mutations call functions. No ORM, no N+1 surprises.
- **Runtime, not a compiler.** The schema is built from your decorated Python at
  startup with `create_fraiseql_app` / `build_fraiseql_schema`. Change code, restart,
  iterate — no compile step.
- **Rust-fast JSON.** The `fraiseql_rs` pipeline turns PostgreSQL JSONB into GraphQL
  responses, keeping Python out of the per-row hot path.
- **FastAPI native.** Ships as a FastAPI/ASGI app with a GraphQL playground,
  middleware, auth integration, and production hardening built in.
- **PostgreSQL-focused.** v1 targets PostgreSQL 13+ exclusively and leans into its
  strengths: JSONB, CTEs, `ltree`, custom functions, and rich indexing.

---

## Get Started

| Step | Guide |
|------|-------|
| Build your first API in 5 minutes | [Quickstart](getting-started/quickstart.md) |
| Go deeper with a guided hour | [First Hour](getting-started/first-hour.md) |
| Install FraiseQL and PostgreSQL | [Installation](getting-started/installation.md) |

```bash
pip install "fraiseql[all]"
```

Requirements: **Python 3.13+** and **PostgreSQL 13+**.

---

## Learn the Concepts

- **[Core Concepts](foundation/02-core-concepts.md)** — types, queries, mutations,
  and how decorators map to the database.
- **[Database-Centric Architecture](foundation/03-database-centric-architecture.md)** —
  the JSONB view pattern, CQRS, and the Trinity identifier convention.
- **[Design Principles](foundation/04-design-principles.md)** — the ideas that shape
  the framework.
- **[Type System](foundation/09-type-system.md)** — scalars, inputs, enums, and how
  Python type hints become GraphQL types.

## Build & Operate

- **[Guides](guides/README.md)** — schema design, authorization, analytics, and
  client integration.
- **[Patterns](patterns/README.md)** — multi-tenant SaaS, OLAP, real-time
  collaboration, e-commerce, and IoT blueprints.
- **[Reference](reference/README.md)** — decorators, scalar types, and `WHERE`
  operators.
- **[Production Deployment](guides/production-deployment.md)** — running FraiseQL at
  scale on FastAPI.

---

## A Note on Versions

This documentation is for **FraiseQL v1** — the Python framework in the
[`fraiseql-python`](https://github.com/fraiseql/fraiseql-python) repository. It is
PostgreSQL-only and runs your schema at runtime over FastAPI, with the optional
`fraiseql_rs` Rust pipeline for fast JSON transformation.

A separate, compiled multi-database engine (FraiseQL v2) lives in a different
repository and is not covered here.
