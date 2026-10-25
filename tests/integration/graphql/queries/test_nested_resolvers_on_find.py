"""Nested-array ``where`` and ``resolve_nested`` fields run on db.find results.

A list field declared with ``fraise_field(supports_where_filtering=True)`` and a
field whose type has ``resolve_nested=True`` are resolved by a resolver of their
own (``core.nested_field_resolver``). db.find answered with the rows Rust builds,
which never pass through those resolvers: over HTTP, ``devices(where: ...)``
returned every element, and a ``resolve_nested`` field not embedded in the row
was null. They count as field resolvers now, so find returns typed rows when a
query selects them.
"""

import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
import fraiseql.db as fraiseql_db
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.fields import fraise_field

pytestmark = [pytest.mark.integration, pytest.mark.database]

_NETWORK_VIEW = "v_nr_network"
_DEPARTMENT_VIEW = "v_nr_department"
_EMPLOYEE_VIEW = "v_nr_employee"
_N1 = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_D1 = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
_E1 = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
_E2 = uuid.UUID("00000000-0000-0000-0000-0000000000e2")


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def views(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(
            f"CREATE VIEW {_NETWORK_VIEW} AS SELECT '{_N1}'::uuid AS id, jsonb_build_object("
            f"'id', '{_N1}', 'name', 'lan', 'devices', jsonb_build_array("
            "jsonb_build_object('hostname', 'web-1', 'status', 'active', 'priority', 1), "
            "jsonb_build_object('hostname', 'web-2', 'status', 'maintenance', 'priority', 2), "
            "jsonb_build_object('hostname', 'db-1', 'status', 'active', 'priority', 3))) AS data"
        )
        await conn.execute(
            f"CREATE VIEW {_DEPARTMENT_VIEW} AS SELECT '{_D1}'::uuid AS id, "
            f"jsonb_build_object('id', '{_D1}', 'name', 'research') AS data"
        )
        # The employee rows hold the department's id, not the department
        await conn.execute(
            f"CREATE VIEW {_EMPLOYEE_VIEW} AS SELECT v.id, jsonb_build_object("
            "'id', v.id, 'name', v.name, 'department_id', v.department_id) AS data FROM (VALUES "
            f"('{_E1}'::uuid, 'ann', '{_D1}'::uuid), ('{_E2}'::uuid, 'bob', NULL::uuid)) "
            "AS v(id, name, department_id)"
        )
        await conn.commit()
    yield


def _build_app(class_db_pool) -> TestClient:
    from fraiseql.fastapi.dependencies import set_db_pool

    @fraiseql.type
    class NrDevice:
        hostname: str
        status: str
        priority: int

    @fraiseql.type(sql_source=_NETWORK_VIEW)
    class NrNetwork:
        id: uuid.UUID
        name: str
        devices: list[NrDevice] = fraise_field(
            default_factory=list, supports_where_filtering=True, nested_where_type=NrDevice
        )

    @fraiseql.type(sql_source=_DEPARTMENT_VIEW, resolve_nested=True)
    class NrDepartment:
        id: uuid.UUID
        name: str

    @fraiseql.type(sql_source=_EMPLOYEE_VIEW)
    class NrEmployee:
        id: uuid.UUID
        name: str
        department_id: uuid.UUID | None
        department: NrDepartment | None

    @fraiseql.query
    async def nr_networks(info) -> list[NrNetwork]:
        return await info.context["db"].find(_NETWORK_VIEW, "nrNetworks", info)

    @fraiseql.query
    async def nr_network(info, id: uuid.UUID) -> NrNetwork | None:
        return await info.context["db"].find_one(
            _NETWORK_VIEW, "nrNetwork", info, where={"id": {"eq": id}}
        )

    @fraiseql.query
    async def nr_employees(info) -> list[NrEmployee]:
        return await info.context["db"].find(_EMPLOYEE_VIEW, "nrEmployees", info)

    set_db_pool(class_db_pool)
    config = FraiseQLConfig(database_url="postgresql://test/test")
    app = create_fraiseql_app(
        config=config, types=[NrNetwork, NrDevice, NrDepartment, NrEmployee], production=False
    )
    return TestClient(app)


def _data(client: TestClient, query: str, variables: dict | None = None) -> dict:
    body = client.post("/graphql", json={"query": query, "variables": variables or {}}).json()
    assert "errors" not in body, body
    return body["data"]


@pytest.mark.usefixtures("clear_registry_class")
class TestNestedResolversOnFind:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, views):
        return _build_app(class_db_pool)

    def test_nested_array_where_filters_the_elements(self, client) -> None:
        query = '{ nrNetworks { name devices(where: {status: {eq: "active"}}) { hostname } } }'
        networks = _data(client, query)["nrNetworks"]

        assert networks == [
            {"name": "lan", "devices": [{"hostname": "web-1"}, {"hostname": "db-1"}]}
        ]

    def test_nested_array_where_with_a_variable_and_or(self, client) -> None:
        query = "query($w: NrDeviceWhereInput) { nrNetworks { devices(where: $w) { hostname } } }"
        where = {"OR": [{"priority": {"gte": 3}}, {"status": {"eq": "maintenance"}}]}
        networks = _data(client, query, {"w": where})["nrNetworks"]

        assert networks == [{"devices": [{"hostname": "web-2"}, {"hostname": "db-1"}]}]

    def test_nested_array_where_on_find_one(self, client) -> None:
        query = (
            f'{{ nrNetwork(id: "{_N1}") {{ devices(where: {{priority: {{lt: 2}}}}) '
            "{ hostname priority } } }"
        )
        data = _data(client, query)

        assert data == {"nrNetwork": {"devices": [{"hostname": "web-1", "priority": 1}]}}

    def test_nested_array_without_where_goes_out_as_rust_bytes(self, client, monkeypatch) -> None:
        calls: list[str] = []
        real = fraiseql_db.execute_via_rust_pipeline

        async def spy(*args, **kwargs):
            calls.append(args[3])
            return await real(*args, **kwargs)

        monkeypatch.setattr(fraiseql_db, "execute_via_rust_pipeline", spy)

        networks = _data(client, "{ nrNetworks { devices { hostname } } }")["nrNetworks"]
        assert networks == [
            {"devices": [{"hostname": "web-1"}, {"hostname": "web-2"}, {"hostname": "db-1"}]}
        ]
        assert calls == ["nrNetworks"]

        calls.clear()
        _data(client, "{ nrNetworks { devices(where: {priority: {eq: 1}}) { hostname } } }")
        assert calls == []
