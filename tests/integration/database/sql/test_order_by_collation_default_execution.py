"""Issue #482: the configured collation default, executed against a live database.

#481 made an *explicit* per-field collation work on every path and deliberately
left ``default_string_collation`` inert, because nothing in the order_by
pipeline tracked field types and a blanket default would have produced

* a silently lexicographic sort for a numeric JSONB field -- 1, 10, 2 -- and
* ``ERROR: collations are not supported by type integer`` for a numeric flat
  column.

Both of those are why this needs a live database rather than a text assertion.
The first does not error, so only the returned order can tell; the second only
errors at the server. So these tests run the whole repository path -- config,
view registry, type resolution, SQL generation -- and look at what PostgreSQL
gives back.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from psycopg.sql import SQL

from fraiseql.db import FraiseQLRepository, _table_metadata, _type_registry, register_type_for_view
from fraiseql.types import fraise_type

pytestmark = [pytest.mark.integration, pytest.mark.database]

VIEW = "v_482_docs"

# Byte order puts uppercase first; a linguistic collation orders
# case-insensitively. Rows that disagree prove the collation reached the sort.
NAMES = ["a", "B", "c"]
BYTE_ORDER = ["B", "a", "c"]

# Lexicographic text order would be 1, 10, 2.
AMOUNTS = [2, 10, 1]


@fraise_type
class _Doc:
    """The registered type: how the collation resolver learns which field is text."""

    id: uuid.UUID
    name: str
    amount: int


async def _linguistic_collation(pool: Any) -> str | None:
    """A collation on this server that disagrees with ``"C"`` about case."""
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
                    (NAMES,),
                )
            except Exception:
                await conn.rollback()
                continue
            if [r[0] for r in await cursor.fetchall()] != BYTE_ORDER:
                return candidate
            await conn.rollback()
    return None


class _Config:
    """Stand-in for the one FraiseQLConfig attribute this path reads."""

    def __init__(self, collation: str | None) -> None:
        self.default_string_collation = collation


@pytest.fixture
async def docs_table(class_db_pool, test_schema) -> AsyncIterator[None]:
    """The same values as flat columns and inside JSONB, with the view registered."""
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {test_schema}")
        await cursor.execute(
            f"CREATE TABLE IF NOT EXISTS {VIEW} "
            f"(id UUID PRIMARY KEY, name TEXT NOT NULL, amount INT NOT NULL, data JSONB NOT NULL)"
        )
        for name, amount in zip(NAMES, AMOUNTS, strict=True):
            await cursor.execute(
                f"INSERT INTO {VIEW} (id, name, amount, data) VALUES (%s, %s, %s, %s::jsonb)",
                (uuid.uuid4(), name, amount, f'{{"name": "{name}", "amount": {amount}}}'),
            )
        await conn.commit()

    register_type_for_view(VIEW, _Doc, table_columns={"id", "name", "amount", "data"})

    yield

    for registry in (_table_metadata, _type_registry):
        registry.pop(VIEW, None)

    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {test_schema}")
        await cursor.execute(f"DROP TABLE IF EXISTS {VIEW} CASCADE")
        await conn.commit()


async def _run(pool: Any, schema: str, order_by: Any, collation: str | None, **kwargs) -> list:
    """Build the query the way the repository does, then execute it."""
    repo = FraiseQLRepository(pool, context={"config": _Config(collation)})
    query = repo._build_find_query(VIEW, order_by=order_by, jsonb_column="data", **kwargs)

    async with pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {schema}")
        await cursor.execute(query.statement, query.params)
        return [row[0] for row in await cursor.fetchall()]


# The repository always selects ``jsonb_column::text`` -- Rust does the field
# projection, not PostgreSQL -- so each row arrives as a JSON string.
def _names(rows: list) -> list[str]:
    return [json.loads(row)["name"] for row in rows]


def _amounts(rows: list) -> list[int]:
    return [json.loads(row)["amount"] for row in rows]


class TestDefaultReachesTextFields:
    """The setting finally does what it has always documented."""

    async def test_default_changes_the_order_of_a_text_field(
        self, class_db_pool, test_schema, docs_table
    ) -> None:
        linguistic = await _linguistic_collation(class_db_pool)
        if linguistic is None:
            pytest.skip('no collation on this server disagrees with "C" about case')

        byte = _names(await _run(class_db_pool, test_schema, {"name": "ASC"}, "C"))
        ling = _names(await _run(class_db_pool, test_schema, {"name": "ASC"}, linguistic))

        assert byte == BYTE_ORDER
        assert ling != byte, f"the configured default {linguistic!r} did not reach the sort"

    async def test_no_default_leaves_the_database_collation(
        self, class_db_pool, test_schema, docs_table
    ) -> None:
        rows = _names(await _run(class_db_pool, test_schema, {"name": "ASC"}, None))

        assert sorted(rows) == sorted(NAMES)


class TestDefaultDoesNotReachNonTextFields:
    """The two failures #481 refused to ship."""

    async def test_numeric_jsonb_field_stays_numeric(
        self, class_db_pool, test_schema, docs_table
    ) -> None:
        """A blanket default makes this 1, 10, 2 -- silently, with no error."""
        amounts = _amounts(await _run(class_db_pool, test_schema, {"amount": "ASC"}, "C"))

        assert amounts == [1, 2, 10]

    async def test_numeric_flat_column_does_not_error(
        self, class_db_pool, test_schema, docs_table
    ) -> None:
        """A blanket default fails outright: collations are not supported by type integer."""
        amounts = _amounts(
            await _run(
                class_db_pool,
                test_schema,
                {"amount": "ASC"},
                "C",
                native_dimensions={"amount"},
            )
        )

        assert amounts == [1, 2, 10]

    async def test_text_flat_column_still_gets_the_default(
        self, class_db_pool, test_schema, docs_table
    ) -> None:
        """The flat-column path must collate text even though it must not collate integers."""
        linguistic = await _linguistic_collation(class_db_pool)
        if linguistic is None:
            pytest.skip('no collation on this server disagrees with "C" about case')

        byte = _names(
            await _run(
                class_db_pool, test_schema, {"name": "ASC"}, "C", native_dimensions={"name"}
            )
        )
        ling = _names(
            await _run(
                class_db_pool, test_schema, {"name": "ASC"}, linguistic, native_dimensions={"name"}
            )
        )

        assert byte == BYTE_ORDER
        assert ling != byte
