"""A nested object's ``__typename`` is its own type's name, not its parent's.

From docs/examples/dict-based-nested-filtering.md: an ``Assignment`` with an
embedded ``device: Device``. The nested device came back as
``"__typename": "Assignment"``.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import create_fraiseql_app

pytestmark = [pytest.mark.integration, pytest.mark.database]

_VIEW = "v_typename_assignment"


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def assignments(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(
            f"""
            CREATE VIEW {_VIEW} AS
            SELECT v.id, jsonb_build_object(
                'id', v.id, 'status', v.status,
                'device', jsonb_build_object(
                    'id', v.device_id, 'name', v.device_name, 'is_active', true,
                    'location', 'datacenter-1'
                ),
                'devices', jsonb_build_array(jsonb_build_object(
                    'id', v.device_id, 'name', v.device_name, 'is_active', true,
                    'location', 'datacenter-1'
                ))
            ) AS data
            FROM (VALUES ('a1', 'active', 'd1', 'router-01'),
                         ('a2', 'pending', 'd2', 'switch-02')) AS v(id, status, device_id, device_name)
            """
        )
        await conn.commit()
    yield


@pytest.mark.usefixtures("clear_registry_class")
class TestNestedObjectTypename:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, assignments):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type
        class TypenameDevice:
            id: str
            name: str
            is_active: bool
            location: str

        @fraiseql.type(sql_source=_VIEW)
        class TypenameAssignment:
            id: str
            status: str
            device: TypenameDevice
            devices: list[TypenameDevice]

        @fraiseql.query
        async def assignments(info) -> list[TypenameAssignment]:
            return await info.context["db"].find(_VIEW, "assignments", info)

        @fraiseql.query
        async def assignment(info, id: str) -> TypenameAssignment | None:
            return await info.context["db"].find_one(
                _VIEW, "assignment", info, where={"id": {"eq": id}}
            )

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",  # the pool above is used
            types=[TypenameAssignment, TypenameDevice],
            production=False,
        )
        return TestClient(app)

    def _data(self, client: TestClient, query: str) -> dict:
        body = client.post("/graphql", json={"query": query}).json()
        assert "errors" not in body, body
        return body["data"]

    def test_nested_typename_selected(self, client) -> None:
        data = self._data(
            client,
            "{ assignments { __typename id device { __typename id name } "
            "devices { __typename id } } }",
        )
        for row in data["assignments"]:
            assert row["__typename"] == "TypenameAssignment"
            assert row["device"]["__typename"] == "TypenameDevice", row
            assert [d["__typename"] for d in row["devices"]] == ["TypenameDevice"], row

    def test_nested_typename_only_on_nested(self, client) -> None:
        data = self._data(client, "{ assignments { id device { __typename name } } }")
        assert [row["device"] for row in data["assignments"]] == [
            {"__typename": "TypenameDevice", "name": "router-01"},
            {"__typename": "TypenameDevice", "name": "switch-02"},
        ]

    def test_nested_without_typename(self, client) -> None:
        data = self._data(client, "{ assignments { id device { id name } } }")
        devices = [row["device"] for row in data["assignments"]]
        assert [(d["id"], d["name"]) for d in devices] == [("d1", "router-01"), ("d2", "switch-02")]
        assert all(d.get("__typename", "TypenameDevice") == "TypenameDevice" for d in devices)

    def test_find_one_nested_typename(self, client) -> None:
        data = self._data(
            client, '{ assignment(id: "a2") { __typename device { __typename id } } }'
        )
        assert data["assignment"] == {
            "__typename": "TypenameAssignment",
            "device": {"__typename": "TypenameDevice", "id": "d2"},
        }


# The page's "Complete Example": plain @fraiseql.type classes, register_type_for_view
# and repo.find, with no app built. Without an app the Rust schema registry is
# empty, and that path gave every nested object the row's type name. The
# registry is set once per process, so this runs in a fresh interpreter.
_DOCS_EXAMPLE = """
import asyncio, json, sys, uuid

from psycopg_pool import AsyncConnectionPool

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view


@fraiseql.type
class Device:
    id: str
    name: str
    is_active: bool
    location: str


@fraiseql.type
class Assignment:
    id: str
    status: str
    device: Device


register_type_for_view("assignments", Assignment, has_jsonb_data=True)


async def main():
    schema = f"typename_{uuid.uuid4().hex[:8]}"
    url = sys.argv[1]
    async with AsyncConnectionPool(url, open=False) as admin:
        async with admin.connection() as conn:
            await conn.execute(f"CREATE SCHEMA {schema}")
            await conn.execute(
                f"CREATE VIEW {schema}.assignments AS SELECT 'a1'::text AS id, "
                "jsonb_build_object('id', 'a1', 'status', 'active', 'device', "
                "jsonb_build_object('id', 'd1', 'name', 'production-router', "
                "'is_active', true, 'location', 'datacenter-1')) AS data"
            )
    try:
        pool = AsyncConnectionPool(
            url, open=False, kwargs={"options": f"-csearch_path={schema}"}
        )
        async with pool:
            repo = FraiseQLRepository(pool)
            where_dict = {
                "status": {"in": ["active", "pending"]},
                "device": {"is_active": {"eq": True}, "name": {"contains": "production"}},
            }
            print(json.dumps(json.loads(bytes(await repo.find("assignments", where=where_dict)))))
    finally:
        async with AsyncConnectionPool(url, open=False) as admin:
            async with admin.connection() as conn:
                await conn.execute(f"DROP SCHEMA {schema} CASCADE")


asyncio.run(main())
"""


def test_docs_example_without_an_app(postgres_url) -> None:
    import json
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", _DOCS_EXAMPLE, postgres_url],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    (row,) = json.loads(result.stdout.strip().splitlines()[-1])["data"]["assignments"]
    assert row["__typename"] == "Assignment"
    # The row's type isn't the device's; with no registry its type isn't known
    assert row["device"].get("__typename") != "Assignment", row
    assert row["device"]["name"] == "production-router"
