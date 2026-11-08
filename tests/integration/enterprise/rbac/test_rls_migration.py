"""004_rbac_row_level_security.sql applies with or without the tables it protects."""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.database, pytest.mark.enterprise]

RLS_SQL = (
    Path(__file__).parents[4]
    / "src"
    / "fraiseql"
    / "enterprise"
    / "migrations"
    / "004_rbac_row_level_security.sql"
).read_text()


async def _policies(conn, schema: str) -> set[tuple[str, str]]:
    cur = await conn.execute(
        "SELECT tablename, policyname FROM pg_policies WHERE schemaname = %s", (schema,)
    )
    return set(await cur.fetchall())


async def _functions(conn, schema: str) -> set[str]:
    cur = await conn.execute(
        """
        SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = %s
        """,
        (schema,),
    )
    return {row[0] for row in await cur.fetchall()}


class TestRlsMigrationWithoutTheTables:
    async def test_applies_and_creates_the_helper_functions(self, rbac_pool, test_schema) -> None:
        async with rbac_pool.connection() as conn:
            await conn.execute(RLS_SQL)
            await conn.execute(RLS_SQL)  # idempotent

            assert {"user_has_role", "user_has_permission"} <= await _functions(conn, test_schema)
            assert await _policies(conn, test_schema) == set()


class TestRlsMigrationWithSomeOfTheTables:
    async def test_protects_the_tables_that_exist(self, rbac_pool, test_schema) -> None:
        async with rbac_pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE orders (id UUID PRIMARY KEY, tenant_id UUID, user_id UUID)"
            )
            await conn.execute(RLS_SQL)

            assert await _policies(conn, test_schema) == {
                ("orders", "tenant_isolation_orders"),
                ("orders", "own_data_update_orders"),
            }
            cur = await conn.execute(
                "SELECT relrowsecurity FROM pg_class WHERE oid = 'orders'::regclass"
            )
            assert (await cur.fetchone())[0] is True


class TestRlsMigrationWithAllTheTables:
    async def test_protects_all_three(self, rbac_pool, test_schema) -> None:
        async with rbac_pool.connection() as conn:
            await conn.execute("CREATE TABLE users (id UUID PRIMARY KEY, tenant_id UUID)")
            await conn.execute(
                "CREATE TABLE orders (id UUID PRIMARY KEY, tenant_id UUID, user_id UUID)"
            )
            await conn.execute("CREATE TABLE products (id UUID PRIMARY KEY, tenant_id UUID)")
            await conn.execute(RLS_SQL)

            assert {table for table, _ in await _policies(conn, test_schema)} == {
                "users",
                "orders",
                "products",
            }
