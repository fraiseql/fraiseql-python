---
title: "FraiseQL Anti-Patterns: What NOT to Do"
description: This document catalogs anti-patterns—designs that seem reasonable but lead to problems in practice. Learning what NOT to do is as important as learning what TO do.
keywords: ["anti-patterns", "design", "scalability", "performance", "n+1", "pagination", "postgresql", "views"]
tags: ["documentation", "reference"]
---

# FraiseQL Anti-Patterns: What NOT to Do

**Audience:** Developers, architects, technical leads

---

## Executive Summary

This document catalogs anti-patterns—designs that seem reasonable but lead to
problems in practice. Learning what NOT to do is as important as learning what
TO do.

FraiseQL v1 is a **Python runtime GraphQL framework for PostgreSQL**. You
declare types and resolvers with decorators (`@fraiseql.type`,
`@fraiseql.query`, `@fraiseql.mutation`); the schema is built in memory at app
startup and served over FastAPI. The architecture is CQRS:

- **Reads** come from PostgreSQL **read views** (`v_`) or table-backed
  projection views (`tv_`) via `db.find` / `db.find_one`.
- **Writes** run through PostgreSQL **functions** (`fn_`) via
  `db.execute_function` — all write business logic lives in the database.

Most of the anti-patterns below boil down to one root cause: *fighting the
CQRS model* by pushing logic into the Python layer that belongs in your views
and functions.

Each anti-pattern includes:

- **Problem**: Why it's wrong
- **Symptoms**: How you'll know you're doing it
- **Solution**: Correct approach
- **Cost of ignoring**: Real consequences

---

## 1. Query & Mutation Anti-Patterns

### 1.1 Deep Nested Queries (N+1 Problem)

**Anti-pattern**: Resolving nested relationships one row at a time

```graphql
# ❌ WRONG: Dangerous nesting depth
query GetUserWithEverything {
  user(id: "user-1") {
    id
    name
    posts {                    # 1 query
      id
      comments {              # 1 query per post (N+1!)
        id
        author {              # 1 query per comment (N+1+1!)
          id
          name
        }
      }
    }
  }
}
```

**Problem:**

- For 10 posts with 5 comments each = 50+ database round trips
- Explosion gets worse with deeper nesting
- Can time out or overload the database

**Symptoms:**

- Queries time out despite a small result set
- Database CPU spikes on a single GraphQL request
- Per-field resolvers each issue their own `SELECT`

**Solution A — compose nesting inside the view.** In FraiseQL, the natural fix
is to build the nested shape once in your `v_`/`tv_` view's `data` JSONB, so a
single `db.find` returns the whole tree:

```sql
-- A read view that pre-composes posts (and their comment counts) as JSONB.
CREATE VIEW v_user AS
SELECT
    u.id,                                      -- public UUID (the GraphQL id)
    jsonb_build_object(
        'id',    u.id,
        'name',  u.name,
        'posts', (
            SELECT jsonb_agg(jsonb_build_object(
                'id',           p.id,
                'title',        p.title,
                'commentCount', (SELECT count(*) FROM tb_comment c
                                 WHERE c.fk_post = p.pk_post)
            ))
            FROM tb_post p
            WHERE p.fk_user = u.pk_user
        )
    ) AS data
FROM tb_user u;
```

**Solution B — batch the field with a dataloader.** When a field genuinely
needs a separate resolver, use `@fraiseql.dataloader_field` so FraiseQL batches
the lookups into one query instead of N:

```python
import fraiseql

@fraiseql.dataloader_field
async def author(info, comment: Comment) -> User:
    # Called once per comment, but FraiseQL collects the keys and issues a
    # single batched load — turning N+1 queries into 1.
    db = info.context["db"]
    return await db.find_one("v_user", id=comment.author_id)
```

**Solution C — cap depth and page nested lists.** Keep request shapes sane and
always paginate nested collections:

```graphql
# ✅ CORRECT: Controlled nesting, paginated nested lists, aggregates not joins
query GetUserWithPosts {
  user(id: "user-1") {
    id
    name
    posts(limit: 20) {
      id
      title
      commentCount  # Aggregated in the view, not nested + counted in app
    }
  }
}
```

