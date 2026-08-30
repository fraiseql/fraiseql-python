"""Issue #476: the ORDER BY collation, executed against a live database.

The unit tests assert on SQL text, and for this bug that is not enough. The
JSONB branch emitted ``t -> 'name' COLLATE "x"`` for years and every string
assertion passed -- but PostgreSQL parses that as ``t -> ('name' COLLATE "x")``,
attaching the collation to the *key literal*, comparing ``jsonb``, and ignoring
the collation entirely. It does not error, so nothing caught it.

So these tests never look at the generated SQL. They run the same query twice
under two collations that disagree about case, and assert the row order
actually differs. A dropped collation (the old flat-column branches) and a
misbound one (the old JSONB branch) both fail that: they return the same order
both times.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from psycopg.sql import SQL

from fraiseql.sql.order_by_generator import OrderBy

pytestmark = pytest.mark.database

TABLE = "t_476_collation"

# Byte order puts uppercase first ("B" < "a" < "c"); a linguistic collation
# orders case-insensitively ("a" < "B" < "c"). Any collation pair that
# disagrees about these three rows proves the collation reached the sort.
ROWS = ["a", "B", "c"]
BYTE_ORDER = ["B", "a", "c"]


async def _linguistic_collation(pool: Any) -> str | None:
    """A collation available on this server that disagrees with ``"C"``.

    Which ones exist depends on how the server was built and which locales the
    host has, so it is discovered rather than assumed, and the tests skip when
    none is usable instead of failing on an unrelated environment difference.
    """
    async with pool.connection() as conn, conn.cursor() as cursor:
        for candidate in ("en-US-x-icu", "und-x-icu", "en_US.utf8", "en_US.UTF-8"):
            await cursor.execute(
                "SELECT 1 FROM pg_collation WHERE collname = %s LIMIT 1", (candidate,)
            )
            if await cursor.fetchone() is None:
                continue
            try:
                await cursor.execute(
                    SQL("SELECT v FROM unnest(%s::text[]) AS s(v) ORDER BY v COLLATE {}").format(
                        SQL('"{}"'.format(candidate.replace('"', '""')))
                    ),
                    (ROWS,),
                )
            except Exception:
                await conn.rollback()
                continue
            if [r[0] for r in await cursor.fetchall()] != BYTE_ORDER:
                return candidate
            await conn.rollback()
    return None


@pytest.fixture
async def collation_rows(class_db_pool, test_schema) -> AsyncIterator[None]:
    """Three rows carrying the same text as a flat column and inside JSONB."""
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {test_schema}")
        await cursor.execute(
            f"CREATE TABLE IF NOT EXISTS {TABLE} "
            f"(id UUID PRIMARY KEY, name TEXT NOT NULL, data JSONB NOT NULL)"
        )
        for name in ROWS:
            await cursor.execute(
                f"INSERT INTO {TABLE} (id, name, data) VALUES (%s, %s, %s::jsonb)",
                (uuid.uuid4(), name, f'{{"name": "{name}", "profile": {{"last_name": "{name}"}}}}'),
            )
        await conn.commit()

    yield

    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {test_schema}")
        await cursor.execute(f"DROP TABLE IF EXISTS {TABLE} CASCADE")
        await conn.commit()


async def _order(pool: Any, schema: str, instruction: OrderBy, **to_sql_kwargs: Any) -> list[str]:
    """Run one ``OrderBy`` against the table and return the names, in row order.

    ``table_ref`` is the JSONB column, which is what the repository passes for a
    JSONB view (``db.py``: ``table_ref = jsonb_column if ... else "t"``); the
    flat-column branch renders ``t."col"`` and relies on the alias instead.
    """
    to_sql_kwargs.setdefault("table_ref", "data")
    async with pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {schema}")
        await cursor.execute(
            SQL("SELECT name FROM {} AS t ORDER BY ").format(SQL(TABLE))
            + instruction.to_sql(**to_sql_kwargs)
        )
        return [row[0] for row in await cursor.fetchall()]


@pytest.mark.database
class TestCollationReachesTheSort:
    """One assertion, three times: a different collation must give a different order."""

    async def _pair(self, pool: Any, schema: str, **to_sql_kwargs: Any) -> tuple[list, list, str]:
        linguistic = await _linguistic_collation(pool)
        if linguistic is None:
            pytest.skip('no collation on this server disagrees with "C" about case')
        byte = await _order(pool, schema, OrderBy(field="name", collation="C"), **to_sql_kwargs)
        ling = await _order(
            pool, schema, OrderBy(field="name", collation=linguistic), **to_sql_kwargs
        )
        return byte, ling, linguistic

    async def test_native_column_path(self, class_db_pool, test_schema, collation_rows) -> None:
        byte, ling, name = await self._pair(class_db_pool, test_schema, native_columns={"name"})
        assert byte == BYTE_ORDER
        assert ling != byte, f"collation {name!r} did not reach the sort on the flat-column path"

    async def test_column_mapping_path(self, class_db_pool, test_schema, collation_rows) -> None:
        byte, ling, name = await self._pair(
            class_db_pool, test_schema, column_mapping={"name": "name"}
        )
        assert byte == BYTE_ORDER
        assert ling != byte, f"collation {name!r} did not reach the sort on the mapping path"

    async def test_jsonb_path(self, class_db_pool, test_schema, collation_rows) -> None:
        byte, ling, name = await self._pair(class_db_pool, test_schema)
        assert byte == BYTE_ORDER
        assert ling != byte, f"collation {name!r} did not reach the sort on the JSONB path"

    async def test_nested_jsonb_path(self, class_db_pool, test_schema, collation_rows) -> None:
        """The nested path extracts a leaf, so it must collate the leaf."""
        linguistic = await _linguistic_collation(class_db_pool)
        if linguistic is None:
            pytest.skip('no collation on this server disagrees with "C" about case')
        nested = OrderBy(field="profile.last_name", collation="C")
        byte = await _order(class_db_pool, test_schema, nested)
        ling = await _order(
            class_db_pool,
            test_schema,
            OrderBy(field="profile.last_name", collation=linguistic),
        )
        assert byte == BYTE_ORDER
        assert ling != byte


@pytest.mark.database
class TestUncollatedOrderingUnchanged:
    """The no-collation paths must keep the behaviour they had."""

    async def test_jsonb_numeric_ordering_survives(
        self, class_db_pool, test_schema, collation_rows
    ) -> None:
        """``->`` is used without a collation precisely to keep numeric sorts numeric."""
        async with class_db_pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(f"SET search_path TO {test_schema}")
            await cursor.execute(f"DELETE FROM {TABLE}")
            for n in (2, 10, 1):
                await cursor.execute(
                    f"INSERT INTO {TABLE} (id, name, data) VALUES (%s, %s, %s::jsonb)",
                    (uuid.uuid4(), str(n), f'{{"amount": {n}}}'),
                )
            await conn.commit()

        order = await _order(class_db_pool, test_schema, OrderBy(field="amount"))
        assert order == ["1", "2", "10"], "numeric JSONB ordering must not become lexicographic"
