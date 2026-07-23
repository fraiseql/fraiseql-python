---
title: Common Gotchas & Pitfalls
description: Learn from common mistakes and pitfalls when using FraiseQL. Each gotcha includes diagnosis steps and solutions.
keywords: ["debugging", "implementation", "best-practices", "deployment", "tutorial"]
tags: ["documentation", "reference"]
---

# Common Gotchas & Pitfalls

**Status:** ✅ Production Ready
**Audience:** Developers, Architects
**Reading Time:** 20-25 minutes
**Last Updated:** 2026-02-05

Learn from common mistakes and pitfalls when using FraiseQL. Each gotcha includes diagnosis steps and solutions.

---

## Overview

This guide documents common mistakes, surprising behaviors, and anti-patterns discovered through production use. Understanding these pitfalls will help you avoid costly mistakes.

---

## 1. N+1 Query Problem

### The Problem

**Symptom:** Application is slow despite queries looking simple. Database receives many small queries instead of one large query.

**Example:**

```graphql
query {
  users {
    id
    name
    posts {      # ← This causes N+1!
      id
      title
    }
  }
}
```

**What happens:**

1. Query fetches 100 users → 1 database query
2. For EACH user, fetches their posts → 100 more queries
3. Total: 101 queries instead of 1

### Why This Happens

FraiseQL resolves nested fields one level at a time. Without optimization, it fetches parent entities first, then child entities separately.

### How to Diagnose

**Enable query logging:**

```python
import logging

logging.getLogger("fraiseql").setLevel(logging.DEBUG)
```

Then run the FastAPI app (for example `uvicorn app:app`) and count the `SELECT` statements emitted per request in the logs.

### Solutions

**Solution 1: Use a DataLoader field (RECOMMENDED)**

Batch a relationship with `@fraiseql.dataloader_field` so all children load in a single query:

```python
import fraiseql

@fraiseql.dataloader_field
async def posts(user: User, info) -> list[Post]:
    db = info.context["db"]
    return await db.find("v_post", fk_user=user.id)
```

**Result:** ~2 queries total (users + batched posts)

**Solution 2: Use table-backed views (tv_*)**

Pre-compose the nested data in a projection view so the child list ships inside the parent's `data` JSONB:

```python
import fraiseql

@fraiseql.type(sql_source="tv_user_with_posts", jsonb_column="data")
class UserWithPosts:
    """Projection view with posts already composed in the data JSONB."""
    id: ID
    name: str
    posts: list[PostSummary]  # Pre-composed in tv_user_with_posts
```

**Solution 3: Flatten queries temporarily**

Instead of:

```graphql
query {
  users { posts { comments { likes } } }
}
```

Do:

```graphql
query {
  users { id posts { id } }
}

query {
  posts { id comments { id } }
}

query {
  comments { id likes }
}
```

**Solution 4: Add pagination to nested fields**

```graphql
query {
  users(first: 50) {          # Smaller parent batch
    id
    name
    posts(first: 10) {        # Smaller child batch
      id
      title
    }
  }
}
```

### Prevention

- ✅ Monitor query count in production logs
- ✅ Set up alerts for >50 queries per request
- ✅ Use profiling tools to detect N+1 early
- ✅ Test with large datasets (1000+ records)
- ✅ Document expected query count for each resolver

---

## 2. Pagination Edge Cases

### Edge Case: Offset Pagination Past End

**Symptom:** Query with `skip: 10000` returns empty results, but data exists.

**Why:** Offset pagination becomes inefficient with large offsets. After row 10,000, the database must skip 10,000 rows for every query.

**Solutions:**

**Use keyset pagination (RECOMMENDED):**

```graphql
query {
  users(after: "user123", first: 100) {
    id
    name
  }
}
```

**Keyset advantages:**

- Constant performance regardless of offset
- Works with sorting
- Handles inserts/deletes during pagination

### Edge Case: Results Changing During Pagination

**Symptom:** When paginating through results, you get duplicate records or skip records.

**Why:** If data is inserted/deleted between pagination requests, the result set changes.

**Example:**

```text
Request 1: skip 0, take 10   → gets records 1-10
[New record inserted]
Request 2: skip 10, take 10  → gets records 12-21 (record 11 is new)
Result: Skipped record 11!
```

**Solutions:**

**Use keyset pagination:**

```graphql
query {
  users(after: "cursor_from_previous", first: 10) {
    id
    cursor
  }
}
```

