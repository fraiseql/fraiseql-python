"""``mask_database_error`` on errors raised by a real PostgreSQL server."""

import psycopg
import pytest

from fraiseql.errors.masking import mask_database_error

pytestmark = pytest.mark.database


async def _error(conn: psycopg.AsyncConnection, sql: str) -> psycopg.Error:
    try:
        await conn.execute(sql)
    except psycopg.Error as error:
        await conn.rollback()
        return error
    pytest.fail(f"{sql} did not fail")


async def test_a_raise_keeps_only_its_primary_message(db_connection) -> None:
    await db_connection.execute(
        """
        CREATE FUNCTION pg_temp.fn_refuse() RETURNS int LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'out of stock: %', 3 USING DETAIL = 'sku 42', HINT = 'restock';
        END $$
        """
    )
    error = await _error(db_connection, "SELECT pg_temp.fn_refuse()")
    assert "CONTEXT" in str(error)

    masked = mask_database_error({"message": str(error), "path": ["refuse"]}, error)

    assert masked == {
        "message": "out of stock: 3",
        "path": ["refuse"],
        "extensions": {"code": "INTERNAL_SERVER_ERROR"},
    }


async def test_any_other_server_error_is_hidden(db_connection) -> None:
    error = await _error(db_connection, "SELECT * FROM tb_does_not_exist")
    assert "LINE 1" in str(error)

    masked = mask_database_error({"message": str(error)}, error)

    assert masked["message"] == "Internal server error"
