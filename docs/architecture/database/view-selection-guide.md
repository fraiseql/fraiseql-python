<!-- Skip to main content -->
---

title: View Selection Guide: Choosing Between v_*, tv_*, va_*, and ta_*
description: FraiseQL supports **four distinct view patterns** across two query planes. This guide helps you choose the right pattern for your use case.
keywords: ["design", "scalability", "performance", "patterns", "security"]
tags: ["documentation", "reference"]
---

# View Selection Guide: Choosing Between v_*, tv_*, va_*, and ta_*

## Overview

FraiseQL supports **four distinct view patterns** across two query planes. This guide helps you choose the right pattern for your use case.

## View Patterns at a Glance

| Pattern | Plane | Type | Storage | Use Case | Latency | Maintenance |
|---------|-------|------|---------|----------|---------|------------|
| `v_*` | JSON | Logical | None | Simple GraphQL queries | Medium (100-500ms) | None |
| `tv_*` | JSON | Table | JSONB | Complex nested GraphQL | Fast (50-200ms) | Trigger/scheduled refresh |
| `va_*` | Arrow | Logical | None | Simple analytics queries | Medium (500ms-5s) | None |
| `ta_*` | Arrow | Table | Columnar | Large-scale analytics | Very Fast (50-100ms) | Trigger/scheduled refresh |

## Decision Tree

```text
<!-- Code example in TEXT -->
START: What query plane are you working in?

├─ JSON PLANE (GraphQL queries)
│  ├─ Simple query? (1-2 tables, flat structure)
│  │  └─ YES → Use v_*
│  │        Why: No JOIN overhead, instant to deploy
│  │        Example: Query single user or user list
│  │
│  └─ Complex query? (3+ tables, nested data)
│     ├─ HIGH read volume (>100 reqs/sec)?
│     │  └─ Use tv_* (table-backed)
│     │     Why: Pre-computed JSONB, sub-second latency
│     │     Example: User profiles with posts/comments
│     │
│     └─ LOW read volume (<100 reqs/sec)?
│        ├─ Query time > 1 second?
│        │  └─ Use tv_* (table-backed)
│        │     Why: Composition cost exceeds storage cost
│        │
│        └─ Query time < 1 second?
│           └─ Use v_* (logical)
│              Why: Storage overhead not justified
│
└─ ARROW PLANE (Analytics queries)
   ├─ Small dataset? (<100K rows)
   │  └─ Use va_* (logical)
   │     Why: No storage overhead, simple to maintain
   │     Example: Daily sales summary (10K rows)
   │
   └─ Large dataset? (>1M rows)
      ├─ Query time > 1 second?
      │  └─ Use ta_* (table-backed)
      │     Why: Columnar format, BRIN indexes
      │     Example: 10M historical transactions
      │
      └─ Query time < 1 second?
         └─ Use va_* (logical)
            Why: Storage overhead not justified
```text
<!-- Code example in TEXT -->

## Quick Reference by Scenario

### GraphQL Queries

**Simple Cases (Use v_*)**:

- ✅ Query single user by ID → `v_user`
- ✅ Query list of posts → `v_post`
- ✅ Query user with one related entity → `v_user` (no deep nesting)

**Complex Cases (Use tv_*)**:

- ✅ User profile with posts, comments, and likes
- ✅ Order with line items, customer, and shipment
- ✅ Dashboard requiring pre-aggregated data
- ✅ GraphQL subscriptions (real-time updates)

### Analytics Queries

**Small Datasets (Use va_*)**:

- ✅ Daily sales summary (computed once per day)
- ✅ Weekly user metrics (5K rows)
- ✅ Monthly revenue report (1K rows)

**Large Datasets (Use ta_*)**:

- ✅ 10M+ transaction history
- ✅ 100K+ event stream (append-only)
- ✅ Time-series analytics (millions of data points)

## Performance Comparison Matrix

### Query Execution Time (Lower is Better)

| Query Type | v_* | tv_* | va_* | ta_* |
|-----------|-----|------|------|------|
| Single entity (User by ID) | **50-100ms** | 50-100ms | - | - |
| Entity with 1 related (User + Posts) | 100-300ms | **100-200ms** | - | - |
| Entity with 3+ related (User + Posts + Comments + Likes) | 2-5s | **50-200ms** | - | - |
| Analytics: 10K rows, simple filter | - | - | **100-200ms** | 100-150ms |
| Analytics: 1M rows, range query | - | - | 2-10s | **50-100ms** |
| Analytics: 100M rows, aggregation | - | - | >30s | **200-500ms** |

### Memory Usage (Lower is Better)

