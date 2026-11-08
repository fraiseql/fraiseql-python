---
title: Event Sourcing
description: Event sourcing patterns with audit logs and event streams
tags:
  - event-sourcing
  - audit
  - events
  - CQRS
  - patterns
---

# Event Sourcing & Audit Trails

Event sourcing patterns in FraiseQL: entity change logs, temporal queries, audit trails, and CQRS with event-driven architectures.

## Overview

Event sourcing stores all changes to application state as a sequence of events. FraiseQL supports event sourcing through entity change logs, Debezium-style before/after snapshots, and temporal query capabilities.

**Key Patterns:**

- Entity Change Log as event store
- Before/after snapshots (Debezium pattern)
- Event replay capabilities
- Temporal queries (state at timestamp)
- Audit trail patterns
- CQRS with event sourcing

## Entity Change Log

### Schema Design

Complete audit log capturing all entity changes:

```sql
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE audit.entity_change_log (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    changed_by UUID,  -- User who made the change
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    before_snapshot JSONB,  -- State before change
    after_snapshot JSONB,   -- State after change
    changed_fields JSONB,   -- Only changed fields
    metadata JSONB,         -- Additional context
    transaction_id BIGINT,  -- Group related changes
    correlation_id UUID,    -- Trace across services
    CONSTRAINT valid_snapshots CHECK (
        (operation = 'INSERT' AND before_snapshot IS NULL) OR
        (operation = 'DELETE' AND after_snapshot IS NULL) OR
        (operation = 'UPDATE' AND before_snapshot IS NOT NULL AND after_snapshot IS NOT NULL)
    )
);

-- Indexes for common queries
CREATE INDEX idx_entity_change_log_entity ON audit.entity_change_log(entity_type, entity_id, changed_at DESC);
CREATE INDEX idx_entity_change_log_user ON audit.entity_change_log(changed_by, changed_at DESC);
CREATE INDEX idx_entity_change_log_time ON audit.entity_change_log(changed_at DESC);
CREATE INDEX idx_entity_change_log_tx ON audit.entity_change_log(transaction_id);
CREATE INDEX idx_entity_change_log_correlation ON audit.entity_change_log(correlation_id);

-- GIN index for JSONB searches
CREATE INDEX idx_entity_change_log_before ON audit.entity_change_log USING GIN (before_snapshot);
CREATE INDEX idx_entity_change_log_after ON audit.entity_change_log USING GIN (after_snapshot);
```

### Automatic Change Tracking

PostgreSQL trigger to automatically log changes:

```sql
CREATE OR REPLACE FUNCTION audit.log_entity_change()
RETURNS TRIGGER AS $$
DECLARE
    v_changed_fields JSONB;
    v_user_id UUID;
    v_correlation_id UUID;
BEGIN
    -- Extract user ID from session
    v_user_id := NULLIF(current_setting('app.current_user_id', TRUE), '')::UUID;
    v_correlation_id := NULLIF(current_setting('app.correlation_id', TRUE), '')::UUID;

    -- Calculate changed fields for UPDATE
    IF TG_OP = 'UPDATE' THEN
        SELECT jsonb_object_agg(key, value)
        INTO v_changed_fields
        FROM jsonb_each(to_jsonb(NEW))
        WHERE value IS DISTINCT FROM (to_jsonb(OLD) -> key);
    END IF;

    INSERT INTO audit.entity_change_log (
        entity_type,
        entity_id,
        operation,
        changed_by,
        before_snapshot,
        after_snapshot,
        changed_fields,
        transaction_id,
        correlation_id
    ) VALUES (
        TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
        CASE
            WHEN TG_OP = 'DELETE' THEN OLD.id
            ELSE NEW.id
        END,
        TG_OP,
        v_user_id,
        CASE
            WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD)
            ELSE NULL
        END,
        CASE
            WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW)
            ELSE NULL
        END,
        v_changed_fields,
        txid_current(),
        v_correlation_id
    );

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Attach to tables
CREATE TRIGGER trg_orders_change_log
    AFTER INSERT OR UPDATE OR DELETE ON orders.orders
    FOR EACH ROW EXECUTE FUNCTION audit.log_entity_change();

CREATE TRIGGER trg_order_items_change_log
    AFTER INSERT OR UPDATE OR DELETE ON orders.order_items
    FOR EACH ROW EXECUTE FUNCTION audit.log_entity_change();
```

