"""The audit_events table of 001_audit_tables.sql: inserts and chain verification."""

from pathlib import Path

import pytest
import pytest_asyncio
from psycopg.types.json import Jsonb

pytestmark = [pytest.mark.integration, pytest.mark.enterprise]

MIGRATION = Path("src/fraiseql/enterprise/migrations/001_audit_tables.sql")
TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


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


@pytest.mark.asyncio
class TestVerifyAuditChainPerTenant:
    async def _interleaved_events(self, conn) -> list[str]:
        ids = []
        for i, tenant in enumerate([TENANT_A, TENANT_B, TENANT_A, None, TENANT_B, TENANT_A]):
            ids.append(await insert_event(conn, tenant, f"2026-04-0{i + 1}T10:00:00Z", {"n": i}))
        return ids

    async def test_valid_events_of_two_tenants_pass(self, audit_conn) -> None:
        ids = await self._interleaved_events(audit_conn)

        result = await verify(audit_conn)

        assert set(result) == set(ids)
        assert all(result.values())

    async def test_reports_the_tenant_of_each_event(self, audit_conn) -> None:
        await self._interleaved_events(audit_conn)

        cur = await audit_conn.execute(
            "SELECT tenant_id::text, count(*) FROM verify_audit_chain() "
            "GROUP BY tenant_id ORDER BY tenant_id NULLS LAST"
        )
        assert await cur.fetchall() == [(TENANT_A, 3), (TENANT_B, 2), (None, 1)]

    async def test_a_tampered_event_is_detected(self, audit_conn) -> None:
        ids = await self._interleaved_events(audit_conn)
        await audit_conn.execute(
            "UPDATE audit_events SET event_data = %s WHERE id = %s", [Jsonb({"n": 99}), ids[2]]
        )

        result = await verify(audit_conn)

        assert [eid for eid, valid in result.items() if not valid] == [ids[2]]

    async def test_a_deleted_event_is_detected(self, audit_conn) -> None:
        ids = await self._interleaved_events(audit_conn)
        await audit_conn.execute("DELETE FROM audit_events WHERE id = %s", [ids[1]])

        result = await verify(audit_conn)

        # The next event of tenant B no longer links to the one before it.
        assert [eid for eid, valid in result.items() if not valid] == [ids[4]]

    async def test_a_time_range_starting_mid_chain_passes(self, audit_conn) -> None:
        ids = await self._interleaved_events(audit_conn)

        result = await verify(
            audit_conn, "SELECT * FROM verify_audit_chain('2026-04-03T00:00:00Z', NULL)"
        )

        assert set(result) == set(ids[2:])
        assert all(result.values())


UNIFIED_MIGRATION = Path("src/fraiseql/enterprise/migrations/002_unified_audit.sql")


@pytest_asyncio.fixture
async def unified_conn(db_connection):
    """A rolled-back transaction with 002_unified_audit.sql applied."""
    await db_connection.execute(UNIFIED_MIGRATION.read_text())
    await db_connection.execute("INSERT INTO audit_signing_keys (key_value) VALUES ('test-key')")
    return db_connection


async def insert_unified_event(conn, tenant_id: str, timestamp: str, n: int) -> str:
    cur = await conn.execute(
        "INSERT INTO audit_events (tenant_id, entity_type, operation_type, new_data, timestamp) "
        "VALUES (%s, 'post', 'INSERT', %s, %s) RETURNING id",
        [tenant_id, Jsonb({"n": n}), timestamp],
    )
    return str((await cur.fetchone())[0])


@pytest.mark.asyncio
class TestUnifiedVerifyAuditChainPerTenant:
    """The same checks against 002_unified_audit.sql, whose trigger also chains per tenant."""

    async def _interleaved_events(self, conn) -> list[str]:
        return [
            await insert_unified_event(conn, tenant, f"2026-04-0{i + 1}T10:00:00Z", i)
            for i, tenant in enumerate([TENANT_A, TENANT_B, TENANT_A, TENANT_B, TENANT_A])
        ]

    async def test_valid_events_of_two_tenants_pass(self, unified_conn) -> None:
        ids = await self._interleaved_events(unified_conn)

        result = await verify(unified_conn)

        assert set(result) == set(ids)
        assert all(result.values())

    async def test_a_tampered_event_is_detected(self, unified_conn) -> None:
        ids = await self._interleaved_events(unified_conn)
        await unified_conn.execute(
            "UPDATE audit_events SET new_data = %s WHERE id = %s", [Jsonb({"n": 99}), ids[3]]
        )

        result = await verify(unified_conn)

        assert [eid for eid, valid in result.items() if not valid] == [ids[3]]

    async def test_one_tenant_from_mid_chain_passes(self, unified_conn) -> None:
        ids = await self._interleaved_events(unified_conn)

        result = await verify(
            unified_conn,
            f"SELECT * FROM verify_audit_chain('{TENANT_A}', '2026-04-02T00:00:00Z')",
        )

        assert set(result) == {ids[2], ids[4]}
        assert all(result.values())