**Cost of ignoring:** unpredictable latency, database saturation under load, and
GraphQL requests that work in dev but melt in production.

---

### 1.2 Unbounded Result Sets

**Anti-pattern**: Queries (and views) without a `LIMIT`

```graphql
# ❌ WRONG: No limit, returns every row in the view
query GetAllUsers {
  users {
    id
    name
    email
  }
}
```

```python
# ❌ WRONG: resolver hands the whole view back, no bound
@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user")   # could be millions of rows
```

**Problem:**

- Returns the entire table behind the view
- Memory exhaustion and timeouts
- Huge response payloads saturate the network

**Symptoms:**

- Server runs out of memory
- Client connection hangs
- Database and app latency spike together

**Solution**: Always paginate — accept `limit`/`offset` (or cursor args) and
push them into the read:

```python
# ✅ CORRECT: bounded read with a sane default cap
@fraiseql.query
async def users(info, limit: int = 50, offset: int = 0) -> list[User]:
    db = info.context["db"]
    limit = min(limit, 200)   # hard ceiling regardless of client request
    return await db.find("v_user", limit=limit, offset=offset)
```

For client-driven paging, expose a cursor connection:

```graphql
# ✅ CORRECT: paginated with a cursor connection
query GetUsers($first: Int!, $after: String) {
  users(first: $first, after: $after) {
    edges {
      cursor
      node { id name email }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

**Cost of ignoring:** a single innocent-looking query can OOM the process or
stall every other request sharing the connection pool.

---

### 1.3 Business Logic in Python Instead of `fn_` Functions

**Anti-pattern**: Implementing write logic (validation, derived state,
multi-row updates) in the Python resolver instead of a PostgreSQL function

```python
# ❌ WRONG: mutation logic lives in Python, runs many round trips,
#          and is not transactional
@fraiseql.mutation
async def create_order(info, input: CreateOrderInput) -> CreateOrderSuccess:
    db = info.context["db"]

    # Validate by hand, in the app
    customer = await db.find_one("v_customer", id=input.customer_id)
    if customer is None:
        return CreateOrderError(message="unknown customer")

    # Several separate writes — not atomic, racy
    order = await db.execute_function("fn_insert_order_row", {...})
    for line in input.lines:
        await db.execute_function("fn_insert_order_line", {...})
    await db.execute_function("fn_recompute_order_total", {"id": order["id"]})

    return CreateOrderSuccess(order=Order(**order))
```

**Problem:**

- Multi-step writes are not atomic — a failure midway leaves partial state
- Validation rules drift from the database's own constraints
- Every step is a network round trip; latency stacks up
- The same logic gets re-implemented (inconsistently) in every caller

**Symptoms:**

- Resolvers are long and full of `if`/`await db...` chains
- Bugs where half an operation "took" and half didn't
- Business rules enforced in Python but missing at the SQL layer

**Solution**: Put the write logic in one `fn_` PostgreSQL function. The resolver
just validates the shape of the input and calls it; the function does
validation, the writes, and returns a JSONB result in a single transaction:

```python
# ✅ CORRECT: resolver is thin; the database owns the write
@fraiseql.mutation
async def create_order(
    info, input: CreateOrderInput
) -> CreateOrderSuccess | CreateOrderError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_order",
        {"customer_id": input.customer_id, "lines": input.lines},
    )
    if not result.get("success"):
        return CreateOrderError(
            message=result.get("message", "failed"),
            code=result.get("code", "VALIDATION_ERROR"),
        )
    return CreateOrderSuccess(order=Order(**result["order"]))
```

```sql
-- fn_create_order does the validation + all writes atomically and returns JSONB.
CREATE FUNCTION fn_create_order(p_customer_id uuid, p_lines jsonb)
RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_order_id uuid;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM tb_customer WHERE id = p_customer_id) THEN
        RETURN jsonb_build_object('success', false,
                                  'code', 'UNKNOWN_CUSTOMER',
                                  'message', 'unknown customer');
    END IF;

    INSERT INTO tb_order (fk_customer)
    SELECT pk_customer FROM tb_customer WHERE id = p_customer_id
    RETURNING id INTO v_order_id;

    INSERT INTO tb_order_line (fk_order, sku, qty)
    SELECT (SELECT pk_order FROM tb_order WHERE id = v_order_id),
           line->>'sku', (line->>'qty')::int
    FROM jsonb_array_elements(p_lines) AS line;

    RETURN jsonb_build_object('success', true,
                              'order', (SELECT data FROM v_order WHERE id = v_order_id));
