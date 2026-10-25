# tests/integration/enterprise/audit/test_audit_bridge.py

"""Test bridge between tenant.tb_audit_log and cryptographic audit_events.

This demonstrates how existing log_and_return_mutation() calls can automatically
benefit from cryptographic chain integrity by enabling the bridge trigger.
"""

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.enterprise


@pytest_asyncio.fixture(scope="function", loop_scope="function")
async def setup_bridge_schema(class_db_pool, test_schema) -> None:
    """Set up bridge schema and tenant.tb_audit_log table for testing."""
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        # Check if audit_events exists
        cur = await conn.execute(
            """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'audit_events' AND table_schema = current_schema()
                )
            """
        )
        exists = (await cur.fetchone())[0]

        if not exists:
            # Read and execute the migration
            migration_path = Path("src/fraiseql/enterprise/migrations/001_audit_tables.sql")
            migration_sql = migration_path.read_text()
            await conn.execute(migration_sql)

        # Disable partition trigger for tests
        await conn.execute(
            "ALTER TABLE audit_events DISABLE TRIGGER create_audit_partition_trigger"
        )

        # Ensure test signing key exists
        cur = await conn.execute(
            "SELECT COUNT(*) FROM audit_signing_keys WHERE key_value = %s",
            ["test-key-for-testing"],
        )
        key_exists = (await cur.fetchone())[0] > 0

        if not key_exists:
            await conn.execute(
                "INSERT INTO audit_signing_keys (key_value, active) VALUES (%s, %s)",
                ["test-key-for-testing", True],
            )

        # Create tenant schema and tb_audit_log if not exists
        await conn.execute("CREATE SCHEMA IF NOT EXISTS tenant")

        await conn.execute(
            """
                CREATE TABLE IF NOT EXISTS tenant.tb_audit_log (
                    pk_audit_log UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    pk_organization UUID NOT NULL,
                    user_id UUID,
                    entity_type TEXT NOT NULL,
                    entity_id UUID,
                    operation_type TEXT NOT NULL,
                    operation_subtype TEXT,
                    changed_fields TEXT[],
                    old_data JSONB,
                    new_data JSONB,
                    metadata JSONB,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    correlation_id UUID DEFAULT gen_random_uuid()
                )
            """
        )

        # Enable the bridge trigger for testing
        # First, drop if exists to avoid errors
        await conn.execute(
            """
                DROP TRIGGER IF EXISTS bridge_to_cryptographic_audit
                ON tenant.tb_audit_log
            """
        )

        await conn.execute(
            """
                CREATE TRIGGER bridge_to_cryptographic_audit
                    AFTER INSERT ON tenant.tb_audit_log
                    FOR EACH ROW
                    EXECUTE FUNCTION bridge_audit_to_chain()
            """
        )

        await conn.commit()


@pytest.mark.asyncio
async def test_bridge_automatically_populates_audit_events(db_repo, setup_bridge_schema) -> None:
    """Verify bridge trigger automatically creates audit_events from tb_audit_log."""
    import psycopg.types.json

    from fraiseql.db import DatabaseQuery

    # Simulate a mutation being logged via log_and_return_mutation()
    org_id = uuid4()
    user_id = uuid4()
    entity_id = uuid4()

    # Insert into tb_audit_log (simulating log_and_return_mutation() call)
    audit_log_result = await db_repo.run(
        DatabaseQuery(
            statement="""
                INSERT INTO tenant.tb_audit_log (
                    pk_organization, user_id, entity_type, entity_id,
                    operation_type, operation_subtype, changed_fields,
                    old_data, new_data, metadata
                ) VALUES (
                    %(org_id)s, %(user_id)s, %(entity_type)s, %(entity_id)s,
                    %(operation_type)s, %(operation_subtype)s, %(changed_fields)s,
                    %(old_data)s, %(new_data)s, %(metadata)s
                )
                RETURNING pk_audit_log
            """,
            params={
                "org_id": org_id,
                "user_id": user_id,
                "entity_type": "post",
                "entity_id": entity_id,
                "operation_type": "INSERT",
                "operation_subtype": "new",
                "changed_fields": ["title", "content"],
                "old_data": None,
                "new_data": psycopg.types.json.Jsonb(
                    {"title": "Test Post", "content": "Test content"}
                ),
                "metadata": psycopg.types.json.Jsonb({"business_actions": ["slug_generated"]}),
            },
            fetch_result=True,
        )
    )

    audit_log_id = audit_log_result[0]["pk_audit_log"]

    # Verify bridge automatically created entry in audit_events
    events = await db_repo.run(
        DatabaseQuery(
            statement="SELECT * FROM audit_events WHERE id = %(id)s",
            params={"id": audit_log_id},
            fetch_result=True,
        )
    )

    assert len(events) == 1
    event = events[0]

    # Verify data was bridged correctly
    assert event["event_type"] == "INSERT.new"
    assert event["tenant_id"] == org_id
    assert event["user_id"] == user_id

    # Verify event_data contains all tb_audit_log fields
    event_data = event["event_data"]
    assert event_data["entity_type"] == "post"
    assert event_data["entity_id"] == str(entity_id)
    assert event_data["operation_type"] == "INSERT"
    assert event_data["changed_fields"] == ["title", "content"]
    assert event_data["new_data"]["title"] == "Test Post"

    # Verify cryptographic fields were auto-populated by PostgreSQL trigger
    assert event["event_hash"] is not None
    assert event["signature"] is not None
    # First event for this tenant should have no previous_hash
    assert event["previous_hash"] is None


