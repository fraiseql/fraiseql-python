"""A nested-array ``where`` filters the elements when graphql-core runs the query.

graphql-core passes the ``where`` argument to the resolver as a dict keyed by the
GraphQL names. The nested-array resolver only read where objects (``__dict__``,
``_to_sql_where``), so a dict matched every element: the field returned them all.
An operator the Python filter doesn't know matched every element too.
"""

import uuid
from enum import Enum

import pytest
from graphql import graphql

import fraiseql
from fraiseql import build_fraiseql_schema
from fraiseql.fields import fraise_field

pytestmark = pytest.mark.unit


@pytest.fixture
def schema(clear_registry):
    @fraiseql.enum
    class NwStatus(Enum):
        ACTIVE = "active"
        OFFLINE = "offline"

    @fraiseql.type
    class NwLocation:
        city: str

    @fraiseql.type
    class NwDevice:
        hostname: str
        status: NwStatus
        priority: int
        ip_address: str | None
        location: NwLocation | None

    @fraiseql.type(sql_source="v_nw_network")
    class NwNetwork:
        id: uuid.UUID
        devices: list[NwDevice] = fraise_field(
            default_factory=list, supports_where_filtering=True, nested_where_type=NwDevice
        )

    row = {
        "id": str(uuid.uuid4()),
        "devices": [
            {
                "hostname": "web-1",
                "status": "active",
                "priority": 1,
                "ip_address": "10.0.0.1",
                "location": {"city": "Paris"},
            },
            {
                "hostname": "web-2",
                "status": "offline",
                "priority": 2,
                "ip_address": None,
                "location": {"city": "Lyon"},
            },
            {
                "hostname": "db-1",
                "status": "active",
                "priority": 3,
                "ip_address": "10.0.0.3",
                "location": None,
            },
        ],
    }

    @fraiseql.query
    async def nw_networks(info) -> list[NwNetwork]:
        return [NwNetwork.from_dict(row)]

    return build_fraiseql_schema(query_types=[nw_networks])


async def _hostnames(schema, where: str) -> list[str]:
    result = await graphql(schema, f"{{ nwNetworks {{ devices(where: {where}) {{ hostname }} }} }}")
    assert result.errors is None, result.errors
    return [d["hostname"] for d in result.data["nwNetworks"][0]["devices"]]


@pytest.mark.parametrize(
    ("where", "expected"),
    [
        ('{hostname: {eq: "web-2"}}', ["web-2"]),
        ('{status: {eq: "active"}}', ["web-1", "db-1"]),
        ('{status: {neq: "active"}}', ["web-2"]),
        ("{priority: {gte: 2}}", ["web-2", "db-1"]),
        ('{hostname: {in: ["web-1", "db-1"]}}', ["web-1", "db-1"]),
        ('{hostname: {startswith: "web"}}', ["web-1", "web-2"]),
        ('{hostname: {contains: "-1"}}', ["web-1", "db-1"]),
        ("{ipAddress: {isnull: true}}", ["web-2"]),
        ('{status: {eq: "active"}, hostname: {startswith: "db"}}', ["db-1"]),
        ('{OR: [{priority: {eq: 1}}, {hostname: {eq: "db-1"}}]}', ["web-1", "db-1"]),
        ('{AND: [{status: {eq: "active"}}, {priority: {lt: 3}}]}', ["web-1"]),
        ("{}", ["web-1", "web-2", "db-1"]),
    ],
)
async def test_where_filters_the_elements(schema, where: str, expected: list[str]) -> None:
    assert await _hostnames(schema, where) == expected


async def test_where_from_a_variable(schema) -> None:
    query = "query($w: NwDeviceWhereInput) { nwNetworks { devices(where: $w) { hostname } } }"
    where = {
        "OR": [{"priority": {"gte": 3}}, {"ipAddress": {"isnull": True}}],
        "NOT": {"hostname": {"eq": "db-1"}},
    }
    result = await graphql(schema, query, variable_values={"w": where})

    assert result.errors is None, result.errors
    assert result.data["nwNetworks"][0]["devices"] == [{"hostname": "web-2"}]


async def test_an_operator_the_python_filter_lacks_is_an_error(schema) -> None:
    result = await graphql(
        schema, '{ nwNetworks { devices(where: {hostname: {ilike: "WEB%"}}) { hostname } } }'
    )

    assert result.errors
    assert "'ilike' is not supported in a nested array where" in result.errors[0].message
