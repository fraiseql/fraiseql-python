# tests/integration/enterprise/audit/test_unified_audit.py

"""Test unified audit table with CDC + cryptographic chain.

Demonstrates the simplified architecture:
- One table: audit_events (not two separate tables)
- No bridge trigger needed
- CDC features + crypto chain in one place
- Direct integration with log_and_return_mutation()
"""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg.types.json
import psycopg_pool
import pytest
from psycopg.sql import SQL

from fraiseql.db import FraiseQLRepository

pytestmark = pytest.mark.enterprise


@pytest.fixture
def setup_unified_audit(class_db_pool: psycopg_pool.AsyncConnectionPool, test_schema) -> None:
    import asyncio

    asyncio.run(_setup_unified_audit(class_db_pool, test_schema))


async def _setup_unified_audit(
    class_db_pool: psycopg_pool.AsyncConnectionPool, test_schema
) -> None:
    """Set up unified audit table."""
    async with class_db_pool.connection() as conn:
        await conn.execute(SQL(f"SET search_path TO {test_schema}, public"))
        # Drop old tables if they exist
        await conn.execute(SQL("DROP TABLE IF EXISTS audit_events CASCADE"))
        await conn.execute(SQL("DROP TABLE IF EXISTS audit_signing_keys CASCADE"))

        # Load unified migration
        migration_path = Path("src/fraiseql/enterprise/migrations/002_unified_audit.sql")
        migration_sql = migration_path.read_text()
        await conn.execute(migration_sql)

        # Insert test signing key
        await conn.execute(
            "INSERT INTO audit_signing_keys (key_value, active) VALUES (%s, %s)",
            ["test-key-for-testing", True],
        )

        await conn.commit()


@pytest.mark.asyncio
async def test_unified_table_has_all_features(
    db_repo: FraiseQLRepository, setup_unified_audit
) -> None:
    """Verify unified table has both CDC and crypto features."""
    from fraiseql.db import DatabaseQuery

    tenant_id = uuid4()
    user_id = uuid4()
    entity_id = uuid4()

    # Insert a mutation (simulating log_and_return_mutation)
    await db_repo.run(
        DatabaseQuery(
            statement=SQL("""
                INSERT INTO audit_events (
                    tenant_id, user_id, entity_type, entity_id,
                    operation_type, operation_subtype, changed_fields,
                    old_data, new_data, metadata
                ) VALUES (
                    %(tenant_id)s, %(user_id)s, %(entity_type)s, %(entity_id)s,
                    %(operation_type)s, %(operation_subtype)s, %(changed_fields)s,
                    %(old_data)s, %(new_data)s, %(metadata)s
                )
            """),
            params={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "entity_type": "post",
                "entity_id": entity_id,
                "operation_type": "INSERT",
                "operation_subtype": "new",
                "changed_fields": ["title", "content", "slug"],
                "old_data": None,
                "new_data": psycopg.types.json.Jsonb(
                    {"title": "Test Post", "content": "Test content", "slug": "test-post"}
                ),
                "metadata": psycopg.types.json.Jsonb(
                    {
                        "business_actions": ["slug_generated", "stats_initialized"],
                        "generated_slug": "test-post",
                    }
                ),
            },
            fetch_result=False,
        )
    )

    # Retrieve and verify ALL features in one table
    events = cast(
        list[dict[str, Any]],
        await db_repo.run(
            DatabaseQuery(
                statement=SQL("SELECT * FROM audit_events WHERE tenant_id = %(tenant_id)s"),
                params={"tenant_id": tenant_id},
                fetch_result=True,
            )
        ),
    )

    assert len(events) == 1
    event = cast(dict[str, Any], events[0])

    # ✅ CDC features
    assert event["operation_type"] == "INSERT"
    assert event["operation_subtype"] == "new"
    assert event["changed_fields"] == ["title", "content", "slug"]
    assert event["old_data"] is None
    assert event["new_data"]["title"] == "Test Post"

    # ✅ Business metadata
    assert event["metadata"]["business_actions"] == ["slug_generated", "stats_initialized"]
    assert event["metadata"]["generated_slug"] == "test-post"

    # ✅ Crypto features (auto-populated by trigger)
    assert event["event_hash"] is not None
    assert event["signature"] is not None
    assert event["previous_hash"] is None  # First event in chain

    # ✅ All in ONE row, ONE table


