"""A mutation response holds what the query selected, under its response keys (#581, #573).

Each case builds the selection document the resolver builds
(``_response_selections``), then the response with
``fraiseql_rs.build_mutation_response``, without a database. In HTTP mode that
response is what the client receives, so it must apply aliases, filter lists,
and leave out everything the query didn't select.
"""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from graphql import FragmentDefinitionNode, OperationDefinitionNode, build_schema, parse

from fraiseql import _get_fraiseql_rs
from fraiseql.mutations import rust_executor
from fraiseql.mutations.mutation_decorator import _response_selections

_SCHEMA = build_schema("""
    interface Node { id: ID! }
    interface Named { name: String }
    type Person implements Node & Named { id: ID! name: String email: String }
    type Org implements Node { id: ID! title: String }
    type Robot implements Named { name: String serial: String }
    union Owner = Person | Org
    type Tag { id: ID! label: String }
    type Meta { id: ID! kind: String }
    type Location {
        id: ID! name: String owner: Node ownerU: Owner owners: [Node] named: Named
        tags: [Tag] grid: [[Tag]] fields: Meta
    }
    type Error { message: String code: Int }
    type UpdateLocationSuccess { message: String status: String location: Location! }
    type UpdateLocationError { message: String code: Int status: String errors: [Error] }
    union UpdateLocationResult = UpdateLocationSuccess | UpdateLocationError
    type Query { ping: Int }
    type Mutation { updateLocation: UpdateLocationResult }
""")

_ENTITY = {
    "id": "l1",
    "name": "HQ",
    "secret": "x",
    "owner": {"__typename": "Person", "id": "p1", "name": "Ada", "title": "Dr", "email": "a@x"},
    "owner_u": {"__typename": "Org", "id": "o1", "name": "acme-internal", "title": "ACME"},
    "owners": [
        {"__typename": "Person", "id": "p1", "name": "Ada", "title": "Dr"},
        {"__typename": "Org", "id": "o1", "name": "acme-internal", "title": "ACME"},
    ],
    "named": {"id": "r1", "name": "R2", "serial": "S-1"},
    "tags": [
        {"id": "t1", "label": "a", "secret": "T1"},
        {"id": "t2", "label": "b", "secret": "T2"},
    ],
    "grid": [[{"id": "t1", "label": "a", "secret": "T1"}]],
    "fields": {"id": "m1", "kind": "k", "secret": "M"},
}

_SUCCESS = {
    "status": "success",
    "message": "ok",
    "entity_id": "l1",
    "entity_type": "Location",
    "entity": _ENTITY,
    "updated_fields": ["name"],
    "cascade": None,
    "metadata": None,
}

_FAILURE = {
    "status": "validation:invalid_input",
    "message": "bad",
    "entity_id": None,
    "entity_type": None,
    "entity": None,
    "updated_fields": None,
    "cascade": None,
    "metadata": None,
}


@pytest.fixture
def rs() -> Any:
    module = _get_fraiseql_rs()
    if module is None:
        pytest.skip("Rust extension not available")
    return module


def _info(query: str) -> SimpleNamespace:
    definitions = parse(query).definitions
    operation = next(d for d in definitions if isinstance(d, OperationDefinitionNode))
    root = operation.selection_set.selections[0]
    return SimpleNamespace(
        schema=_SCHEMA,
        field_nodes=[root],
        fragments={d.name.value: d for d in definitions if isinstance(d, FragmentDefinitionNode)},
        path=SimpleNamespace(key=root.alias.value if root.alias else root.name.value),
    )