### Change Log Repository

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row

@dataclass
class EntityChange:
    """Entity change event."""
    id: int
    entity_type: str
    entity_id: str
    operation: str
    changed_by: str | None
    changed_at: datetime
    before_snapshot: dict[str, Any] | None
    after_snapshot: dict[str, Any] | None
    changed_fields: dict[str, Any] | None
    metadata: dict[str, Any] | None
    transaction_id: int
    correlation_id: str | None

class EntityChangeLogRepository:
    """Repository for entity change logs."""

    def __init__(self, db_pool):
        # A psycopg AsyncConnectionPool, e.g. fraiseql.fastapi.dependencies.get_db_pool()
        self.db = db_pool

    async def get_entity_history(
        self,
        entity_type: str,
        entity_id: str,
        limit: int = 100
    ) -> list[EntityChange]:
        """Get complete history for an entity."""
        async with self.db.connection() as conn:
            result = await conn.cursor(row_factory=dict_row).execute("""
                SELECT * FROM audit.entity_change_log
                WHERE entity_type = %s AND entity_id = %s
                ORDER BY changed_at DESC
                LIMIT %s
            """, (entity_type, entity_id, limit))

            return [
                EntityChange(**row)
                for row in await result.fetchall()
            ]

    async def get_changes_by_user(
        self,
        user_id: str,
        limit: int = 100
    ) -> list[EntityChange]:
        """Get all changes made by a user."""
        async with self.db.connection() as conn:
            result = await conn.cursor(row_factory=dict_row).execute("""
                SELECT * FROM audit.entity_change_log
                WHERE changed_by = %s
                ORDER BY changed_at DESC
                LIMIT %s
            """, (user_id, limit))

            return [EntityChange(**row) for row in await result.fetchall()]

    async def get_changes_in_transaction(
        self,
        transaction_id: int
    ) -> list[EntityChange]:
        """Get all changes in a transaction."""
        async with self.db.connection() as conn:
            result = await conn.cursor(row_factory=dict_row).execute("""
                SELECT * FROM audit.entity_change_log
                WHERE transaction_id = %s
                ORDER BY id
            """, (transaction_id,))

            return [EntityChange(**row) for row in await result.fetchall()]

    async def get_entity_at_time(
        self,
        entity_type: str,
        entity_id: str,
        at_time: datetime
    ) -> dict[str, Any] | None:
        """Get entity state at specific point in time."""
        async with self.db.connection() as conn:
            result = await conn.cursor(row_factory=dict_row).execute("""
                SELECT after_snapshot
                FROM audit.entity_change_log
                WHERE entity_type = %s
                  AND entity_id = %s
                  AND changed_at <= %s
                  AND operation != 'DELETE'
                ORDER BY changed_at DESC
                LIMIT 1
            """, (entity_type, entity_id, at_time))

            row = await result.fetchone()
            return row["after_snapshot"] if row else None
```

## Before/After Snapshots

Debezium-style change data capture:

### GraphQL Queries for Audit

```python
import fraiseql
from fraiseql.fastapi.dependencies import get_db_pool

@fraiseql.type
class EntityChange:
    id: int
    entity_type: str
    entity_id: str
    operation: str
    changed_by: str | None
    changed_at: datetime
    before_snapshot: dict | None
    after_snapshot: dict | None
    changed_fields: dict | None
    metadata: dict | None
    transaction_id: int
    correlation_id: str | None

@fraiseql.query
async def get_order_history(info, order_id: str) -> list[EntityChange]:
    """Get complete audit trail for an order."""
    repo = EntityChangeLogRepository(get_db_pool())
    return await repo.get_entity_history("orders.orders", order_id)

@fraiseql.query
async def get_order_at_time(info, order_id: str, at_time: datetime) -> dict | None:
    """Get order state at specific point in time."""
    repo = EntityChangeLogRepository(get_db_pool())
    return await repo.get_entity_at_time("orders.orders", order_id, at_time)

@fraiseql.query
async def get_user_activity(info, user_id: str, limit: int = 50) -> list[EntityChange]:
    """Get all changes made by a user."""
    repo = EntityChangeLogRepository(get_db_pool())
    return await repo.get_changes_by_user(user_id, limit)
```

## Event Replay

Rebuild entity state from event log:

```python
from datetime import datetime
from decimal import Decimal