END;
$$;
```

**Cost of ignoring:** non-atomic writes, duplicated and divergent business
rules, and slow mutations that fan out into many round trips. See
[design principles](../../foundation/04-design-principles.md) for the rationale
behind keeping write logic in the database.

---

### 1.4 Synchronous Blocking Side Effects in Resolvers

**Anti-pattern**: Block resolver completion on a slow external call

```python
# ❌ WRONG: mutation waits on an external service inside the request path
@fraiseql.mutation
async def create_order(
    info, input: CreateOrderInput
) -> CreateOrderSuccess | CreateOrderError:
    db = info.context["db"]
    result = await db.execute_function("fn_create_order", {...})

    # Blocks the whole request on third-party I/O
    email_service.send_confirmation(result["order"]["id"])   # 2 seconds!
    analytics.log_event("order_created", result["order"])    # 1 second!

    return CreateOrderSuccess(order=Order(**result["order"]))
```

**Problem:**

- Request latency now includes every side-effect's latency
- A slow or failing third party degrades or breaks the mutation
- The user waits on work that has nothing to do with the response

**Symptoms:**

- Mutations taking seconds instead of tens of milliseconds
- Outages in a notification/analytics provider taking down writes
- Tail latency dominated by external calls

**Solution**: Get the durable write done in PostgreSQL, then dispatch side
effects out of the request path. The most robust approach keeps the dispatch
*inside the transaction's reach* by recording intent in the database (an outbox
row written by `fn_create_order`) and draining it with a separate worker:

```sql
-- fn_create_order also enqueues the side effect transactionally.
INSERT INTO tb_outbox (kind, payload)
VALUES ('order_confirmation',
        jsonb_build_object('order_id', v_order_id));
```

A background worker (a separate process, not the GraphQL request) reads
`tb_outbox` and performs the email/analytics calls with retries. The resolver
returns as soon as the database commits:

```python
# ✅ CORRECT: the request path only does the durable write
@fraiseql.mutation
async def create_order(
    info, input: CreateOrderInput
) -> CreateOrderSuccess | CreateOrderError:
    db = info.context["db"]
    result = await db.execute_function("fn_create_order", {...})
    if not result.get("success"):
        return CreateOrderError(message=result.get("message", "failed"))
    return CreateOrderSuccess(order=Order(**result["order"]))
```

If you genuinely must dispatch from the process, hand the work to your own
worker/queue — never `await` a slow third party inside the resolver, and never
fire untracked background tasks whose failures vanish silently.

**Cost of ignoring:** user-visible latency tied to systems you don't control,
and side effects that are either blocking *or* silently dropped on failure.

---

## 2. Authorization Anti-Patterns

### 2.1 Scattered Authorization in Resolver Code

**Anti-pattern**: Re-checking permissions ad hoc in every resolver

```python
# ❌ WRONG: authorization scattered and easy to forget
@fraiseql.query
async def get_user(info, id: ID) -> User | None:
    db = info.context["db"]
    user = await db.find_one("v_user", id=id)

    current = info.context["current_user"]
    if user.created_by != current.id and not current.is_admin:
        raise PermissionError("Not authorized")
    return user

@fraiseql.mutation
async def delete_user(info, id: ID) -> bool:
    # A *different* check, written by hand, in a different place
    db = info.context["db"]
    current = info.context["current_user"]
    target = await db.find_one("v_user", id=id)
    if target.id != current.id and not current.is_admin:
        raise PermissionError("Not authorized")
    await db.execute_function("fn_delete_user", {"id": id})
    return True
```

**Problem:**

- Rules are duplicated and drift apart between operations
- Impossible to audit — there is no single place that says "who can do what"
- Easy to forget a check on a new resolver (a silent security hole)

**Symptoms:**

- Inconsistent behavior between similar operations
- Security reviews keep finding missing checks
- Accidental exposure of records a user shouldn't see

**Solution**: Declare authorization once via an `Authorizer` and attach it to
the operation, instead of re-implementing checks inline:

```python
# ✅ CORRECT: one authorizer, attached declaratively
from fraiseql import Authorizer