def _respond(rs: Any, query: str, result: dict = _SUCCESS, by_alias: bool = True) -> dict:
    """The response's data for a query, as the mutation resolver builds it."""
    info = _info(query)
    document = _response_selections(
        info, "UpdateLocationSuccess", "UpdateLocationError", by_alias=by_alias
    )
    key = info.path.key if by_alias else "updateLocation"
    out = rs.build_mutation_response(
        json.dumps(result),
        key,
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
    return json.loads(out)["data"]


def _location(rs: Any, selection: str) -> dict:
    query = f"mutation {{ updateLocation {{ ... on UpdateLocationSuccess {{ location {selection} }} }} }}"
    return _respond(rs, query)["updateLocation"]["location"]


class TestAliases:
    def test_aliased_entity_field(self, rs: Any) -> None:
        location = _location(rs, "{ id other: owner { id } }")

        assert location == {
            "__typename": "Location",
            "id": "l1",
            "other": {"__typename": "Person", "id": "p1"},
        }

    def test_one_field_under_two_aliases_keeps_both_selections(self, rs: Any) -> None:
        location = _location(rs, "{ id owner { name } other: owner { id } }")

        assert location["owner"] == {"__typename": "Person", "name": "Ada"}
        assert location["other"] == {"__typename": "Person", "id": "p1"}

    def test_root_and_leaf_aliases(self, rs: Any) -> None:
        data = _respond(
            rs,
            "mutation { m: updateLocation { ... on UpdateLocationSuccess {"
            " msg: message loc: location { ident: id } } } }",
        )

        assert data == {
            "m": {
                "__typename": "UpdateLocationSuccess",
                "msg": "ok",
                "loc": {"__typename": "Location", "ident": "l1"},
            }
        }

    def test_aliased_typename(self, rs: Any) -> None:
        data = _respond(rs, "mutation { updateLocation { t: __typename } }")

        assert data == {
            "updateLocation": {"__typename": "UpdateLocationSuccess", "t": "UpdateLocationSuccess"}
        }


class TestUnselectedData:
    def test_list_elements_are_filtered(self, rs: Any) -> None:
        location = _location(rs, "{ id tags { id } }")

        assert location["tags"] == [
            {"__typename": "Tag", "id": "t1"},
            {"__typename": "Tag", "id": "t2"},
        ]

    def test_nested_lists_are_filtered(self, rs: Any) -> None:
        location = _location(rs, "{ grid { label } }")

        assert location["grid"] == [[{"__typename": "Tag", "label": "a"}]]

    def test_typename_only_returns_typename_only(self, rs: Any) -> None:
        data = _respond(rs, "mutation { updateLocation { __typename } }")

        assert data == {"updateLocation": {"__typename": "UpdateLocationSuccess"}}

    def test_only_an_error_fragment_returns_typename_only(self, rs: Any) -> None:
        data = _respond(
            rs, "mutation { updateLocation { ... on UpdateLocationError { message } } }"
        )

        assert data == {"updateLocation": {"__typename": "UpdateLocationSuccess"}}

    def test_entity_field_named_fields_is_filtered(self, rs: Any) -> None:
        location = _location(rs, "{ id fields { kind } }")

        assert location == {
            "__typename": "Location",
            "id": "l1",
            "fields": {"__typename": "Meta", "kind": "k"},
        }

    def test_fragment_on_the_union_applies(self, rs: Any) -> None:
        data = _respond(
            rs,
            "mutation { updateLocation { ... on UpdateLocationResult { __typename }"
            " ... on UpdateLocationSuccess { message } } }",
        )

        assert data == {"updateLocation": {"__typename": "UpdateLocationSuccess", "message": "ok"}}


class TestTypeConditions:
    def test_interface_field_keeps_the_matching_fragment_only(self, rs: Any) -> None:
        location = _location(rs, "{ owner { ... on Person { name } ... on Org { title } } }")

        assert location["owner"] == {"__typename": "Person", "name": "Ada"}

    def test_union_field_keeps_the_matching_fragment_only(self, rs: Any) -> None:
        location = _location(rs, "{ ownerU { ... on Person { name } ... on Org { title } } }")

        assert location["ownerU"] == {"__typename": "Org", "title": "ACME"}

    def test_interface_condition_under_union_field(self, rs: Any) -> None:
        location = _location(rs, "{ ownerU { ... on Node { id } ... on Person { name } } }")

        assert location["ownerU"] == {"__typename": "Org", "id": "o1"}

    def test_list_of_interfaces_is_filtered_per_element(self, rs: Any) -> None:
        location = _location(rs, "{ owners { id ... on Person { name } ... on Org { title } } }")

        assert location["owners"] == [
            {"__typename": "Person", "id": "p1", "name": "Ada"},
            {"__typename": "Org", "id": "o1", "title": "ACME"},
        ]

    def test_named_fragment_on_an_object_type_under_interface(self, rs: Any) -> None:
        data = _respond(
            rs,
            """mutation { updateLocation { ... on UpdateLocationSuccess {
                location { owner { ...P ...O } } } } }
            fragment P on Person { name }
            fragment O on Org { title }""",
        )

        assert data["updateLocation"]["location"]["owner"] == {
            "__typename": "Person",
            "name": "Ada",
        }

    def test_without_typename_in_data_every_fragment_applies(self, rs: Any) -> None:
        location = _location(rs, "{ named { ... on Robot { serial } ... on Person { email } } }")

        assert location["named"] == {"serial": "S-1"}


class TestErrorResponse:
    def test_error_fields_under_their_response_keys(self, rs: Any) -> None:
        data = _respond(
            rs,
            "mutation { updateLocation { ... on UpdateLocationError { why: message c: code"
            " errors { message } } } }",
            result=_FAILURE,
        )

        assert data == {
            "updateLocation": {
                "__typename": "UpdateLocationError",
                "why": "bad",
                "c": 422,
                "errors": [{"__typename": "Error", "message": "bad"}],
            }
        }

    def test_unselected_code_is_left_out(self, rs: Any) -> None:
        data = _respond(
            rs, "mutation { updateLocation { ... on UpdateLocationError { message } } }", _FAILURE
        )

        assert data == {"updateLocation": {"__typename": "UpdateLocationError", "message": "bad"}}


class TestOutsideHttpMode:
    """graphql-core completes the result: it reads fields by name and applies aliases."""

    def test_fields_are_keyed_by_name_and_merged(self, rs: Any) -> None:
        data = _respond(
            rs,
            "mutation { m: updateLocation { ... on UpdateLocationSuccess {"
            " loc: location { ident: id owner { name } other: owner { id } } } } }",
            by_alias=False,
        )

        location = data["updateLocation"]["location"]
        assert location["id"] == "l1"
        assert location["owner"] == {"__typename": "Person", "name": "Ada", "id": "p1"}


class TestVersionSkew:
    def test_extension_rejects_a_call_without_a_format_2_document(self, rs: Any) -> None:
        args = (json.dumps(_SUCCESS), "updateLocation", "S", "E", "location", None, None, True)
        legacy = json.dumps({"fields": ["id"]})

        for entity_selections in (None, legacy):
            with pytest.raises(ValueError, match="selection document"):
                rs.build_mutation_response(*args, None, None, entity_selections)

    def test_python_refuses_an_extension_with_another_format(
        self, rs: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(rust_executor, "_get_fraiseql_rs", SimpleNamespace)

        with pytest.raises(RuntimeError, match="rebuild"):
            rust_executor._checked_fraiseql_rs()
