"""The repository's read helpers (aggregate, sum/avg/min/max, count...) on a real PostgreSQL.

The views are FraiseQL's usual shape, an ``id`` column and a JSONB ``data`` column,
and are not registered for a type: the helpers have to work from the view alone.
A flat table covers the column case.
"""

import json
from collections.abc import AsyncIterator

import psycopg
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


class TestFieldHelpersWithWhere:
    """The where's values are bind parameters: they have to reach the query."""

    async def test_on_columns(self, class_db_pool, views) -> None:
        repo = FraiseQLRepository(class_db_pool)
        table = f"{views}.tb_order"
        done = {"status": {"eq": "done"}}

        assert await repo.sum(table, "amount", where=done) == 30.0
        assert await repo.avg(table, "amount", where=done) == 15.0
        assert await repo.min(table, "amount", where=done) == 10
        assert await repo.max(table, "amount", where=done) == 20
        assert await repo.distinct(table, "amount", where=done) == [10, 20]
        assert sorted(await repo.pluck(table, "amount", where=done)) == [10, 20]

    async def test_with_mandatory_filters(self, class_db_pool, views) -> None:
        repo = FraiseQLRepository(class_db_pool)
        table = f"{views}.tb_order"
        done = {"status": "done"}

        assert await repo.sum(table, "amount", mandatory_filters=done) == 30.0
        assert await repo.max(table, "amount", mandatory_filters=done) == 20
        assert await repo.distinct(table, "status", mandatory_filters=done) == ["done"]


class TestPluckLimitOffset:
    async def test_limit_and_offset(self, class_db_pool, views) -> None:
        repo = FraiseQLRepository(class_db_pool)

        assert len(await repo.pluck(f"{views}.tb_order", "id", limit=2)) == 2
        assert len(await repo.pluck(f"{views}.tb_order", "id", limit=5, offset=2)) == 1

    @pytest.mark.parametrize("arg", ["limit", "offset"])
    async def test_sql_in_a_string_is_a_value_not_sql(self, class_db_pool, views, arg) -> None:
        """A string limit/offset is bound as a value; it used to be written into the SQL."""
        repo = FraiseQLRepository(class_db_pool)

        with pytest.raises(psycopg.errors.InvalidTextRepresentation):
            await repo.pluck(
                f"{views}.tb_order", "id", **{arg: f"1; DROP TABLE {views}.tb_order CASCADE"}
            )

        assert sorted(await repo.pluck(f"{views}.tb_order", "id")) == [1, 2, 3]


class TestFieldHelpersOnAJsonbView:
    """The field lives in ``data``: it is read from there, registered type or not."""

    async def test_unregistered(self, class_db_pool, views) -> None:
        repo = FraiseQLRepository(class_db_pool)
        view = f"{views}.v_order"

        assert await repo.sum(view, "amount") == 35.0
        assert await repo.avg(view, "amount", where={"status": {"eq": "done"}}) == 15.0
        assert await repo.min(view, "amount") == 5
        assert await repo.max(view, "amount") == 20
        assert await repo.min(view, "placed") == "2025-01-01"
        assert await repo.max(view, "status") == "open"
        assert await repo.distinct(view, "status") == ["done", "open"]
        assert sorted(await repo.pluck(view, "amount")) == [5, 10, 20]
        assert sorted(await repo.pluck(view, "id")) == [1, 2, 3]

    async def test_no_rows(self, class_db_pool, views) -> None:
        repo = FraiseQLRepository(class_db_pool)
        view = f"{views}.v_order"
        lost = {"status": {"eq": "lost"}}

        assert await repo.sum(view, "amount", where=lost) == 0.0
        assert await repo.min(view, "amount", where=lost) is None
        assert await repo.max(view, "amount", where=lost) is None
        assert await repo.distinct(view, "amount", where=lost) == []

    async def test_registered(self, class_db_pool, views, clear_registry) -> None:
        import fraiseql

        @fraiseql.type(sql_source=f"{views}.v_order")
        class Order:
            id: int
            amount: int
            status: str

        repo = FraiseQLRepository(class_db_pool)
        view = f"{views}.v_order"

        assert await repo.sum(view, "amount", where={"status": {"eq": "done"}}) == 30.0
        assert await repo.max(view, "amount") == 20
        assert await repo.distinct(view, "status") == ["done", "open"]


