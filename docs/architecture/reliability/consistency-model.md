---
title: Consistency Model
description: FraiseQL v1 inherits PostgreSQL's strict serializable consistency. This document specifies the consistency guarantees clients can rely on.
keywords: ["consistency", "acid", "isolation", "postgresql", "transactions"]
tags: ["documentation", "reference"]
---

# Consistency Model

**Status:** Stable
**Audience:** Architects, database engineers, enterprise evaluators

---

## 1. Overview

FraiseQL v1 is a Python runtime GraphQL framework backed by a **single PostgreSQL
database**. Its consistency guarantees are exactly PostgreSQL's consistency
guarantees: FraiseQL does not add a consistency layer of its own, and it does not
weaken what PostgreSQL provides.

### 1.1 Core Principle

> **What PostgreSQL guarantees, FraiseQL guarantees.**

FraiseQL queries call PostgreSQL read views (`v_`/`tv_`) and mutations call
PostgreSQL functions (`fn_`). Every statement runs inside a PostgreSQL transaction,
so the ACID and isolation properties you configure on the database are the
properties your GraphQL API exposes.

### 1.2 Consistency Foundation

| Property | PostgreSQL Mechanism |
|----------|----------------------|
| Atomicity | Transactional `BEGIN`/`COMMIT`, all-or-nothing |
| Consistency (logical) | Constraints, foreign keys, check constraints |
| Isolation | MVCC, Read Committed by default, Serializable available |
| Durability | Write-ahead logging (WAL) |

---

## 2. Single-Database Consistency (Primary Guarantee)

### 2.1 ACID Transaction Guarantees

FraiseQL queries and mutations respect PostgreSQL's ACID properties.

#### 2.1.1 Atomicity

**What it means:** A mutation either fully succeeds or fully fails. No partial
updates.

**Scope:** A single mutation, which executes one `fn_` PostgreSQL function inside
one transaction.

- All side effects of the function apply, or none apply.
- No partial state is visible to other queries.

**Guarantee:**

```sql
-- Before mutation
SELECT COUNT(*) FROM tb_user;  -- 100
```

```graphql
# Mutation fails (email uniqueness constraint violation)
mutation {
  createUser(input: { name: "Bob", email: "duplicate@example.com" }) {
    ... on CreateUserSuccess { user { id } }
    ... on CreateUserError { message code }
  }
}
```

```sql
-- After mutation
SELECT COUNT(*) FROM tb_user;  -- Still 100 (no partial insert)
```

#### 2.1.2 Consistency (Logical)

**What it means:** Database integrity constraints are never violated.

**Scope:** All queries, mutations, and subscriptions.

- Foreign key constraints enforced
- Unique constraints enforced
- Check constraints enforced
- Referential integrity maintained

**Guarantee:**

```graphql
# Foreign key constraint: tb_order.fk_user → tb_user.pk_user
# This mutation fails because the referenced user does not exist:
mutation {
  createOrder(input: { userId: "00000000-0000-0000-0000-000000009999", amount: 100 }) {
    ... on CreateOrderSuccess { order { id } }
    ... on CreateOrderError { message code }
  }
}
# After the error, database state is unchanged.
```

#### 2.1.3 Isolation

**What it means:** Concurrent operations do not interfere with each other beyond
what the configured isolation level permits.

**Isolation levels** (in order of strictness):

| Level | Dirty Reads | Non-Repeatable | Phantom | Notes |
|-------|-------------|----------------|---------|-------|
| **Read Uncommitted** | Prevented | Possible | Possible | PostgreSQL treats this as Read Committed |
| **Read Committed** | Prevented | Possible | Possible | PostgreSQL default |
| **Repeatable Read** | Prevented | Prevented | Prevented (PostgreSQL) | Snapshot isolation |
| **Serializable** | Prevented | Prevented | Prevented | Serializable Snapshot Isolation (SSI) |

**FraiseQL isolation:** Each request runs at PostgreSQL's configured isolation
level (Read Committed by default). If your `fn_` functions or session require
stronger guarantees, set `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE` (or
configure it on the connection) inside the database; FraiseQL faithfully reflects
whatever PostgreSQL is configured to enforce.

```graphql
# Two concurrent mutations updating the same row
# Client A:
mutation { updateUser(input: { id: "...", name: "Alice Update 1" }) {
  ... on UpdateUserSuccess { user { name } }
} }

# Client B:
mutation { updateUser(input: { id: "...", name: "Alice Update 2" }) {
  ... on UpdateUserSuccess { user { name } }
} }

# Under Serializable isolation: one commits, the other fails with a
# serialization conflict and can be retried. Under Read Committed:
# the second write overwrites the first (last-writer-wins).
```

