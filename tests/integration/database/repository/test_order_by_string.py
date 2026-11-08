"""A string ``order_by`` on a real PostgreSQL: columns sort, SQL never runs.

``db.find(view, order_by="...")`` used to put the string after ``ORDER BY`` as
is; ``"id; DROP TABLE ..."`` dropped the table.
"""

import json
from collections.abc import AsyncIterator

import pytest

from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.db import FraiseQLRepository

pytestmark = [pytest.mark.integration, pytest.mark.database]

ITEMS = [(1, "b", 2), (2, "a", 2), (3, "c", 1)]


@pytest.fixture
async def view(class_db_pool, test_schema) -> AsyncIterator[str]:
    """``{schema}.v_item``: ``id``, ``name``, ``"Rank"`` columns and a JSONB ``data``."""
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(
            f'CREATE TABLE {test_schema}.tb_item (id int, name text, "Rank" int, data jsonb)'
        )
        await cursor.execute(f"CREATE TABLE {test_schema}.tb_victim (x int)")
        for item_id, name, rank in ITEMS:
            await cursor.execute(
                f"INSERT INTO {test_schema}.tb_item VALUES (%s, %s, %s, %s::jsonb)",
                (item_id, name, rank, json.dumps({"id": item_id})),
            )
        await cursor.execute(
            f"CREATE VIEW {test_schema}.v_item AS SELECT * FROM {test_schema}.tb_item"
        )
        await conn.commit()

    yield f"{test_schema}.v_item"

    async with class_db_pool.connection() as conn:
        await conn.execute(f"DROP TABLE IF EXISTS {test_schema}.tb_item CASCADE")
        await conn.execute(f"DROP TABLE IF EXISTS {test_schema}.tb_victim")
        await conn.commit()


def _ids(result: RustResponseBytes) -> list[int]:
    rows = next(iter(json.loads(bytes(result))["data"].values()))
    return [row["id"] for row in rows]


class TestStringOrderBy:
    async def test_sorts_on_the_columns(self, class_db_pool, view) -> None:
        repo = FraiseQLRepository(class_db_pool)

        assert _ids(await repo.find(view, "items", order_by="name DESC")) == [3, 1, 2]
        assert _ids(await repo.find(view, "items", order_by='"Rank", id DESC')) == [3, 2, 1]

    async def test_sql_in_the_string_raises_and_never_runs(
        self, class_db_pool, view, test_schema
    ) -> None:
        repo = FraiseQLRepository(class_db_pool)

        with pytest.raises(ValueError, match="order_by"):
            await repo.find(view, "items", order_by=f"id; DROP TABLE {test_schema}.tb_victim")

        async with class_db_pool.connection() as conn:
            cursor = await conn.execute("SELECT to_regclass(%s)", (f"{test_schema}.tb_victim",))
            assert (await cursor.fetchone())[0] is not None
