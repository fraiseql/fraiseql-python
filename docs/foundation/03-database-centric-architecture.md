---
title: Database-Centric Architecture
description: FraiseQL treats the PostgreSQL database as the primary application interface, not as a storage afterthought. This page explains why that choice matters and how it shapes FraiseQL's runtime design.
keywords: ["design", "query-execution", "cqrs", "jsonb", "postgresql", "graphql", "views", "performance"]
tags: ["documentation", "foundation"]
---

# Database-Centric Architecture

**Audience:** Architects, database teams, developers building data systems
**Prerequisite:** [Core Concepts](./02-core-concepts.md)
**Reading Time:** 20-25 minutes

---

## Overview

FraiseQL's fundamental design choice is to treat the **PostgreSQL database as the primary application interface**, not as a storage afterthought. This page explains why this choice matters, how it shapes FraiseQL's architecture, and what implications it has for your systems.

**Core insight:** In FraiseQL, the database schema is not an implementation detail—it is your API definition. PostgreSQL is the source of truth for data relationships, types, validation, and performance.

FraiseQL is a **runtime** framework: you describe your types, queries, and mutations with Python decorators, and the GraphQL schema is built **in memory at application startup** by `create_fraiseql_app` (or `build_fraiseql_schema`). There is no build step and no compiled artifact—the running FastAPI process is the whole story.

---

## Part 1: The Core Philosophy

### GraphQL as a Database Access Layer, Not API Aggregation

Traditional GraphQL servers are designed to aggregate data from multiple sources:

```text
Client
  ↓ (GraphQL Query)
GraphQL Server
  ├→ REST API call
  ├→ Another GraphQL service
  ├→ Database query
  ├→ Cache lookup
  ├→ Custom resolver logic
  └→ Webhook
  ↓
Client (aggregated response)
```

**Problem:** The server becomes a coordination layer, and you need to write resolvers for every field, cache invalidation logic, N+1 prevention, and so on.

---

### FraiseQL's Approach: Database-First Architecture

FraiseQL assumes PostgreSQL is your **primary and usually only data source**:

```text
Client
  ↓ (GraphQL Query)
FraiseQL (FastAPI app)
  ├→ Validate (against the in-memory schema)
  ├→ Authorize (declarative rules)
  └→ Execute (read a v_/tv_ view or call an fn_ function)
  ↓
PostgreSQL (single source of truth)
  ↓
Client (direct result)
```

**Advantage:** Clear data flow, minimal custom resolver code, deterministic behavior.

---

### Why This Assumption Matters

This design choice has profound consequences:

**1. Simplicity**

- Little to no custom resolver code needed
- Schema definition = API definition
- What you see in the schema is what you get

**2. Performance**

- PostgreSQL handles query planning and optimization
- No application-level coordination overhead
- Reads come from purpose-built views; the optional Rust extension (`fraiseql_rs`) accelerates JSON shaping on the hot path

**3. Correctness**

- Database constraints enforced
- Transactions guarantee consistency
- Relationships are explicit (foreign keys)

**4. Consistency**

- Single source of truth (the database)
- No cache invalidation problems
- All clients see consistent data

**5. Debuggability**

- Look at the view or function, understand the query
- No hidden resolver logic
- Performance bottlenecks are clear (database metrics)

---

### When This Assumption is Valid

FraiseQL works best when:

- Your primary data source is **PostgreSQL**
- Your data has **clear structure and relationships** (not fully unstructured)
- Your API needs to be **performant** (N+1 queries unacceptable)
- Your team has **database expertise** (schemas, views, indexes, functions)
- You value **predictability** over unconstrained flexibility

---

### When This Assumption Breaks Down

FraiseQL is **not** the right choice when:

- Your primary data is **unstructured** (documents, blobs)
- You need to aggregate from **many external APIs** (microservices federation)
- Your schema is **highly dynamic** (must change at runtime per request)
- You have **deeply nested custom logic** better expressed in application code
- You're using a non-PostgreSQL database (FraiseQL v1 is PostgreSQL-only)

---

## Part 2: How FraiseQL Thinks About Data

### The Data Hierarchy

```text
PostgreSQL Schema (DBA responsibility)
    ↓
FraiseQL Type Definition (Developer responsibility)
    ↓
GraphQL API (Client interface)
```

