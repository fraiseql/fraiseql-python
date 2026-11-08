"""@fraiseql.connection pages a real view over GraphQL.

The decorator called ``db.paginate``, which ``FraiseQLRepository`` didn't have,
so every connection query answered with an error. The repository now pages
with ``find`` and ``count``: Relay edges, cursors and pageInfo, forward with
first/after and backward with last/before, filtered by ``where``.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import Connection

pytestmark = [pytest.mark.integration, pytest.mark.database]

_VIEW = "v_connection_item"

_PAGE = """
query Page($first: Int, $after: String, $last: Int, $before: String, $where: ConnectionItemWhereInput) {
  connectionItems(first: $first, after: $after, last: $last, before: $before, where: $where) {
    edges { cursor node { id name } }
    pageInfo { hasNextPage hasPreviousPage startCursor endCursor }
    totalCount
  }
}
"""


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def connection_items(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute("CREATE TABLE tb_connection_item (id INT PRIMARY KEY, name TEXT)")
        # Ids 1..12: past 9, text order and numeric order differ
        await conn.execute(
            "INSERT INTO tb_connection_item SELECT i, 'item ' || i FROM generate_series(1, 12) AS i"
        )
        await conn.execute(
            f"CREATE VIEW {_VIEW} AS SELECT id, "
            "jsonb_build_object('id', id, 'name', name) AS data FROM tb_connection_item"
        )
        await conn.commit()
    yield


@pytest.mark.usefixtures("clear_registry_class")
class TestConnectionDecorator:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, connection_items):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type(sql_source=_VIEW)
        class ConnectionItem:
            id: int
            name: str

        # The order the docs show: @connection over @query
        @fraiseql.connection(node_type=ConnectionItem, view_name=_VIEW, default_page_size=5)
        @fraiseql.query
        async def connection_items(info, first: int | None = None) -> Connection[ConnectionItem]:
            pass

        # And the other way round
        @fraiseql.query
        @fraiseql.connection(node_type=ConnectionItem, view_name=_VIEW)
        async def items_query_outer(info) -> Connection[ConnectionItem]:
            pass

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",  # the pool above is used
            types=[ConnectionItem],
            production=False,
        )
        return TestClient(app)

    def _page(self, client: TestClient, **variables) -> dict:
        body = client.post("/graphql", json={"query": _PAGE, "variables": variables}).json()
        assert "errors" not in body, body
        return body["data"]["connectionItems"]

    @staticmethod
    def _ids(page: dict) -> list[int]:
        return [edge["node"]["id"] for edge in page["edges"]]

    def test_first_page(self, client) -> None:
        page = self._page(client, first=3)
        assert self._ids(page) == [1, 2, 3]
        assert page["totalCount"] == 12
        assert page["pageInfo"]["hasNextPage"] is True
        assert page["pageInfo"]["hasPreviousPage"] is False
        assert page["pageInfo"]["startCursor"] == page["edges"][0]["cursor"]
        assert page["pageInfo"]["endCursor"] == page["edges"][-1]["cursor"]
        assert [edge["node"]["name"] for edge in page["edges"]] == ["item 1", "item 2", "item 3"]

    def test_default_page_size(self, client) -> None:
        assert self._ids(self._page(client)) == [1, 2, 3, 4, 5]

    def test_after_walks_every_page(self, client) -> None:
        seen: list[int] = []
        after = None
        while True:
            page = self._page(client, first=5, after=after)
            seen += self._ids(page)
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        assert seen == list(range(1, 13))
        assert page["pageInfo"]["hasPreviousPage"] is True

    def test_last_and_before(self, client) -> None:
        page = self._page(client, last=3)
        assert self._ids(page) == [10, 11, 12]
        assert page["pageInfo"]["hasPreviousPage"] is True
        before = page["pageInfo"]["startCursor"]
        page = self._page(client, last=3, before=before)
        assert self._ids(page) == [7, 8, 9]
        assert page["pageInfo"]["hasNextPage"] is True

    def test_where_filters_page_and_count(self, client) -> None:
        page = self._page(client, first=2, where={"id": {"gt": 8}})
        assert self._ids(page) == [9, 10]
        assert page["totalCount"] == 4
        page = self._page(
            client, first=2, after=page["pageInfo"]["endCursor"], where={"id": {"gt": 8}}
        )
        assert self._ids(page) == [11, 12]
        assert page["pageInfo"]["hasNextPage"] is False

    def test_past_the_end_is_empty(self, client) -> None:
        last = self._page(client, first=12)["pageInfo"]["endCursor"]
        page = self._page(client, first=3, after=last)
        assert page["edges"] == []
        assert page["pageInfo"]["hasNextPage"] is False
        assert page["pageInfo"]["startCursor"] is None

    def test_query_over_connection(self, client) -> None:
        query = "{ itemsQueryOuter(first: 2) { edges { node { id } } totalCount } }"
        body = client.post("/graphql", json={"query": query}).json()
        assert "errors" not in body, body
        page = body["data"]["itemsQueryOuter"]
        assert self._ids(page) == [1, 2]
        assert page["totalCount"] == 12
