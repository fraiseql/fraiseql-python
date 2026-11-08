"""apply_native_auth_schema() creates the native auth tables from the packaged SQL."""

from importlib import resources

import pytest
from psycopg_pool import AsyncConnectionPool

from fraiseql.auth.native import apply_native_auth_schema

pytestmark = [pytest.mark.integration, pytest.mark.database]

NATIVE_AUTH_TABLES = {"tb_user", "tb_session", "tb_used_refresh_token", "tb_password_reset"}


def test_native_auth_schema_sql_is_package_data() -> None:
    """The migration ships inside the fraiseql.auth.native package."""
    sql = resources.files("fraiseql.auth.native").joinpath(
        "migrations", "001_native_auth_schema.sql"
    )
    assert sql.is_file()
    assert "CREATE TABLE IF NOT EXISTS tb_user" in sql.read_text()


class TestApplyNativeAuthSchema:
    async def test_creates_the_tables_in_the_given_schema(self, class_db_pool, test_schema) -> None:
        await apply_native_auth_schema(class_db_pool, schema=test_schema)
        # A second run is a no-op (the example applies it at every startup).
        await apply_native_auth_schema(class_db_pool, schema=test_schema)

        async with class_db_pool.connection() as conn:
            cur = await conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                (test_schema,),
            )
            tables = {row[0] for row in await cur.fetchall()}
        assert tables >= NATIVE_AUTH_TABLES

    async def test_leaves_the_pooled_connections_search_path_alone(
        self, postgres_url, test_schema
    ) -> None:
        # One connection, so the migration and the check below share it.
        pool = AsyncConnectionPool(postgres_url, min_size=1, max_size=1, open=False)
        await pool.open()
        try:
            async with pool.connection() as conn:
                cur = await conn.execute("SHOW search_path")
                before = (await cur.fetchone())[0]

            await apply_native_auth_schema(pool, schema=test_schema)

            async with pool.connection() as conn:
                cur = await conn.execute("SHOW search_path")
                assert (await cur.fetchone())[0] == before
        finally:
            await pool.close()
