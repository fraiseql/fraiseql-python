---
title: Consistency Model in FraiseQL
description: How FraiseQL gives you strong consistency on a single PostgreSQL database — MVCC, transactions, read-your-writes, RLS, and the CQRS read/write split.
keywords: ["consistency", "transactions", "mvcc", "postgresql", "cqrs", "rls"]
tags: ["documentation", "guide"]
---

# Consistency Model in FraiseQL

**Status:** Production Ready
**Audience:** Architects, Developers
**Reading Time:** 10-12 minutes

## Prerequisites

**Required Knowledge:**

- ACID properties and database transactions
- PostgreSQL MVCC (Multi-Version Concurrency Control) basics
- Transaction isolation levels (Read Committed, Repeatable Read, Serializable)
- The FraiseQL CQRS split: read views (`v_`/`tv_`) and write functions (`fn_`)
- Row-Level Security (RLS) for multi-tenancy

**Required Software:**

- FraiseQL v1
- PostgreSQL 14+

## Where Consistency Comes From

FraiseQL is a **single-database** framework: every query and mutation runs against **one PostgreSQL database**. There is no cross-database replication, no federation, and no distributed transaction coordinator to reason about. As a result, FraiseQL's consistency guarantees are exactly **PostgreSQL's guarantees** — strong, ACID, MVCC-based — with no extra machinery to weaken them.

| Guarantee | Provided? | How |
|-----------|-----------|-----|
| **ACID transactions** | Yes | Each mutation runs inside a single PostgreSQL transaction |
| **Strong read consistency** | Yes | MVCC snapshots; no dirty or non-repeatable reads inside a transaction |
| **Read-your-writes** | Yes (within a transaction) | A write and a subsequent read in the same transaction see the same snapshot |
| **Tenant isolation** | Yes | Row-Level Security policies driven by session GUCs |

Because there is exactly one source of truth, you never have to ask "which replica did I read from?" or "have my writes propagated yet?" — those questions belong to multi-database systems, not to FraiseQL v1.

---

## The CQRS Split and What It Means for Consistency

FraiseQL separates **reads** from **writes**, but both sides hit the same PostgreSQL database, so they stay consistent:

- **Reads (`@fraiseql.query`)** call `db.find` / `db.find_one` against `v_`/`tv_` views. A `v_` view is a plain `SELECT` that builds a `data` JSONB column — it always reflects the latest committed state of the underlying `tb_` tables. A `tv_` view is a table-backed projection refreshed by functions/triggers in the same database.
- **Writes (`@fraiseql.mutation`)** call `fn_` PostgreSQL functions via `db.execute_function`. The function performs validation plus the write inside a transaction and returns a JSONB success/failure payload.

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.query
async def user(info, id: ID) -> "User | None":
    db = info.context["db"]
    return await db.find_one("v_user", id=id)   # reads latest committed state

@fraiseql.mutation
async def update_user(info, input: "UpdateUserInput") -> "UpdateUserSuccess | UpdateUserError":
    db = info.context["db"]
    result = await db.execute_function("fn_update_user", {"id": input.id, "name": input.name})
    if not result.get("success"):
        return UpdateUserError(message=result.get("message", "failed"))
    return UpdateUserSuccess(user=User(**result["user"]))
```

**Key point:** Because a `v_` view reads directly from the same tables the `fn_` function wrote to, a query issued *after* a mutation commits observes that mutation's effects. There is no replication lag to wait out.

---

## Mutations Are Synchronous and Transactional

When a client sends a mutation, FraiseQL executes the `fn_` function inside a PostgreSQL transaction and **blocks until it commits or rolls back**. The client receives the final result — never a "queued, check back later" acknowledgement.

```graphql
mutation CreateOrder($input: CreateOrderInput!) {
  createOrder(input: $input) {
    id
    status
    items { id quantity }
  }
}
```

What happens inside PostgreSQL:

1. FraiseQL opens a transaction and sets session GUCs (tenant, user) with `SET LOCAL`.
2. The `fn_create_order` function validates input, reserves inventory, and writes the order — all in the same transaction.
3. On success, the transaction commits atomically and the result is returned.
4. On any error, the transaction rolls back; no partial state is left behind.

This is the classic ACID guarantee: **all-or-nothing**. The atomicity that older versions of this page attributed to a distributed "SAGA" is, in v1, simply the atomicity of a single PostgreSQL transaction — write your multi-step logic inside one `fn_` function and it either fully applies or fully rolls back.

---

## Isolation: What You See Inside a Transaction

PostgreSQL's default isolation level is **Read Committed**: each statement sees a fresh snapshot of committed data. For stronger guarantees you can run your `fn_` function under a stricter level:

```sql
-- Inside fn_transfer_inventory, enforce repeatable reads for the duration:
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;

-- Or, for full serializability when correctness is critical:
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
UPDATE tb_inventory SET qty = qty - $1 WHERE fk_warehouse = $2;
SELECT qty FROM tb_inventory WHERE fk_warehouse = $2;  -- sees the decremented value
```

| Isolation level | Prevents | Use when |
|-----------------|----------|----------|
| **Read Committed** (default) | Dirty reads | General CRUD, the common case |
| **Repeatable Read** | Dirty + non-repeatable reads | Multi-statement reads that must agree |
| **Serializable** | All anomalies, incl. write skew | Financial/inventory invariants |

**Read-your-writes:** Within a single transaction, a read after a write always sees that write — that is MVCC working on one snapshot. Across separate requests, a query sees every mutation that has already **committed**.

---

## Multi-Tenant Isolation via Row-Level Security

Tenant isolation in FraiseQL v1 is enforced by **PostgreSQL Row-Level Security**, not by application-level filtering you have to remember to apply. The flow is:

1. The request carries `tenant_id` in `info.context`.
2. FraiseQL's CQRS repository issues `SET LOCAL app.tenant_id = …` per transaction.
3. Your RLS policies read `current_setting('app.tenant_id')` and scope every row automatically.

```sql
-- Enable RLS on the write table
ALTER TABLE tb_order ENABLE ROW LEVEL SECURITY;

