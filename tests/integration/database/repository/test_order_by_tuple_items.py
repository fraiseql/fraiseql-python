"""db.find sorts by ``(field, direction)`` tuples and bare field names.

``order_by=[("created_at", "DESC")]`` (the form ``fraiseql init`` generated)
resolved to no sort key and the rows came back in whatever order PostgreSQL
returned them.
"""

import pytest
import pytest_asyncio

pytestmark = pytest.mark.database

from tests.fixtures.database.database_conftest import *  # noqa: F403
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view

_VIEW = "v_tuple_order_item"


class TestOrderByTupleItems:
    @pytest.fixture(scope="class")
    def item_type(self, clear_registry_class):
        @fraiseql.type(sql_source=_VIEW)
        class TupleOrderItem:
            id: int
            name: str
            created_at: str

        return TupleOrderItem

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def item_view(self, class_db_pool, test_schema, item_type):
        register_type_for_view(_VIEW, item_type, table_columns={"id", "data"}, has_jsonb_data=True)
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute(
                "CREATE TABLE tuple_order_items (id INT PRIMARY KEY, name TEXT, "
                "created_at TIMESTAMPTZ)"
            )
            # Insertion order differs from both the created_at and the name order.
            await conn.execute(
                """
                INSERT INTO tuple_order_items VALUES
                    (1, 'beta', '2026-01-02'),
                    (2, 'alpha', '2026-01-03'),
                    (3, 'gamma', '2026-01-01')
                """
            )
            await conn.execute(
                f"CREATE VIEW {_VIEW} AS SELECT id, jsonb_build_object('id', id, "
                "'name', name, 'created_at', created_at) AS data FROM tuple_order_items"
            )
            await conn.commit()
        yield

    async def _names(self, pool, order_by) -> list[str]:
        repo = FraiseQLRepository(pool, context={"mode": "development"})
        rows = extract_graphql_data(await repo.find(_VIEW, order_by=order_by), _VIEW)
        return [row["name"] for row in rows]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("order_by", "expected"),
        [
            ([("created_at", "DESC")], ["alpha", "beta", "gamma"]),
            ([("createdAt", "asc")], ["gamma", "beta", "alpha"]),
            ([("name",)], ["alpha", "beta", "gamma"]),
            (["name"], ["alpha", "beta", "gamma"]),
            (("name", "DESC"), ["gamma", "beta", "alpha"]),
            ([{"created_at": "DESC"}], ["alpha", "beta", "gamma"]),
        ],
    )
    async def test_sorts(self, class_db_pool, item_view, order_by, expected) -> None:
        assert await self._names(class_db_pool, order_by) == expected

    @pytest.mark.asyncio
    async def test_unreadable_direction_raises(self, class_db_pool, item_view) -> None:
        with pytest.raises(ValueError, match="direction"):
            await self._names(class_db_pool, [("created_at", "descending")])
