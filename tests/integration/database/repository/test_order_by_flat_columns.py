"""order_by on a view without a JSONB column sorts on its columns.

Such a view is selected as ``t``, and fraiseql sorted on ``t -> 'field'``, a
JSONB extraction from the row itself: ``operator does not exist: <view> ->
unknown``. Only fields declared with native_dimensions or column_mapping sorted
on ``t."field"``.
"""

from datetime import datetime

import pytest
import pytest_asyncio

pytestmark = pytest.mark.database

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.sql.order_by_generator import OrderBy, OrderBySet, OrderDirection

_VIEW = "flat_document_view"


class TestOrderByFlatColumns:
    @pytest.fixture(scope="class")
    def document_type(self, clear_registry_class):
        @fraiseql.type(sql_source=_VIEW, jsonb_column=None)
        class FlatDocument:
            id: int
            title: str
            rank: int
            created_at: datetime

        return FlatDocument

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def flat_view(self, class_db_pool, test_schema, document_type):
        register_type_for_view(
            _VIEW,
            document_type,
            table_columns={"id", "title", "rank", "created_at"},
            has_jsonb_data=False,
        )
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute(
                "CREATE TABLE flat_documents "
                "(id INT PRIMARY KEY, title TEXT, rank INT, created_at TIMESTAMPTZ)"
            )
            # rank sorts differently as a number (2 < 10) than as text ('10' < '2')
            await conn.execute(
                """
                INSERT INTO flat_documents VALUES
                    (1, 'beta', 10, '2026-01-02'),
                    (2, 'alpha', 2, '2026-01-03'),
                    (3, 'gamma', 30, '2026-01-01')
                """
            )
            await conn.execute(f"CREATE VIEW {_VIEW} AS SELECT * FROM flat_documents")
            await conn.commit()
        yield

    async def _titles(self, pool, order_by) -> list[str]:
        repo = FraiseQLRepository(pool, context={"mode": "development"})
        rows = extract_graphql_data(await repo.find(_VIEW, order_by=order_by), _VIEW)
        return [row["title"] for row in rows]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("order_by", "expected"),
        [
            ({"created_at": "desc"}, ["alpha", "beta", "gamma"]),
            ([{"created_at": "asc"}], ["gamma", "beta", "alpha"]),
            ({"rank": "asc"}, ["alpha", "beta", "gamma"]),
            ({"title": "desc"}, ["gamma", "beta", "alpha"]),
            (
                OrderBySet([OrderBy("created_at", OrderDirection.DESC)]),
                ["alpha", "beta", "gamma"],
            ),
        ],
    )
    async def test_sorts_on_the_column(
        self, class_db_pool, flat_view, order_by, expected: list[str]
    ) -> None:
        assert await self._titles(class_db_pool, order_by) == expected
