"""db.find answers a nested field under its alias.

A root field's alias was honoured, a nested one was not: ``{ notes { x: authorInfo
{ firstName } } }`` came back as ``{"authorInfo": {...}}``. The selection handed to
Rust named a nested object by its field name, whatever the alias, and kept one
entry per JSON path, so two aliases of one field couldn't both be answered.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

pytestmark = [pytest.mark.integration, pytest.mark.database]

_VIEW = "v_alias_note"


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def alias_notes(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(
            f"CREATE VIEW {_VIEW} AS SELECT 1 AS id, jsonb_build_object("
            "'id', 1, 'title', 't', "
            "'author_info', jsonb_build_object('first_name', 'f', 'last_name', 'l'), "
            "'tags', jsonb_build_array(jsonb_build_object('tag_name', 'a', 'weight', 1), "
            "jsonb_build_object('tag_name', 'b', 'weight', 2))) AS data"
        )
        await conn.commit()
    yield


@pytest.mark.usefixtures("clear_registry_class")
class _NestedAliases:
    camel: bool
    registry: bool

    @pytest.fixture(scope="class")
    def client(self, class_db_pool, alias_notes):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type
        class AliasAuthor:
            first_name: str
            last_name: str

        @fraiseql.type
        class AliasTag:
            tag_name: str
            weight: int

        @fraiseql.type(sql_source=_VIEW)
        class AliasNote:
            id: int
            title: str
            author_info: AliasAuthor
            tags: list[AliasTag]

        @fraiseql.query
        async def notes(info) -> list[AliasNote]:
            return await info.context["db"].find(_VIEW, info=info)

        @fraiseql.query
        async def note(info) -> AliasNote | None:
            return await info.context["db"].find_one(_VIEW, info=info, mandatory_filters={"id": 1})

        @fraiseql.type
        class AliasPage:
            title: str

            @fraiseql.field
            async def page_notes(self, info) -> list[AliasNote]:
                # Below the root: graphql-core completes what find returns
                return await info.context["db"].find(_VIEW, info=info)

        @fraiseql.query
        async def page(info) -> AliasPage:
            return AliasPage(title="p")

        set_db_pool(class_db_pool)
        config = FraiseQLConfig(database_url="postgresql://test/test", auto_camel_case=self.camel)
        app = create_fraiseql_app(
            config=config,
            types=[AliasNote, AliasAuthor, AliasTag, AliasPage],
            queries=[notes, note, page],
            production=False,
            enable_schema_registry=self.registry,
        )
        return TestClient(app)

    def _data(self, client: TestClient, query: str) -> dict:
        if not self.camel:
            for camel, snake in (
                ("authorInfo", "author_info"),
                ("firstName", "first_name"),
                ("lastName", "last_name"),
                ("tagName", "tag_name"),
                ("pageNotes", "page_notes"),
            ):
                query = query.replace(camel, snake)
        body = client.post("/graphql", json={"query": query}).json()
        assert "errors" not in body, body
        return _without_typename(body["data"])

    def _key(self, camel: str) -> str:
        return camel if self.camel else {"authorInfo": "author_info"}.get(camel, camel)

    def test_nested_object(self, client) -> None:
        data = self._data(client, "{ notes { x: authorInfo { n: firstName } } }")

        assert data == {"notes": [{"x": {"n": "f"}}]}

    def test_nested_list(self, client) -> None:
        data = self._data(client, "{ notes { id labels: tags { t: tagName weight } } }")

        assert data == {
            "notes": [{"id": 1, "labels": [{"t": "a", "weight": 1}, {"t": "b", "weight": 2}]}]
        }

    def test_find_one(self, client) -> None:
        data = self._data(client, "{ note { x: authorInfo { lastName } } }")

        assert data == {"note": {"x": {self._name("lastName"): "l"}}}

    def test_two_aliases_of_one_field(self, client) -> None:
        data = self._data(
            client, "{ notes { a: authorInfo { firstName } b: authorInfo { lastName } } }"
        )

        assert data == {
            "notes": [{"a": {self._name("firstName"): "f"}, "b": {self._name("lastName"): "l"}}]
        }

    def test_an_aliased_and_an_unaliased_field(self, client) -> None:
        data = self._data(
            client, "{ notes { authorInfo { firstName } x: authorInfo { lastName } } }"
        )

        assert data == {
            "notes": [
                {
                    self._key("authorInfo"): {self._name("firstName"): "f"},
                    "x": {self._name("lastName"): "l"},
                }
            ]
        }

    def test_several_root_fields(self, client) -> None:
        data = self._data(
            client,
            "{ notes { x: authorInfo { n: firstName } } one: note { t: tags { tagName } } }",
        )

        assert data == {
            "notes": [{"x": {"n": "f"}}],
            "one": {"t": [{self._name("tagName"): "a"}, {self._name("tagName"): "b"}]},
        }

    def test_find_below_the_root(self, client) -> None:
        data = self._data(
            client,
            "{ page { title ns: pageNotes { x: authorInfo { n: firstName } labels: tags "
            "{ tagName } } } }",
        )

        assert data == {
            "page": {
                "title": "p",
                "ns": [
                    {
                        "x": {"n": "f"},
                        "labels": [{self._name("tagName"): "a"}, {self._name("tagName"): "b"}],
                    }
                ],
            }
        }

    def _name(self, camel: str) -> str:
        if self.camel:
            return camel
        return "".join(f"_{c.lower()}" if c.isupper() else c for c in camel)


def _without_typename(value):
    if isinstance(value, dict):
        return {k: _without_typename(v) for k, v in value.items() if k != "__typename"}
    if isinstance(value, list):
        return [_without_typename(v) for v in value]
    return value


class TestNestedAliases(_NestedAliases):
    camel, registry = True, True


class TestNestedAliasesSnakeCase(_NestedAliases):
    camel, registry = False, True


class TestNestedAliasesWithoutRegistry(_NestedAliases):
    camel, registry = True, False


class TestNestedAliasesWithoutRegistrySnakeCase(_NestedAliases):
    camel, registry = False, False
