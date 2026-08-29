"""Issue #467, third leg: ordering on a mapped column changes row order, for real.

The SQL-text tests prove the expression is `t."col"`. They cannot prove the rows
come back in a different order, and that is the whole risk of this change: a
JSONB snapshot is compared with jsonb semantics, a real column with the column's
own type. Where the snapshot holds a number or a date as a *string*, the two
disagree — lexicographically "10" < "9", and "01/10/2025" < "05/01/2025".

So these run against a live database and assert on values: one numeric mapped
column, one date mapped column, each ordered both ways.

They also exercise the ``AS t`` alias a mapped sort key needs on the plain
(non-aggregated) SELECT — without it PostgreSQL rejects the statement outright,
so a missing alias fails here as a syntax error rather than as bad SQL text.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from fraiseql.db import FraiseQLRepository, _table_metadata, _type_registry, register_type_for_view

pytestmark = pytest.mark.database

VIEW = "v_467_order_values"
COLUMNS = {"id", "identifier", "period_date", "model_count", "data"}
MAPPING = {
    "dimensions.stats.count": "model_count",
    "dimensions.stats.day": "period_date",
}

# The JSONB snapshot stores the count and the day as *strings*, in a spelling
# whose lexicographic order is neither the numeric nor the chronological one.
# 'label' is deliberately unmapped: it must sort identically either way.
ROWS = [
    ("nine", "2025-10-01", 9, "01/10/2025", "c-label"),
    ("ten", "2025-01-05", 10, "05/01/2025", "a-label"),
    ("hundred", "2025-02-10", 100, "10/02/2025", "b-label"),
]


def _snapshot(count: int, day_text: str, label: str) -> dict:
    return {"dimensions": {"stats": {"count": str(count), "day": day_text, "label": label}}}


class _Stats:
    """Stand-in for a @fraise_type analytics class."""


@pytest.fixture
async def stats_table(class_db_pool, test_schema) -> AsyncIterator[None]:
    """A hybrid table whose flat columns and JSONB snapshot sort differently."""
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {test_schema}")
        await cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {VIEW} (
                id UUID PRIMARY KEY,
                identifier TEXT,
                period_date DATE,
                model_count INTEGER,
                data JSONB
            )
        """)
        for identifier, day, count, day_text, label in ROWS:
            await cursor.execute(
                f"INSERT INTO {VIEW} (id, identifier, period_date, model_count, data) "
                f"VALUES (%s, %s, %s, %s, %s::jsonb)",
                (
                    uuid.uuid4(),
                    identifier,
                    day,
                    count,
                    json.dumps(_snapshot(count, day_text, label)),
                ),
            )
        await conn.commit()

    yield

    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {test_schema}")
        await cursor.execute(f"DROP TABLE IF EXISTS {VIEW} CASCADE")
        await conn.commit()

    _table_metadata.pop(VIEW, None)
    _type_registry.pop(VIEW, None)


def _register(*, with_mapping: bool) -> None:
    register_type_for_view(
        VIEW,
        _Stats,
        table_columns=COLUMNS,
        has_jsonb_data=True,
        jsonb_column="data",
        column_mapping=MAPPING if with_mapping else None,
    )


async def _order(pool: Any, schema: str, order_by: dict, *, with_mapping: bool) -> list[str]:
    """Run the built query against the database and return the identifiers, in order."""
    _register(with_mapping=with_mapping)
    repo = FraiseQLRepository(pool)
    query = repo._build_find_query(VIEW, jsonb_column="data", order_by=order_by)

    async with pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {schema}")
        await cursor.execute(query.statement, query.params)
        rows = await cursor.fetchall()

    # The projection is the JSONB snapshot; identify rows by the count they carry.
    counts = [json.loads(row[0])["dimensions"]["stats"]["count"] for row in rows]
    by_count = {str(count): identifier for identifier, _, count, _, _ in ROWS}
    return [by_count[c] for c in counts]


class TestNumericMappedColumn:
    """A count stored as a JSONB string sorts lexicographically; the column does not."""

    async def test_ascending_is_numeric_not_lexicographic(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        ordered = await _order(
            class_db_pool,
            test_schema,
            {"dimensions": {"stats": {"count": "asc"}}},
            with_mapping=True,
        )

        assert ordered == ["nine", "ten", "hundred"]

    async def test_descending_is_numeric(self, class_db_pool, test_schema, stats_table) -> None:
        ordered = await _order(
            class_db_pool,
            test_schema,
            {"dimensions": {"stats": {"count": "desc"}}},
            with_mapping=True,
        )

        assert ordered == ["hundred", "ten", "nine"]

    async def test_without_the_mapping_the_order_is_lexicographic(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        """The contrast that makes this a real change, not just different SQL text."""
        ordered = await _order(
            class_db_pool,
            test_schema,
            {"dimensions": {"stats": {"count": "asc"}}},
            with_mapping=False,
        )

        assert ordered == ["ten", "hundred", "nine"]


class TestDateMappedColumn:
    """A day stored as a DD/MM/YYYY string sorts by its digits; the DATE column does not."""

    async def test_ascending_is_chronological(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        ordered = await _order(
            class_db_pool,
            test_schema,
            {"dimensions": {"stats": {"day": "asc"}}},
            with_mapping=True,
        )

        assert ordered == ["ten", "hundred", "nine"]

    async def test_descending_is_chronological(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        ordered = await _order(
            class_db_pool,
            test_schema,
            {"dimensions": {"stats": {"day": "desc"}}},
            with_mapping=True,
        )

        assert ordered == ["nine", "hundred", "ten"]

    async def test_without_the_mapping_the_order_is_lexicographic(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        ordered = await _order(
            class_db_pool,
            test_schema,
            {"dimensions": {"stats": {"day": "asc"}}},
            with_mapping=False,
        )

        assert ordered == ["nine", "ten", "hundred"]


class TestUnmappedOrderingIsUnchanged:
    """Anything the mapping does not name sorts exactly as it did — same rows, same order."""

    async def test_unmapped_path_is_identical_with_and_without_the_mapping(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        order_by = {"dimensions": {"stats": {"label": "asc"}}}

        with_mapping = await _order(class_db_pool, test_schema, order_by, with_mapping=True)
        without_mapping = await _order(class_db_pool, test_schema, order_by, with_mapping=False)

        assert with_mapping == without_mapping
        assert with_mapping == ["ten", "hundred", "nine"]
