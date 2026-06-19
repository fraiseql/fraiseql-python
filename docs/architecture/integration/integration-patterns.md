---
title: "FraiseQL Integration Patterns: FDW, FastAPI, and Clients"
description: How FraiseQL v1 integrates with external systems through PostgreSQL FDW, FastAPI composition, and GraphQL clients.
keywords: ["integration", "postgres-fdw", "fastapi", "graphql-client", "notify", "outbox", "patterns"]
tags: ["documentation", "reference"]
---

# FraiseQL Integration Patterns: FDW, FastAPI, and Clients

**Audience:** Integration architects, backend engineers, platform teams

---

## Executive Summary

FraiseQL v1 is a Python runtime GraphQL framework that serves a PostgreSQL
database over FastAPI. It does not ship a federation gateway, a webhook engine,
or a message-broker publisher. Instead, integration happens at three well-defined
layers, each using technology you already control:

1. **Database-level integration** — read external or remote PostgreSQL data
   *inside your views* with PostgreSQL Foreign Data Wrappers (FDW), and reach out
   from `fn_` functions via `LISTEN/NOTIFY` or an outbox table.
2. **Application-level integration** — mount the FraiseQL FastAPI app inside a
   larger FastAPI/ASGI application, add middleware, and share authentication so
   REST and GraphQL are served together.
3. **Client integration** — talk to FraiseQL over standard GraphQL-over-HTTP and
   the GraphQL-over-WebSocket subscription endpoint.

Each layer is composed from standard tools (PostgreSQL, FastAPI, GraphQL clients),
not from FraiseQL-specific integration decorators.

---

## 1. Database-Level Integration

The deepest integration surface in FraiseQL is PostgreSQL itself. Because every
GraphQL query reads from a `v_`/`tv_` view and every mutation calls an `fn_`
function, anything PostgreSQL can do becomes available to your API without a new
FraiseQL feature.

### 1.1 Reading External Data with PostgreSQL FDW

PostgreSQL Foreign Data Wrappers let a `v_`/`tv_` view read tables that live in
*another* PostgreSQL database (or, with the right wrapper, another data source) as
if they were local. This is a **PostgreSQL feature you compose into your views** —
FraiseQL never sees the difference, because it only ever queries the view.

```sql
-- In your application database:
CREATE EXTENSION IF NOT EXISTS postgres_fdw;

CREATE SERVER orders_fdw
  FOREIGN DATA WRAPPER postgres_fdw
  OPTIONS (host 'orders-db', dbname 'orders_db', port '5432');

CREATE USER MAPPING FOR current_user
  SERVER orders_fdw
  OPTIONS (user 'fdw_reader', password 'secret');

-- Expose the remote read view as a local foreign table.
-- Mirror the remote v_order shape: a public id (UUID) plus a data JSONB column.
CREATE FOREIGN TABLE remote_v_order (
    id      UUID,
    fk_user UUID,
    data    JSONB
) SERVER orders_fdw
  OPTIONS (schema_name 'public', table_name 'v_order');
```

Now reference the foreign table from a normal FraiseQL read view. The view still
produces the standard `id` + `data` JSONB shape that FraiseQL expects:

```sql
CREATE VIEW v_user_with_orders AS
SELECT
    u.id,
    u.data
      || jsonb_build_object(
           'orders',
           COALESCE(
             (SELECT jsonb_agg(o.data ORDER BY o.data->>'createdAt' DESC)
              FROM remote_v_order o
              WHERE o.fk_user = u.id),
             '[]'::jsonb
           )
         ) AS data
FROM v_user u;
```

Your `@fraiseql.type` and `@fraiseql.query` stay unchanged — they target
`v_user_with_orders` like any other view:

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.type(sql_source="v_user_with_orders", jsonb_column="data")
class User:
    id: ID
    name: str
    orders: list["Order"]


@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user_with_orders")
```

**This is not FraiseQL federation.** There is no gateway, no entity-resolution
protocol, and no subgraph registry. The join happens entirely inside PostgreSQL,
so the cost profile is a database join (single-digit milliseconds when the foreign
server is nearby and indexed) rather than an HTTP round-trip per entity.

**Operational notes for FDW views:**

- Foreign-table reads are only as fast as the remote query plan. Add appropriate
  indexes on the remote side and use `IMPORT FOREIGN SCHEMA` or `ANALYZE` so the
  planner has statistics.
- Network and credential failures surface as query errors. Wrap heavy FDW joins in
  a `tv_` projection table that you refresh on a schedule if you need to decouple
  read latency from the remote system's availability.
- Never expose internal `pk_`/`fk_` columns through the view's `data` JSONB —
  publish only the public `id` (UUID) and the requested fields.

### 1.2 Reaching Out from `fn_` Functions

Mutations call `fn_` PostgreSQL functions through `db.execute_function(...)`. Those
functions can signal other systems as part of the same transaction, so there is no
need for a FraiseQL-side publisher.

**`LISTEN/NOTIFY` for in-process / nearby listeners:**

```sql
CREATE FUNCTION fn_create_order(input JSONB)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    new_id UUID := gen_random_uuid();
BEGIN
    INSERT INTO tb_order (id, fk_user, data)
    VALUES (new_id, (input->>'userId')::uuid, input);

    -- Emit an event on commit; any LISTENer on this channel receives it.
    PERFORM pg_notify(
        'order_events',
        jsonb_build_object('type', 'order_created', 'id', new_id)::text
    );

    RETURN jsonb_build_object('success', true, 'id', new_id);
