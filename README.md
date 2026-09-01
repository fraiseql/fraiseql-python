# FraiseQL

[![Quality Gate](https://github.com/fraiseql/fraiseql-python/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/fraiseql/fraiseql-python/actions/workflows/ci.yml)
[![Documentation](https://github.com/fraiseql/fraiseql-python/actions/workflows/docs.yml/badge.svg?branch=dev)](https://github.com/fraiseql/fraiseql-python/actions/workflows/docs.yml)
[![Release](https://img.shields.io/github/v/release/fraiseql/fraiseql-python)](https://github.com/fraiseql/fraiseql-python/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**A Python GraphQL framework for PostgreSQL.** Declare types and operations with
decorators, point them at PostgreSQL views and functions, and FraiseQL serves a
typed GraphQL API over FastAPI — no build step, no code generation.

PostgreSQL returns JSONB. An integrated Rust pipeline (`fraiseql_rs`) transforms it
into the HTTP response. You write Python; the hot path runs in Rust.

**Requires:** Python 3.13+ · PostgreSQL 13+

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    """A user in the system.

    Fields:
        id: Unique user identifier
        name: User's full name
        email: User's email address
    """
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

Attribute docstrings become GraphQL descriptions. List queries get `where`,
`orderBy`, `limit` and `offset` wired in automatically.

---

## How it works

```
Typical ORM stack:  PostgreSQL → rows → ORM objects → Python dicts → JSON → HTTP
FraiseQL:           PostgreSQL → JSONB → Rust field selection → HTTP
```

The view composes the whole response shape in one query, so there is no N+1 problem
and no Python serialization in the hot path. On the
[transformation benchmark](benchmarks/rust_vs_python_benchmark.py) the JSON step runs
3.6–5.9x faster than the equivalent pure-Python path — 4.1x on a 7 KB nested payload,
4.0x on a 32 KB one.

It also makes the security model structural rather than defensive:

```sql
CREATE VIEW v_user AS
SELECT id, jsonb_build_object('id', id, 'email', email) AS data
FROM tb_user;
-- password_hash and api_key are not in the JSONB, so they cannot leak
```

With an ORM-backed schema, forgetting to exclude a column is a data leak. Here the
view *is* the contract. Reads go through `v_*` views and `tv_*` projection tables;
writes go through `fn_*` PostgreSQL functions ([CQRS](docs/core/concepts-glossary.md)).

---

## v1 vs v2 — which repo do you want?

This repository is **v1 (`fraiseql-python`)**. There is a separate v2 project with a
different architecture. Both are actively maintained.

| | **v1 — this repo** | **v2 — [fraiseql/fraiseql](https://github.com/fraiseql/fraiseql)** |
|---|---|---|
| Status | Stable (1.25.0) | Active (2.14.1; breaking changes ship in minor releases) |
| Engine | Python + Rust pipeline | Compiled Rust engine |
| Schema authoring | Python decorators | 16+ languages |
| Databases | **PostgreSQL only** | PostgreSQL, MySQL, SQLite, SQL Server |
| Deployment | Runtime (FastAPI, hot reload) | Build-time (`fraiseql-cli compile`) |

Pick v1 for a Python codebase already invested in PostgreSQL, with fast iteration and
no build step. Pick v2 for polyglot teams, multiple databases, or compile-time
guarantees.

---

## Is this for you?

**Good fit if you** run PostgreSQL and are comfortable writing views and functions,
want a database-first API, need multi-tenant isolation, care about JSON throughput,
or lean on LLMs for code generation — SQL and Python are well-trained, and there is
no proprietary DSL in the way.

**Look elsewhere if you** need a database other than PostgreSQL (that is v2), do not
want JSONB in your schema, are building your first GraphQL API, or want an ORM to
model your data for you.

See [Choosing FraiseQL](docs/guides/choosing-fraiseql.md) for a longer comparison.

---

## Quick start

```bash
pip install "fraiseql<2"        # or: pip install "fraiseql[all]<2"
fraiseql init my-api
cd my-api
fraiseql dev
```

v1 and v2 share the `fraiseql` name on PyPI, and the bare name now resolves to v2 —
hence the `<2` pin. Your API is live at `http://localhost:8000/graphql`.

- [5-Minute Quickstart](docs/getting-started/quickstart.md) — copy, paste, run
- [First Hour Guide](docs/getting-started/first-hour.md) — build a complete blog API
- [Understanding FraiseQL](docs/guides/understanding-fraiseql.md) — architecture in 10 minutes
- [Installation](docs/getting-started/installation.md) — platform notes and troubleshooting

---

## Features

- **[GraphQL Cascade](docs/features/graphql-cascade.md)** — mutations report what they
  changed and which queries to invalidate; clients request as much or as little of it
  as they want.
- **[Mutations without boilerplate](docs/core/mutation-success-error.md)** —
  `@fraiseql.success` auto-injects `status`, `message`, `updated_fields` and `id`; the
  SQL function holds the business logic.
- **[Specialized scalars](docs/core/types-and-schema.md)** — 50+ validated types
  (`EmailAddress`, `Money`, `IpAddress`, `LTree`, `CUSIP`, `DateRange`, …) with
  type-aware SQL operators.
- **[Advanced filtering](docs/advanced/filter-operators.md)** — full-text search, JSONB
  paths, array operators, regex, ranges, and
  [nested array filters](docs/advanced/nested-array-filtering.md) with `AND`/`OR`/`NOT`.
- **[Vector search](docs/features/pgvector.md)** — pgvector integration for semantic
  search and RAG, with 6 distance operators.
- **[Trinity identifiers](docs/core/trinity-pattern.md)** — `pk_*` integer keys for fast
  joins (never exposed), `id` UUIDs for a stable public API, `identifier` slugs for URLs.
- **[Security](docs/production/security.md)** — RLS, rate limiting, CSRF, security
  headers, field-level authorization, KMS backends (Vault/AWS/GCP), audit logging, and
  SBOM generation via `fraiseql sbom generate`. Enforcement maturity varies per feature:
  security *profiles* enforce 7 of their 14 settings, and query depth, query complexity,
  introspection policy and audit level are configured but not enforced by the profile
  (see the module docstring in `src/fraiseql/security/profiles/definitions.py`). Check a
  given control before relying on it in production.
- **[Everything in PostgreSQL](docs/features/in-postgresql-everything.md)** — caching
  (`UNLOGGED` tables), error tracking and OpenTelemetry traces live in the same
  database, so a small deployment needs no Redis, Sentry or APM service.
- **[Automatic Persisted Queries](docs/performance/apq-optimization-guide.md)** — memory
  or PostgreSQL-backed storage for multi-instance coordination.
- **Resilience testing** — a separate, informational workflow runs the 71 failure-injection
  tests marked `chaos_real_db` (of 145 in `tests/chaos/`) against real PostgreSQL, apart from
  the per-PR suite ([strategy](docs/archive/testing/chaos-engineering-strategy.md)).

---

## Docs and tooling

- [Full documentation](docs/index.md) · [Concepts & glossary](docs/core/concepts-glossary.md)
- [API reference](docs/reference/README.md) · [CLI reference](docs/reference/cli.md)
- [Performance guide](docs/performance/index.md) · [Production deployment](docs/guides/production-deployment.md)
- [Examples](examples/README.md) — blog, e-commerce, multi-tenant SaaS, RAG, and more

The `fraiseql` CLI covers `init`, `dev`, `check`, `doctor`, `generate`, `sql`,
`migrate`, `turbo`, `sbom` and `query-stats`. Run `fraiseql --help` or see the
[CLI reference](docs/reference/cli.md).

---

## Contributing

```bash
git clone https://github.com/fraiseql/fraiseql-python
cd fraiseql-python
uv sync                     # runtime + dev deps, builds the Rust extension
uv run pre-commit install
```

Requires a Rust toolchain for `fraiseql_rs`. The runtime floor is PostgreSQL 13; the
integration tests want 14+, and CI runs them on 16.
See the [Contributing Guide](CONTRIBUTING.md).

---

## About

FraiseQL is created by **Lionel Hamayon** ([@evoludigit](https://github.com/evoludigit)).
The idea: let PostgreSQL return the JSON, let Rust shape it, and keep Python out of
the hot path.

MIT licensed — see [LICENSE](LICENSE).