class TestQueryTimeout:
    """``query_timeout`` (seconds) is the statement timeout of every read."""

    @pytest.fixture
    async def slow_view(self, class_db_pool, views) -> str:
        async with class_db_pool.connection() as conn:
            await conn.execute(
                f"CREATE OR REPLACE VIEW {views}.v_slow_order AS "
                f"SELECT id, data FROM {views}.tb_order, pg_sleep(1)"
            )
            await conn.commit()
        return f"{views}.v_slow_order"

    @pytest.mark.parametrize(
        "read",
        [
            lambda repo, view: repo.find(view, "orders"),
            lambda repo, view: repo.find_one(view, "order", where={"id": {"eq": 1}}),
            lambda repo, view: repo.count(view),
            lambda repo, view: repo.exists(view),
            lambda repo, view: repo.sum(view, "amount"),
            lambda repo, view: repo.aggregate(view, {"n": "COUNT(*)"}),
        ],
        ids=["find", "find_one", "count", "exists", "sum", "aggregate"],
    )
    async def test_a_slow_read_is_cancelled(self, class_db_pool, slow_view, read) -> None:
        import psycopg

        repo = FraiseQLRepository(class_db_pool, context={"query_timeout": 0.2})

        with pytest.raises(psycopg.errors.QueryCanceled):
            await read(repo, slow_view)

    async def test_a_read_within_the_timeout_runs(self, class_db_pool, slow_view) -> None:
        repo = FraiseQLRepository(class_db_pool, context={"query_timeout": 5})

        assert await repo.count(slow_view) == 3

    async def test_the_timeout_ends_with_the_read(self, class_db_pool, views) -> None:
        repo = FraiseQLRepository(class_db_pool, context={"query_timeout": 0.2})
        await repo.count(f"{views}.v_order")

        async with class_db_pool.connection() as conn:
            cursor = await conn.execute("SHOW statement_timeout")
            assert (await cursor.fetchone())[0] == "0"


class TestWhereOnAnUnregisteredJsonbView:
    """A field that isn't a column of the view is read from its ``data`` column."""

    async def test_count_and_exists(self, class_db_pool, views) -> None:
        repo = FraiseQLRepository(class_db_pool)
        view = f"{views}.v_order"

        assert await repo.count(view, where={"status": {"eq": "done"}}) == 2
        assert await repo.count(view, where={"amount": {"gte": 10}}) == 2
        assert await repo.exists(view, where={"status": {"eq": "open"}}) is True
        assert await repo.exists(view, where={"status": {"eq": "lost"}}) is False

    async def test_a_column_stays_a_column(self, class_db_pool, views) -> None:
        repo = FraiseQLRepository(class_db_pool)

        assert await repo.count(f"{views}.v_order", where={"id": {"in": [1, 3]}}) == 2

    async def test_aggregate(self, class_db_pool, views) -> None:
        repo = FraiseQLRepository(class_db_pool)

        stats = await repo.aggregate(
            f"{views}.v_order",
            {"orders": "COUNT(*)", "total": "SUM((data ->> 'amount')::numeric)"},
            where={"status": {"eq": "done"}},
        )

        assert stats == {"orders": 2, "total": 30}

    async def test_a_flat_table_still_filters_on_its_columns(self, class_db_pool, views) -> None:
        repo = FraiseQLRepository(class_db_pool)

        assert await repo.count(f"{views}.tb_order", where={"status": {"eq": "done"}}) == 2
