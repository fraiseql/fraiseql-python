"""An operation with several mutation fields answers each of them.

In HTTP mode a class mutation's resolver returns the response Rust built
(RustResponseBytes), and execute_graphql passed the one it captured through as
the whole HTTP body. With two mutation fields both ran, but the middleware kept
only the last capture: the client got one result, under the field's name
rather than its alias, and no sign that the other had run.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import create_fraiseql_app

pytestmark = [pytest.mark.integration, pytest.mark.database]

_SELECTION = (
    "{ __typename ... on CreateLabelSuccess { label { name } } ... on CreateLabelError { status } }"
)


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def label_schema(class_db_pool, test_schema):
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
        await conn.execute("CREATE TABLE tb_label (id SERIAL PRIMARY KEY, name TEXT UNIQUE)")
        await conn.execute(
            "CREATE VIEW v_label AS "
            "SELECT id, jsonb_build_object('id', id, 'name', name) AS data FROM tb_label"
        )
        await conn.execute(
            """
            CREATE FUNCTION create_label(input jsonb) RETURNS mutation_response
            LANGUAGE plpgsql AS $$
            DECLARE v_id int;
            BEGIN
                IF EXISTS (SELECT 1 FROM tb_label WHERE name = input->>'name') THEN
                    RETURN ROW('conflict:name', 'exists', NULL, NULL, NULL, NULL, NULL, NULL)
                        ::mutation_response;
                END IF;
                INSERT INTO tb_label (name) VALUES (input->>'name') RETURNING id INTO v_id;
                RETURN ROW('created', 'ok', v_id::text, 'Label',
                    (SELECT data FROM v_label WHERE id = v_id), NULL, NULL, NULL)
                    ::mutation_response;
            END $$
            """
        )
        await conn.commit()
    yield


@pytest.mark.usefixtures("clear_registry_class")
class TestSeveralMutationsInOneOperation:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, test_schema, label_schema):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type(sql_source="v_label")
        class Label:
            id: int
            name: str

        @fraiseql.input
        class CreateLabelInput:
            name: str

        @fraiseql.success
        class CreateLabelSuccess:
            label: Label

        @fraiseql.error
        class CreateLabelError:
            pass

        @fraiseql.mutation(schema=test_schema)
        class CreateLabel:
            input: CreateLabelInput
            success: CreateLabelSuccess
            error: CreateLabelError

        @fraiseql.query
        async def labels(info) -> list[Label]:
            return await info.context["db"].find("v_label", "labels", info)

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",  # the pool above is used
            types=[Label],
            queries=[labels],
            mutations=[CreateLabel],
            production=False,
        )
        return TestClient(app)

    def _post(self, client, query: str) -> dict:
        body = client.post("/graphql", json={"query": query}).json()
        assert "errors" not in body, body
        return body["data"]

    def test_two_aliased_mutations_both_answer(self, client) -> None:
        data = self._post(
            client,
            f'mutation {{ a: createLabel(input: {{name: "one"}}) {_SELECTION} '
            f'b: createLabel(input: {{name: "two"}}) {_SELECTION} }}',
        )

        assert list(data) == ["a", "b"]
        assert data["a"]["label"]["name"] == "one"
        assert data["b"]["label"]["name"] == "two"

    def test_success_and_error_in_one_operation(self, client) -> None:
        data = self._post(
            client,
            f'mutation {{ createLabel(input: {{name: "three"}}) {_SELECTION} '
            f'again: createLabel(input: {{name: "three"}}) {_SELECTION} }}',
        )

        assert data["createLabel"]["__typename"] == "CreateLabelSuccess"
        assert data["again"]["__typename"] == "CreateLabelError"
        assert data["again"]["status"] == "conflict:name"

    def test_one_mutation_is_unchanged(self, client) -> None:
        data = self._post(
            client, f'mutation {{ createLabel(input: {{name: "four"}}) {_SELECTION} }}'
        )

        # __typename is selected on the result, not on the label
        assert data == {
            "createLabel": {"__typename": "CreateLabelSuccess", "label": {"name": "four"}}
        }

    def test_a_failing_field_keeps_its_error_next_to_a_success(self, client) -> None:
        body = client.post(
            "/graphql",
            json={
                "query": f'mutation {{ ok: createLabel(input: {{name: "five"}}) {_SELECTION} '
                f'bad: createLabel(input: {{name: ""}}) {_SELECTION} }}'
            },
        ).json()

        assert body["data"]["ok"]["label"]["name"] == "five"
        assert body["data"]["bad"] is None
        assert [error["path"] for error in body["errors"]] == [["bad"]]

    def test_every_mutation_ran(self, client) -> None:
        self._post(
            client,
            f'mutation {{ x: createLabel(input: {{name: "six"}}) {_SELECTION} '
            f'y: createLabel(input: {{name: "seven"}}) {_SELECTION} }}',
        )
        names = {label["name"] for label in self._post(client, "{ labels { name } }")["labels"]}

        assert {"six", "seven"} <= names
