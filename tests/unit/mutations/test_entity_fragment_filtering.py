"""Fragments in a mutation's selection reach the Rust entity filter as fields.

Each case extracts the selections the way the mutation resolver does, then
builds the response with fraiseql_rs.build_mutation_response, without a
database. Related to GitHub issue #566.
"""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from graphql import FragmentDefinitionNode, OperationDefinitionNode, build_schema, parse

from fraiseql import _get_fraiseql_rs
from fraiseql.mutations.mutation_decorator import _response_selections

_SCHEMA = build_schema("""
    interface Node { id: ID! }
    type Person implements Node { id: ID! name: String! email: String }
    type Org implements Node { id: ID! title: String! }
    union Owner = Person | Org
    type Location { id: ID! name: String owner: Node ownerU: Owner }
    type UpdateLocationSuccess { message: String location: Location! }
    type UpdateLocationError { message: String code: Int }
    union UpdateLocationResult = UpdateLocationSuccess | UpdateLocationError
    type Query { ping: Int }
    type Mutation { updateLocation: UpdateLocationResult }
""")

_ENTITY = {
    "id": "l1",
    "name": "HQ",
    "secret": "x",
    "owner": {"__typename": "Person", "id": "p1", "name": "Ada", "email": "a@x"},
    "owner_u": {"__typename": "Org", "id": "o1", "title": "ACME"},
}

_RESULT = {
    "status": "success",
    "message": "ok",
    "entity_id": "l1",
    "entity_type": "Location",
    "entity": _ENTITY,
    "updated_fields": None,
    "cascade": None,
    "metadata": None,
}


@pytest.fixture
def fraiseql_rs() -> Any:
    rs = _get_fraiseql_rs()
    if rs is None:
        pytest.skip("Rust extension not available")
    return rs


def _respond(rs: Any, query: str) -> dict[str, Any]:
    """Build the updateLocation response for a query, as the mutation resolver would."""
    definitions = parse(query).definitions
    operation = next(d for d in definitions if isinstance(d, OperationDefinitionNode))
    info = SimpleNamespace(
        schema=_SCHEMA,
        field_nodes=[operation.selection_set.selections[0]],
        fragments={d.name.value: d for d in definitions if isinstance(d, FragmentDefinitionNode)},
    )
    document = _response_selections(
        info, "UpdateLocationSuccess", "UpdateLocationError", by_alias=True
    )
    out = rs.build_mutation_response(
        json.dumps(_RESULT),
        "updateLocation",
        "UpdateLocationSuccess",
        "UpdateLocationError",
        "location",
        None,
        None,
        True,
        None,
        None,
        json.dumps(document),
    )
    return json.loads(out)["data"]["updateLocation"]


def test_named_fragment_on_entity_keeps_its_fields(fraiseql_rs: Any) -> None:
    data = _respond(
        fraiseql_rs,
        """mutation { updateLocation { ... on UpdateLocationSuccess {
            location { ...LocFields } } } }
        fragment LocFields on Location { id name }""",
    )

    assert data["location"] == {"id": "l1", "name": "HQ"}


def test_named_fragment_inside_success_fragment_keeps_the_entity(fraiseql_rs: Any) -> None:
    data = _respond(
        fraiseql_rs,
        """mutation { updateLocation { ... on UpdateLocationSuccess { ...SF } } }
        fragment SF on UpdateLocationSuccess { location { id } }""",
    )

    assert data["location"] == {"id": "l1"}


def test_named_fragment_under_interface_field_keeps_its_fields(fraiseql_rs: Any) -> None:
    data = _respond(
        fraiseql_rs,
        """mutation { updateLocation { ... on UpdateLocationSuccess {
            location { id owner { ...PersonFields } } } } }
        fragment PersonFields on Person { name }""",
    )

    assert data["location"]["owner"] == {"name": "Ada"}


def test_inline_fragment_under_interface_field_selects_its_fields(fraiseql_rs: Any) -> None:
    data = _respond(
        fraiseql_rs,
        """mutation { updateLocation { ... on UpdateLocationSuccess {
            location { id owner { ... on Person { name } } } } } }""",
    )

    assert data["location"]["owner"] == {"name": "Ada"}


def test_field_and_inline_fragment_under_interface_field(fraiseql_rs: Any) -> None:
    data = _respond(
        fraiseql_rs,
        """mutation { updateLocation { ... on UpdateLocationSuccess {
            location { id owner { id ... on Person { name } } } } } }""",
    )

    assert data["location"]["owner"] == {"id": "p1", "name": "Ada"}


def test_fragments_under_union_field_leak_nothing(fraiseql_rs: Any) -> None:
    data = _respond(
        fraiseql_rs,
        """mutation { updateLocation { ... on UpdateLocationSuccess {
            location { ownerU { __typename ... on Person { name } ... on Org { title } } } } } }""",
    )

    assert data["location"] == {"ownerU": {"__typename": "Org", "title": "ACME"}}


def test_typename_only_under_interface_field(fraiseql_rs: Any) -> None:
    data = _respond(
        fraiseql_rs,
        """mutation { updateLocation { ... on UpdateLocationSuccess {
            location { id owner { __typename } } } } }""",
    )

    assert data["location"]["owner"] == {"__typename": "Person"}
