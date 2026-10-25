<!-- Skip to main content -->
---

title: Enterprise Audit Logging Documentation
description: An append-only audit_events table whose rows PostgreSQL hashes and signs into a chain, and AuditLogger to write them
keywords: []
tags: ["documentation", "reference"]
---

# Enterprise Audit Logging Documentation

**Topic**: Audit Event Logging & Chain Verification

---

## Overview

`fraiseql.enterprise` ships an audit trail kept in PostgreSQL:

- **`audit_events`**: one row per event (`event_type`, `event_data` JSONB, `user_id`,
  `tenant_id`, `timestamp`, `ip_address`).
- **A hash chain built by PostgreSQL**: a `BEFORE INSERT` trigger sets each row's
  `previous_hash` (the latest `event_hash` of the same tenant), its `event_hash`
  (SHA-256 over the previous hash and the event data) and its `signature`
  (HMAC-SHA256 of the hash with the active key of `audit_signing_keys`).
- **`verify_audit_chain()`**: an SQL function that recomputes the hashes.
- **`AuditLogger`**: a small Python class that inserts events, one at a time or in
  batches, through a `FraiseQLRepository`.

Nothing logs events on its own: your code calls `AuditLogger.log_event` (or inserts
into `audit_events`) where something should be audited.

---

## Setup

The schema is in `migrations/001_audit_tables.sql` of the installed
`fraiseql.enterprise` package. FraiseQL doesn't apply it: run it once per database,
as part of your migrations.

```bash
SQL=$(python -c "import fraiseql.enterprise, pathlib; print(pathlib.Path(fraiseql.enterprise.__file__).parent / 'migrations' / '001_audit_tables.sql')")
psql "$DATABASE_URL" -f "$SQL"
```

Then, in SQL:

```sql
-- The signature needs an active signing key; without one an insert fails with
-- "No active signing key available". Keep the real key in a secrets store.
INSERT INTO audit_signing_keys (key_value) VALUES ('replace-with-a-secret-key');
```

The file needs the `pgcrypto` extension (it runs `CREATE EXTENSION IF NOT EXISTS
pgcrypto`). It can be run again: it keeps the rows and replaces the functions.

`audit_events` is a plain table, not partitioned. Before 1.31.0 the file also
installed a `create_audit_partition_trigger` that made every insert fail ("cannot
CREATE TABLE .. PARTITION OF"); running the 1.31.0 file again drops it. To partition
the table by month, create it partitioned yourself before running the file (`PARTITION
BY RANGE (timestamp)`, with `timestamp` in the primary key) and create the partitions
ahead of time, with pg_partman or a scheduled job: an insert trigger can't add the
partition its own row goes into.

---

## Logging Events

```python
from fraiseql.enterprise.audit.event_logger import AuditLogger

# repo: a FraiseQLRepository, e.g. info.context["db"] in a resolver
audit_logger = AuditLogger(repo, batch_size=100)

# Written at once; returns the event id (a UUID)
event_id = await audit_logger.log_event(
    "user.updated",
    {"user_id": "u-42", "changed_fields": ["email"]},
    user_id=None,  # a UUID string, or None
    tenant_id="11111111-1111-1111-1111-111111111111",
    ip_address="203.0.113.1",
)

# Batched: kept in memory until batch_size events are queued or flush_batch() runs
await audit_logger.log_event("user.login", {"method": "password"}, immediate=False)
await audit_logger.flush_batch()  # writes the batch in one transaction
```

`log_event(event_type, event_data, user_id=None, tenant_id=None, ip_address=None,
immediate=True)` takes any `event_type` string; there is no fixed list. `user_id` and
`tenant_id` are UUID columns, `ip_address` an `INET`. Queued events are lost if the
process stops before `flush_batch()`, so call it at shutdown.

In a resolver:

```python
import fraiseql
from fraiseql.enterprise.audit.event_logger import AuditLogger


@fraiseql.query
async def audited_ping(info) -> str:
    await AuditLogger(info.context["db"]).log_event(
        "ping.called",
        {"source": "graphql"},
        tenant_id=info.context.get("tenant_id"),
    )
    return "pong"
```

---

## Reading Events

Read the table with SQL (`db.run(DatabaseQuery(...))`, or any PostgreSQL client):

```sql
-- Recent events of a tenant
SELECT id, event_type, event_data, user_id, timestamp, ip_address
FROM audit_events
WHERE tenant_id = '11111111-1111-1111-1111-111111111111'
ORDER BY timestamp DESC
LIMIT 100;

-- Logins from one address
SELECT timestamp, user_id, event_data
FROM audit_events
WHERE event_type = 'user.login' AND ip_address = '203.0.113.1'
ORDER BY timestamp DESC;
```

## Verifying the Chain

```sql
SELECT event_id, event_timestamp, tenant_id, chain_valid, expected_hash, actual_hash
FROM verify_audit_chain();                       -- or verify_audit_chain(start, end)

-- Only the problems
SELECT * FROM verify_audit_chain() WHERE NOT chain_valid;

-- One tenant
SELECT * FROM verify_audit_chain()
WHERE tenant_id = '11111111-1111-1111-1111-111111111111';
```

`verify_audit_chain(start_timestamp, end_timestamp)` checks each tenant's chain on its
own, as the trigger builds them (events without a tenant form one more chain): it walks
a tenant's events in time order and recomputes each `event_hash` from the tenant's
event before it. With a `start_timestamp`, a tenant's first event in the range is
checked against that tenant's latest event before the range. An event whose data was
changed is reported invalid; so is the event after a deleted one. It doesn't check the
signatures. It returns the events tenant by tenant; add `ORDER BY event_timestamp` for
a single timeline.

Before 1.31.0 it walked all tenants as one chain, and reported valid events invalid as
soon as there was more than one tenant; running the 1.31.0 `001_audit_tables.sql` again
replaces it (the `tenant_id` column is new).

---

## Immutability

The file creates an `audit_events_insert_only` policy (`USING (false)`, `WITH CHECK
(true)`), which only takes effect once row-level security is enabled on the table
(`ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY`), and then hides the rows from
`SELECT` too for roles it applies to. A table owner or superuser bypasses it. To make
the table append-only for the application, grant its role `INSERT` (and `SELECT` if it
reads the events) but not `UPDATE` or `DELETE`.

---

## GraphQL Types

`fraiseql.enterprise.audit` also has `AuditEvent`, `AuditEventFilter`,
`AuditEventConnection`, `AuditQueries` and a `LogAuditEvent` mutation. They are
placeholders: `AuditQueries.audit_events` returns an empty connection,
`verify_audit_chain` returns `true`, and `LogAuditEvent` writes nothing. Expose your
own queries and mutations over the table instead.

---

## Bridging an Existing `tb_audit_log`

The file also defines `bridge_audit_to_chain()`, a trigger function that copies each
row inserted into a `tb_audit_log` table (with `pk_audit_log`, `operation_type`,
`entity_type`, `old_data`, `new_data`, `pk_organization`, ... columns) into
`audit_events`. It installs no trigger; to use it:

```sql
CREATE TRIGGER bridge_to_cryptographic_audit
    AFTER INSERT ON tenant.tb_audit_log
    FOR EACH ROW
    EXECUTE FUNCTION bridge_audit_to_chain();
```

`migrations/002_unified_audit.sql` describes another `audit_events` layout (CDC
columns, `tenant_id NOT NULL`, `log_and_return_mutation()`). It is not compatible with
`AuditLogger`, which writes the columns of `001_audit_tables.sql`: apply one of the two.

---

## See Also

- [RBAC](./rbac.md)
- [Production Security](../production/security.md)