from psycopg.rows import dict_row

from fraiseql.fastapi.dependencies import get_db_pool
from fraiseql.types import ID

class OrderEventReplayer:
    """Replay order events to rebuild state."""

    @staticmethod
    async def replay_to_state(
        entity_id: str,
        up_to_time: datetime | None = None
    ) -> dict:
        """Replay events to rebuild order state."""
        repo = EntityChangeLogRepository(get_db_pool())

        async with repo.db.connection() as conn:
            query = """
                SELECT operation, after_snapshot, changed_at
                FROM audit.entity_change_log
                WHERE entity_type = 'orders.orders'
                  AND entity_id = %s
            """
            params = [entity_id]

            if up_to_time:
                query += " AND changed_at <= %s"
                params.append(up_to_time)

            query += " ORDER BY changed_at ASC"

            result = await conn.cursor(row_factory=dict_row).execute(query, params)
            events = await result.fetchall()

        if not events:
            return None

        # Start with first event (INSERT)
        state = dict(events[0]["after_snapshot"])

        # Apply subsequent changes
        for event in events[1:]:
            if event["operation"] == "UPDATE":
                state.update(event["after_snapshot"])
            elif event["operation"] == "DELETE":
                return None  # Entity deleted

        return state

    @staticmethod
    async def rebuild_aggregate(entity_id: str) -> Order:
        """Rebuild complete Order aggregate from events."""
        state = await OrderEventReplayer.replay_to_state(entity_id)
        if not state:
            return None

        # Rebuild Order object
        order = Order(
            id=state["id"],
            customer_id=state["customer_id"],
            total=Decimal(str(state["total"])),
            status=state["status"],
            created_at=state["created_at"],
            updated_at=state["updated_at"]
        )

        # Rebuild order items from their change logs
        items_repo = EntityChangeLogRepository(get_db_pool())
        async with items_repo.db.connection() as conn:
            result = await conn.cursor(row_factory=dict_row).execute("""
                SELECT DISTINCT entity_id
                FROM audit.entity_change_log
                WHERE entity_type = 'orders.order_items'
                  AND (after_snapshot->>'order_id')::UUID = %s
            """, (entity_id,))

            item_ids = [row["entity_id"] for row in await result.fetchall()]

        for item_id in item_ids:
            item_state = await OrderEventReplayer.replay_to_state(item_id)
            if item_state:  # Not deleted
                order.items.append(OrderItem(**item_state))

        return order
```

## Temporal Queries

Query entity state at any point in time:

```python
from psycopg.rows import dict_row

import fraiseql
from fraiseql.fastapi.dependencies import get_db_pool

@fraiseql.query
async def get_order_timeline(
    info,
    order_id: str,
    from_time: datetime,
    to_time: datetime
) -> list[dict]:
    """Get order state snapshots over time."""
    repo = EntityChangeLogRepository(get_db_pool())

    async with repo.db.connection() as conn:
        result = await conn.cursor(row_factory=dict_row).execute("""
            SELECT
                changed_at,
                operation,
                after_snapshot,
                changed_by
            FROM audit.entity_change_log
            WHERE entity_type = 'orders.orders'
              AND entity_id = %s
              AND changed_at BETWEEN %s AND %s
            ORDER BY changed_at ASC
        """, (order_id, from_time, to_time))

        return [dict(row) for row in await result.fetchall()]

@fraiseql.query
async def compare_states(
    info,
    order_id: str,
    time1: datetime,
    time2: datetime
) -> dict:
    """Compare order state at two different times."""
    repo = EntityChangeLogRepository(get_db_pool())

    state1 = await repo.get_entity_at_time("orders.orders", order_id, time1)
    state2 = await repo.get_entity_at_time("orders.orders", order_id, time2)

    # Calculate diff
    changes = {}
    all_keys = set(state1.keys()) | set(state2.keys())

    for key in all_keys:
        val1 = state1.get(key)
        val2 = state2.get(key)
        if val1 != val2:
            changes[key] = {"from": val1, "to": val2}

    return {
        "state_at_time1": state1,
        "state_at_time2": state2,
        "changes": changes
    }
```

## Audit Trails

### Complete Audit Dashboard

```python
from psycopg.rows import dict_row

import fraiseql
from fraiseql.fastapi.dependencies import get_db_pool