#### 2.1.4 Durability

**What it means:** Once a mutation succeeds, the change persists even after a
crash.

**Scope:** Confirmed mutations.

- The mutation returns a success result (in the GraphQL `data` field, not `errors`).
- PostgreSQL has flushed the change to durable storage via the WAL.
- The change survives a server restart or power loss.

**Guarantee:**

```graphql
# Mutation succeeds (returns in data field)
mutation {
  createUser(input: { name: "Bob", email: "bob@example.com" }) {
    ... on CreateUserSuccess { user { id } }
  }
}
# The client receives data: { createUser: { user: { id: "..." } } }

# The server crashes immediately afterward.
# After PostgreSQL restarts, the change is still present:
query { user(id: "...") { name } }  # Returns "Bob"
```

**Non-guarantee:**

```graphql
# Mutation fails (returns in the errors field or as a typed error union)
mutation {
  createUser(input: { name: "Alice", email: "duplicate@example.com" }) {
    ... on CreateUserError { message }
  }
}
# data: null on the field / typed error returned

# If the server crashes now, the change was never applied
# (it was never committed, so there is nothing to be durable).
```

---

## 3. Read Consistency

### 3.1 Read-After-Write Consistency (RAW)

**What it means:** After a write commits, subsequent reads see the write.

**Scope:** A single PostgreSQL primary.

```graphql
# Write commits
mutation {
  updateUser(input: { id: "...", name: "Alice" }) {
    ... on UpdateUserSuccess { user { name } }
  }
}

# A subsequent read sees the write
query { user(id: "...") { name } }  # Returns "Alice"
```

**Guarantee:** Against a single PostgreSQL primary, read-after-write is
immediate. A committed write is visible to every later read of that primary.

### 3.2 Read-Your-Writes Consistency (RYW)

**What it means:** A client always sees the results of its own committed writes.

**Scope:** A single PostgreSQL primary.

```graphql
# Request 1: write
mutation { updateUserProfile(input: { name: "NewName" }) {
  ... on UpdateUserSuccess { user { name } }
} }

# Request 2: read (any FraiseQL worker, same database)
query { me { name } }  # Returns "NewName"
```

Because every FraiseQL worker reads from the same PostgreSQL primary, multiple
application processes do not break read-your-writes: the database is the single
source of truth.

### 3.3 Monotonic Reads

**What it means:** A client never sees a version of data earlier than a previous
read.

**Scope:** A single PostgreSQL primary.

```graphql
# Read 1: user has 5 posts
query { user(id: "...") { posts { totalCount } } }  # Returns 5

# Another client adds a post.

# Read 2: still at least 5
query { user(id: "...") { posts { totalCount } } }  # Returns >= 5, never < 5
```

Against a single primary, committed data does not disappear, so reads are
monotonic by construction.

### 3.4 Read Replicas (Deployment Note)

PostgreSQL supports streaming **read replicas** as a deployment option. Replicas
apply WAL asynchronously and therefore lag the primary, so reads served by a
replica are **eventually consistent** with respect to recent writes on the
primary.

This is a property of your PostgreSQL deployment, **not a FraiseQL feature**:

- FraiseQL connects to whatever `database_url` you give it via a single
  `psycopg_pool.AsyncConnectionPool`. It does **not** route queries to replicas,
  split reads from writes, or perform automatic failover.
- If you point FraiseQL at a replica, reads can be stale relative to the primary.
  If you point it at the primary (the common single-node setup), all of the
  read-consistency guarantees in 3.1-3.3 hold.
- Read/write splitting and failover are handled below FraiseQL, for example by a
  connection proxy (PgBouncer, pgpool) or your infrastructure, and are out of
  scope for the framework.

---

## 4. Write Consistency

### 4.1 Serialized Writes

**What it means:** Concurrent writes to the same row do not interleave; PostgreSQL
serializes them.

**Scope:** All mutations.

```graphql
# Concurrent mutations on the same row, each implemented by a fn_ function:
#   fn_debit_balance: UPDATE tb_user SET balance = balance - $1 WHERE id = $2
# Client A: debit 100
# Client B: debit 50
# Initial balance: 1000

# PostgreSQL row locks serialize the two updates:
# Possible: A then B -> 900 then 850
# Never: both read 1000 independently -> 900 and 950
```

