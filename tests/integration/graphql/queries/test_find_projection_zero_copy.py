"""db.find answers with exactly the selected fields when Rust has no schema registry.

Without the registry (``enable_schema_registry=False``), or for a view no type is
registered for, Rust streams the rows through its zero-copy transformer. Its
selection was a 128-bit map of hashed root keys: a key hashing to a selected key's
bit was written too (``secret_note17`` came back with ``author``), a nested object
lost every field (``author: {}``), and keys were camelCased whatever
``auto_camel_case`` said.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

pytestmark = [pytest.mark.integration, pytest.mark.database]

# A string JSON escapes ("t \"q\" \\"): it comes back as stored
_TITLE = 't "q" \\'
# "secret_note17" and "author" fell on the same bit of the old hash map
_ROW = (
    "jsonb_build_object('id', 1, 'title', 't \"q\" \\', 'secret_note17', 'LEAK', "
    "'secret_note', 's', "
    "'author', jsonb_build_object('first_name', 'f', 'last_name', 'l', 'password', 'pw'), "
    "'tags', jsonb_build_array(jsonb_build_object('tag_name', 'a', 'secret', 'x'), "
    "jsonb_build_object('tag_name', 'b', 'secret', 'y')))"
)


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def post_views(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(f"CREATE VIEW v_zc_post AS SELECT 1 AS id, {_ROW} AS data")
        # No type names this view, so its rows are read whole (row_to_json): its
        # fields are columns
        await conn.execute(
            "CREATE VIEW v_zc_post_unregistered AS SELECT (d->>'id')::int AS id, "
            "d->>'title' AS title, d->>'secret_note17' AS secret_note17, "
            "d->>'secret_note' AS secret_note, d->'author' AS author, d->'tags' AS tags "
            f"FROM (SELECT {_ROW} AS d) AS row"
        )
        await conn.commit()
    yield


@pytest.mark.usefixtures("clear_registry_class")
class _ZeroCopyProjection:
    registry: bool
    camel: bool
    root: str  # the query reading the view

    @pytest.fixture(scope="class")
    def client(self, class_db_pool, post_views):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type
        class ZcAuthor:
            first_name: str
            last_name: str

        @fraiseql.type
        class ZcTag:
            tag_name: str

        @fraiseql.type(sql_source="v_zc_post")
        class ZcPost:
            id: int
            title: str
            author: ZcAuthor
            tags: list[ZcTag]

        @fraiseql.type
        class ZcRawPost:
            id: int
            title: str
            author: ZcAuthor
            tags: list[ZcTag]

        @fraiseql.query
        async def posts(info) -> list[ZcPost]:
            return await info.context["db"].find("v_zc_post", info=info)

        @fraiseql.query
        async def raw_posts(info) -> list[ZcRawPost]:
            return await info.context["db"].find("v_zc_post_unregistered", info=info)

        @fraiseql.query
        async def whole_posts(info) -> list[ZcPost]:
            # Without info, the rows are read whole
            return await info.context["db"].find("v_zc_post")

        set_db_pool(class_db_pool)
        config = FraiseQLConfig(database_url="postgresql://test/test", auto_camel_case=self.camel)
        app = create_fraiseql_app(
            config=config,
            types=[ZcPost, ZcRawPost, ZcAuthor, ZcTag],
            queries=[posts, raw_posts, whole_posts],
            production=False,
            enable_schema_registry=self.registry,
        )
        return TestClient(app)

    def _rows(self, client: TestClient, selection: str) -> list[dict]:
        root = self.root if self.camel else self.root.replace("rawPosts", "raw_posts")
        body = client.post("/graphql", json={"query": f"{{ {root} {selection} }}"}).json()
        assert "errors" not in body, body
        return [_without_typename(row) for row in body["data"][root]]

    def _name(self, camel: str, snake: str) -> str:
        return camel if self.camel else snake

    def test_a_key_hashing_like_a_selected_one_is_left_out(self, client) -> None:
        first_name = self._name("firstName", "first_name")
        [row] = self._rows(client, f"{{ author {{ {first_name} }} }}")

        assert row == {"author": {first_name: "f"}}

    def test_a_nested_object_keeps_its_selected_fields(self, client) -> None:
        first_name = self._name("firstName", "first_name")
        last_name = self._name("lastName", "last_name")
        [row] = self._rows(client, f"{{ id author {{ {last_name} {first_name} }} }}")

        assert row == {"id": 1, "author": {first_name: "f", last_name: "l"}}

    def test_a_nested_list_keeps_its_selected_fields(self, client) -> None:
        tag_name = self._name("tagName", "tag_name")
        [row] = self._rows(client, f"{{ title tags {{ {tag_name} }} }}")

        assert row == {"title": _TITLE, "tags": [{tag_name: "a"}, {tag_name: "b"}]}

    def test_a_whole_row_keeps_its_strings_as_stored(self, client) -> None:
        root = self._name("wholePosts", "whole_posts")
        body = client.post("/graphql", json={"query": f"{{ {root} {{ title }} }}"}).json()

        assert "errors" not in body, body
        assert [row["title"] for row in body["data"][root]] == [_TITLE]


def _without_typename(value):
    # __typename is checked on its own (test_typename_only_when_selected)
    if isinstance(value, dict):
        return {k: _without_typename(v) for k, v in value.items() if k != "__typename"}
    if isinstance(value, list):
        return [_without_typename(v) for v in value]
    return value


class TestWithoutRegistry(_ZeroCopyProjection):
    registry, camel, root = False, True, "posts"


class TestWithoutRegistrySnakeCase(_ZeroCopyProjection):
    registry, camel, root = False, False, "posts"


class TestUnregisteredView(_ZeroCopyProjection):
    registry, camel, root = True, True, "rawPosts"


class TestUnregisteredViewSnakeCase(_ZeroCopyProjection):
    registry, camel, root = True, False, "rawPosts"
