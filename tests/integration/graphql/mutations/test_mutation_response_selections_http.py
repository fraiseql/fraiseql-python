"""Mutation responses over HTTP hold what the query selected, under its keys (#581, #573).

In HTTP mode the Rust-built mutation response is sent to the client as is, so it
must apply aliases (the root field's too), filter lists, return only __typename when
the success type has no selection, and pick fragments under interface and union
fields by the object's __typename. Outside HTTP mode graphql-core completes the
result itself; the same queries must give the same data there.
"""

import json
from typing import Annotated

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from graphql import graphql

import fraiseql
from fraiseql.db import FraiseQLRepository
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.mutations.decorators import FraiseUnion

pytestmark = pytest.mark.integration

_ENTITY = {
    "id": "l1",
    "name": "HQ",
    "secret": "x",
    "owner": {"__typename": "Person", "id": "p1", "name": "Ada", "email": "a@x", "title": "Dr"},
    "owner_u": {"__typename": "Org", "id": "o1", "title": "ACME", "name": "acme-internal"},
    "tags": [
        {"id": "t1", "label": "a", "secret": "s1"},
        {"id": "t2", "label": "b", "secret": "s2"},
    ],
}


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def update_location_function(class_db_pool, test_schema) -> None:
    async with class_db_pool.connection() as conn:
        await conn.execute(
            f"""
            CREATE TYPE {test_schema}.mutation_response AS (
                status text, message text, entity_id text, entity_type text,
                entity jsonb, updated_fields text[], cascade jsonb, metadata jsonb
            );
            CREATE FUNCTION {test_schema}.update_location(input jsonb)
            RETURNS {test_schema}.mutation_response LANGUAGE sql AS $$
                SELECT ROW(
                    CASE WHEN input->>'id' = 'missing' THEN 'not_found:location'
                         ELSE 'updated' END,
                    'ok', 'l1', 'Location',
                    CASE WHEN input->>'id' = 'missing' THEN NULL
                         ELSE '{json.dumps(_ENTITY)}'::jsonb END,
                    NULL, NULL, NULL
                )::{test_schema}.mutation_response
            $$;
            """
        )
        await conn.commit()


@pytest.fixture
def mutation(test_schema, clear_registry):
    @fraiseql.interface
    class Node:
        id: str

    @fraiseql.type(implements=[Node])
    class Person:
        id: str
        name: str
        email: str | None = None

    @fraiseql.type(implements=[Node])
    class Org:
        id: str
        title: str

    @fraiseql.type
    class Tag:
        id: str
        label: str | None = None

    @fraiseql.type
    class Location:
        id: str
        name: str | None
        owner: Node | None
        owner_u: Annotated[Person | Org, FraiseUnion("Owner")] | None
        tags: list[Tag] | None

    @fraiseql.input
    class UpdateLocationInput:
        id: str

    @fraiseql.success
    class UpdateLocationSuccess:
        message: str | None
        location: Location

    @fraiseql.error
    class UpdateLocationError:
        message: str | None

    @fraiseql.mutation(schema=test_schema)
    class UpdateLocation:
        input: UpdateLocationInput
        success: UpdateLocationSuccess
        error: UpdateLocationError

    @fraiseql.mutation(schema=test_schema, function="update_location", name="relocate")
    class MoveLocation:
        input: UpdateLocationInput
        success: UpdateLocationSuccess
        error: UpdateLocationError

    @fraiseql.query
    async def ping(info) -> int:
        return 1

    return {
        "types": [Person, Org, Tag, Location],
        "mutations": [UpdateLocation, MoveLocation],
        "queries": [ping],
    }


@pytest.fixture
def client(class_db_pool, update_location_function, mutation) -> TestClient:
    from fraiseql.fastapi.dependencies import set_db_pool

    set_db_pool(class_db_pool)

    async def context_getter(request, user=None):
        return {"db": FraiseQLRepository(class_db_pool), "user": user}

    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        production=False,
        context_getter=context_getter,
        **mutation,
    )
    return TestClient(app)


def _success(selection: str, root: str = "updateLocation") -> str:
    return f'mutation {{ {root}(input: {{id: "l1"}}) {{ ... on UpdateLocationSuccess {{ {selection} }} }} }}'


def _post(client: TestClient, query: str) -> dict:
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "errors" not in body, body["errors"]
    return body["data"]


_CASES = {
    "aliased nested field": (
        _success("location { id other: owner { id } }"),
        {"updateLocation": {"location": {"id": "l1", "other": {"id": "p1"}}}},
    ),
    "aliases on the root, a leaf and the entity": (
        _success("msg: message loc: location { ident: id }", root="m: updateLocation"),
        {"m": {"msg": "ok", "loc": {"ident": "l1"}}},
    ),
    "list elements filtered": (
        _success("location { tags { id } }"),
        {"updateLocation": {"location": {"tags": [{"id": "t1"}, {"id": "t2"}]}}},
    ),
    "typename only": (
        'mutation { updateLocation(input: {id: "l1"}) { __typename } }',
        {"updateLocation": {"__typename": "UpdateLocationSuccess"}},
    ),
    "typename where selected": (
        _success("t: __typename location { __typename owner { __typename id } }"),
        {
            "updateLocation": {
                "t": "UpdateLocationSuccess",
                "location": {
                    "__typename": "Location",
                    "owner": {"__typename": "Person", "id": "p1"},
                },
            }
        },
    ),
    "error fragment only": (
        'mutation { updateLocation(input: {id: "l1"}) { ... on UpdateLocationError { message } } }',
        {"updateLocation": {}},
    ),
    "interface field picks the matching fragment": (
        _success("location { owner { ... on Person { name } ... on Org { title } } }"),
        {"updateLocation": {"location": {"owner": {"name": "Ada"}}}},
    ),
    "union field picks the matching fragment": (
        _success("location { ownerU { ... on Person { name } ... on Org { title } } }"),
        {"updateLocation": {"location": {"ownerU": {"title": "ACME"}}}},
    ),
}


@pytest.mark.usefixtures("test_schema")
class TestMutationResponseSelectionsOverHttp:
    @pytest.mark.parametrize("case", list(_CASES))
    def test_response_holds_the_selection(self, client: TestClient, case: str) -> None:
        query, expected = _CASES[case]

        assert _post(client, query) == expected

    def test_field_named_with_name_is_keyed_by_it(self, client: TestClient) -> None:
        # The key came from the class name (moveLocation), not the field's name
        data = _post(client, 'mutation { relocate(input: {id: "l1"}) { __typename } }')

        assert data == {"relocate": {"__typename": "UpdateLocationSuccess"}}

    def test_error_response_under_its_alias(self, client: TestClient) -> None:
        data = _post(
            client,
            'mutation { r: updateLocation(input: {id: "missing"}) {'
            " ... on UpdateLocationError { why: message code } } }",
        )

        assert data == {"r": {"why": "ok", "code": 404}}

    # Outside HTTP mode graphql-core builds the entity's Python type from the dict,
    # which holds only the selected fields, and may hold JSONB keys the type lacks
    @pytest.mark.parametrize("case", list(_CASES))
    async def test_graphql_core_gives_the_same_data(
        self, class_db_pool, update_location_function, mutation, case: str
    ) -> None:
        query, expected = _CASES[case]
        schema = build_fraiseql_schema(
            query_types=mutation["queries"], mutation_resolvers=mutation["mutations"]
        )

        result = await graphql(
            schema, query, context_value={"db": FraiseQLRepository(class_db_pool)}
        )

        assert result.errors is None
        assert result.data == expected