owner_or_admin = OwnerOrAdminAuthorizer()   # implements Authorizer

@fraiseql.query(authorizer=owner_or_admin)
async def get_user(info, id: ID) -> User | None:
    db = info.context["db"]
    return await db.find_one("v_user", id=id)

@fraiseql.mutation
async def delete_user(
    info, input: DeleteUserInput
) -> DeleteUserSuccess | DeleteUserError:
    # The same rule is enforced by fn_delete_user as well — see below.
    db = info.context["db"]
    result = await db.execute_function("fn_delete_user", {"id": input.id})
    if not result.get("success"):
        return DeleteUserError(message=result.get("message", "forbidden"))
    return DeleteUserSuccess(id=input.id)
```

Defense in depth: enforce the *data* boundary in PostgreSQL too. `fn_delete_user`
should refuse the operation (and your views should filter by tenant/owner) so a
missed check in the app cannot leak data. Field-level authorization is available
via `@fraiseql.type(..., authorize_fields=...)` and the
`@fraiseql.field`/`@fraiseql.dataloader_field` resolver path.

> **Resolver-bypass note:** authorization attached to a resolver only runs when
> that resolver runs. Cached or batched paths can shortcut the per-field
> resolver, so always enforce the authoritative boundary in the database
> (`fn_` functions and tenant-scoped views), not in the resolver alone.

**Cost of ignoring:** an unauditable patchwork of checks, one forgotten `if`
away from a breach.

---

### 2.2 Trusting Client-Provided Identity or Role

**Anti-pattern**: Reading the caller's role from GraphQL input

```python
# ❌ WRONG: the client tells you their role (and can lie)
@fraiseql.query
async def admin_panel(info, role: str) -> AdminPanel:
    if role == "admin":               # forgeable!
        return build_admin_panel(info)
    raise PermissionError()
```

**Problem:**

- Anyone can send `role: "admin"` in the variables
- The security boundary is on the client (i.e. nonexistent)
- Privilege escalation is trivial

**Symptoms:**

- Users reaching data their role shouldn't allow
- Audit logs showing unauthorized access
- A breach waiting to happen

**Solution**: Derive identity and role from the verified request context (a
validated JWT or session), never from operation arguments:

```python
# ✅ CORRECT: identity comes from the verified context, not the input
@fraiseql.query(authorizer=AdminOnlyAuthorizer())
async def admin_panel(info) -> AdminPanel:
    # info.context["current_user"] was populated from a verified token by
    # auth middleware; the client cannot forge it.
    return build_admin_panel(info)
```

**Cost of ignoring:** any user can impersonate any role; there is effectively no
access control at all.

---

## 3. Caching Anti-Patterns

FraiseQL v1 ships a real PostgreSQL-backed result cache
(`cached_query`, `ResultCache` / `CachedRepository`, with `CascadeRule` and
`setup_auto_cascade_rules` for invalidation). The anti-patterns are about using
it carelessly.

### 3.1 Caching Without Invalidation

**Anti-pattern**: Cache query results but never invalidate them on write

```python
# ❌ WRONG: a long TTL with no invalidation path
from fraiseql.caching import cached_query

@fraiseql.query
async def product(info, id: ID) -> Product | None:
    db = info.context["db"]
    return await cached_query(
        db, "v_product", id=id, ttl=3600,   # 1 hour
    )
```

```graphql
# A mutation updates the price...
mutation { updateProduct(input: {id: "p-1", price: 150}) { product { price } } }
# ...but nothing invalidates product:p-1, so queries serve the stale price
# for up to an hour.
```

**Problem:**

- Stale results served after a write
- Reads and writes disagree
- Users see old data and lose trust in the API

**Symptoms:**

- "I updated it but it still shows the old value"
- Cache hits returning superseded data
- Inconsistency that "fixes itself" after the TTL expires

**Solution**: Tie invalidation to the write with cascade rules so that mutating
a `tv_`/`v_` source invalidates the dependent cached queries automatically:

```python
# ✅ CORRECT: register cascade rules so writes invalidate dependent reads
from fraiseql.caching import ResultCache, CascadeRule, setup_auto_cascade_rules