Keyset pagination uses the last record's `id` as the cursor, which is immune to inserts.

**Or use a stable snapshot:**

Wrap a multi-page export in a single PostgreSQL transaction (`REPEATABLE READ`) so every page reads from the same snapshot.

### Edge Case: Cursor Expiry

**Symptom:** Pagination cursor becomes invalid after database changes.

**Why:** The cursor points to a record that was deleted or modified.

**Solution:**

**Handle an expired cursor gracefully on the client:**

```python
try:
    result = await client.query(query, variables={"after": cursor})
except FraiseQLError as e:
    if e.code == "E_PAGINATION_CURSOR_EXPIRED":
        # Restart from beginning or last valid position
        cursor = None
        result = await client.query(query, variables={"after": cursor})
```

---

## 3. Cache Invalidation Timing

### Gotcha: Stale Cache After Mutation

**Symptom:** Mutation succeeds, but a subsequent query still returns the old cached value.

**Example:**

```graphql
mutation {
  updateUser(id: "123", name: "Alice") {
    id
    name
  }
}

query {
  user(id: "123") {
    name  # Still returns old name!
  }
}
```

**Why:** The cached query result was not invalidated by the write. FraiseQL's PostgreSQL-backed cache (`ResultCache`/`CachedRepository`) needs a cascade rule that links the mutation's table to the cached query.

### Solutions

**Solution 1: Configure cascade invalidation rules**

Use `setup_auto_cascade_rules` (with the `SchemaAnalyzer`) so writes to a table automatically invalidate the query results that depend on it:

```python
from fraiseql.caching import setup_auto_cascade_rules

await setup_auto_cascade_rules(cache, schema_analyzer)
```

**Solution 2: TTL-based invalidation**

Set a short cache TTL so stale entries expire on their own:

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    cache_ttl=60,  # All cached query results expire after 60 seconds
)
```

`cache_ttl` is also settable via the `FRAISEQL_CACHE_TTL` environment variable.

**Solution 3: Manual invalidation in the mutation**

```python
import fraiseql

@fraiseql.mutation
async def update_user(info, input: UpdateUserInput) -> UpdateUserSuccess | UpdateUserError:
    db = info.context["db"]
    cache = info.context["cache"]
    result = await db.execute_function("fn_update_user", {"id": input.id, "name": input.name})
    await cache.invalidate(User, id=input.id)  # Drop stale query results for this user
    return UpdateUserSuccess(user=User(**result["user"]))
```

### Gotcha: Cache Hit When You Need Fresh Data

**Symptom:** Critical data is cached but needs to be fresh for real-time operations.

**Example:**

```graphql
query {
  inventory(productId: "123") {
    quantity  # Cached, but inventory changes every second!
  }
}
```

### Solutions

**Solution 1: Skip caching for volatile reads**

Don't wrap volatile queries in `CachedRepository`; read straight from the view via `db.find` so every request hits PostgreSQL.

**Solution 2: Use subscriptions for real-time data**

```graphql
subscription {
  inventoryChanged(productId: "123") {
    quantity
    updatedAt
  }
}
```

---

## 4. Authorization Bypass via Field Omission

### Gotcha: Forgetting Field-Level Authorization

**Symptom:** A sensitive field is readable by unauthorized users.

**Example:**

```python
import fraiseql

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str
    password_hash: str  # ← OOPS! Exposed to everyone
    salary: Decimal     # ← OOPS! Exposed to everyone
```

**Why:** Anything you put in the read view's `data` JSONB and expose as a field is readable by any caller unless you restrict it. The safest fix is to never project secrets into the view at all.

### Solution

**Keep secrets out of the read view.** `password_hash` and similar columns live only on the `tb_` write table and are never selected into the `v_user.data` JSONB, so they cannot be queried:

```sql
CREATE VIEW v_user AS
SELECT
    id,
    jsonb_build_object(
        'id', id,
        'name', name,
        'email', email
        -- password_hash is intentionally NOT exposed
    ) AS data
FROM tb_user;
```

**Restrict whole-type or per-query access with an `Authorizer`:**

```python
import fraiseql

@fraiseql.query(authorizer=salary_authorizer)
async def user_compensation(info, id: ID) -> Compensation | None:
    db = info.context["db"]
    return await db.find_one("v_compensation", id=id)