### 4.2 Multi-Statement Atomicity

**What it means:** A mutation's PostgreSQL function may perform many statements;
they all commit together or all roll back.

**Scope:** A single `fn_` function call.

```sql
-- Inside fn_create_order, all statements share one transaction:
CREATE FUNCTION fn_create_order(p_input jsonb) RETURNS jsonb AS $$
BEGIN
  INSERT INTO tb_order (...) VALUES (...);          -- statement 1
  UPDATE tb_user SET balance = balance - ... ;      -- statement 2
  INSERT INTO tb_audit_log (...) VALUES (...);      -- statement 3
  RETURN jsonb_build_object('success', true, ...);
END;
$$ LANGUAGE plpgsql;
```

If any statement raises, the entire function rolls back and the mutation returns a
typed error. No partial state is ever visible.

### 4.3 Write Conflicts

**What it means:** Conflicting concurrent writes are detected and one of them
fails, so it can be retried.

**Scope:** Concurrent modifications, when using optimistic concurrency.

```sql
-- Optimistic concurrency inside fn_update_user using a version column:
UPDATE tb_user
SET name = p_name, version = version + 1
WHERE id = p_id AND version = p_expected_version;
-- 0 rows affected => caller's version was stale => return a conflict error
```

```graphql
# Client A: updateUser(id, name: "Alice", expectedVersion: 5)
# Client B: updateUser(id, name: "Bob",   expectedVersion: 5)
# A commits first (version -> 6). B's UPDATE matches 0 rows and
# returns a typed conflict error.
```

Optimistic concurrency is a pattern you implement inside your `fn_` functions; see
[Error Handling Model](./error-handling-model.md) for how conflicts surface as
typed errors.

---

## 5. Subscription Consistency

### 5.1 Event Ordering Guarantees

Subscriptions provide **per-entity ordering** of events.

```graphql
# Subscription on a single order
subscription { orderUpdated(id: "...") { id status timestamp } }
```

```text
Events for the same entity are ordered:
  Event 1: status = "pending"   (timestamp: T1)
  Event 2: status = "shipped"   (timestamp: T2)
  Event 3: status = "delivered" (timestamp: T3)

The client always sees them in this order; never Event 3 before Event 1.
```

### 5.2 Event Delivery

Delivery is **at-least-once**:

- Each event is delivered at least once.
- A client may receive a duplicate (for example after a network retry).
- Clients should be idempotent and de-duplicate by event identifier.

```json
{ "eventId": "evt_12345", "data": { "id": "...", "status": "shipped" } }
{ "eventId": "evt_12345", "data": { "id": "...", "status": "shipped" } }
```

The client checks `eventId` and skips events it has already processed.

### 5.3 No Cross-Entity Ordering

Events from different entities may arrive out of order:

```text
Database timeline:
  T1: Order A updated -> Event 1
  T2: User B updated  -> Event 2
  T3: Order C updated -> Event 3

A client subscribed to multiple entities may receive: Event 2, Event 3, Event 1.
Events are per-entity ordered, not globally ordered.
```

See [Subscriptions](../realtime/subscriptions.md) for the full subscription model.

---

## 6. Caching Consistency

### 6.1 Cache Invalidation on Write

When a mutation commits, related cache entries are invalidated so subsequent reads
reflect the new state.

```graphql
# Initial query, result cached
query { user(id: "...") { name posts { id } } }
# Cached: name="Alice", posts=[...]

# Mutation
mutation { updateUser(input: { id: "...", name: "Bob" }) {
  ... on UpdateUserSuccess { user { name } }
} }
# Related cache entries for that user are invalidated.

# Next query reads fresh data from PostgreSQL
query { user(id: "...") { name } }  # name="Bob"
```

### 6.2 Cache TTL (Time-to-Live)

Cached results may carry a maximum age. A result younger than its TTL is served
from cache; once it expires, the next read re-fetches from PostgreSQL.

```text
Cache entry max age: 60 seconds
  age < 60s  -> served from cache
  age >= 60s -> stale, re-fetched from the database
```

### 6.3 Cache Coherence

In a single-node deployment, the cache is invalidated on write, so reads after a
committed mutation observe the new value. In a multi-worker deployment, configure
a shared cache backend so invalidations are visible to all workers; otherwise each
worker maintains its own cache and stale entries persist only until their TTL
expires.

---

## 7. Consistency Under Failures

### 7.1 Database Unavailable

**Query:** Returns an error, no partial data.