cache = ResultCache(...)
setup_auto_cascade_rules(cache)          # derive rules from the schema, or:
cache.add_cascade_rule(
    CascadeRule(source="tv_product", invalidates=["v_product", "v_featured"])
)
```

When `fn_update_product` writes the product, the cascade rule clears the cached
`v_product` and `v_featured` entries. See
[state management](./state-management.md) for the full caching/invalidation
model.

**Cost of ignoring:** the cache becomes a correctness bug, not a performance
win.

---

### 3.2 Caching Sensitive Data Carelessly

**Anti-pattern**: Cache PII or per-tenant data under a guessable, unscoped key

```python
# ❌ WRONG: caches email (PII) under a key with no tenant scope
cache.set(f"user:{user_id}", user_with_email)
```

**Problem:**

- PII lingers in a shared cache outside your access controls
- In a multi-tenant system, an unscoped key can collide or leak across tenants
- "Right to be forgotten" is hard when copies live in cache

**Symptoms:**

- Audits finding PII in cache storage
- Privacy/compliance violations
- One tenant's data surfacing for another

**Solution**: Cache only what is safe to share, scope keys by tenant, and keep
sensitive fields on a short or no TTL:

```python
# ✅ CORRECT: cache public projection, tenant-scoped key, sensitive data excluded
cache.set(f"tenant:{tenant_id}:user:{user_id}", {
    "id": user_id,
    "name": "Alice",
    "avatar_url": "https://...",
    # no email, no phone, no tokens
})
```

The cleanest version is to keep sensitive columns out of the cached `v_`/`tv_`
view's `data` JSONB entirely, and never put internal keys (`pk_`/`fk_`) anywhere
near the cache.

**Cost of ignoring:** a privacy incident and a cache you can't safely purge.

---

## 4. Performance Anti-Patterns

### 4.1 Premature Optimization

**Anti-pattern**: Optimize before measuring

```python
# ❌ WRONG: hand-rolled offset batching, never profiled
@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    out: list[User] = []
    for i in range(0, 100_000, 1000):
        out.extend(await db.find("v_user", limit=1000, offset=i))
    return out
# Offset pagination is O(n) in the offset — this is *slower*, not faster,
# and it still returns an unbounded result set (see 1.2).
```

**Problem:**

- Effort spent on the wrong bottleneck
- More complex code, no measured benefit
- The "optimization" can be slower than the naive version

**Symptoms:**

- Changes that add complexity without moving the numbers
- Optimizations made on a hunch, not a profile

**Solution**: Measure first. In FraiseQL the bottleneck is almost always the
SQL behind a view, so look there — usually it's a missing index:

```sql
-- Profile (EXPLAIN ANALYZE the view query) shows a seq scan on the filter column.
CREATE INDEX idx_user_status ON tb_user (status);
-- One line; 500ms -> 50ms. No application change needed.
```

See [performance characteristics](../../foundation/12-performance-characteristics.md)
for what to measure and the expected shapes of fast vs slow queries.

**Cost of ignoring:** time burned on non-bottlenecks while the real one (an
index, or an over-fetching view) goes untouched.

---

### 4.2 Ignoring Indexes and Over-Fetching in Views

**Anti-pattern**: Building wide views that scan whole tables and select columns
nobody asked for

```sql
-- ❌ WRONG: builds a fat data blob and filters on an unindexed column
CREATE VIEW v_order AS
SELECT
    o.id,
    jsonb_build_object(
        'id',        o.id,
        'status',    o.status,
        'lines',     (SELECT jsonb_agg(...) FROM tb_order_line ...),
        'history',   (SELECT jsonb_agg(...) FROM tb_order_event ...),  -- huge, rarely read
        'rawAudit',  o.audit_blob                                      -- never requested
    ) AS data
FROM tb_order o;

