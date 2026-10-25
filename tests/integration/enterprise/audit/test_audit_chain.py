"""The audit_events table of 001_audit_tables.sql: inserts and chain verification."""

from pathlib import Path

import pytest
import pytest_asyncio
from psycopg.types.json import Jsonb

pytestmark = [pytest.mark.integration, pytest.mark.enterprise]

MIGRATION = Path("src/fraiseql/enterprise/migrations/001_audit_tables.sql")
TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest_asyncio.fixture
async def audit_conn(db_connection):
    """A connection in a rolled-back transaction, with the migration applied as-is."""
    await db_connection.execute(MIGRATION.read_text())
    await db_connection.execute("INSERT INTO audit_signing_keys (key_value) VALUES ('test-key')")
    return db_connection


async def insert_event(conn, tenant_id: str | None, timestamp: str, data: dict) -> str:
    cur = await conn.execute(
        "INSERT INTO audit_events (event_type, event_data, tenant_id, timestamp) "
        "VALUES ('test.event', %s, %s, %s) RETURNING id",
        [Jsonb(data), tenant_id, timestamp],
    )
    return str((await cur.fetchone())[0])


async def verify(conn, query: str = "SELECT * FROM verify_audit_chain()") -> dict[str, bool]:
    cur = await conn.execute(query)
    return {str(row[0]): row[2] for row in await cur.fetchall()}


@pytest.mark.asyncio
class TestAuditEventsTable:
    async def test_insert_succeeds_with_the_migration_as_shipped(self, audit_conn) -> None:
        await insert_event(audit_conn, TENANT_A, "2026-03-10T12:00:00Z", {"n": 1})

        cur = await audit_conn.execute("SELECT count(*) FROM audit_events")
        assert (await cur.fetchone())[0] == 1

    async def test_inserts_across_a_month_boundary(self, audit_conn) -> None:
        await insert_event(audit_conn, TENANT_A, "2026-01-31T23:59:59Z", {"n": 1})
        await insert_event(audit_conn, TENANT_A, "2026-02-01T00:00:00Z", {"n": 2})
        await insert_event(audit_conn, TENANT_A, "2026-03-01T00:00:00Z", {"n": 3})

        assert list((await verify(audit_conn)).values()) == [True, True, True]

    async def test_applying_the_migration_twice_keeps_inserts_working(self, audit_conn) -> None:
        await audit_conn.execute(MIGRATION.read_text())

        await insert_event(audit_conn, TENANT_A, "2026-03-10T12:00:00Z", {"n": 1})