```graphql
query { user(id: "...") { name } }
# PostgreSQL is unreachable -> error; data is null.
```

**Mutation:** Returns an error, no changes applied.

```graphql
mutation { updateUser(input: { id: "...", name: "Bob" }) { ... } }
# PostgreSQL is unreachable -> error; the database is unchanged.
```

### 7.2 Connection Lost Mid-Request

- **Before the response is sent:** The client sees an error; if the transaction
  did not commit, no data changed.
- **After the response is sent:** The data is consistent because PostgreSQL has
  already committed.

### 7.3 Server Crash

- **Committed mutations:** Persisted by PostgreSQL (WAL durability).
- **Cache:** Rebuilt from PostgreSQL after restart.
- **In-flight requests:** Clients receive errors and should retry.

See [Failure Modes and Recovery](./failure-modes-and-recovery.md) for detailed
recovery procedures.

---

## 8. Strong Consistency by Default

Against a single PostgreSQL primary, FraiseQL is **immediately consistent**: a
committed write is visible to the very next read.

```graphql
mutation { updateUser(input: { id: "...", name: "Alice" }) { ... } }
query { user(id: "...") { name } }  # Sees "Alice" immediately
```

If you need eventual consistency for a particular workload (for example fan-out to
external systems or read offloading to replicas), build it explicitly with
subscriptions plus downstream services, or with a replica deployment as described
in section 3.4. FraiseQL itself does not silently relax consistency.

---

## 9. Consistency Levels by Operation

| Operation | Consistency (single primary) | Isolation | Write Atomicity | Read Freshness |
|-----------|------------------------------|-----------|-----------------|----------------|
| **Query** | Strong | PostgreSQL level | N/A | Immediate |
| **Mutation** | Strong | PostgreSQL level | Atomic (per `fn_`) | Immediate |
| **Subscription** | Per-entity ordered | PostgreSQL level | N/A | At-least-once |
| **Cached Query** | Within TTL | PostgreSQL level | N/A | At most TTL stale |
| **Replica Read** | Eventual (replica lag) | PostgreSQL level | N/A | Lag-bounded |

---

## 10. Consistency Anti-Patterns

### 10.1 Assuming Stale Reads Against the Primary

**Wrong:**

```python
# This is NOT necessary against a single primary.
mutation { updateUser(input: { id: "...", name: "Alice" }) { ... } }
time.sleep(1)  # waiting for "propagation"
result = query { user(id: "...") { name } }
```

**Right:**

```python
mutation { updateUser(input: { id: "...", name: "Alice" }) { ... } }
result = query { user(id: "...") { name } }  # Sees "Alice" immediately
```

### 10.2 Assuming Global Event Ordering

**Wrong:**

```graphql
subscription {
  orderUpdated { id status }
  userUpdated { id name }
}
# Assuming events arrive in global timestamp order.
```

**Right:**

```graphql
subscription { orderUpdated { id status timestamp } }
```

```python
# Order events on the client using their timestamps.
events.sort(key=lambda e: e["timestamp"])
```

### 10.3 Expecting FraiseQL to Route to Replicas

**Wrong:** Assuming FraiseQL load-balances reads across replicas or fails over
automatically.

**Right:** FraiseQL connects to one `database_url`. Read/write splitting,
failover, and replica routing belong to your PostgreSQL deployment or a connection
proxy in front of it.

---

## Summary

FraiseQL v1 consistency model:

- **Single PostgreSQL primary:** strong, immediately consistent reads after
  committed writes.
- **Isolation:** whatever PostgreSQL is configured to enforce (Read Committed by
  default, Serializable available).
- **Mutations:** atomic per `fn_` function; all-or-nothing.
- **Durability:** PostgreSQL write-ahead logging.
- **Subscriptions:** per-entity ordered, at-least-once delivery.
- **Caching:** invalidated on write, otherwise bounded by TTL.
- **Replicas/failover:** a PostgreSQL deployment concern, not a FraiseQL feature.

**Golden rule:** What PostgreSQL guarantees, FraiseQL guarantees. Nothing more,
nothing less.

---

## Related Documents

- [Error Handling Model](./error-handling-model.md)
- [Failure Modes and Recovery](./failure-modes-and-recovery.md)
- [Versioning Strategy](./versioning-strategy.md)
- [Subscriptions](../realtime/subscriptions.md)
- [View Selection Guide](../database/view-selection-guide.md)
- [Performance Characteristics](../../foundation/12-performance-characteristics.md)
- [Schema Conventions](../../specs/schema-conventions.md)