SELECT data FROM v_order WHERE data->>'status' = 'OPEN';   -- can't use an index
```

**Problem:**

- The view materializes far more JSONB than any query selects
- Filtering on a JSONB expression bypasses ordinary column indexes
- Sequential scans on large tables for routine queries

**Symptoms:**

- Slow reads that `EXPLAIN ANALYZE` shows as seq scans
- High memory churn building JSONB that's immediately discarded
- A "simple" list query that's mysteriously expensive

**Solution**: Keep filterable columns as real, indexed columns on the view;
build heavy sub-objects only where they're actually needed (or in a dedicated
`tv_` projection refreshed out of band):

```sql
-- ✅ CORRECT: expose an indexed status column; keep the heavy bits out of the list view
CREATE VIEW v_order AS
SELECT
    o.id,
    o.status,                                  -- real column → indexable filter
    jsonb_build_object('id', o.id, 'status', o.status, 'total', o.total) AS data
FROM tb_order o;

CREATE INDEX idx_order_status ON tb_order (status);
-- Order history / audit live in a separate detail view fetched only when asked for.
```

**Cost of ignoring:** every list query pays for data it throws away, and the
database can't use indexes for the filters that matter.

---

## 5. Data Modeling Anti-Patterns

### 5.1 Storing Derived Data Without Updating It

**Anti-pattern**: Compute a derived value once and store it as a plain column
that nothing keeps current

```sql
-- ❌ WRONG: score is computed at insert and then drifts
CREATE TABLE tb_user (
    pk_user bigint GENERATED ALWAYS AS IDENTITY,
    id      uuid DEFAULT gen_random_uuid(),
    name    text,
    score   int      -- set once, never recomputed as activity accrues
);
```

**Problem:**

- The stored value diverges from reality over time
- Readers assume it's current; it isn't
- No signal that it's stale

**Symptoms:**

- Aggregates and scores that don't match the underlying rows
- "The number is wrong" reports that can't be reproduced from the data
- Inconsistency between the column and a fresh `COUNT(*)`

**Solution**: Compute on read in a view, or maintain it in the database with a
trigger or projection table — never leave it to chance:

```sql
-- Option A: compute on read in the view's data JSONB
CREATE VIEW v_user AS
SELECT
    u.id,
    jsonb_build_object(
        'id',    u.id,
        'name',  u.name,
        'score', (SELECT count(*) FROM tb_activity a WHERE a.fk_user = u.pk_user)
    ) AS data
FROM tb_user u;

-- Option B: maintain it on write with a trigger (when reads must be cheap)
CREATE FUNCTION fn_bump_user_score() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE tb_user
       SET score = (SELECT count(*) FROM tb_activity WHERE fk_user = NEW.fk_user)
     WHERE pk_user = NEW.fk_user;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_bump_user_score
AFTER INSERT ON tb_activity
FOR EACH ROW EXECUTE FUNCTION fn_bump_user_score();
```

For heavy aggregates, a `tv_` projection table refreshed by a function/trigger
is the table-backed version of the same idea. See the
[aggregation model](../analytics/aggregation-model.md) for derived-data
patterns and FraiseQL's runtime auto-aggregation.

**Cost of ignoring:** silently wrong numbers that erode trust and are painful to
reconcile after the fact.

---

## 6. Concurrency Anti-Patterns

### 6.1 Updating Without a Version (or Conditional) Check

**Anti-pattern**: Read-then-write without guarding against a concurrent update

```text
# ❌ WRONG: lost-update race
Tx 1: read user (version 1)
Tx 2: update user, version 1 -> 2
Tx 1: update user using its stale copy, clobbering Tx 2's change
```

**Problem:**

- Lost updates: the last writer silently overwrites the others
- No conflict is detected or reported
- Data corruption that's invisible until someone notices missing changes

**Symptoms:**

- "My edit disappeared"
- Fields reverting to older values
- Non-reproducible inconsistencies under load

**Solution**: Make the write conditional inside the `fn_` function — increment a
`version` column and update only when the version still matches, returning a
conflict result when it doesn't:

```sql
-- ✅ CORRECT: optimistic concurrency enforced in the database
CREATE FUNCTION fn_update_user_email(p_id uuid, p_email text, p_version int)
RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_rows int;
BEGIN
    UPDATE tb_user
       SET email = p_email,
           version = version + 1
     WHERE id = p_id
       AND version = p_version;      -- only if nobody else moved it
    GET DIAGNOSTICS v_rows = ROW_COUNT;

    IF v_rows = 0 THEN
        RETURN jsonb_build_object('success', false, 'code', 'CONFLICT',
                                  'message', 'version mismatch, refresh and retry');
    END IF;
    RETURN jsonb_build_object('success', true);
