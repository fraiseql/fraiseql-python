"""A list query's where/orderBy/limit/offset reach db.find without being declared.

fraiseql adds these arguments to every query returning list[FraiseType], and the
docs show ``async def users(info) -> list[User]: return await db.find("v_user",
info=info)`` using them. A resolver that didn't declare them never received
them, and nothing else applied them: the query answered as if the client hadn't
filtered, sorted or paginated. db.find on the type's view now applies them.
"""

import logging
import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import create_fraiseql_app

pytestmark = [pytest.mark.integration, pytest.mark.database]

_VIEW = "v_list_argument_item"


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def list_argument_items(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute("CREATE TABLE tb_list_argument_item (id INT PRIMARY KEY, name TEXT)")
        await conn.execute(
            "INSERT INTO tb_list_argument_item VALUES (1, 'a'), (2, 'b'), (3, 'c'), (4, 'd')"
        )
        await conn.execute(
            f"CREATE VIEW {_VIEW} AS SELECT id, "
            "jsonb_build_object('id', id, 'name', name) AS data FROM tb_list_argument_item"
        )
        await conn.commit()
    yield


def _client(pool, queries, types) -> TestClient:
    from fraiseql.fastapi.dependencies import set_db_pool

    set_db_pool(pool)
    app = create_fraiseql_app(
        database_url="postgresql://test/test",  # the pool above is used
        types=types,
        queries=queries,
        production=False,
    )
    return TestClient(app)


def _names(client: TestClient, query: str) -> list[str]:
    body = client.post("/graphql", json={"query": query}).json()
    assert "errors" not in body, body
    return [item["name"] for item in next(iter(body["data"].values()))]


@pytest.mark.usefixtures("clear_registry_class")
class TestUndeclaredListArguments:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, list_argument_items):
        @fraiseql.type(sql_source=_VIEW)
        class ListArgumentItem:
            id: int
            name: str

        @fraiseql.query
        async def items(info) -> list[ListArgumentItem]:
            # Declares none of the list arguments, as in the docs
            return await info.context["db"].find(_VIEW, "items", info)

        @fraiseql.query
        async def items_without_info(info) -> list[ListArgumentItem]:
            return await info.context["db"].find(_VIEW, "itemsWithoutInfo")

        @fraiseql.query
        async def first_two(info, limit: int | None = 2) -> list[ListArgumentItem]:
            # Declares limit (so a client's limit replaces the default), not the others
            return await info.context["db"].find(_VIEW, "firstTwo", info, limit=limit)

        @fraiseql.query
        async def only_b(info) -> list[ListArgumentItem]:
            # Its own filter wins over a client's where
            where = {"name": {"eq": "b"}}
            return await info.context["db"].find(_VIEW, "onlyB", info, where=where)

        return _client(
            class_db_pool, [items, items_without_info, first_two, only_b], [ListArgumentItem]
        )

    def test_where_applies(self, client) -> None:
        assert _names(client, '{ items(where: {name: {in: ["b", "c"]}}) { name } }') == ["b", "c"]

    def test_order_by_limit_and_offset_apply(self, client) -> None:
        query = "{ items(orderBy: [{name: DESC}], limit: 2, offset: 1) { name } }"
        assert _names(client, query) == ["c", "b"]

    def test_without_arguments_everything_comes_back(self, client) -> None:
        assert sorted(_names(client, "{ items { name } }")) == ["a", "b", "c", "d"]

    def test_find_without_info_applies_them_too(self, client) -> None:
        query = '{ itemsWithoutInfo(where: {name: {eq: "d"}}) { name } }'
        assert _names(client, query) == ["d"]

    def test_declared_argument_is_the_resolvers(self, client) -> None:
        query = "{ firstTwo(orderBy: [{name: ASC}]) { name } }"
        assert _names(client, query) == ["a", "b"]
        query = "{ firstTwo(orderBy: [{name: ASC}], limit: 3, offset: 1) { name } }"
        assert _names(client, query) == ["b", "c", "d"]

    def test_resolver_filter_wins(self, client) -> None:
        assert _names(client, '{ onlyB(where: {name: {eq: "a"}}) { name } }') == ["b"]

    def test_two_fields_keep_their_own_arguments(self, client) -> None:
        body = client.post(
            "/graphql",
            json={
                "query": '{ x: items(where: {name: {eq: "a"}}) { name } '
                'y: items(where: {name: {eq: "c"}}) { name } }'
            },
        ).json()
        assert "errors" not in body, body
        assert [item["name"] for item in body["data"]["x"]] == ["a"]
        assert [item["name"] for item in body["data"]["y"]] == ["c"]


def test_type_without_sql_source_warns_at_schema_build(clear_registry, caplog) -> None:
    @fraiseql.type
    class InMemoryItem:
        id: uuid.UUID

    @fraiseql.query
    async def in_memory_items(info) -> list[InMemoryItem]:
        return []

    with caplog.at_level(logging.WARNING, logger="fraiseql.gql.builders.query_builder"):
        fraiseql.build_fraiseql_schema()

    messages = [r.getMessage() for r in caplog.records if "in_memory_items" in r.getMessage()]
    assert len(messages) == 1
    assert "where, orderBy, limit, offset" in messages[0]