| Scenario | v_* | tv_* | va_* | ta_* |
|----------|-----|------|------|------|
| 1K records with deep nesting | 50-100MB | **20-30MB** | - | - |
| 10K records with deep nesting | 500-800MB | **100-200MB** | - | - |
| 100K row analytics query | - | - | 200-500MB | **50-100MB** |
| 10M row analytics query | - | - | 2-5GB | **500MB-1GB** |

### Storage Overhead (Lower is Better)

| Pattern | Overhead | Notes |
|---------|----------|-------|
| `v_*` | 0% | No storage (logical view) |
| `tv_*` | 20-50% | JSONB pre-composition |
| `va_*` | 0% | No storage (logical view) |
| `ta_*` | 10-30% | Columnar format, BRIN indexes |

## When to Migrate

### Migrate from v_*to tv_* when

✅ **GraphQL query times exceed 1 second**

- Measure: Run production queries and log execution time
- Action: Create tv_* table with pre-composed JSONB
- Benefit: 10-50x faster queries

✅ **Query complexity has 3+ JOINs**

- Indicator: Query hits database for nested data multiple times
- Action: Pre-compose nested data into tv_* JSONB
- Benefit: Single table scan vs. multiple JOINs

✅ **High read volume (>100 requests/sec) to same data structure**

- Indicator: Database CPU high during peak traffic
- Action: Cache computations in tv_* table
- Benefit: Query cost moves from compute-heavy to storage-read

✅ **Real-time GraphQL subscriptions require fast updates**

- Indicator: Subscription latency varies based on nesting depth
- Action: Trigger-based tv_* refresh ensures consistent latency
- Benefit: Subscription updates in <100ms

### Migrate from va_*to ta_* when

✅ **Analytics query times exceed 1 second**

- Measure: Run EXPLAIN on Arrow queries
- Action: Create ta_* table with columnar storage
- Benefit: 50-100x faster on time-series queries

✅ **Dataset larger than 1M rows**

- Indicator: VA query memory usage > 1GB
- Action: Use BRIN indexes on time-series columns
- Benefit: Queries scan fewer pages

✅ **Read volume high, staleness acceptable**

- Indicator: Multiple concurrent analytics queries affecting other workloads
- Action: Batch refresh ta_* tables during off-hours
- Benefit: Analytics isolated from OLTP

### Don't Migrate when

❌ **Query already fast** (<500ms for GraphQL, <1s for analytics)

- Keep logical views unless write overhead forces migration

❌ **Storage is severely constrained**

- Keep logical views; optimize queries instead

❌ **Write volume is unpredictable**

- Triggers may become overhead; use scheduled batch instead

## Migration Path Examples

### Example 1: Complex User Profile (v_*→ tv_*)

**Current State**:

```sql
<!-- Code example in SQL -->
-- v_user_full: Logical view with real-time composition
-- Query time: 3-5 seconds
SELECT * FROM v_user_full WHERE id = ?;
```text
<!-- Code example in TEXT -->

**Problem**: Users reported slow profile loading on high-traffic pages.

**Decision**: Migrate to tv_* for pre-composed data.

**Implementation**:

```sql
<!-- Code example in SQL -->
-- Step 1: Create intermediate composed views (helper)
CREATE VIEW v_user_posts_composed AS ...
CREATE VIEW v_user_full_composed AS ...

-- Step 2: Create tv_user_profile table
CREATE TABLE tv_user_profile AS SELECT * FROM v_user_full_composed;

-- Step 3: Add refresh trigger
CREATE TRIGGER trg_refresh_tv_user_profile ON tb_user ...

-- Step 4: Update GraphQL binding
@FraiseQL.type(view="tv_user_profile")
class User: ...

-- Step 5: Verify performance
-- Query time: 100-200ms ✅
-- User experience: 25-50x faster ✅
```text
<!-- Code example in TEXT -->

**Before/After**:

- **Before**: 3-5 second page load + database spike during peak traffic
- **After**: 100-200ms page load, consistent performance

### Example 2: Large Analytics Dataset (va_*→ ta_*)

**Current State**:

```sql
<!-- Code example in SQL -->
-- va_orders: Logical view over 10M rows
-- Query time: 5-10 seconds
SELECT * FROM va_orders WHERE created_at >= ? AND created_at < ?;
```text
<!-- Code example in TEXT -->

**Problem**: BI dashboard queries timing out, blocking other queries.

**Decision**: Migrate to ta_* for optimized columnar storage.

**Implementation**:

```sql
<!-- Code example in SQL -->
-- Step 1: Create ta_orders table with BRIN indexes
CREATE TABLE ta_orders (
    id TEXT PRIMARY KEY,
    total NUMERIC,
    created_at TIMESTAMPTZ,
    ...
);
CREATE INDEX idx_ta_orders_created_at_brin ON ta_orders USING BRIN(created_at);

-- Step 2: Populate from va_orders
INSERT INTO ta_orders SELECT * FROM va_orders;

-- Step 3: Add refresh trigger (or scheduled batch)
CREATE TRIGGER trg_refresh_ta_orders ON tb_order ...

-- Step 4: Update Arrow schema binding
registry.get("ta_orders")

-- Step 5: Verify performance
-- Query time: 50-100ms ✅
-- Memory: 500MB-1GB (vs 2-5GB) ✅
```text
<!-- Code example in TEXT -->

**Before/After**:

- **Before**: 5-10 second queries, dashboard timeouts, other queries blocked
- **After**: 50-100ms queries, instant dashboard, no impact to OLTP

## Client API Patterns

### GraphQL (JSON Plane)

Clients don't explicitly choose views; the schema binding determines which view to use:

```typescript
<!-- Code example in TypeScript -->
// Client query (same for both v_* and tv_*)
const query = gql`
  query {
    user(id: "550e8400...") {
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
`;

// FraiseQL schema binding (server-side)
@FraiseQL.type(view="tv_user_profile")  // Uses tv_* for performance
class User:
    id: UUID  # UUID v4 for GraphQL ID
    name: str
    posts: list[Post]
```text
<!-- Code example in TEXT -->

**When to use which**:

- Simple queries: `@FraiseQL.type(view="v_user")` (no view specified)
- Complex queries: `@FraiseQL.type(view="tv_user_profile")` (explicit view)

### Arrow Flight (Analytics Plane)

Clients explicitly choose the view when creating tickets:

```python
<!-- Code example in Python -->
import pyarrow.flight as flight

client = flight.connect("grpc://localhost:50051")

# Use logical view (va_orders)
ticket_small = {
    "view": "va_orders",  # Explicit choice
    "filter": "created_at > '2026-01-01'",
    "limit": 10000
}
stream = client.do_get(flight.Ticket(json.dumps(ticket_small).encode()))

# Use table-backed view (ta_orders)
ticket_large = {
    "view": "ta_orders",  # Explicit choice - faster for large datasets
    "filter": "created_at > '2026-01-01'",
    "limit": 1000000
}
stream = client.do_get(flight.Ticket(json.dumps(ticket_large).encode()))
```text
<!-- Code example in TEXT -->

**View Discovery**:

```python
<!-- Code example in Python -->
# List available views
views = client.list_flights(criteria=None)
for flight_info in views:
    print(f"View: {flight_info.name}")
    print(f"  Type: {'table' if flight_info.name.startswith('ta_') else 'logical'}")
    print(f"  Rows: {flight_info.total_records}")
```text
<!-- Code example in TEXT -->

## Decision Checklist

Before creating a new view, answer these questions:

### For GraphQL (JSON Plane)

- [ ] Is the query for a single entity? → Use `v_*`
- [ ] Does the query require 3+ JOINs? → Consider `tv_*`
- [ ] Are query times > 1 second? → Use `tv_*`
- [ ] Is read volume > 100 reqs/sec to this view? → Use `tv_*`
- [ ] Can you accept 100-300ms latency? → Use `v_*`
- [ ] Do you need real-time subscriptions? → Use `tv_*` with triggers

**Recommendation**: Default to `v_*`. Migrate to `tv_*` only if performance metrics require it.

### For Arrow Flight (Analytics)

- [ ] Is the dataset < 100K rows? → Use `va_*`
- [ ] Is query time < 1 second? → Use `va_*`
- [ ] Is the dataset > 1M rows? → Use `ta_*`
- [ ] Are query times > 1 second? → Use `ta_*`
- [ ] Is storage constrained? → Use `va_*`

**Recommendation**: Default to `va_*`. Migrate to `ta_*` for large datasets.

## Performance Testing

### Test GraphQL Performance (v_*vs tv_*)

```sql
<!-- Code example in SQL -->
-- Measure v_* execution time
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM v_user_full WHERE id = ?;
-- Note query time (look for "Execution Time")

-- Measure tv_* execution time
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM tv_user_profile WHERE id = ?;
-- Should be 10-50x faster
```text
<!-- Code example in TEXT -->

### Test Analytics Performance (va_*vs ta_*)

```sql
<!-- Code example in SQL -->
-- Measure va_* execution time
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM va_orders WHERE created_at >= ? AND created_at < ?;

-- Measure ta_* execution time
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM ta_orders WHERE created_at >= ? AND created_at < ?;
-- Should be 50-100x faster for large datasets
```text
<!-- Code example in TEXT -->

## See Also

- [tv_* Table Pattern (JSON Plane Details)](./tv-table-pattern.md)
- [Schema Conventions](../../specs/schema-conventions.md)
- [FraiseQL Database Architecture](../../architecture/)
