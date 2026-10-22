"""A success without an entity: null for a nullable entity field, an error otherwise.

The success type's entity field typed ``Note | None`` wasn't recognised as the
entity field, so a null entity left the key out of the response; a non-null
``note: Note`` selected under an alias (``n: note``) came back null without an
error, and only the unaliased selection raised.
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
async def note_functions(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(
            """
            CREATE TYPE mutation_response AS (
                status text, message text, entity_id text, entity_type text,
                entity jsonb, updated_fields text[], cascade jsonb, metadata jsonb
            )
            """
        )
        await conn.execute(
            "CREATE VIEW v_null_note AS SELECT 1 AS id, jsonb_build_object('id', 1) AS data"
        )
        for name, entity in (
            ("make_note", "NULL"),
            ("maybe_note", "NULL"),
            ("found_note", "jsonb_build_object('id', 1)"),
        ):
            await conn.execute(
                f"""
                CREATE FUNCTION {name}(input jsonb) RETURNS mutation_response
                LANGUAGE sql AS $$
                    SELECT ROW('created', 'ok', NULL, NULL, {entity}, NULL, NULL, NULL)
                        ::mutation_response
                $$
                """
            )
        await conn.commit()
    yield


@pytest.mark.usefixtures("clear_registry_class")
class TestNullEntity:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, test_schema, note_functions):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type(sql_source="v_null_note")
        class NullNote:
            id: int

        @fraiseql.input
        class NoteInput:
            title: str

        @fraiseql.success
        class NoteMade:
            note: NullNote

        @fraiseql.success
        class NoteMaybe:
            note: NullNote | None

        @fraiseql.error
        class NoteError:
            pass

        @fraiseql.mutation(schema=test_schema)
        class MakeNote:
            input: NoteInput
            success: NoteMade
            error: NoteError

        @fraiseql.mutation(schema=test_schema)
        class MaybeNote:
            input: NoteInput
            success: NoteMaybe
            error: NoteError

        @fraiseql.mutation(schema=test_schema)
        class FoundNote:
            input: NoteInput
            success: NoteMaybe
            error: NoteError

        @fraiseql.query
        async def null_notes(info) -> list[NullNote]:
            return []

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",  # the pool above is used
            types=[NullNote],
            queries=[null_notes],
            mutations=[MakeNote, MaybeNote, FoundNote],
            production=False,
        )
        return TestClient(app)

    def _post(self, client, query: str) -> dict:
        return client.post("/graphql", json={"query": query}).json()

    @pytest.mark.parametrize("key", ["note", "n"])
    def test_nullable_entity_is_null(self, client, key) -> None:
        alias = "" if key == "note" else f"{key}: "
        body = self._post(
            client,
            f'mutation {{ maybeNote(input: {{title: "t"}}) {{ ... on NoteMaybe {{ {alias}note {{ id }} }} }} }}',
        )

        assert "errors" not in body, body
        assert body["data"]["maybeNote"] == {"__typename": "NoteMaybe", key: None}

    def test_nullable_entity_when_present(self, client) -> None:
        body = self._post(
            client,
            'mutation { foundNote(input: {title: "t"}) { ... on NoteMaybe { note { id } } } }',
        )

        assert body["data"]["foundNote"]["note"]["id"] == 1

    @pytest.mark.parametrize("selection", ["note { id }", "n: note { id }"])
    def test_non_null_entity_is_an_error(self, client, selection) -> None:
        body = self._post(
            client,
            f'mutation {{ makeNote(input: {{title: "t"}}) {{ ... on NoteMade {{ {selection} }} }} }}',
        )

        assert body["data"]["makeNote"] is None
        assert "null entity" in body["errors"][0]["message"]

    def test_unselected_non_null_entity_is_no_error(self, client) -> None:
        body = self._post(
            client, 'mutation { makeNote(input: {title: "t"}) { ... on NoteMade { message } } }'
        )

        assert "errors" not in body, body
        assert body["data"]["makeNote"]["message"] == "ok"