@pytest.mark.asyncio
async def test_log_and_return_mutation_function(
    db_repo: FraiseQLRepository, setup_unified_audit
) -> None:
    """Test the simplified log_and_return_mutation() function."""
    from fraiseql.db import DatabaseQuery

    tenant_id = uuid4()
    user_id = uuid4()
    post_id = uuid4()

    # Call log_and_return_mutation() - simpler, no bridge needed
    result = cast(
        list[dict[str, Any]],
        await db_repo.run(
            DatabaseQuery(
                statement=SQL("""
                SELECT * FROM log_and_return_mutation(
                    %(tenant_id)s,
                    %(user_id)s,
                    'post',
                    %(post_id)s,
                    'INSERT',
                    'new',
                    ARRAY['title', 'content'],
                    'Post created successfully',
                    NULL,
                    %(new_data)s,
                    %(metadata)s
                )
            """),
                params={
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "post_id": post_id,
                    "new_data": psycopg.types.json.Jsonb(
                        {"title": "My Post", "content": "Post content"}
                    ),
                    "metadata": psycopg.types.json.Jsonb(
                        {"business_actions": ["created"], "word_count": 2}
                    ),
                },
                fetch_result=True,
            )
        ),
    )

    # Verify return value
    assert len(result) == 1
    ret = cast(dict[str, Any], result[0])
    assert ret["success"] is True
    assert ret["operation_type"] == "INSERT"
    assert ret["message"] == "Post created successfully"

    # Verify audit event was logged
    events = cast(
        list[dict[str, Any]],
        await db_repo.run(
            DatabaseQuery(
                statement=SQL("SELECT * FROM audit_events WHERE entity_id = %(post_id)s"),
                params={"post_id": post_id},
                fetch_result=True,
            )
        ),
    )

    assert len(events) == 1
    event = cast(dict[str, Any], events[0])
    assert event["new_data"]["title"] == "My Post"
    assert event["event_hash"] is not None  # Crypto auto-added
    assert event["signature"] is not None


@pytest.mark.asyncio
async def test_cryptographic_chain_with_cdc_data(
    db_repo: FraiseQLRepository, setup_unified_audit
) -> None:
    """Verify crypto chain works with full CDC data."""
    from fraiseql.db import DatabaseQuery

    tenant_id = uuid4()
    user_id = uuid4()

    # Create 3 mutations with full CDC tracking
    mutations = [
        {
            "entity": "user",
            "entity_id": uuid4(),
            "op": "INSERT",
            "subtype": "new",
            "old": None,
            "new": {"name": "John Doe", "email": "john@example.com"},
            "fields": ["name", "email"],
        },
        {
            "entity": "post",
            "entity_id": uuid4(),
            "op": "INSERT",
            "subtype": "new",
            "old": None,
            "new": {"title": "Post 1", "status": "draft"},
            "fields": ["title", "status"],
        },
        {
            "entity": "post",
            "entity_id": uuid4(),  # Will update the same post below
            "op": "UPDATE",
            "subtype": "published",
            "old": {"title": "Post 1", "status": "draft"},
            "new": {"title": "Post 1 Updated", "status": "published"},
            "fields": ["title", "status"],
        },
    ]

    for m in mutations:
        await db_repo.run(
            DatabaseQuery(
                statement=SQL("""
                    INSERT INTO audit_events (
                        tenant_id, user_id, entity_type, entity_id,
                        operation_type, operation_subtype, changed_fields,
                        old_data, new_data, metadata
                    ) VALUES (
                        %(tenant_id)s, %(user_id)s, %(entity)s, %(entity_id)s,
                        %(op)s, %(subtype)s, %(fields)s,
                        %(old)s, %(new)s, '{}'::jsonb
                    )
                """),
                params={
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "entity": m["entity"],
                    "entity_id": m["entity_id"],
                    "op": m["op"],
                    "subtype": m["subtype"],
                    "fields": m["fields"],
                    "old": psycopg.types.json.Jsonb(m["old"]) if m["old"] else None,
                    "new": psycopg.types.json.Jsonb(m["new"]),
                },
                fetch_result=False,
            )
        )

    # Verify chain integrity
    events = cast(
        list[dict[str, Any]],
        await db_repo.run(
            DatabaseQuery(
                statement=SQL("""
                SELECT * FROM audit_events
                WHERE tenant_id = %(tenant_id)s
                ORDER BY timestamp ASC
            """),
                params={"tenant_id": tenant_id},
                fetch_result=True,
            )
        ),
    )

    assert len(events) == 3

    # Verify cryptographic chain
    for i, event in enumerate(events):
        if i == 0:
            assert event["previous_hash"] is None
        else:
            assert event["previous_hash"] == events[i - 1]["event_hash"]

        # Verify CDC data is preserved
        assert event["changed_fields"] is not None
        assert event["new_data"] is not None

    # Verify specific CDC data for UPDATE
    update_event = cast(dict[str, Any], events[2])
    assert update_event["operation_type"] == "UPDATE"
    assert update_event["old_data"]["status"] == "draft"
    assert update_event["new_data"]["status"] == "published"
    assert "title" in update_event["changed_fields"]
    assert "status" in update_event["changed_fields"]


