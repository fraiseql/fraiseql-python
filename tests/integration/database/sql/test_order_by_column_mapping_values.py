"""Issue #467, third leg: what ordering on a mapped column actually changes.

The SQL-text tests prove the expression is `t."col"`. They cannot prove which
rows come back first, and that is the whole risk of this change: a JSONB snapshot
is compared with jsonb semantics, a real column with the column's own type.

Dates in a JSONB snapshot are always ISO 8601 — the Date scalar serializes with
``isoformat()`` and validates the string on the way out — and ISO dates sort
lexicographically in chronological order. So for the shape this library actually
produces, **the mapping does not reorder values**. The same holds for a measure
stored as a JSON number, which is why the generator uses ``->`` and not ``->>``.

What does change, always, is where NULLs land: jsonb ``null`` is the lowest jsonb
value and sorts first, while a SQL NULL sorts last in ASC. And values genuinely
reorder in two shapes a snapshot can still carry — a number written as a string,
and an ISO *timestamp* whose rows do not share one UTC offset.

Each of those is asserted below, against a live database, mapped and unmapped.
These also exercise the ``AS t`` alias a mapped sort key needs on the plain
(non-aggregated) SELECT: without it PostgreSQL rejects the statement outright, so
a missing alias fails here as a syntax error rather than as bad SQL text.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from fraiseql.db import FraiseQLRepository, _table_metadata, _type_registry, register_type_for_view

pytestmark = pytest.mark.database

VIEW = "v_467_order_values"
COLUMNS = {"id", "period_date", "model_count", "moment_ts", "data"}

# Every mapped path resolves to the same flat column its snapshot value mirrors.
MAPPING = {
    "dimensions.stats.day": "period_date",
    "dimensions.stats.count": "model_count",
    "dimensions.stats.count_text": "model_count",
    "dimensions.stats.moment": "moment_ts",
}

# (tag, period_date, model_count, moment_ts). The 'none' row carries jsonb null
# in every snapshot slot and SQL NULL in every column.
ROWS = [
    ("oct", "2025-10-01", 9, "2025-01-05T00:00:00+02:00"),
    ("jan", "2025-01-05", 10, "2025-01-04T23:30:00+00:00"),
    ("feb", "2025-02-10", 100, "2025-01-05T01:00:00+05:00"),
    ("none", None, None, None),
]


class _Stats:
    """Stand-in for a @fraise_type analytics class."""


def _snapshot(tag: str, day: str | None, count: int | None, moment: str | None) -> dict:
    """The frozen JSONB view of a row, mirroring the flat columns."""
    return {
        "tag": tag,
        "dimensions": {
            "stats": {
                "day": day,
                "count": count,
                "count_text": None if count is None else str(count),
                "moment": moment,
                "label": None if count is None else f"label-{count:03d}",
            }
        },
    }


@pytest.fixture
async def stats_table(class_db_pool, test_schema) -> AsyncIterator[None]:
    """A hybrid table whose JSONB snapshot mirrors its flat columns."""
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {test_schema}")
        await cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {VIEW} (
                id UUID PRIMARY KEY,
                period_date DATE,
                model_count INTEGER,
                moment_ts TIMESTAMPTZ,
                data JSONB
            )
        """)
        for tag, day, count, moment in ROWS:
            await cursor.execute(
                f"INSERT INTO {VIEW} (id, period_date, model_count, moment_ts, data) "
                f"VALUES (%s, %s, %s, %s, %s::jsonb)",
                (uuid.uuid4(), day, count, moment, json.dumps(_snapshot(tag, day, count, moment))),
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


async def _order(pool: Any, schema: str, path: str, direction: str, *, mapped: bool) -> list[str]:
    """Run the built query against the database and return the row tags, in order."""
    _register(with_mapping=mapped)
    repo = FraiseQLRepository(pool)
    leaf = path.rsplit(".", 1)[-1]
    query = repo._build_find_query(
        VIEW,
        jsonb_column="data",
        order_by={"dimensions": {"stats": {leaf: direction}}},
    )

    async with pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {schema}")
        await cursor.execute(query.statement, query.params)
        rows = await cursor.fetchall()

    return [json.loads(row[0])["tag"] for row in rows]


def _without_nulls(tags: list[str]) -> list[str]:
    return [t for t in tags if t != "none"]


class TestIsoDatesKeepTheirOrder:
    """The convention is ISO, and ISO dates sort the same either way."""

    async def test_ascending_values_are_unchanged_by_the_mapping(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        mapped = await _order(class_db_pool, test_schema, "stats.day", "asc", mapped=True)
        unmapped = await _order(class_db_pool, test_schema, "stats.day", "asc", mapped=False)

        assert _without_nulls(mapped) == ["jan", "feb", "oct"]
        assert _without_nulls(unmapped) == _without_nulls(mapped)

    async def test_descending_values_are_unchanged_by_the_mapping(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        mapped = await _order(class_db_pool, test_schema, "stats.day", "desc", mapped=True)
        unmapped = await _order(class_db_pool, test_schema, "stats.day", "desc", mapped=False)

        assert _without_nulls(mapped) == ["oct", "feb", "jan"]
        assert _without_nulls(unmapped) == _without_nulls(mapped)


class TestJsonNumbersKeepTheirOrder:
    """``->`` preserves the jsonb type, so a measure stored as a number already sorted right."""

    async def test_values_are_unchanged_by_the_mapping(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        mapped = await _order(class_db_pool, test_schema, "stats.count", "asc", mapped=True)
        unmapped = await _order(class_db_pool, test_schema, "stats.count", "asc", mapped=False)

        assert _without_nulls(mapped) == ["oct", "jan", "feb"]
        assert _without_nulls(unmapped) == _without_nulls(mapped)


class TestNullPlacementChanges:
    """The one change that is always there: jsonb null sorts first, SQL NULL sorts last."""

    async def test_ascending_moves_nulls_from_first_to_last(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        mapped = await _order(class_db_pool, test_schema, "stats.day", "asc", mapped=True)
        unmapped = await _order(class_db_pool, test_schema, "stats.day", "asc", mapped=False)

        assert unmapped[0] == "none"
        assert mapped[-1] == "none"

    async def test_descending_moves_nulls_from_last_to_first(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        mapped = await _order(class_db_pool, test_schema, "stats.day", "desc", mapped=True)
        unmapped = await _order(class_db_pool, test_schema, "stats.day", "desc", mapped=False)

        assert unmapped[-1] == "none"
        assert mapped[0] == "none"

    async def test_the_same_holds_for_a_numeric_column(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        mapped = await _order(class_db_pool, test_schema, "stats.count", "asc", mapped=True)
        unmapped = await _order(class_db_pool, test_schema, "stats.count", "asc", mapped=False)

        assert unmapped[0] == "none"
        assert mapped[-1] == "none"


class TestValuesReorderWhenTheSnapshotIsNotTyped:
    """Two shapes where the mapping genuinely changes which row comes first."""

    async def test_a_number_written_as_a_string_sorted_lexicographically(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        mapped = await _order(class_db_pool, test_schema, "stats.count_text", "asc", mapped=True)
        unmapped = await _order(class_db_pool, test_schema, "stats.count_text", "asc", mapped=False)

        assert _without_nulls(mapped) == ["oct", "jan", "feb"]  # 9, 10, 100
        assert _without_nulls(unmapped) == ["jan", "feb", "oct"]  # "10", "100", "9"

    async def test_iso_timestamps_with_differing_offsets(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        """Every string here is valid ISO 8601 — lexicographic still is not chronological."""
        mapped = await _order(class_db_pool, test_schema, "stats.moment", "asc", mapped=True)
        unmapped = await _order(class_db_pool, test_schema, "stats.moment", "asc", mapped=False)

        assert _without_nulls(mapped) == ["feb", "oct", "jan"]
        assert _without_nulls(unmapped) == ["jan", "oct", "feb"]


class TestUnmappedOrderingIsUnchanged:
    """Anything the mapping does not name sorts exactly as it did."""

    async def test_unmapped_path_is_identical_with_and_without_the_mapping(
        self, class_db_pool, test_schema, stats_table
    ) -> None:
        mapped = await _order(class_db_pool, test_schema, "stats.label", "asc", mapped=True)
        unmapped = await _order(class_db_pool, test_schema, "stats.label", "asc", mapped=False)

        assert mapped == unmapped
        assert _without_nulls(mapped) == ["oct", "jan", "feb"]
