"""db.find answers __typename where the query selects it, and nowhere else.

The response holds exactly the selected fields (GraphQL spec, "Executing Selection
Sets"). Rust gave every object of a known type a ``__typename``, selected or not.
Clients that need it (Apollo, urql, Relay) add it to their queries themselves.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import create_fraiseql_app

pytestmark = [pytest.mark.integration, pytest.mark.database]

_VIEW = "v_typename_note"


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def typename_notes(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(
            f"CREATE VIEW {_VIEW} AS SELECT 1 AS id, jsonb_build_object("
            "'id', 1, '__typename', 'Stale', "
            "'author_info', jsonb_build_object('first_name', 'f'), "
            "'tags', jsonb_build_array(jsonb_build_object('tag_name', 'a'))) AS data"
        )
        await conn.commit()
    yield


@pytest.mark.usefixtures("clear_registry_class")
class _Typename:
    registry: bool

    @pytest.fixture(scope="class")
    def client(self, class_db_pool, typename_notes):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type
        class TnAuthor:
            first_name: str

        @fraiseql.type
        class TnTag:
            tag_name: str

        @fraiseql.type(sql_source=_VIEW)
        class TnNote:
            id: int
            author_info: TnAuthor
            tags: list[TnTag]

        @fraiseql.query
        async def notes(info) -> list[TnNote]:
            return await info.context["db"].find(_VIEW, info=info)

        @fraiseql.query
        async def note(info) -> TnNote | None:
            return await info.context["db"].find_one(_VIEW, info=info, mandatory_filters={"id": 1})

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",
            types=[TnNote, TnAuthor, TnTag],
            queries=[notes, note],
            production=False,
            enable_schema_registry=self.registry,
        )
        return TestClient(app)

    def _data(self, client: TestClient, query: str) -> dict:
        body = client.post("/graphql", json={"query": query}).json()
        assert "errors" not in body, body
        return body["data"]

    def test_not_selected_not_written(self, client) -> None:
        data = self._data(client, "{ notes { id authorInfo { firstName } tags { tagName } } }")

        assert data == {
            "notes": [{"id": 1, "authorInfo": {"firstName": "f"}, "tags": [{"tagName": "a"}]}]
        }

    def test_selected_at_every_level(self, client) -> None:
        data = self._data(
            client,
            "{ notes { __typename authorInfo { __typename firstName } "
            "tags { __typename tagName } } }",
        )

        assert data == {
            "notes": [
                {
                    "__typename": "TnNote",
                    "authorInfo": {"__typename": "TnAuthor", "firstName": "f"},
                    "tags": [{"__typename": "TnTag", "tagName": "a"}],
                }
            ]
        }

    def test_selected_under_an_alias(self, client) -> None:
        data = self._data(client, "{ note { t: __typename x: authorInfo { k: __typename } } }")

        assert data == {"note": {"t": "TnNote", "x": {"k": "TnAuthor"}}}

    def test_several_root_fields(self, client) -> None:
        data = self._data(
            client, "{ notes { id authorInfo { __typename } } one: note { __typename id } }"
        )

        assert data == {
            "notes": [{"id": 1, "authorInfo": {"__typename": "TnAuthor"}}],
            "one": {"__typename": "TnNote", "id": 1},
        }


class TestTypename(_Typename):
    registry = True


class TestTypenameWithoutRegistry(_Typename):
    registry = False
