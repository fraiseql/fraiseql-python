"""A root query answers under its response key, whatever field_name db.find gets.

The single-field pass-through serves db.find's response as is, and its key was
the field_name argument: ``db.find("v_note", "post_notes", info)`` answered
``{"post_notes": ...}`` to a client asking for ``postNotes``, and an alias
(``x: postNotes``) came back under the field's name.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import create_fraiseql_app

pytestmark = [pytest.mark.integration, pytest.mark.database]


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def note_view(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(
            "CREATE VIEW v_key_note AS "
            "SELECT 1 AS id, jsonb_build_object('id', 1, 'note_title', 'a') AS data"
        )
        await conn.commit()
    yield


@pytest.mark.usefixtures("clear_registry_class")
class TestFindResponseKey:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, test_schema, note_view):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type(sql_source="v_key_note")
        class KeyNote:
            id: int
            note_title: str

        @fraiseql.query
        async def post_notes(info) -> list[KeyNote]:
            return await info.context["db"].find("v_key_note", "post_notes", info)

        @fraiseql.query
        async def other_notes(info) -> list[KeyNote]:
            return await info.context["db"].find("v_key_note", info=info)

        @fraiseql.query
        async def one_note(info) -> KeyNote | None:
            return await info.context["db"].find_one("v_key_note", "one_note", info)

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",  # the pool above is used
            types=[KeyNote],
            queries=[post_notes, other_notes, one_note],
            production=False,
        )
        return TestClient(app)

    @pytest.mark.parametrize(
        ("query", "key"),
        [
            ("{ postNotes { noteTitle } }", "postNotes"),
            ("{ x: postNotes { noteTitle } }", "x"),
            ("{ x: otherNotes { noteTitle } }", "x"),
            ("{ oneNote { noteTitle } }", "oneNote"),
            ("{ y: oneNote { noteTitle } }", "y"),
        ],
    )
    def test_response_key(self, client, query, key) -> None:
        body = client.post("/graphql", json={"query": query}).json()

        assert "errors" not in body, body
        assert list(body["data"]) == [key]
        value = body["data"][key]
        row = value[0] if isinstance(value, list) else value
        assert row["noteTitle"] == "a"