```

**Or enforce row visibility with PostgreSQL Row-Level Security (RLS):**

Define an RLS policy on the underlying table that reads request context set by FraiseQL (for example `current_setting('app.tenant_id')` and `current_setting('app.user_id')`), so callers only ever see rows they are allowed to read.

---

## 5. Type Mismatches in Filters

### Gotcha: String vs Number Comparison

**Symptom:** A filter doesn't match the expected records, or returns an error.

**Example:**

```graphql
query {
  products(where: { id: { eq: "123" } }) {  # String
    id
  }
}
```

**Database schema:**

```sql
CREATE TABLE tb_product (
  pk_product BIGINT GENERATED ALWAYS AS IDENTITY,
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  sku TEXT
);
```

**Why:** Type mismatch. The GraphQL field type must line up with what the view exposes. Comparing a string literal against a numeric or UUID column produces no matches (or a coercion error).

### Solution

**Make Python field types match the columns the view projects:**

```python
import fraiseql

@fraiseql.type(sql_source="v_product", jsonb_column="data")
class Product:
    id: ID           # public UUID column
    sku: str         # text identifier
    price: Decimal   # use Decimal for money, not float
```

### Gotcha: NULL Handling in WHERE Clauses

**Symptom:** A filter with NULL doesn't work as expected.

**Example:**

```graphql
query {
  users(where: { middleName: { eq: null } }) {  # Finds users WITH middle names!
    id
  }
}
```

**Why:** In SQL, `column = NULL` is never true (use `IS NULL` instead).

### Solution

**Use the `isnull` operator:**

```graphql
query {
  users(where: { middleName: { isnull: true } }) {  # Correct!
    id
  }
}
```

---

## 6. View Performance Degradation

### Gotcha: Logical View Gets Slower Over Time

**Symptom:** A query that was fast at launch gets slower as the table grows.

**Why:** Logical views (`v_*`) compute their `data` JSONB on the fly. With millions of rows, building nested JSON aggregations per query becomes expensive.

### Solution

**Switch to a table-backed projection view (`tv_*`):**

```python
import fraiseql

# Replace v_user_summary (logical view computed per query):
@fraiseql.type(sql_source="v_user_summary", jsonb_column="data")
class UserSummary:
    id: ID
    name: str
    post_count: int

# With tv_user_summary (a real table holding pre-composed JSONB,
# refreshed by triggers/functions):
@fraiseql.type(sql_source="tv_user_summary", jsonb_column="data")
class UserSummary:
    id: ID
    name: str
    post_count: int
    updated_at: DateTime
```

**Table-backed view advantages:**

- Pre-composed and stored (fast reads)
- No recalculation per query
- Trade-off: requires a refresh strategy (triggers or scheduled functions)

---

## 7. Date/Time Timezone Issues

### Gotcha: DateTime vs Date Comparison

**Symptom:** A date filter includes the wrong records or excludes correct ones.

**Example:**

```graphql
query {
  orders(where: { createdAt: { gte: "2026-02-05" } }) {
    id
  }
}
```

**Problem:** `"2026-02-05"` is interpreted as `2026-02-05T00:00:00Z`. If a user created an order at `2026-02-04T23:00:00Z` (the previous day in their timezone), it won't match.

### Solutions

**Solution 1: Use DateTime with an explicit timezone**

```graphql
query {
  orders(where: {
    createdAt: {
      gte: "2026-02-05T00:00:00-05:00"  # Explicit timezone
    }
  }) {
    id
  }
}
```

**Solution 2: Use the Date type for date-only fields**

```python
import fraiseql
from fraiseql.types import Date, DateTime

@fraiseql.type(sql_source="v_order", jsonb_column="data")
class Order:
    id: ID
    created_date: Date     # Use Date for date-only values
    created_at: DateTime   # Use DateTime for timestamps
```

**Solution 3: Compare at the database level inside the view**

```sql
SELECT * FROM tb_order
WHERE DATE(created_at AT TIME ZONE 'UTC') = '2026-02-05'
```

---

## 8. Memory Leaks from Unclosed Subscriptions

### Gotcha: Subscription Connections Not Closed Properly

**Symptom:** Memory usage grows indefinitely in production.

**Why:** WebSocket connections are held open but not properly closed on disconnect.

### Solutions

**Solution 1: Clean up the async generator**

A `@fraiseql.subscription` resolver is an async generator. Use `try/finally` so resources are released when the client disconnects and the generator is closed:

```python
import fraiseql