END;
$$;
```

The resolver passes the client's `version` through and surfaces the conflict as
a typed error result. See the
[consistency model](../reliability/consistency-model.md) for transaction and
concurrency guarantees.

**Cost of ignoring:** silent data loss under concurrency that's nearly
impossible to debug after the fact.

---

## 7. Subscription Anti-Patterns

FraiseQL v1 subscriptions are real and WebSocket-based: `@fraiseql.subscription`
decorates an **async generator** whose yielded values are streamed to the
client. The event source is *your* generator — it can be backed by PostgreSQL
`LISTEN/NOTIFY`, polling, or an external stream.

### 7.1 Subscribing to Everything and Filtering on the Client

**Anti-pattern**: Stream all events and let the client throw most away

```graphql
# ❌ WRONG: subscribe to all events, filter in the browser
subscription OnAllEvents {
  events { type timestamp data }
}
```

**Problem:**

- The server pushes events every client doesn't care about
- Bandwidth and client CPU wasted on filtering
- Slow consumers fall behind and connections drop

**Symptoms:**

- WebSocket disconnects under event volume
- High network usage for a handful of relevant events
- Client-side filtering logic that mirrors what the server already knows

**Solution**: Filter at the source — take arguments in the subscription
generator and only `yield` matching events (FraiseQL also provides a
`subscription_filter` helper):

```python
# ✅ CORRECT: filter server-side; only matching events leave the server
from collections.abc import AsyncGenerator

@fraiseql.subscription
async def order_created(info, customer_id: UUID) -> AsyncGenerator[Order, None]:
    async for order in watch_orders():
        if order.customer_id == customer_id:
            yield order
```

**Cost of ignoring:** dropped connections and wasted bandwidth that gets worse
as traffic grows.

---

### 7.2 Ignoring Connection Liveness

**Anti-pattern**: Assume a WebSocket subscription stays healthy forever

```python
# ❌ WRONG: no liveness handling; a dead connection looks "subscribed"
subscription = await client.subscribe(query)
async for event in subscription:
    process_event(event)   # silently stops if the socket is half-open
```

**Problem:**

- A half-open connection delivers no events but looks connected
- The client believes it's live and misses updates
- No recovery without a manual refresh

**Symptoms:**

- A subscription that's "active" but quietly stops updating
- Users unaware they've missed events
- Reconnects only after someone notices

**Solution**: Use the GraphQL-over-WebSocket transport's keepalive
(`graphql-transport-ws` ping/pong) and reconnect on missed pongs. On the server,
FraiseQL's `WebSocketConnection` / `SubscriptionManager` handle the protocol;
on the client, enable ping and re-subscribe on disconnect:

```python
# ✅ CORRECT: client monitors liveness and reconnects
subscription = await client.subscribe(query, keepalive=30)

async def watch_liveness():
    while subscription.is_active:
        if time.monotonic() - subscription.last_message > 60:
            await subscription.reconnect()
        await asyncio.sleep(10)
```

**Cost of ignoring:** users silently stop receiving real-time updates and don't
find out until it matters.

---

## 8. Testing Anti-Patterns

### 8.1 Testing Behavior but Skipping Authorization

**Anti-pattern**: Test the happy path and never test who is allowed to do it

```python
# ❌ WRONG: only asserts the result, never the access boundary
async def test_get_user():
    result = await run_query(GET_USER, variables={"id": "user-1"})
    assert result.data["user"]["name"] == "Alice"
    # No test that a different user is rejected!
```

**Problem:**

- Authorization regressions sail through the test suite
- A removed or broken check is caught only in production
- The security boundary is the least-tested part of the system

**Symptoms:**

- Green tests, but real users hit (or bypass) access errors
- Security reviews finding untested authorization paths

**Solution**: Test both the allowed and the denied case explicitly, with the
caller identity coming from context (as it does in production):

```python
# ✅ CORRECT: assert both the grant and the denial
async def test_get_user_owner_allowed():
    result = await run_query(GET_USER, current_user="user-1",
                             variables={"id": "user-1"})
    assert result.data["user"]["name"] == "Alice"

