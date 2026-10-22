"""The __typename of a mutation entity comes from SQL, the data or the schema, never "Entity".

Calls fraiseql_rs.build_mutation_response with an 8-field mutation_response, without a
database. Related to GitHub issue #567.
"""

import json
from typing import Any

import pytest

from fraiseql import _get_fraiseql_rs
from tests.unit.mutations.selection_document import UNFILTERED

_RESULT = {
    "status": "updated",
    "message": "ok",
    "entity_id": "l1",
    "entity_type": None,
    "entity": {"id": "l1", "name": "HQ"},
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


def _respond(
    rs: Any,
    result: dict[str, Any],
    entity_type: str | None,
    entity_field_name: str | None = "location",
) -> dict[str, Any]:
    out = rs.build_mutation_response(
        json.dumps(result),
        "updateLocation",
        "UpdateLocationSuccess",
        "UpdateLocationError",
        entity_field_name,
        entity_type,
        entity_selections=UNFILTERED,
    )
    return json.loads(out)["data"]["updateLocation"]


def test_type_passed_by_python_names_the_entity(fraiseql_rs: Any) -> None:
    data = _respond(fraiseql_rs, _RESULT, "Location")

    assert data["location"]["__typename"] == "Location"


def test_no_type_anywhere_leaves_typename_out(fraiseql_rs: Any) -> None:
    data = _respond(fraiseql_rs, _RESULT, None)

    assert data["location"] == {"id": "l1", "name": "HQ"}


def test_no_type_and_no_field_name_uses_entity(fraiseql_rs: Any) -> None:
    data = _respond(fraiseql_rs, _RESULT, None, entity_field_name=None)

    assert data["entity"] == {"id": "l1", "name": "HQ"}


def test_type_from_sql_wins(fraiseql_rs: Any) -> None:
    data = _respond(fraiseql_rs, {**_RESULT, "entity_type": "Location"}, "Place")

    assert data["location"]["__typename"] == "Location"


def test_type_from_sql_names_the_field(fraiseql_rs: Any) -> None:
    data = _respond(fraiseql_rs, {**_RESULT, "entity_type": "Location"}, None, None)

    assert data["location"]["__typename"] == "Location"


def test_typename_in_the_data_is_kept(fraiseql_rs: Any) -> None:
    entity = {"__typename": "Location", "id": "l1", "name": "HQ"}
    data = _respond(fraiseql_rs, {**_RESULT, "entity": entity}, None)

    assert data["location"]["__typename"] == "Location"
