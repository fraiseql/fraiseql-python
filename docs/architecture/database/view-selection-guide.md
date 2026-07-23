---
title: "View Selection Guide: Choosing Between v_* and tv_*"
description: FraiseQL exposes GraphQL reads through PostgreSQL views. This guide helps you choose between a logical view (v_*) and a table-backed projection view (tv_*).
keywords: ["design", "scalability", "performance", "patterns", "security"]
tags: ["documentation", "reference"]
---

# View Selection Guide: Choosing Between v_* and tv_*

## Overview

In FraiseQL v1, every GraphQL read resolves against a PostgreSQL view that returns a
`data` JSONB column. There are **two view patterns** to choose from, and the choice is
the single biggest lever for read performance. This guide helps you pick the right one.

| Pattern | Type | Storage | Use Case | Latency | Maintenance |
|---------|------|---------|----------|---------|-------------|
| `v_*` | Logical view | None | Simple GraphQL queries | Medium (100-500ms) | None |
| `tv_*` | Table-backed projection | JSONB table | Complex nested GraphQL | Fast (50-200ms) | Trigger/scheduled refresh |

A `v_*` view composes its `data` JSONB at query time with a plain `SELECT`. A `tv_*` view
is a real table holding pre-composed JSONB, refreshed by triggers or a scheduled job —
you pay storage and refresh cost up front to make reads fast and predictable.

Both are bound to a GraphQL type the same way, at runtime, when the app starts:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str
```

Switching a type from a logical view to a table-backed projection is just a one-line
change to `sql_source` — clients never see the difference.

## Decision Tree

```text
START: How complex is the read?

├─ Simple query? (1-2 tables, flat structure)
│  └─ YES → Use v_*
│        Why: No JOIN overhead, nothing to maintain
│        Example: Query a single user or a user list
│
└─ Complex query? (3+ tables, nested data)
   ├─ HIGH read volume (>100 reqs/sec)?
   │  └─ Use tv_* (table-backed projection)
   │     Why: Pre-composed JSONB, sub-second latency
   │     Example: User profiles with posts/comments
   │
   └─ LOW read volume (<100 reqs/sec)?
      ├─ Query time > 1 second?
      │  └─ Use tv_* (table-backed projection)
      │     Why: Composition cost exceeds storage cost
      │
      └─ Query time < 1 second?
         └─ Use v_* (logical view)
            Why: Storage overhead not justified
```

## Quick Reference by Scenario

**Simple Cases (Use v_*)**:

- ✅ Query single user by ID → `v_user`
- ✅ Query list of posts → `v_post`
- ✅ Query user with one related entity → `v_user` (no deep nesting)

**Complex Cases (Use tv_*)**:

- ✅ User profile with posts, comments, and likes
- ✅ Order with line items, customer, and shipment
- ✅ Dashboard requiring pre-aggregated data
- ✅ GraphQL subscriptions (real-time updates)

## Performance Comparison Matrix

### Query Execution Time (Lower is Better)

| Query Type | v_* | tv_* |
|-----------|-----|------|
| Single entity (User by ID) | **50-100ms** | 50-100ms |
| Entity with 1 related (User + Posts) | 100-300ms | **100-200ms** |
| Entity with 3+ related (User + Posts + Comments + Likes) | 2-5s | **50-200ms** |

### Memory Usage (Lower is Better)

| Scenario | v_* | tv_* |
|----------|-----|------|
| 1K records with deep nesting | 50-100MB | **20-30MB** |
| 10K records with deep nesting | 500-800MB | **100-200MB** |

### Storage Overhead (Lower is Better)

| Pattern | Overhead | Notes |
|---------|----------|-------|
| `v_*` | 0% | No storage (logical view) |
| `tv_*` | 20-50% | JSONB pre-composition stored in a table |

## When to Migrate

### Migrate from v_* to tv_* when

✅ **GraphQL query times exceed 1 second**

- Measure: Run production queries and log execution time
- Action: Create a `tv_*` table with pre-composed JSONB
- Benefit: 10-50x faster queries

✅ **Query complexity has 3+ JOINs**

- Indicator: Query composes nested data from multiple tables on every read
- Action: Pre-compose nested data into a `tv_*` JSONB column
- Benefit: Single indexed lookup vs. multiple JOINs

✅ **High read volume (>100 requests/sec) to the same data structure**

- Indicator: Database CPU high during peak traffic
- Action: Cache the composition in a `tv_*` table
- Benefit: Query cost moves from compute-heavy to storage-read

✅ **Real-time GraphQL subscriptions require fast updates**

- Indicator: Subscription latency varies with nesting depth
- Action: Trigger-based `tv_*` refresh ensures consistent latency
- Benefit: Subscription updates in <100ms

### Don't Migrate when

❌ **Query already fast** (<500ms)

- Keep the logical view unless write overhead forces migration

❌ **Storage is severely constrained**

- Keep the logical view; optimize the underlying query instead

❌ **Write volume is unpredictable**

- Refresh triggers may become overhead; use a scheduled batch refresh instead

## Migration Path Example

### Complex User Profile (v_* → tv_*)

**Current State**:

```sql
-- v_user_full: logical view with real-time composition
-- Query time: 3-5 seconds
SELECT * FROM v_user_full WHERE id = $1;
```

**Problem**: Users reported slow profile loading on high-traffic pages.

**Decision**: Migrate to a `tv_*` table-backed projection for pre-composed data.

**Implementation**:

```sql
-- Step 1: Create the projection table holding pre-composed JSONB
CREATE TABLE tv_user_profile AS
SELECT id, data FROM v_user_full;

