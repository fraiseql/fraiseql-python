"""With auto_camel_case=False, a nested object answers under the key the client asked for.

The selection handed to Rust names each nested object by its response key. That
key was always ``to_camel_case(field)``, so ``{ notes { author_info { first_name } } }``
came back as ``{"authorInfo": {...}}``: a key the client never requested, and
``author_info`` missing. A leaf already used the name from the query.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

pytestmark = [pytest.mark.integration, pytest.mark.database]

_VIEW = "v_snake_case_note"


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def snake_case_notes(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(
            f"CREATE VIEW {_VIEW} AS SELECT 1 AS id, jsonb_build_object("
            "'id', 1, 'created_at', '2024', "
            "'author_info', jsonb_build_object('first_name', 'f', 'last_name', 'l')) AS data"
        )
        await conn.commit()
    yield


@pytest.mark.usefixtures("clear_registry_class")
class TestAutoCamelCaseOff:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, snake_case_notes):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type
        class NoteAuthor:
            first_name: str
            last_name: str

        @fraiseql.type(sql_source=_VIEW)
        class SnakeCaseNote:
            id: int
            created_at: str
            author_info: NoteAuthor

        @fraiseql.query
        async def notes(info) -> list[SnakeCaseNote]:
            return await info.context["db"].find(_VIEW, "notes", info)

        set_db_pool(class_db_pool)
        config = FraiseQLConfig(database_url="postgresql://test/test", auto_camel_case=False)
        app = create_fraiseql_app(
            config=config, types=[SnakeCaseNote, NoteAuthor], queries=[notes], production=False
        )
        return TestClient(app)

    def _notes(self, client: TestClient, query: str) -> list[dict]:
        body = client.post("/graphql", json={"query": query}).json()
        assert "errors" not in body, body
        return body["data"]["notes"]

    def test_nested_object_keeps_its_snake_case_key(self, client) -> None:
        [note] = self._notes(client, "{ notes { author_info { first_name } } }")

        assert note["author_info"] == {"first_name": "f"}
        assert "authorInfo" not in note

    def test_leaf_keys_are_the_requested_ones(self, client) -> None:
        [note] = self._notes(client, "{ notes { id created_at author_info { last_name } } }")

        assert set(note) == {"id", "created_at", "author_info"}
        assert set(note["author_info"]) == {"last_name"}
