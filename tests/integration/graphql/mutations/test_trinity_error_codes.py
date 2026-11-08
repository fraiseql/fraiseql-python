"""Errors built with the trinity helpers get their 4xx code.

migrations/trinity/005_add_mutation_response.sql's mutation_validation_error,
mutation_not_found and mutation_conflict return failed:validation,
failed:not_found and failed:duplicate. The error type's code came out 500 for
all three: only the validation:/not_found:/conflict: prefixes had their codes.
"""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import create_fraiseql_app

pytestmark = [pytest.mark.integration, pytest.mark.database]

_HELPERS = Path(__file__).resolve().parents[4] / "migrations/trinity/005_add_mutation_response.sql"

_SELECTION = (
    "{ __typename ... on SaveLabelSuccess { label { name } } "
    "... on SaveLabelError { status code } }"
)


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def label_schema(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(_HELPERS.read_text())
        await conn.execute("CREATE TABLE tb_label (id SERIAL PRIMARY KEY, name TEXT UNIQUE)")
        await conn.execute(
            "CREATE VIEW v_label AS "
            "SELECT id, jsonb_build_object('id', id, 'name', name) AS data FROM tb_label"
        )
        await conn.execute(
            """
            CREATE FUNCTION save_label(input jsonb) RETURNS mutation_response
            LANGUAGE plpgsql AS $$
            DECLARE v_id int;
            BEGIN
                IF input->>'name' = 'invalid' THEN
                    RETURN mutation_validation_error('name is required', 'name');
                END IF;
                IF input->>'name' = 'missing' THEN
                    RETURN mutation_not_found('Label', 'missing');
                END IF;
                IF EXISTS (SELECT 1 FROM tb_label WHERE name = input->>'name') THEN
                    RETURN mutation_conflict('name already used');
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
class TestTrinityErrorCodes:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, test_schema, label_schema):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type(sql_source="v_label")
        class Label:
            id: int
            name: str

        @fraiseql.input
        class SaveLabelInput:
            name: str

        @fraiseql.success
        class SaveLabelSuccess:
            label: Label

        @fraiseql.error
        class SaveLabelError:
            pass

        @fraiseql.mutation(schema=test_schema)
        class SaveLabel:
            input: SaveLabelInput
            success: SaveLabelSuccess
            error: SaveLabelError

        @fraiseql.query
        async def labels(info) -> list[Label]:
            return await info.context["db"].find("v_label", "labels", info)

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",  # the pool above is used
            types=[Label],
            queries=[labels],
            mutations=[SaveLabel],
            production=False,
        )
        return TestClient(app)

    def _save(self, client, name: str) -> dict:
        body = client.post(
            "/graphql",
            json={"query": f'mutation {{ saveLabel(input: {{name: "{name}"}}) {_SELECTION} }}'},
        ).json()
        assert "errors" not in body, body
        return body["data"]["saveLabel"]

    @pytest.mark.parametrize(
        ("name", "status", "code"),
        [
            ("invalid", "failed:validation", 422),
            ("missing", "failed:not_found", 404),
        ],
    )
    def test_error_code(self, client, name, status, code) -> None:
        assert self._save(client, name) == {
            "__typename": "SaveLabelError",
            "status": status,
            "code": code,
        }

    def test_conflict(self, client) -> None:
        assert self._save(client, "taken")["__typename"] == "SaveLabelSuccess"

        assert self._save(client, "taken") == {
            "__typename": "SaveLabelError",
            "status": "failed:duplicate",
            "code": 409,
        }