@pytest.mark.asyncio
async def test_verify_chain_function(db_repo: FraiseQLRepository, setup_unified_audit) -> None:
    """Test PostgreSQL chain verification function."""
    from fraiseql.db import DatabaseQuery

    tenant_id = uuid4()

    # Create chain of 3 events
    for i in range(3):
        await db_repo.run(
            DatabaseQuery(
                statement=SQL("""
                    INSERT INTO audit_events (
                        tenant_id, user_id, entity_type, entity_id,
                        operation_type, operation_subtype, changed_fields,
                        old_data, new_data, metadata
                    ) VALUES (
                        %(tenant_id)s, NULL, 'test', gen_random_uuid(),
                        'INSERT', 'test', ARRAY[]::TEXT[],
                        NULL, %(data)s, '{}'::jsonb
                    )
                """),
                params={
                    "tenant_id": tenant_id,
                    "data": psycopg.types.json.Jsonb({"index": i}),
                },
                fetch_result=False,
            )
        )

    # Verify chain using PostgreSQL function
    verification = await db_repo.run(
        DatabaseQuery(
            statement=SQL("SELECT * FROM verify_audit_chain(%(tenant_id)s)"),
            params={"tenant_id": tenant_id},
            fetch_result=True,
        )
    )

    assert len(verification) == 3

    # All events should have valid chain
    for v in verification:
        assert v["chain_valid"] is True
        assert v["expected_hash"] == v["actual_hash"]


@pytest.mark.asyncio
async def test_noop_operations(db_repo: FraiseQLRepository, setup_unified_audit) -> None:
    """Test NOOP operations (duplicate detection, validation failures)."""
    from fraiseql.db import DatabaseQuery

    tenant_id = uuid4()
    user_id = uuid4()
    existing_post_id = uuid4()

    # Simulate NOOP: duplicate slug
    result = cast(
        list[dict[str, Any]],
        await db_repo.run(
            DatabaseQuery(
                statement=SQL("""
                SELECT * FROM log_and_return_mutation(
                    %(tenant_id)s,
                    %(user_id)s,
                    'post',
                    %(existing_post_id)s,
                    'NOOP',
                    'noop:slug_exists',
                    ARRAY[]::TEXT[],
                    'Post with similar title already exists',
                    %(existing_data)s,
                    %(existing_data)s,
                    %(metadata)s
                )
            """),
                params={
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "existing_post_id": existing_post_id,
                    "existing_data": psycopg.types.json.Jsonb(
                        {"title": "Existing Post", "slug": "existing-post"}
                    ),
                    "metadata": psycopg.types.json.Jsonb(
                        {"business_rule": "unique_slug", "attempted_title": "Existing Post"}
                    ),
                },
                fetch_result=True,
            )
        ),
    )

    # Verify NOOP result
    assert result[0]["success"] is False
    assert result[0]["operation_type"] == "NOOP"
    assert result[0]["error_code"] == "noop:slug_exists"

    # Verify NOOP was logged to audit chain
    events = await db_repo.run(
        DatabaseQuery(
            statement=SQL("SELECT * FROM audit_events WHERE entity_id = %(post_id)s"),
            params={"post_id": existing_post_id},
            fetch_result=True,
        )
    )

    assert len(events) == 1
    assert events[0]["operation_type"] == "NOOP"
    assert events[0]["operation_subtype"] == "noop:slug_exists"
    assert events[0]["event_hash"] is not None  # Even NOOPs are in crypto chain