Each level maps directly. Note the identifier discipline: tables use an internal `pk_` BIGINT for fast joins (never exposed), a public `id` UUID for the GraphQL `id`, and an optional human-readable `identifier` slug.

**Database Level (write tables — the source of truth):**

```sql
CREATE TABLE tb_user (
    pk_user    BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    id         UUID NOT NULL DEFAULT gen_random_uuid(),
    username   VARCHAR(255) NOT NULL,
    email      VARCHAR(255) NOT NULL,
    is_active  BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE TABLE tb_order (
    pk_order   BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    id         UUID NOT NULL DEFAULT gen_random_uuid(),
    fk_user    BIGINT NOT NULL REFERENCES tb_user(pk_user),
    total      NUMERIC(10, 2) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

**Read View Level (what GraphQL actually queries):**

A read view always exposes a public `id` column (for `WHERE id = $1`) plus a `data` JSONB column built with `jsonb_build_object(...)`. Internal `pk_`/`fk_` keys never appear inside `data`.

```sql
CREATE VIEW v_user AS
SELECT
    u.id,                       -- public UUID, used for lookups
    jsonb_build_object(
        'id',        u.id,
        'username',  u.username,
        'email',     u.email,
        'isActive',  u.is_active,
        'createdAt', u.created_at
    ) AS data
FROM tb_user u
WHERE u.deleted_at IS NULL;     -- only active users
```

**FraiseQL Type Level (maps the type to its read view):**

```python
import fraiseql
from datetime import datetime
from fraiseql.types import ID


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    username: str
    email: str
    is_active: bool
    created_at: datetime
    orders: list["Order"]          # resolved from the order view


@fraiseql.type(sql_source="v_order", jsonb_column="data")
class Order:
    id: ID
    total: float
    user: User                     # nested read, composed in the view
    created_at: datetime
```

**GraphQL API Level:**

```graphql
type User {
  id: ID!
  username: String!
  email: String!
  isActive: Boolean!
  createdAt: DateTime!
  orders: [Order!]!
}

type Order {
  id: ID!
  total: Float!
  user: User!
  createdAt: DateTime!
}

query GetUser {
  user(id: "550e8400-e29b-41d4-a716-446655440000") {
    id
    username
    orders {
      id
      total
    }
  }
}
```

---

### Mapping: Tables → Views → Types

Foreign keys in the write tables express relationships. You realize those relationships in the **read view** by composing nested JSONB, then point the GraphQL type at that view:

```sql
-- A view that pre-composes the order together with its user.
CREATE VIEW v_order AS
SELECT
    o.id,
    jsonb_build_object(
        'id',        o.id,
        'total',     o.total,
        'createdAt', o.created_at,
        'user', jsonb_build_object(
            'id',       u.id,
            'username', u.username,
            'email',    u.email
        )
    ) AS data
FROM tb_order o
JOIN tb_user u ON u.pk_user = o.fk_user;
```

```python
@fraiseql.type(sql_source="v_order", jsonb_column="data")
class Order:
    id: ID
    total: float
    user: User                     # available because the view composed it
```

The view structure is the API structure. You shape data once, in SQL, and FraiseQL serves exactly the requested fields out of the `data` JSONB.

---

## Part 3: Read Views — `v_` and `tv_`

FraiseQL reads come from views whose `data` JSONB column carries the entity payload. There are two flavors, chosen by how the read is materialized:

### Overview Matrix

| View Type | Prefix | Storage | Use Case | Refresh |
|-----------|--------|---------|----------|---------|
| **Logical Read View** | `v_*` | none (computed on read) | simple to moderate queries; real-time data | always live |
| **Table-Backed Projection** | `tv_*` | a real table holding pre-composed JSONB | heavy nested reads, high read volume | functions/triggers |

---

### 1. `v_*` — Logical Read Views

**Definition:** Plain PostgreSQL views (no physical storage) that build a `data` JSONB on every read.

**When to use:**

- Simple to moderate queries (a handful of joined tables)
- Small to medium result sets
- Real-time data needed (the view always reflects current state)
- Data changes frequently

```sql
CREATE VIEW v_user AS
SELECT
    u.id,
    jsonb_build_object(
        'id',        u.id,
        'username',  u.username,
        'email',     u.email,
        'createdAt', u.created_at
    ) AS data
