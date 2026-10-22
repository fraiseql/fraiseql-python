# FraiseQL Examples

Example applications for FraiseQL 1.x, the Python framework that serves a GraphQL
API from PostgreSQL views and functions at runtime. Each example defines its types
with decorators (`@fraiseql.type`, `@fraiseql.query`, `@fraiseql.mutation`) and
serves them with `create_fraiseql_app`.

- [index.md](index.md) lists every example by difficulty and use case.
- [learning-paths.md](learning-paths.md) orders them into learning paths.
- [pattern_comparison.md](pattern_comparison.md) compares the mutation patterns.

## Start here

| Example | What it shows | Needs |
|---|---|---|
| [`todo_quickstart.py`](todo_quickstart.py) | Types, queries and mutations in one file, on an in-memory list | Nothing: no query reaches a database |
| [`quickstart_5min.py`](quickstart_5min.py) | The code from the 5-minute quickstart guide | PostgreSQL ([`quickstart_5min_schema.sql`](quickstart_5min_schema.sql)) |
| [`blog_simple/`](blog_simple/README.md) | A blog: JSONB views that embed related objects, list arguments passed to `db.find`, class mutations backed by SQL functions | PostgreSQL, or `docker compose up` |

## Run end to end

These were run end to end through the app, against PostgreSQL where they use one:

| Example | What it shows |
|---|---|
| [`blog_simple/`](blog_simple/README.md) | Nested reads from one view, mutations returning `mutation_response`, the current user passed to SQL functions |
| [`saas-starter/`](saas-starter/README.md) | Multi-tenant scoping with `mandatory_filters` and `context_params`, usage tracking, an activity log |
| [`vector_search/`](vector_search/README.md) | pgvector similarity search with each distance operator |
| [`rag-system/`](rag-system/README.md) | Retrieval-augmented generation: documents, embeddings and answers |
| [`ltree-hierarchical-data/`](ltree-hierarchical-data/README.md) | An organization chart on `ltree` paths |
| [`security/`](security/README.md) | Rate limiting, CSRF protection and security headers |
| [`token_revocation_example.py`](token_revocation_example.py) | Logout through token revocation (needs an Auth0 tenant) |
| [`apq_multi_tenant/`](apq_multi_tenant/README.md) | Automatic persisted queries with per-tenant caches |
| [`turbo_router_with_complexity.py`](turbo_router_with_complexity.py) | TurboRouter with complexity-based caching |

## Running an example

```bash
pip install "fraiseql[fastapi]<2"

# A PostgreSQL database (pgvector/pgvector:pg16 for vector_search and rag-system)
docker run -d -e POSTGRES_USER=fraiseql -e POSTGRES_PASSWORD=fraiseql \
  -e POSTGRES_DB=fraiseql -p 5432:5432 postgres:16
```

Then follow the example's README: most load a `schema.sql` (or `db/setup.sql`)
with `psql` and read the connection from `DATABASE_URL` or `DB_*` variables.

## A minimal app

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import ID


@fraiseql.type(sql_source="v_user")  # a view with an id column and a data JSONB column
class User:
    id: ID
    name: str
    email: str


@fraiseql.query
async def users(
    info, where=None, order_by=None, limit: int | None = None, offset: int | None = None
) -> list[User]:
    db = info.context["db"]
    return await db.find(
        "v_user", "users", info, where=where, order_by=order_by, limit=limit, offset=offset
    )


app = create_fraiseql_app(
    database_url="postgresql://fraiseql:fraiseql@localhost:5432/fraiseql",
    types=[User],
    queries=[users],
)
```

Run it with `uvicorn app:app` and open http://localhost:8000/graphql.

## How the examples are tested

`tests/integration/examples/test_every_example_builds.py` imports every
`examples/**.py` in its own process and builds the schema it registers. An example
that doesn't build yet is listed there with the reason. `test_blog_integration.py`
and `test_security_example.py` run the `blog_simple` and `security` apps.

## Contributing an example

Start from [`_TEMPLATE/`](_TEMPLATE/README.md). An example should run against the
current release: import and build (the test above checks it), and say in its README
what it needs and how to run it.
