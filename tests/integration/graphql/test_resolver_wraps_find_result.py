"""A resolver can wrap what db.find / db.find_one return in another object.

In HTTP mode both return RustResponseBytes, a complete ``{"data": {...}}``
response that only works as a root field's whole result. Wrapped in a success
type (a function mutation reading its row back) or a page object, graphql-core
couldn't complete it, and the router served the captured bytes as the whole
response: ``{"data": {"v_note": ...}}`` instead of the operation's fields.
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
async def note_schema(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(
            "CREATE TABLE tb_note (id SERIAL PRIMARY KEY, title TEXT, created_at TIMESTAMPTZ "
            "DEFAULT now())"
        )
        await conn.execute(
            "CREATE VIEW v_note AS SELECT id, jsonb_build_object('id', id, 'title', title, "
            "'created_at', created_at) AS data FROM tb_note"
        )
        await conn.execute("INSERT INTO tb_note (title) VALUES ('first'), ('second')")
        await conn.execute(
            """
            CREATE FUNCTION fn_create_note(input jsonb, OUT success boolean, OUT id int)
            LANGUAGE sql AS $$
                INSERT INTO tb_note (title) VALUES (input->>'title') RETURNING true, id
            $$
            """
        )
        await conn.commit()
    yield


@pytest.mark.usefixtures("clear_registry_class")
class TestResolverWrapsFindResult:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, test_schema, note_schema):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type(sql_source="v_note")
        class Note:
            id: int
            title: str
            created_at: str

        @fraiseql.type
        class NotePage:
            notes: list[Note]
            first: Note | None
            total: int

        @fraiseql.input
        class CreateNoteInput:
            title: str

        @fraiseql.success
        class CreateNoteSuccess:
            note: Note

        @fraiseql.error
        class CreateNoteError:
            pass

        @fraiseql.mutation
        async def create_note(info, input: CreateNoteInput) -> CreateNoteSuccess | CreateNoteError:
            db = info.context["db"]
            result = await db.execute_function(
                f"{test_schema}.fn_create_note", {"title": input.title}
            )
            note = await db.find_one("v_note", mandatory_filters={"id": result["id"]})
            return CreateNoteSuccess(note=note)

        @fraiseql.query
        async def note_page(info) -> NotePage:
            db = info.context["db"]
            notes = await db.find("v_note", order_by={"id": "ASC"})
            first = await db.find_one("v_note", mandatory_filters={"id": 1})
            return NotePage(notes=notes, first=first, total=2)

        @fraiseql.query
        async def notes(info) -> list[Note]:
            return await info.context["db"].find("v_note", info=info, order_by={"id": "ASC"})

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",  # the pool above is used
            types=[Note, NotePage],
            queries=[note_page, notes],
            mutations=[create_note],
            production=False,
        )
        return TestClient(app)

    def _post(self, client, query: str) -> dict:
        body = client.post("/graphql", json={"query": query}).json()
        assert "errors" not in body, body
        return body["data"]

    def test_query_wrapping_find_results(self, client) -> None:
        data = self._post(
            client, "{ notePage { total notes { id title } first { title createdAt } } }"
        )

        page = data["notePage"]
        assert page["total"] == 2
        assert [(n["id"], n["title"]) for n in page["notes"]][:2] == [(1, "first"), (2, "second")]
        assert page["first"]["title"] == "first"
        assert page["first"]["createdAt"]

    def test_mutation_reading_its_row_back(self, client) -> None:
        data = self._post(
            client,
            'mutation { createNote(input: {title: "third"}) { '
            "__typename ... on CreateNoteSuccess { note { id title } } } }",
        )

        assert data["createNote"]["__typename"] == "CreateNoteSuccess"
        assert data["createNote"]["note"]["title"] == "third"

    def test_a_root_find_still_passes_through(self, client) -> None:
        data = self._post(client, "{ notes { title } }")

        assert [n["title"] for n in data["notes"]][:2] == ["first", "second"]