async def test_get_user_other_denied():
    result = await run_query(GET_USER, current_user="user-1",
                             variables={"id": "user-2"})
    assert result.errors[0].extensions["code"] == "FORBIDDEN"

async def test_delete_user_non_owner_denied():
    result = await run_mutation(DELETE_USER, current_user="user-1",
                                variables={"input": {"id": "user-2"}})
    assert result.data["deleteUser"]["__typename"] == "DeleteUserError"
```

Also test the database boundary: a `fn_` function or tenant-scoped view should
refuse a forbidden operation even if the resolver check were removed.

**Cost of ignoring:** the most security-critical behavior is the only behavior
nobody verifies.

---

## 9. Operational Anti-Patterns

### 9.1 Skipping Health Checks on Deploy

**Anti-pattern**: Route traffic to a new instance before it can actually serve
requests

```text
# ❌ WRONG: traffic shifts the moment the process starts
1. Start new app process
2. Load balancer immediately routes to it
3. ...but startup (schema build, DB pool warm-up) isn't done
4. First requests fail or hang
```

The FraiseQL schema is built **in memory at startup** from your decorators and
the live database connection — there is no compiled artifact to ship or version.
What can differ between instances is the *running code* and the *database it
points at*, so an instance is only ready once it has built its schema and
connected.

**Problem:**

- Requests hit an instance that isn't finished starting
- Errors during the warm-up window
- Confusing "works on one pod, fails on another" reports

**Symptoms:**

- Spikes of errors right after each deploy
- Failures correlated with newly-added instances
- Intermittent failures behind a load balancer

**Solution**: Gate traffic on a readiness check, and roll instances so old ones
keep serving until new ones are ready and pointed at a compatible database:

```text
# ✅ CORRECT: ready-gated rollout
1. Start new app process (builds schema, warms the connection pool)
2. Readiness probe passes only after startup completes
3. Load balancer routes to it; an old instance is drained
4. Apply DB migrations before/with the rollout so views/functions are compatible
```

**Cost of ignoring:** every deploy produces a burst of user-facing errors and
flaky, instance-dependent behavior.

---

## Summary: Anti-Pattern Checklist

Before shipping code, check:

- ❌ Per-row nested resolvers? (compose in the view or use `@fraiseql.dataloader_field`)
- ❌ Unbounded result sets? (always paginate, with a hard ceiling)
- ❌ Write logic in Python? (put it in a `fn_` function, atomically)
- ❌ Blocking side effects in resolvers? (use an outbox / out-of-band worker)
- ❌ Authorization scattered in resolvers? (declare an `Authorizer`; enforce in the DB too)
- ❌ Trusting client-provided role/identity? (derive it from the verified context)
- ❌ Caching without invalidation? (use `CascadeRule` / `setup_auto_cascade_rules`)
- ❌ Caching sensitive data carelessly? (scope keys, exclude PII)
- ❌ Optimizing before profiling? (measure the SQL; usually it's an index)
- ❌ Filterable data buried in JSONB? (keep indexed columns; trim the view)
- ❌ Derived data stored and forgotten? (compute in a view, or maintain via trigger)
- ❌ Writes without a version check? (conditional update in the `fn_` function)
- ❌ Subscriptions that send everything? (filter in the async generator)
- ❌ No connection-liveness handling? (keepalive + reconnect)
- ❌ Tests that skip authorization? (test both grant and denial)
- ❌ Routing traffic before readiness? (gate on a health check)

---

Learn from others' mistakes. Avoid these patterns and your FraiseQL application
will be safer, faster, and far easier to reason about.

## Related Documentation

- [State management](./state-management.md) — caching and invalidation model
- [Error handling model](../reliability/error-handling-model.md)
- [Consistency model](../reliability/consistency-model.md)
- [View selection guide](../database/view-selection-guide.md) — `v_` vs `tv_` reads
- [Aggregation model](../analytics/aggregation-model.md)
- [Design principles](../../foundation/04-design-principles.md)
- [Performance characteristics](../../foundation/12-performance-characteristics.md)