END;
$$;
```

`pg_notify` payloads are limited (8 KB) and only delivered to currently-connected
listeners — there is no replay. For durable, ordered delivery, prefer the outbox
pattern below.

**Transactional outbox for durable delivery to your own workers:**

```sql
-- Written in the SAME transaction as the business write.
CREATE TABLE tb_outbox (
    pk_outbox    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id           UUID NOT NULL DEFAULT gen_random_uuid(),
    event_type   TEXT NOT NULL,
    payload      JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);

CREATE FUNCTION fn_create_order(input JSONB)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    new_id UUID := gen_random_uuid();
BEGIN
    INSERT INTO tb_order (id, fk_user, data)
    VALUES (new_id, (input->>'userId')::uuid, input);

    INSERT INTO tb_outbox (event_type, payload)
    VALUES ('order_created', jsonb_build_object('orderId', new_id));

    RETURN jsonb_build_object('success', true, 'id', new_id);
END;
$$;
```

A separate worker process — **your application code, not a FraiseQL component** —
polls `tb_outbox` (or listens on a NOTIFY channel that the insert raises), delivers
each event to Kafka/RabbitMQ/an HTTP webhook endpoint, and marks rows processed.
Because the outbox row is written in the same transaction as the business data, you
get a single atomic write with at-least-once downstream delivery; consumers
deduplicate on the event `id`.

> The key principle is **single write to PostgreSQL, events propagate from there.**
> Never write to the database *and* call an external service directly from a
> resolver — if the second call fails you get an inconsistency with no atomicity.
> Let PostgreSQL own the write and let a worker drain the outbox.

For consistency guarantees and the read/write model, see
[../reliability/consistency-model.md](../reliability/consistency-model.md) and
[../../foundation/03-database-centric-architecture.md](../../foundation/03-database-centric-architecture.md).

### 1.3 Other PostgreSQL Integration Surfaces

Because integration lives in the database, you can use the full PostgreSQL
ecosystem inside your views and functions:

- **Extensions** — `pgvector` (similarity search), `pg_trgm` (fuzzy text),
  PostGIS (geospatial), `ltree` (hierarchies). Expose results through a view's
  `data` JSONB.
- **PL/Python / PL/pgSQL** — call out to compute inside `fn_` functions when the
  logic genuinely belongs server-side.
- **Triggers** — keep `tv_` projection tables current, or populate `tb_outbox`
  rows automatically on write.

---

## 2. Application-Level Integration (FastAPI)

`create_fraiseql_app(...)` returns a standard FastAPI application. That makes
FraiseQL a normal citizen of any FastAPI/ASGI deployment: you can add middleware,
mount it under a path, run it beside REST routes, and share authentication.

### 2.1 Adding Middleware

Pass standard Starlette/FastAPI middleware through `create_fraiseql_app`:

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    production=True,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["https://app.example.com"],
            allow_methods=["POST", "GET"],
        ),
        Middleware(GZipMiddleware, minimum_size=1024),
    ],
)
```

Any ASGI middleware works the same way — request logging, tracing, rate limiting,
and so on — because there is nothing FraiseQL-specific about the integration point.

### 2.2 Mounting Inside a Larger Application

Run FraiseQL alongside your existing REST endpoints by mounting it as a
sub-application. GraphQL lives under one path; the rest of your API is unchanged.

```python
from fastapi import FastAPI

from fraiseql.fastapi import create_fraiseql_app

# Your existing REST API.
root = FastAPI(title="Platform API")


@root.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@root.get("/v1/reports/{report_id}")
async def get_report(report_id: str) -> dict:
    ...  # existing REST handler


# The FraiseQL GraphQL app.
graphql_app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    production=True,
)

# Serve GraphQL under /graphql, REST everywhere else.
root.mount("/graphql", graphql_app)
```

Run the composed app with any ASGI server:

```bash
uvicorn app:root --host 0.0.0.0 --port 8000
```

The GraphQL HTTP endpoint, the GraphQL-over-WebSocket subscription endpoint, and
(when `production=False`) the playground are all served under the mount path.

### 2.3 Sharing Authentication

FraiseQL resolves authentication into `info.context`, so the cleanest pattern is to
let one auth layer populate the request and have both REST and GraphQL read from it.
Two common approaches:

- **Shared middleware** — an ASGI auth middleware (JWT/Auth0/session) validates the
  incoming token, attaches the principal to the request scope, and both the REST
  routes and the FraiseQL resolvers read it. Pass it through `middleware=[...]`.
- **FraiseQL authorization** — guard individual operations with
  `@fraiseql.query(authorizer=...)` and `@fraiseql.subscription(authorizer=...)`,
  and field-level access with the `authorize_fields` parameter on
  `@fraiseql.type`. These run inside FraiseQL using the same principal the shared
  middleware established.