FROM tb_user u
WHERE u.deleted_at IS NULL;        -- only active users
```

**Characteristics:**

- **Storage overhead:** 0% (logical view only)
- **Maintenance:** none (computed from base tables)
- **Staleness:** real-time
- **Index support:** uses the base tables' indexes

```python
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    username: str
    email: str
    created_at: datetime
```

Queries simply read the view:

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

---

### 2. `tv_*` — Table-Backed Projection Views

**Definition:** A real table that stores **pre-composed JSONB**, refreshed by functions or triggers. Because the nested structure is already assembled, reads avoid join work at query time.

**When to use:**

- Complex nested structures (User + Orders + Items in a single payload)
- High read volume
- Moderate write volume
- A small, bounded staleness window is acceptable

```sql
-- A table-backed projection: pre-composed nested JSONB.
CREATE TABLE tv_order_with_user (
    id         UUID PRIMARY KEY,
    data       JSONB NOT NULL,     -- {id, total, user: {id, username, email}}
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- GIN index for path lookups inside the JSONB payload.
CREATE INDEX idx_tv_order_with_user_data ON tv_order_with_user USING GIN(data);

-- Refresh function: rebuild the projection for one order.
CREATE OR REPLACE FUNCTION fn_refresh_tv_order_with_user(p_order BIGINT)
RETURNS void AS $$
BEGIN
    INSERT INTO tv_order_with_user (id, data)
    SELECT
        o.id,
        jsonb_build_object(
            'id',    o.id,
            'total', o.total,
            'user', jsonb_build_object(
                'id',       u.id,
                'username', u.username,
                'email',    u.email
            )
        )
    FROM tb_order o
    JOIN tb_user u ON u.pk_user = o.fk_user
    WHERE o.pk_order = p_order
    ON CONFLICT (id) DO UPDATE
        SET data = EXCLUDED.data, updated_at = now();
END;
$$ LANGUAGE plpgsql;

-- Trigger keeps the projection current as orders change.
CREATE TRIGGER trg_refresh_tv_order_with_user
AFTER INSERT OR UPDATE ON tb_order
FOR EACH ROW
EXECUTE FUNCTION fn_refresh_tv_order_with_user();
```

**Characteristics:**

- **Storage overhead:** the size of the pre-composed JSONB
- **Maintenance:** function/trigger-based refresh (automatic)
- **Performance:** fast reads (no join work at query time)
- **Staleness:** bounded by the refresh cadence
- **Index support:** JSONB GIN indexes for path searches

```python
@fraiseql.type(sql_source="tv_order_with_user", jsonb_column="data")
class OrderWithUser:
    id: ID
    total: float
    user: User                     # from the pre-composed JSONB
```

For an in-depth treatment of when to reach for `tv_*` and how to keep projections fresh, see the [tv table pattern](../architecture/database/tv-table-pattern.md) and the [view selection guide](../architecture/database/view-selection-guide.md).

---

## Part 4: PostgreSQL-Specific Strengths

FraiseQL v1 targets PostgreSQL exclusively, which lets it lean on capabilities that generic, lowest-common-denominator database layers cannot use. The architecture above is built directly on these:

**JSONB as the wire format.** Read views build their payload with `jsonb_build_object`, and FraiseQL serves exactly the requested GraphQL fields straight out of that `data` column. JSONB also supports rich indexing and containment operators:

```sql
CREATE TABLE tb_event (
    pk_event   BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    id         UUID NOT NULL DEFAULT gen_random_uuid(),
    data       JSONB NOT NULL,          -- native JSONB
    tags       TEXT[] NOT NULL DEFAULT '{}',   -- native array type
    status     public.event_status NOT NULL    -- custom enum type
);

-- GIN index over the JSONB document for fast containment/path queries.
CREATE INDEX idx_tb_event_data ON tb_event USING GIN(data);
```

```python
import fraiseql
from fraiseql.types import ID, JSON


@fraiseql.type(sql_source="v_event", jsonb_column="data")
class Event:
    id: ID
    data: JSON                     # maps to JSONB
    tags: list[str]                # maps to a PostgreSQL array
    status: str                    # maps to a PostgreSQL enum
```

**CTEs and window functions.** Read views can use common table expressions and window functions to express analytics-style shaping (running totals, rankings, partitioned aggregates) without leaving SQL.

**PostgreSQL functions for all writes.** Mutations call `fn_` functions, so transactional write logic, validation, and complex multi-table updates live in the database where they are atomic. See Part 5.

**`ltree` for hierarchies.** Tree-structured data (categories, org charts, threaded comments) can be modeled with the `ltree` extension and exposed via the `LTree` scalar (`from fraiseql.types import LTree`), with native ancestor/descendant operators.

**Rich indexing.** Beyond B-tree, PostgreSQL offers GIN (JSONB/arrays/full-text), GiST, and BRIN (large append-mostly tables) indexes—pick the right index per access pattern and the read views inherit the benefit.

Because there is a single supported database, FraiseQL never has to abstract these away or emulate them; the SQL you write is the SQL that runs.

---

## Part 5: CQRS — Reads vs. Writes

FraiseQL follows a Command/Query Responsibility Segregation split that maps cleanly onto PostgreSQL primitives.

### Reads (Queries)

`@fraiseql.query` resolvers call `db.find` / `db.find_one` against a `v_*` or `tv_*` view. The view's `data` JSONB is returned and shaped to exactly the requested GraphQL fields.

```python
@fraiseql.query
async def orders(info) -> list[Order]:
    db = info.context["db"]
    return await db.find("v_order")
```

### Writes (Mutations)

`@fraiseql.mutation` resolvers call PostgreSQL `fn_*` functions via `db.execute_function`. The function performs validation and the write inside a transaction, then returns JSONB describing success or failure. **All write business logic lives in PostgreSQL.**

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.input
class CreateUserInput:
    name: str
    email: str


@fraiseql.success
class CreateUserSuccess:
    user: User                     # @success auto-injects status/message/etc.


@fraiseql.error
class CreateUserError:
    message: str
    code: str = "VALIDATION_ERROR"


@fraiseql.mutation
async def create_user(
    info, input: CreateUserInput
) -> CreateUserSuccess | CreateUserError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_user",
        {"name": input.name, "email": input.email},
    )
    if not result.get("success"):
        return CreateUserError(message=result.get("message", "failed"))
    return CreateUserSuccess(user=User(**result["user"]))
```

The corresponding PostgreSQL function owns the write:

```sql
CREATE OR REPLACE FUNCTION fn_create_user(payload JSONB)
RETURNS JSONB AS $$
DECLARE
    v_id UUID;
BEGIN
    IF payload->>'email' IS NULL THEN
        RETURN jsonb_build_object('success', false, 'message', 'email is required');
    END IF;

    INSERT INTO tb_user (username, email)
    VALUES (payload->>'name', payload->>'email')
    RETURNING id INTO v_id;

    RETURN jsonb_build_object(
        'success', true,
        'user', (SELECT data FROM v_user WHERE id = v_id)
    );
END;
$$ LANGUAGE plpgsql;
```

The schema that wires all of this together is assembled **at application startup, in memory**—there are no generated files to ship or keep in sync.

---

## Part 6: Architecture Layers

### The Complete Picture

FraiseQL's database-centric design manifests in three layers:

```text
┌─────────────────────────────────────────────┐
│ Layer 2: AUTHORING (Your Code)              │
│ Python + @fraiseql decorators               │
│                                             │
│ @fraiseql.type(sql_source="v_user")         │
│ class User:                                 │
│   id: ID                                    │
│   username: str                             │
│                                             │
│ @fraiseql.query / @fraiseql.mutation        │
└─────────────────────────────────────────────┘
           │
           │ create_fraiseql_app(...) builds the
           │ GraphQL schema in memory at startup
           ▼
┌─────────────────────────────────────────────┐
│ Layer 1: RUNTIME (FastAPI process)          │
│                                             │
│ - Validate the request against the schema   │
│ - Authorize (declarative rules)             │
│ - Reads:  db.find / db.find_one on v_/tv_   │
│ - Writes: db.execute_function on fn_        │
│ - Shape JSONB to the requested fields       │
│   (the optional fraiseql_rs extension        │
│    accelerates this on the hot path)        │
└─────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│ Layer 0: POSTGRESQL (Source of Truth)       │
│                                             │
│ Write side:                                 │
│   - tb_* normalized tables (DBA-owned)      │
│   - fn_* functions (mutation write logic)   │
│                                             │
│ Read side:                                  │
│   - v_*  logical read views                 │
│   - tv_* table-backed projections           │
│                                             │
│ The single source of truth for all data     │
└─────────────────────────────────────────────┘
```

The optional Rust extension (`fraiseql_rs`) is not a separate layer or data plane—it simply speeds up JSON transformation inside Layer 1.

---

## Part 7: Consequences of Database-Centric Design

### Immediate Benefits

**1. Clarity**

- What you see is what you get
- Read views and functions define the API surface
- No hidden resolver logic

**2. Performance**

- PostgreSQL plans and optimizes queries
- N+1 reads avoided by composing nested data in views
- `tv_*` projections turn heavy nested reads into single-row lookups

**3. Consistency**

- Single source of truth
- No cache invalidation complexity
- Database constraints enforced; ACID transactions guaranteed

**4. Security**

- All writes flow through `fn_*` functions, validated in the database
- Row-level security available in PostgreSQL
- Parameterized queries prevent SQL injection

**5. Debuggability**

- Look at the view or function, understand the query
- No hidden resolver logic
- Performance bottlenecks are visible in database metrics

---

### Design Constraints

**1. Schema Must Be Structured**

- Requires clear database design (normalization, keys, constraints)
- Not suitable for unstructured/document-only data

**2. PostgreSQL Must Be the Primary Data Source**

- Multi-source federation is limited
- External REST/GraphQL sources are secondary at best

**3. Database Expertise Required**

- The team must understand SQL, indexes, views, functions, and triggers
- DBA involvement helps for non-trivial projections
- Schema design quality directly affects API performance

**4. Reads Live in Views, Writes Live in Functions**

- Read shaping is done in `v_*`/`tv_*` views
- Write logic is done in `fn_*` functions
- This discipline is the source of FraiseQL's simplicity—embrace it

---

## Summary: The Database-Centric Philosophy

FraiseQL makes a deliberate choice:

**Core assumption:** Your GraphQL API is a **PostgreSQL access interface**, not a general-purpose API aggregator.

**Implementation:**

- Reads via `v_*` logical views and `tv_*` table-backed projections (JSONB payloads)
- Writes via `fn_*` PostgreSQL functions called through `db.execute_function`
- Trinity identifier pattern: hidden `pk_` BIGINT, public `id` UUID, optional `identifier` slug
- Schema built in memory at app startup—no compile step, no artifacts

**Consequences:**

- Simpler architecture (little to no custom resolver code)
- Better performance (database optimization + pre-composed projections)
- Higher consistency (single source of truth)
- Easier debugging (clear views/functions + metrics)
- Less flexible (cannot easily add external APIs)
- Requires database expertise and a structured schema

**Best for:** Data-centric applications on PostgreSQL with clear schemas and performance requirements.

**Not suitable for:** Heavily federated systems, unstructured data, dynamic per-request schemas, or non-PostgreSQL databases.

---

## Next Steps

Now that you understand FraiseQL's database-centric approach:

1. **Get hands-on** → [Quickstart](../getting-started/quickstart.md) and [First Hour](../getting-started/first-hour.md)
2. **Review the vocabulary** → [Concepts Glossary](../core/concepts-glossary.md) and [Naming Patterns](../reference/naming-patterns.md)
3. **Learn design principles** → [Design Principles](./04-design-principles.md)
4. **Compare alternatives** → [Comparisons](./05-comparisons.md)

---

## Related Topics

- [Core Concepts](./02-core-concepts.md) — database vocabulary and the runtime model
- [Design Principles](./04-design-principles.md) — the guiding principles of FraiseQL
- [Type System](./09-type-system.md) — scalars and type mapping
- [Error Handling & Validation](./10-error-handling-validation.md) — success/error result types
- [Performance Characteristics](./12-performance-characteristics.md) — what to expect at runtime
- [tv Table Pattern](../architecture/database/tv-table-pattern.md) — designing table-backed projections
- [View Selection Guide](../architecture/database/view-selection-guide.md) — choosing `v_*` vs `tv_*`

---

## Key Takeaways

- **FraiseQL treats PostgreSQL as the primary application interface.**
- **Two read view types** cover most needs:
  - `v_*` logical reads (computed on read, real-time)
  - `tv_*` table-backed projections (pre-composed JSONB, fast nested reads)
- **All writes go through `fn_*` PostgreSQL functions** called via `db.execute_function`.
- **The schema is built in memory at startup**—there is no compile step or artifact.
- **PostgreSQL-only by design**, which lets FraiseQL exploit JSONB, CTEs, functions, `ltree`, and rich indexing directly.
- **Trade-off: simplicity for unconstrained flexibility** (not suited to heavily federated systems).
