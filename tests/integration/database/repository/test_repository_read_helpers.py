"""The repository's read helpers (aggregate, sum/avg/min/max, count...) on a real PostgreSQL.

The views are FraiseQL's usual shape, an ``id`` column and a JSONB ``data`` column,
and are not registered for a type: the helpers have to work from the view alone.
A flat table covers the column case.
"""

import json
from collections.abc import AsyncIterator

import pytest

from fraiseql.db import FraiseQLRepository

pytestmark = [pytest.mark.integration, pytest.mark.database]

ORDERS = [
    (1, {"amount": 10, "status": "done", "placed": "2025-01-03"}),
    (2, {"amount": 20, "status": "done", "placed": "2025-01-01"}),
    (3, {"amount": 5, "status": "open", "placed": "2025-01-02"}),
]


@pytest.fixture
async def views(class_db_pool, test_schema) -> AsyncIterator[str]:
    """``{schema}.tb_order`` (flat), ``{schema}.v_order`` (id + data)."""
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(
            f"CREATE TABLE {test_schema}.tb_order "
            "(id int PRIMARY KEY, amount numeric, status text, data jsonb)"
        )
        for order_id, data in ORDERS:
            await cursor.execute(
                f"INSERT INTO {test_schema}.tb_order VALUES (%s, %s, %s, %s::jsonb)",
                (order_id, data["amount"], data["status"], json.dumps(data)),
            )
        await cursor.execute(
            f"CREATE VIEW {test_schema}.v_order AS SELECT id, data FROM {test_schema}.tb_order"
        )
        await conn.commit()

    yield test_schema

    async with class_db_pool.connection() as conn:
        await conn.execute(f"DROP TABLE IF EXISTS {test_schema}.tb_order CASCADE")
        await conn.commit()


class TestAggregate:
    async def test_several_expressions_in_one_query(self, class_db_pool, views) -> None:
        repo = FraiseQLRepository(class_db_pool)

        stats = await repo.aggregate(
            f"{views}.tb_order",
            {"total": "SUM(amount)", "biggest": "MAX(amount)", "orders": "COUNT(*)"},
        )

        assert stats == {"total": 35, "biggest": 20, "orders": 3}

    async def test_with_where(self, class_db_pool, views) -> None:
        repo = FraiseQLRepository(class_db_pool)

        stats = await repo.aggregate(
            f"{views}.tb_order",
            {"total": "SUM(amount)", "orders": "COUNT(*)"},
            where={"status": {"eq": "done"}},
        )

        assert stats == {"total": 30, "orders": 2}