```python
import fraiseql


@fraiseql.query(authorizer=require_authenticated)
async def me(info) -> User | None:
    db = info.context["db"]
    principal = info.context["user"]  # populated by shared auth middleware
    return await db.find_one("v_user", id=principal.id)
```

Because authorization is enforced per resolver, keep it consistent across every
operation — a resolver without an authorizer is open. See
[./extension-points.md](./extension-points.md) for the full set of authorization,
custom-field, and dataloader extension points.

---

## 3. Client Integration

FraiseQL speaks the two standard GraphQL transports, so any conformant client works
without special drivers.

### 3.1 GraphQL over HTTP

Queries and mutations are plain `POST` requests to the GraphQL endpoint:

```bash
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "{ users { id name } }"}'
```

Any GraphQL client (Apollo Client, urql, graphql-request, Relay, or a hand-rolled
`fetch`) connects the same way — point it at the endpoint URL and send the standard
`{ query, variables, operationName }` body.

### 3.2 GraphQL over WebSocket (Subscriptions)

Subscriptions are served over GraphQL-over-WebSocket. FraiseQL supports both the
modern `graphql-transport-ws` protocol and the legacy `graphql-ws` protocol, so
clients negotiate whichever they implement.

```python
import fraiseql
from collections.abc import AsyncGenerator
from uuid import UUID


@fraiseql.subscription
async def task_updates(info, project_id: UUID) -> AsyncGenerator[Task, None]:
    async for task in watch_project_tasks(project_id):
        yield task
```

The event source is **your async generator** — it can be backed by PostgreSQL
`LISTEN/NOTIFY`, polling a `tv_` projection, or an external stream you read. FraiseQL
streams whatever the generator yields to the connected client over WebSocket. For
the subscription model, lifecycle, and client setup, see
[../realtime/subscriptions.md](../realtime/subscriptions.md).

### 3.3 Choosing What a Client Reads

Whether a query is cheap depends on the view it hits. Point read-heavy or
deeply-nested client queries at `tv_` projection tables and lighter queries at
plain `v_` views. The trade-offs are covered in
[../database/view-selection-guide.md](../database/view-selection-guide.md).

---

## 4. Putting It Together: A Reference Topology

A typical FraiseQL deployment that integrates with several external systems uses
each layer for what it does best:

```
        GraphQL clients (HTTP + WebSocket)
                     |
            ┌────────▼─────────┐
            │  FastAPI root    │  REST routes + mounted /graphql
            │  (your app)      │  shared auth middleware
            └────────┬─────────┘
                     │
            ┌────────▼─────────┐
            │   PostgreSQL     │
            │  v_/tv_ views    │◀── FDW ──▶ remote PostgreSQL (read)
            │  fn_ functions   │──▶ tb_outbox ──▶ your worker ──▶ Kafka / webhook
            └──────────────────┘
```

- **Reads** that need remote data join through FDW *inside the view*.
- **Writes** go to PostgreSQL via `fn_` functions; an outbox row makes downstream
  delivery durable and atomic.
- **Your worker** (not FraiseQL) drains the outbox and talks to brokers or HTTP
  endpoints, keeping the single-write principle intact.
- **Clients** use standard GraphQL transports; the playground is available in
  development only.

---

## 5. Best Practices

**Database-level (FDW + functions):**

- Compose FDW reads inside views; keep `@fraiseql.type` definitions unaware of the
  remote source.
- Materialize expensive FDW joins into `tv_` projection tables when remote latency
  or availability is a risk.
- Use the transactional outbox for durable, ordered, exactly-once-effective
  delivery; use `LISTEN/NOTIFY` only for best-effort, nearby listeners.
- Never expose `pk_`/`fk_` columns through a view's `data` JSONB.

**Application-level (FastAPI):**

- Mount FraiseQL under a path inside your existing app rather than running two
  servers when REST and GraphQL share a deployment.
- Establish authentication once in shared middleware and read the principal from
  `info.context` in resolvers.
- Apply an authorizer to every query, mutation, and subscription that needs one — a
  missing authorizer means open access.

**Client-level:**

- Use any standard GraphQL-over-HTTP client; no FraiseQL-specific SDK is required.
- Negotiate `graphql-transport-ws` for subscriptions; fall back to legacy
  `graphql-ws` only for older clients.
- Disable the playground in production (`production=True`).

---

## Related Documentation

- [./extension-points.md](./extension-points.md) — custom fields, dataloaders,
  authorization, and middleware extension points.
- [../realtime/subscriptions.md](../realtime/subscriptions.md) — WebSocket
  subscriptions and the async-generator event model.
- [../reliability/consistency-model.md](../reliability/consistency-model.md) — the
  read/write consistency model behind the single-write principle.
- [../database/view-selection-guide.md](../database/view-selection-guide.md) —
  choosing `v_` vs `tv_` for client query shapes.
- [../../foundation/03-database-centric-architecture.md](../../foundation/03-database-centric-architecture.md)
  — why business logic and integration live in PostgreSQL.