@pytest.mark.asyncio
async def test_bridge_creates_cryptographic_chain(db_repo, setup_bridge_schema) -> None:
    """Verify multiple mutations create a valid cryptographic chain."""
    import psycopg.types.json

    from fraiseql.db import DatabaseQuery

    org_id = uuid4()  # Unique tenant for this test
    user_id = uuid4()

    # Create three mutations via tb_audit_log
    mutations = [
        {"entity": "user", "op": "INSERT", "data": {"name": "User 1"}},
        {"entity": "post", "op": "INSERT", "data": {"title": "Post 1"}},
        {"entity": "post", "op": "UPDATE", "data": {"title": "Post 1 Updated"}},
    ]

    for mutation in mutations:
        await db_repo.run(
            DatabaseQuery(
                statement="""
                    INSERT INTO tenant.tb_audit_log (
                        pk_organization, user_id, entity_type, entity_id,
                        operation_type, operation_subtype, changed_fields,
                        old_data, new_data, metadata
                    ) VALUES (
                        %(org_id)s, %(user_id)s, %(entity_type)s, gen_random_uuid(),
                        %(operation_type)s, 'auto', ARRAY[]::TEXT[],
                        NULL, %(new_data)s, '{}'::jsonb
                    )
                """,
                params={
                    "org_id": org_id,
                    "user_id": user_id,
                    "entity_type": mutation["entity"],
                    "operation_type": mutation["op"],
                    "new_data": psycopg.types.json.Jsonb(mutation["data"]),
                },
                fetch_result=False,
            )
        )

    # Retrieve all events for this tenant
    events = await db_repo.run(
        DatabaseQuery(
            statement="""
                SELECT * FROM audit_events
                WHERE tenant_id = %(tenant_id)s
                ORDER BY timestamp ASC
            """,
            params={"tenant_id": org_id},
            fetch_result=True,
        )
    )

    assert len(events) == 3

    # Verify cryptographic chain integrity
    for i, event in enumerate(events):
        if i == 0:
            # First event has no previous hash
            assert event["previous_hash"] is None
        else:
            # Each subsequent event links to previous
            assert event["previous_hash"] == events[i - 1]["event_hash"]

        # All events have hash and signature
        assert event["event_hash"] is not None
        assert event["signature"] is not None


@pytest.mark.asyncio
async def test_bridge_preserves_debezium_style_data(db_repo, setup_bridge_schema) -> None:
    """Verify bridge preserves old_data and new_data (Debezium CDC style)."""
    import psycopg.types.json

    from fraiseql.db import DatabaseQuery

    org_id = uuid4()
    user_id = uuid4()
    entity_id = uuid4()

    # Simulate an UPDATE with old and new data
    old_data = {"title": "Original Title", "status": "draft"}
    new_data = {"title": "Updated Title", "status": "published"}

    await db_repo.run(
        DatabaseQuery(
            statement="""
                INSERT INTO tenant.tb_audit_log (
                    pk_organization, user_id, entity_type, entity_id,
                    operation_type, operation_subtype, changed_fields,
                    old_data, new_data, metadata
                ) VALUES (
                    %(org_id)s, %(user_id)s, 'post', %(entity_id)s,
                    'UPDATE', 'status_change', %(changed_fields)s,
                    %(old_data)s, %(new_data)s, %(metadata)s
                )
                RETURNING pk_audit_log
            """,
            params={
                "org_id": org_id,
                "user_id": user_id,
                "entity_id": entity_id,
                "changed_fields": ["title", "status"],
                "old_data": psycopg.types.json.Jsonb(old_data),
                "new_data": psycopg.types.json.Jsonb(new_data),
                "metadata": psycopg.types.json.Jsonb(
                    {"business_actions": ["published", "notifications_sent"]}
                ),
            },
            fetch_result=True,
        )
    )

    # Retrieve the bridged event
    events = await db_repo.run(
        DatabaseQuery(
            statement="""
                SELECT * FROM audit_events
                WHERE tenant_id = %(tenant_id)s
                ORDER BY timestamp DESC
                LIMIT 1
            """,
            params={"tenant_id": org_id},
            fetch_result=True,
        )
    )

    assert len(events) == 1
    event = events[0]

    # Verify Debezium-style CDC data is preserved
    event_data = event["event_data"]
    assert event_data["old_data"]["title"] == "Original Title"
    assert event_data["old_data"]["status"] == "draft"
    assert event_data["new_data"]["title"] == "Updated Title"
    assert event_data["new_data"]["status"] == "published"
    assert event_data["changed_fields"] == ["title", "status"]
    assert event_data["metadata"]["business_actions"] == ["published", "notifications_sent"]