-- Step 2: Keep it fresh with a trigger on the source write table
CREATE TRIGGER trg_refresh_tv_user_profile
    AFTER INSERT OR UPDATE OR DELETE ON tb_user
    FOR EACH ROW EXECUTE FUNCTION fn_refresh_tv_user_profile();
```

```python
# Step 3: Point the GraphQL type at the projection view (runtime binding)
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="tv_user_profile", jsonb_column="data")
class User:
    id: ID
    name: str
    posts: list["Post"]
```

**Before/After**:

- **Before**: 3-5 second page load + database spike during peak traffic
- **After**: 100-200ms page load, consistent performance

## Client API

Clients never choose a view. They issue the same GraphQL query regardless of whether the
type is backed by a `v_*` or a `tv_*` view — the server-side binding determines which one
runs:

```graphql
query {
  user(id: "550e8400-e29b-41d4-a716-446655440000") {
    id
    name
    posts {
      id
      title
      comments {
        id
        text
      }
    }
  }
}
```

To move from a logical view to a projection view, change only `sql_source`:

- Simple queries: `@fraiseql.type(sql_source="v_user", jsonb_column="data")`
- Complex queries: `@fraiseql.type(sql_source="tv_user_profile", jsonb_column="data")`

## Decision Checklist

Before creating a new view, answer these questions:

- [ ] Is the query for a single entity? → Use `v_*`
- [ ] Does the query require 3+ JOINs? → Consider `tv_*`
- [ ] Are query times > 1 second? → Use `tv_*`
- [ ] Is read volume > 100 reqs/sec to this view? → Use `tv_*`
- [ ] Can you accept 100-300ms latency? → Use `v_*`
- [ ] Do you need real-time subscriptions? → Use `tv_*` with refresh triggers

**Recommendation**: Default to `v_*`. Migrate to `tv_*` only when production metrics
require it.

## Performance Testing

Measure both views with `EXPLAIN (ANALYZE, BUFFERS)` and compare the reported
**Execution Time**:

```sql
-- Measure the logical view
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM v_user_full WHERE id = $1;

-- Measure the table-backed projection (should be 10-50x faster)
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM tv_user_profile WHERE id = $1;
```

## See Also

- [tv_* Table Pattern](./tv-table-pattern.md)
- [Schema Conventions](../../specs/schema-conventions.md)
- [Naming Patterns](../../reference/naming-patterns.md)
- [Aggregation Model](../analytics/aggregation-model.md)
- [Database-Centric Architecture](../../foundation/03-database-centric-architecture.md)