@fraiseql.type
class AuditSummary:
    total_changes: int
    changes_by_operation: dict[str, int]
    changes_by_user: dict[str, int]
    recent_changes: list[EntityChange]

@fraiseql.query
@requires_role("auditor")
async def get_audit_summary(
    info,
    entity_type: str | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None
) -> AuditSummary:
    """Get comprehensive audit summary."""
    filters = {"entity_type": entity_type, "from_time": from_time, "to_time": to_time}
    async with get_db_pool().connection() as conn:
        # Total changes
        result = await conn.cursor(row_factory=dict_row).execute("""
            SELECT COUNT(*) as total
            FROM audit.entity_change_log
            WHERE (%(entity_type)s::TEXT IS NULL OR entity_type = %(entity_type)s)
              AND (%(from_time)s::TIMESTAMPTZ IS NULL OR changed_at >= %(from_time)s)
              AND (%(to_time)s::TIMESTAMPTZ IS NULL OR changed_at <= %(to_time)s)
        """, filters)
        total = (await result.fetchone())["total"]

        # By operation
        result = await conn.cursor(row_factory=dict_row).execute("""
            SELECT operation, COUNT(*) as count
            FROM audit.entity_change_log
            WHERE (%(entity_type)s::TEXT IS NULL OR entity_type = %(entity_type)s)
              AND (%(from_time)s::TIMESTAMPTZ IS NULL OR changed_at >= %(from_time)s)
              AND (%(to_time)s::TIMESTAMPTZ IS NULL OR changed_at <= %(to_time)s)
            GROUP BY operation
        """, filters)
        by_operation = {row["operation"]: row["count"] for row in await result.fetchall()}

        # By user
        result = await conn.cursor(row_factory=dict_row).execute("""
            SELECT changed_by::TEXT, COUNT(*) as count
            FROM audit.entity_change_log
            WHERE changed_by IS NOT NULL
              AND (%(entity_type)s::TEXT IS NULL OR entity_type = %(entity_type)s)
              AND (%(from_time)s::TIMESTAMPTZ IS NULL OR changed_at >= %(from_time)s)
              AND (%(to_time)s::TIMESTAMPTZ IS NULL OR changed_at <= %(to_time)s)
            GROUP BY changed_by
            ORDER BY count DESC
            LIMIT 10
        """, filters)
        by_user = {row["changed_by"]: row["count"] for row in await result.fetchall()}

        # Recent changes
        result = await conn.cursor(row_factory=dict_row).execute("""
            SELECT * FROM audit.entity_change_log
            WHERE (%(entity_type)s::TEXT IS NULL OR entity_type = %(entity_type)s)
              AND (%(from_time)s::TIMESTAMPTZ IS NULL OR changed_at >= %(from_time)s)
              AND (%(to_time)s::TIMESTAMPTZ IS NULL OR changed_at <= %(to_time)s)
            ORDER BY changed_at DESC
            LIMIT 50
        """, filters)
        recent = [EntityChange(**row) for row in await result.fetchall()]

    return AuditSummary(
        total_changes=total,
        changes_by_operation=by_operation,
        changes_by_user=by_user,
        recent_changes=recent
    )
```

## CQRS Pattern

**[CQRS (Command Query Responsibility Segregation)](../core/concepts-glossary.md#cqrs-command-query-responsibility-segregation)** separates read and write models using event sourcing:

```python
from psycopg.rows import dict_row

from fraiseql.fastapi.dependencies import get_db_pool