@fraiseql.subscription
async def inventory_changed(info, product_id: UUID):
    listener = await open_listener(product_id)
    try:
        async for event in listener:
            yield event
    finally:
        await listener.close()  # Always release on disconnect
```

**Solution 2: Monitor active subscriptions**

```sql
-- Check for long-lived backend connections
SELECT COUNT(*) FROM pg_stat_activity
WHERE state = 'active' AND query LIKE '%LISTEN%';
```

---

## 9. Query Alias Shadowing

### Gotcha: Query Aliases Hiding Field Names

**Symptom:** A query returns unexpected keys, causing confusion about the response structure.

**Example:**

```graphql
query {
  user: users(status: "active") {  # Alias "user" renames field "users"
    id
    name
  }
}
```

**Result:**

```json
{
  "user": [
    { "id": "123", "name": "Alice" }
  ]
}
```

**Later, a different query uses the real field name:**

```graphql
query {
  users(status: "active") {  # Now the key is "users"
    id
  }
}
```

The two responses use different top-level keys for the same field, which leads to confusion.

### Solution

**Use aliases consistently and only when you need two of the same field:**

```graphql
query {
  activeUsers: users(status: "active") {
    id
    name
  }
  inactiveUsers: users(status: "inactive") {
    id
    name
  }
}
```

**Document the expected response structure in the resolver:**

```python
import fraiseql

@fraiseql.query
async def users(info, status: str | None = None) -> list[User]:
    """Return a list of users, optionally filtered by status.

    Response key: "users" (an array of User objects) unless aliased.
    """
    db = info.context["db"]
    return await db.find("v_user", status=status)
```

---

## 10. Connection Pool Exhaustion

### Gotcha: All Connections Held by Slow Queries

**Symptom:** New queries fail with "no connections available".

**Why:** A slow query holds a connection, preventing other queries from running.

### Solutions

**Solution 1: Tune the pool and timeouts**

Configure the pool through `create_fraiseql_app` kwargs (or `FRAISEQL_` environment variables):

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    database_pool_size=20,       # FRAISEQL_DATABASE_POOL_SIZE
    database_pool_timeout=10,    # FRAISEQL_DATABASE_POOL_TIMEOUT (seconds)
    query_timeout=30,            # FRAISEQL_QUERY_TIMEOUT (seconds)
)
```

**Solution 2: Monitor the pool from PostgreSQL**

```sql
-- Check active connections
SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'active';

-- Identify and cancel runaway queries
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE query_start < now() - interval '5 minutes';
```

---

## 11. Recursive Queries Without Limits

### Gotcha: Unbounded Self-Referential Queries

**Symptom:** A query hangs or times out.

**Example:**

```graphql
query {
  user(id: "1") {
    id
    manager {
      id
      manager {        # Recursion not bounded!
        id
        manager { ... }
      }
    }
  }
}
```

### Solution

**Set a maximum query depth in the app config:**

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    max_query_depth=15,  # Reject queries nested deeper than 15 levels
)
```

`max_query_depth` is also settable via `FRAISEQL_MAX_QUERY_DEPTH`. FraiseQL additionally runs query-complexity analysis (`complexity_max_depth`, `complexity_max_score`) that you can tune the same way.

**Or bound the recursion explicitly in the query:**

```graphql
query {
  user(id: "1") {
    id
    manager {
      id
      manager {
        id
        # Stop here (3 levels)
      }
    }
  }
}
```

---

## See Also

**Related Guides:**

- **[Common Patterns](./patterns.md)** — Real-world solutions avoiding gotchas
- **[Performance Tuning Runbook](../operations/performance-tuning-runbook.md)** — Optimizing query performance
- **[Testing Checklist](../reference/testing-checklist.md)** — Testing to catch gotchas early
- **[Troubleshooting Decision Tree](./troubleshooting-decision-tree.md)** — Route to correct guide
- **[Consistency Model](./consistency-model.md)** — Understanding consistency guarantees
- **[Testing Checklist](../reference/testing-checklist.md)** — Testing to catch gotchas early

**Architecture & Design:**

- **[CQRS Design](../architecture/cqrs-design.md)** — How reads and writes execute
- **[Schema Design Best Practices](./schema-design-best-practices.md)** — Designing to avoid issues

**Operations:**

- **[Monitoring & Observability](./monitoring.md)** — Catching issues in production
- **[Observability](../operations/observability.md)** — Observing patterns

---

**Last Updated:** 2026-02-05