-- Every read/write is automatically scoped to the current tenant
CREATE POLICY tenant_isolation ON tb_order
  USING (fk_tenant = current_setting('app.tenant_id')::uuid);
```

Reads can additionally pass `mandatory_filters` to belt-and-braces the scope:

```python
@fraiseql.query
async def orders(info) -> list["Order"]:
    db = info.context["db"]
    return await db.find("v_order", mandatory_filters={"tenant_id": info.context["tenant_id"]})
```

**Guarantee:** No query can leak Tenant A's rows to Tenant B — the database enforces it, and the GUC is reset per transaction so it cannot bleed across requests.

---

## Caching and Consistency

FraiseQL's optional caching layer (`src/fraiseql/caching/`) keeps cached results consistent with the database through **cascade invalidation**, not a separate event bus.

- `ResultCache` / `CachedRepository` store query results keyed by their SQL and arguments.
- `CascadeRule` (and `setup_auto_cascade_rules` / `SchemaAnalyzer`) describe which cache entries a given write invalidates, so a mutation drops the now-stale entries.
- The cache is PostgreSQL-backed (`PostgresCache`), so it lives in the same database as your data.

```python
from fraiseql.caching import CachedRepository, CascadeRule, cached_query
```

When a `fn_` mutation changes a table, the configured cascade rules invalidate the dependent cached queries, so the next read re-fetches fresh data. There is no CDC stream, no message broker, and no eventual-consistency window introduced by the cache — invalidation happens as part of serving the write. See [Cascade Best Practices](./cascade-best-practices.md) for how to define rules.

---

## When FraiseQL's Consistency Model Fits

| Domain | Why it fits |
|--------|-------------|
| **Banking / Payments** | Atomic transactions prevent double-charges and lost writes |
| **Inventory Management** | Serializable transactions prevent overselling |
| **Healthcare** | ACID guarantees keep patient records correct |
| **Financial Reporting** | Strong consistency satisfies audit requirements |
| **Multi-tenant SaaS** | RLS guarantees one tenant's data never bleeds into another's |

If your workload genuinely tolerates stale reads at massive scale (approximate like-counts, presence indicators, high-volume time-series), a purpose-built eventually-consistent store may suit those *specific* features better — but for the transactional core of an application, single-database PostgreSQL consistency is exactly what you want, and what FraiseQL gives you.

---

## Troubleshooting

### "A read right after a mutation shows old data"

**Cause:** The reading query ran in a *different* transaction that started before the mutation committed, or it hit a cached entry that was not invalidated.

**Fix:**

1. Confirm the mutation actually committed (check the `fn_` function's returned `success` payload).
2. If using the cache, verify a `CascadeRule` covers the mutated table — see [Cascade Best Practices](./cascade-best-practices.md).
3. Run reads after the mutation response is received, not concurrently.

### "Lost update / two mutations overwrite each other"

**Cause:** Concurrent transactions under Read Committed both read the old value before writing.

**Fix:**

- Raise the `fn_` function to `SERIALIZABLE` (or `REPEATABLE READ`) and retry on serialization failures.
- Use `SELECT … FOR UPDATE` inside the function to lock the rows you intend to modify.
- Add a version column and check it in the `UPDATE … WHERE version = $expected` clause (optimistic locking).

### "Tenant data leaked across tenants"

**Cause:** RLS is not enabled on the table, or the policy does not read `current_setting('app.tenant_id')`.

**Fix:**

1. Confirm `ALTER TABLE … ENABLE ROW LEVEL SECURITY` and a policy exist on every tenant-scoped table.
2. Verify `info.context` carries `tenant_id` so FraiseQL emits `SET LOCAL app.tenant_id`.
3. Add `mandatory_filters={"tenant_id": …}` on sensitive reads as defense-in-depth.

### "High lock contention on hot rows"

**Cause:** Many simultaneous mutations target the same row.

**Diagnosis:**

```sql
SELECT * FROM pg_locks WHERE NOT granted;
```

**Fix:**

- Add indexes on the columns your `fn_` functions filter on.
- Batch updates where possible to reduce transaction count.
- Consider partitioning frequently updated tables.

---

## See Also

**Architecture:**

- [CQRS Design](../architecture/cqrs-design.md) — the read-view / write-function split this model builds on

**Operational:**

- [Production Deployment](./production-deployment.md) — running the FastAPI app in production
- [Monitoring & Observability](./monitoring.md) — detecting lock contention and slow transactions
- [Performance Tuning](../operations/performance-tuning-runbook.md) — optimizing transactions and views

**Related Guides:**

- [Cascade Best Practices](./cascade-best-practices.md) — keeping cached results consistent
- [Authorization Quick Start](./authorization-quick-start.md) — RLS and field-level authorization
- [Common Gotchas](./common-gotchas.md) — consistency pitfalls and solutions

**Troubleshooting:**

- [Troubleshooting Guide](./troubleshooting.md) — FAQ and solutions