# Write Model (Command Side)
class OrderCommandHandler:
    """Handle order commands, generate events."""

    async def create_order(self, customer_id: str) -> str:
        """Create order - generates OrderCreated event."""
        order_id = str(uuid4())

        async with get_db_pool().connection() as conn:
            await conn.execute("""
                INSERT INTO orders.orders (id, customer_id, total, status)
                VALUES (%s, %s, 0, 'draft')
            """, (order_id, customer_id))

        # Event automatically logged via trigger
        return order_id

    async def add_item(self, order_id: str, product_id: str, quantity: int, price: Decimal):
        """Add item - generates ItemAdded event."""
        async with get_db_pool().connection() as conn:
            await conn.execute("""
                INSERT INTO orders.order_items (id, order_id, product_id, quantity, price, total)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (str(uuid4()), order_id, product_id, quantity, price, price * quantity))

            # Update order total
            await conn.execute("""
                UPDATE orders.orders
                SET total = (
                    SELECT SUM(total) FROM orders.order_items WHERE order_id = %(order_id)s
                )
                WHERE id = %(order_id)s
            """, {"order_id": order_id})

# Read Model (Query Side)
class OrderQueryModel:
    """Optimized read model for order queries."""

    async def get_order_summary(self, order_id: str) -> dict:
        """Get denormalized order summary."""
        async with get_db_pool().connection() as conn:
            result = await conn.cursor(row_factory=dict_row).execute("""
                SELECT
                    o.id,
                    o.customer_id,
                    o.total,
                    o.status,
                    o.created_at,
                    COUNT(oi.id) as item_count,
                    json_agg(
                        json_build_object(
                            'product_id', oi.product_id,
                            'quantity', oi.quantity,
                            'price', oi.price
                        )
                    ) as items
                FROM orders.orders o
                LEFT JOIN orders.order_items oi ON oi.order_id = o.id
                WHERE o.id = %s
                GROUP BY o.id
            """, (order_id,))

            return dict(await result.fetchone())
```

## Event Versioning

Handle event schema evolution:

```python
@dataclass
class VersionedEvent:
    """Event with schema version."""
    version: int
    event_type: str
    payload: dict

class EventUpgrader:
    """Upgrade old event schemas to current version."""

    @staticmethod
    def upgrade_order_created(event: dict, from_version: int) -> dict:
        """Upgrade OrderCreated event schema."""
        if from_version == 1:
            # v1 -> v2: Added customer_email
            event["customer_email"] = None
            from_version = 2

        if from_version == 2:
            # v2 -> v3: Added shipping_address
            event["shipping_address"] = None
            from_version = 3

        return event

    @staticmethod
    def upgrade_event(event: EntityChange) -> dict:
        """Upgrade event to current schema version."""
        current_version = 3
        event_version = event.metadata.get("schema_version", 1) if event.metadata else 1

        if event_version == current_version:
            return event.after_snapshot

        # Apply upgrades
        upgraded = dict(event.after_snapshot)
        if "OrderCreated" in event.entity_type:
            upgraded = EventUpgrader.upgrade_order_created(upgraded, event_version)

        return upgraded
```

## Performance Optimization

### Partitioning

Partition audit logs by time for better performance:

```sql
-- Partition by month
CREATE TABLE audit.entity_change_log (
    id BIGSERIAL,
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- ... other fields
) PARTITION BY RANGE (changed_at);

-- Create monthly partitions
CREATE TABLE audit.entity_change_log_2024_01 PARTITION OF audit.entity_change_log
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE TABLE audit.entity_change_log_2024_02 PARTITION OF audit.entity_change_log
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

-- Auto-create partitions
CREATE OR REPLACE FUNCTION audit.create_monthly_partition(target_date DATE)
RETURNS VOID AS $$
DECLARE
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
BEGIN
    start_date := DATE_TRUNC('month', target_date);
    end_date := start_date + INTERVAL '1 month';
    partition_name := 'entity_change_log_' || TO_CHAR(start_date, 'YYYY_MM');

    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS audit.%I PARTITION OF audit.entity_change_log FOR VALUES FROM (%L) TO (%L)',
        partition_name, start_date, end_date
    );
END;
$$ LANGUAGE plpgsql;
```

### Snapshot Strategy

Periodically snapshot aggregates to avoid full replay:

```sql
CREATE TABLE audit.entity_snapshots (
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    snapshot_data JSONB NOT NULL,
    last_change_id BIGINT NOT NULL,
    PRIMARY KEY (entity_type, entity_id, snapshot_at)
);

-- Create snapshot
INSERT INTO audit.entity_snapshots (entity_type, entity_id, snapshot_at, snapshot_data, last_change_id)
SELECT
    entity_type,
    entity_id,
    NOW(),
    after_snapshot,
    id
FROM audit.entity_change_log
WHERE entity_type = 'orders.orders'
  AND entity_id = '...'
  AND operation != 'DELETE'
ORDER BY changed_at DESC
LIMIT 1;
```

## Next Steps

- [Bounded Contexts](bounded-contexts.md) - Event-driven context integration
- [CQRS](../advanced/database-patterns.md) - Command Query Responsibility Segregation
- [Monitoring](../production/monitoring.md) - Event sourcing metrics
- [Performance](../performance/index.md) - Audit log optimization
