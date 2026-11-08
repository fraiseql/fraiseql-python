"""``fraise_field`` fields in modules that use ``from __future__ import annotations``.

There every annotation is a string. A field assigned ``fraise_field(...)`` got its
``field_type`` from the raw string (``'list[Secret]'``) instead of the resolved type,
and building the schema failed with "Unsupported output type: list[Secret]".
"""

from __future__ import annotations

from typing import Annotated

import pytest

import fraiseql
from fraiseql.fields import fraise_field
from fraiseql.gql.schema_builder import build_fraiseql_schema

pytestmark = pytest.mark.usefixtures("clear_registry")


@fraiseql.type
class Secret:
    id: int
    level: str


@fraiseql.type
class Vault:
    id: int
    secrets: list[Secret] = fraise_field(default_factory=list, description="All secrets")
    filtered: list[Secret] = fraise_field(
        default_factory=list, supports_where_filtering=True, nested_where_type=Secret
    )
    annotated: Annotated[list[Secret], fraise_field(description="Annotated")]
    parent: Vault | None = fraise_field(default=None)


@fraiseql.input
class SecretInput:
    levels: list[str] = fraise_field(default_factory=list)


@fraiseql.query
async def vault(info, where: SecretInput | None = None) -> Vault:
    return Vault(id=1, annotated=[])


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("secrets", list[Secret]),
        ("filtered", list[Secret]),
        ("annotated", list[Secret]),
        ("parent", Vault | None),
    ],
)
def test_fraise_field_type_is_the_resolved_annotation(field: str, expected: object) -> None:
    assert Vault.__gql_fields__[field].field_type == expected


def test_input_fraise_field_type_is_the_resolved_annotation() -> None:
    assert SecretInput.__gql_fields__["levels"].field_type == list[str]


def test_schema_builds_with_fraise_field_list_fields() -> None:
    schema = build_fraiseql_schema(query_types=[Secret, Vault, SecretInput, vault])

    fields = schema.type_map["Vault"].fields
    assert str(fields["secrets"].type) == "[Secret]!"  # as without the future import
    assert fields["secrets"].description == "All secrets"
    assert "where" in fields["filtered"].args
    assert str(fields["parent"].type) == "Vault"
