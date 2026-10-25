"""db.find's response holds the keys in the order the query selects them.

The GraphQL spec orders a response map like its selection set. Rust's
projection wrote the keys in serde_json's map order, alphabetical:
``{ users { name id email } }`` came back as ``{"email", "id", "name"}``.
"""

import json

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import create_fraiseql_app

pytestmark = [pytest.mark.integration, pytest.mark.database]

_VIEW = "v_key_order_user"


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def view(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(
            f"CREATE VIEW {_VIEW} AS SELECT 1 AS id, jsonb_build_object("
            "'id', 1, 'name', 'ann', 'email', 'a@x.io', 'zip_code', '75001', "
            "'address', jsonb_build_object('street', 's', 'city', 'c', 'zip_code', 'z')) AS data"
        )
        await conn.commit()
    yield


def _keys(obj: dict) -> list:
    return [(k, _keys(v)) if isinstance(v, dict) else k for k, v in obj.items()]


@pytest.mark.usefixtures("clear_registry_class")
class _ResponseKeyOrder:
    registry: bool

    @pytest.fixture(scope="class")
    def client(self, class_db_pool, view):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type
        class KoAddress:
            street: str
            city: str
            zip_code: str

        @fraiseql.type(sql_source=_VIEW)
        class KoUser:
            id: int
            name: str
            email: str
            zip_code: str
            address: KoAddress

        @fraiseql.query
        async def ko_users(info) -> list[KoUser]:
            return await info.context["db"].find(_VIEW, "koUsers", info)

        @fraiseql.query
        async def ko_user(info) -> KoUser | None:
            return await info.context["db"].find_one(_VIEW, "koUser", info)

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",
            types=[KoUser, KoAddress],
            production=False,
            enable_schema_registry=self.registry,
        )
        return TestClient(app)

    def _body(self, client: TestClient, query: str) -> dict:
        response = client.post("/graphql", json={"query": query})
        # Read the raw JSON in order (a dict keeps insertion order)
        body = json.loads(response.content)
        assert "errors" not in body, body
        return body["data"]

    def test_list_keys_follow_the_selection(self, client) -> None:
        [user] = self._body(client, "{ koUsers { name id email } }")["koUsers"]

        assert list(user) == ["name", "id", "email"]

    def test_nested_keys_follow_the_selection(self, client) -> None:
        [user] = self._body(client, "{ koUsers { zipCode address { zipCode street city } name } }")[
            "koUsers"
        ]

        assert _keys(user) == ["zipCode", ("address", ["zipCode", "street", "city"]), "name"]

    def test_aliases_and_find_one(self, client) -> None:
        user = self._body(client, "{ koUser { z: zipCode a: address { s: street } id } }")["koUser"]

        assert _keys(user) == ["z", ("a", ["s"]), "id"]

    def test_several_root_fields(self, client) -> None:
        data = self._body(client, "{ koUser { name id } koUsers { email name } }")

        assert list(data) == ["koUser", "koUsers"]
        assert list(data["koUser"]) == ["name", "id"]
        assert list(data["koUsers"][0]) == ["email", "name"]


class TestResponseKeyOrderWithRegistry(_ResponseKeyOrder):
    registry = True


class TestResponseKeyOrderWithoutRegistry(_ResponseKeyOrder):
    """The zero-copy transformer, which wrote each row in its JSONB key order"""

    registry = False
