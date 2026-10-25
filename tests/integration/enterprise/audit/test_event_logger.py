# tests/integration/enterprise/audit/test_event_logger.py

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.enterprise


@pytest_asyncio.fixture(autouse=True, scope="class")
async def setup_audit_schema(class_db_pool, test_schema) -> None:
    """Set up audit schema before running tests."""
    # Check if schema already exists
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
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
            # Read the migration file
            migration_path = Path("src/fraiseql/enterprise/migrations/001_audit_tables.sql")
            migration_sql = migration_path.read_text()

            # Execute the migration
            await conn.execute(migration_sql)

        # Keep PostgreSQL crypto trigger ENABLED (FraiseQL philosophy: "In PostgreSQL Everything")
        # PostgreSQL handles hashing, signing, and chain linking

        # Disable the partition trigger for tests to avoid complexity
        await conn.execute(
            "ALTER TABLE audit_events DISABLE TRIGGER create_audit_partition_trigger"
        )

        # Check if test signing key exists
        cur = await conn.execute(
            "SELECT COUNT(*) FROM audit_signing_keys WHERE key_value = %s",
            ["test-key-for-testing"],
        )
        key_exists = (await cur.fetchone())[0] > 0

        if not key_exists:
            # Insert a test signing key
            await conn.execute(
                "INSERT INTO audit_signing_keys (key_value, active) VALUES (%s, %s)",
                ["test-key-for-testing", True],
            )

        await conn.commit()


@pytest.mark.asyncio
async def test_log_audit_event(db_repo) -> None:
    """Verify audit event is logged to database with proper chain."""
    # This test will fail until we implement the AuditLogger
    from fraiseql.enterprise.audit.event_logger import AuditLogger

    logger = AuditLogger(db_repo)

    event_id = await logger.log_event(
        event_type="user.created",
        event_data={"username": "testuser", "email": "test@example.com"},
        user_id=str(uuid4()),
        tenant_id=str(uuid4()),
        ip_address="192.168.1.100",
    )

    # Retrieve logged event
    from fraiseql.db import DatabaseQuery

    events = await db_repo.run(
        DatabaseQuery(
            statement="SELECT * FROM audit_events WHERE id = %(id)s",
            params={"id": event_id},
            fetch_result=True,
        )
    )

    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "user.created"
    assert event["event_hash"] is not None
    assert event["signature"] is not None


@pytest.mark.asyncio
async def test_log_event_batching(db_repo) -> None:
    """Verify batching functionality works correctly."""
    from fraiseql.enterprise.audit.event_logger import AuditLogger

    logger = AuditLogger(db_repo, batch_size=3)  # Batch size 3 for testing

    # Log events without immediate flush
    event_id1 = await logger.log_event(
        event_type="test.batch1", event_data={"test": "data1"}, immediate=False
    )
    event_id2 = await logger.log_event(
        event_type="test.batch2", event_data={"test": "data2"}, immediate=False
    )

    # Batch should have 2 events now
    assert len(logger._batch) == 2

    # Log one more to trigger flush
    event_id3 = await logger.log_event(
        event_type="test.batch3", event_data={"test": "data3"}, immediate=False
    )

    # Batch should be flushed now (3 >= 3)
    assert len(logger._batch) == 0

    # Verify all events were written
    from fraiseql.db import DatabaseQuery

    for event_id in [event_id1, event_id2, event_id3]:
        events = await db_repo.run(
            DatabaseQuery(
                statement="SELECT * FROM audit_events WHERE id = %(id)s",
                params={"id": event_id},
                fetch_result=True,
            )
        )
        assert len(events) == 1


@pytest.mark.asyncio
async def test_audit_chain_integrity(db_repo) -> None:
    """Verify cryptographic chain integrity."""
    import uuid

    from fraiseql.enterprise.audit.event_logger import AuditLogger

    # Use a unique tenant to ensure we start a new chain
    tenant_id = str(uuid.uuid4())
    logger = AuditLogger(db_repo)

    # Log multiple events for this tenant
    await logger.log_event("chain.test1", {"data": "first"}, tenant_id=tenant_id)
    await logger.log_event("chain.test2", {"data": "second"}, tenant_id=tenant_id)
    await logger.log_event("chain.test3", {"data": "third"}, tenant_id=tenant_id)

    # Retrieve events for this tenant in order
    from fraiseql.db import DatabaseQuery

    events = await db_repo.run(
        DatabaseQuery(
            statement="SELECT * FROM audit_events WHERE tenant_id = %(tenant_id)s ORDER BY timestamp ASC",
            params={"tenant_id": tenant_id},
            fetch_result=True,
        )
    )

    assert len(events) == 3

    # Verify chain: each event's previous_hash should match the previous event's hash
    for i, event in enumerate(events):
        if i == 0:
            # First event in tenant chain should have no previous hash
            assert event["previous_hash"] is None
        else:
            # Subsequent events should reference the previous event's hash
            assert event["previous_hash"] == events[i - 1]["event_hash"]
