---
title: Real-World Application Patterns
description: Application blueprints for production FraiseQL v1 services built on Python, PostgreSQL, and FastAPI.
keywords: ["patterns", "saas", "realtime", "ecommerce", "analytics", "iot", "postgresql"]
tags: ["documentation", "patterns"]
---

# Real-World Application Patterns

**Status:** Production Ready
**Audience:** Architects, senior developers

Application blueprints for building production services with FraiseQL v1. Each blueprint
is a complete, opinionated design built on the same runtime foundation: Python decorators
(`@fraiseql.type`, `@fraiseql.query`, `@fraiseql.mutation`, `@fraiseql.subscription`)
served over FastAPI, with all data and write logic living in PostgreSQL.

---

## How these blueprints fit together

Every pattern below follows FraiseQL's CQRS model:

- **Reads** — `@query` resolvers call `db.find` / `db.find_one` on `v_` / `tv_` views.
  The view's `data` JSONB is shaped to the requested GraphQL fields at runtime.
- **Writes** — `@mutation` resolvers call PostgreSQL `fn_` functions via
  `db.execute_function`. All write business logic and validation live in the database.
- **Streams** — `@subscription` resolvers are async generators (often backed by
  PostgreSQL `LISTEN/NOTIFY`) whose yielded values FraiseQL pushes over WebSocket.
- **Identity** — the trinity pattern (`pk_` internal BIGINT, `id` public UUID,
  optional `identifier` slug) keeps internal keys out of the API.

The schema is assembled in memory at app startup. There is no build step and no
generated artifact — `create_fraiseql_app(...)` (or `build_fraiseql_schema(...)`)
wires your types, queries, and mutations into a running GraphQL service.

---

## The Blueprints

### [Multi-Tenant SaaS with Row-Level Security](./saas-multi-tenant.md)

Build a B2B SaaS where tenants are isolated at the database row level. Each row carries
a `tenant_id`; PostgreSQL Row-Level Security policies read `current_setting('app.tenant_id')`,
and FraiseQL sets that session GUC per transaction from `info.context["tenant_id"]`.

### [Analytics Platform with OLAP](./analytics-olap-platform.md)

Build a BI/analytics service over star-schema fact and dimension tables. Aggregations use
FraiseQL's runtime auto-aggregation (COUNT, SUM, AVG, MIN, MAX, STDDEV, VARIANCE) and
standard PostgreSQL `GROUP BY` / `HAVING` / `FILTER` inside your `v_` / `tv_` views.

### [Real-Time Collaboration with Subscriptions](./realtime-collaboration.md)

Build collaborative tools (document editors, project boards) with live updates. Uses
`@fraiseql.subscription` async generators over WebSocket, typically backed by PostgreSQL
`LISTEN/NOTIFY`, plus presence tracking and activity feeds.

### [E-Commerce with Complex Workflows](./ecommerce-workflows.md)

Build an online store with product catalogs, an order state machine, inventory reservations,
and fulfillment. Writes flow through `fn_` functions; reads come from `v_` / `tv_` views;
order state transitions are enforced in the database.

### [IoT Platform with Time-Series Data](./iot-timeseries.md)

Collect and query high-volume sensor data. Uses time-partitioned tables, rollup tables for
hourly/daily aggregates refreshed by functions, retention policies, and time bucketing with
`DATE_TRUNC` inside views.

---

## Pattern Selection Guide

| Pattern | Best For | Scale |
|---------|----------|-------|
| **Multi-Tenant SaaS** | B2B SaaS platforms, white-label products | 10K-100K+ tenants |
| **Analytics OLAP** | BI dashboards, reporting, business intelligence | 100GB-100TB+ data |
| **Real-Time Collaboration** | Document editors, boards, project management | 100-10K+ concurrent users |
| **E-Commerce** | Online stores, marketplaces, catalogs | 1M-100M+ products |
| **IoT Time-Series** | Sensor networks, monitoring, metrics | Billions of data points |

---

## Concerns Common to Every Blueprint

### Data validation

- Validation lives in PostgreSQL `fn_` functions, which return JSONB indicating success
  or a structured error.
- Referential integrity is enforced by foreign keys and constraints on `tb_` tables.
- GraphQL input types coerce and type-check arguments before they reach the database.

### Error handling

- Mutations return a success-or-error union (`@fraiseql.success` / `@fraiseql.error`),
  so clients receive field-level details and stable error codes.
- Internal error details stay in the database/server logs, not in the API response.

### Performance

- Result caching with cascade invalidation via FraiseQL's PostgreSQL-backed cache
  (`ResultCache`, `CachedRepository`, `cached_query`).
- N+1 prevention with `@fraiseql.dataloader_field` and view-level joins.
- Cursor-based pagination for large result sets; PostgreSQL indexes on read views.

### Security

- Authentication via JWT; authorization via an `Authorizer` passed to
  `@fraiseql.query(authorizer=...)` / `@fraiseql.subscription(authorizer=...)` and/or
  PostgreSQL RLS policies.
- SQL injection prevention through parameterized queries everywhere.
- Rate limiting and audit logging for sensitive operations.

---

## Common Challenges & Solutions

### Challenge: N+1 queries

Fetching a parent then iterating its children issues one query per child. Request nested
relationships in a single GraphQL query (FraiseQL resolves them from the view's JSONB) and
use `@fraiseql.dataloader_field` for batched lookups.

```graphql
query GetPostsWithAuthors {
  posts {
    id
    title
    author {
      id
      name
      email
    }
    comments {
      id
      content
      author { name }
    }
  }
}
```

### Challenge: Large result sets

Querying millions of rows at once strains memory. Use cursor-based pagination.

```graphql
query GetPostsPaginated($first: Int!, $after: String) {
  posts(first: $first, after: $after) {
    edges {
      cursor
      node {
        id
        title
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

### Challenge: Tenant and row-level authorization

Some users may see only a subset of rows. Enforce visibility with PostgreSQL RLS policies
that read session GUCs FraiseQL sets from the request context.

```sql
-- RLS policy on a tenant-scoped table
CREATE POLICY tenant_isolation ON tb_document
  USING (
    tenant_id = current_setting('app.tenant_id')::uuid
    AND (is_public OR owner_id = current_setting('app.user_id')::uuid)
  );
```

### Challenge: Real-time updates

Clients need live data without polling. Stream changes with a WebSocket subscription whose
async generator yields on PostgreSQL `LISTEN/NOTIFY` events.

```graphql
subscription OnUserStatusChanged {
  userStatusChanged {
    userId
    status
    lastSeen
  }
}
```

---

## See Also

**Detailed blueprints:**

- [Multi-Tenant SaaS with RLS](./saas-multi-tenant.md)
- [Analytics Platform with OLAP](./analytics-olap-platform.md)
- [Real-Time Collaboration](./realtime-collaboration.md)
- [E-Commerce Workflows](./ecommerce-workflows.md)
- [IoT Time-Series Data](./iot-timeseries.md)

**Foundations:**

- [Documentation Home](../index.md)
- [Core Concepts](../foundation/02-core-concepts.md)
- [Quickstart](../getting-started/quickstart.md)
