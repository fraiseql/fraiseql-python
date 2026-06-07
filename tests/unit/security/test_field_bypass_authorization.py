"""Resolver-bypass enforcement of automatic field-level authorization (issue #366).

The Rust merge / passthrough / TurboRouter / ``POST /graphql/rust`` paths never invoke
``GraphQLField.resolve``, so the per-field gate installed by ``@fraise_type(authorize_fields=...)``
would silently fail open there. ``enforce_selected_field_authorization`` re-applies the gate by
inspecting the selection set and consulting the same authorizer the resolver path uses — before
any data is served. These tests pin the detection + enforcement core (no HTTP, no DB, no Rust).
"""

from __future__ import annotations

from typing import Any

import pytest
from graphql import GraphQLError, parse

import fraiseql
from fraiseql.gql.builders import SchemaRegistry
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.security.field_auth import (
    enforce_selected_field_authorization,
    iter_gated_selections,
)

pytestmark = pytest.mark.unit


@fraiseql.type(authorize_fields=["secret"])
class Account:
    id: int
    name: str

    @fraiseql.field
    def secret(self) -> str | None:
        return "classified"

    @fraiseql.field
    def public(self) -> str | None:
        return "ok"


@fraiseql.query
async def account(info) -> Account:
    return Account(id=1, name="acme")


class DenyFields:
    """Allows operations; denies every field check."""

    async def authorize_operation(self, *, operation_type: str, **_: Any) -> bool:
        return operation_type != "field"


class AllowAll:
    async def authorize_operation(self, **_: Any) -> bool:
        return True


class Boom:
    async def authorize_operation(self, *, operation_type: str, **_: Any) -> bool:
        if operation_type == "field":
            raise RuntimeError("field PDP down")
        return True


class RecordingFields:
    """Allows everything; records each field check it is asked to make."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def authorize_operation(
        self, *, operation_type: str, operation_name: str, arguments: dict[str, Any], **_: Any
    ) -> bool:
        if operation_type == "field":
            self.calls.append((operation_name, arguments))
        return True


@pytest.fixture(autouse=True)
def _clean_registry():
    registry = SchemaRegistry.get_instance()
    registry.clear()
    from fraiseql.core.graphql_type import _graphql_type_cache

    _graphql_type_cache.clear()
    yield
    registry.clear()
    _graphql_type_cache.clear()


def _build(*, authorizer: Any) -> Any:
    return build_fraiseql_schema(query_types=[Account, account], authorizer=authorizer)


async def _enforce(schema: Any, query: str, *, context: dict[str, Any] | None = None) -> None:
    await enforce_selected_field_authorization(
        schema=schema, query=query, context=context or {}, variables={}
    )


async def test_deny_blocks_selected_gated_field() -> None:
    schema = _build(authorizer=DenyFields())
    with pytest.raises(GraphQLError) as exc:
        await _enforce(schema, "{ account { secret } }")
    assert (exc.value.extensions or {}).get("code") == "FIELD_AUTHORIZATION_ERROR"


async def test_allow_passes_gated_field() -> None:
    schema = _build(authorizer=AllowAll())
    await _enforce(schema, "{ account { secret } }")  # must not raise


async def test_ungated_field_not_enforced() -> None:
    """A query that selects no gated field is a no-op even under a deny-all field authorizer."""
    schema = _build(authorizer=DenyFields())
    await _enforce(schema, "{ account { name public } }")  # must not raise


async def test_no_authorizer_is_noop() -> None:
    schema = _build(authorizer=None)
    await _enforce(schema, "{ account { secret } }")  # must not raise


async def test_raising_field_authorizer_fails_closed() -> None:
    schema = _build(authorizer=Boom())
    with pytest.raises(GraphQLError):
        await _enforce(schema, "{ account { secret } }")


async def test_unparseable_query_is_noop() -> None:
    schema = _build(authorizer=DenyFields())
    await _enforce(schema, "this is not graphql {{{")  # must not raise


async def test_gated_field_in_fragment_is_detected() -> None:
    schema = _build(authorizer=DenyFields())
    query = "{ account { ...f } } fragment f on Account { secret }"
    with pytest.raises(GraphQLError):
        await _enforce(schema, query)


async def test_gated_field_via_inline_fragment_is_detected() -> None:
    schema = _build(authorizer=DenyFields())
    query = "{ account { ... on Account { secret } } }"
    with pytest.raises(GraphQLError):
        await _enforce(schema, query)


async def test_iter_gated_selections_reports_qualified_id() -> None:
    schema = _build(authorizer=AllowAll())
    document = parse("{ account { secret public } }")
    selections = iter_gated_selections(schema, document, {})
    assert selections == [("Account.secret", {})]


async def test_enforcement_calls_authorizer_with_field_identity() -> None:
    recorder = RecordingFields()
    schema = _build(authorizer=recorder)
    await _enforce(schema, "{ account { secret } }")
    assert recorder.calls == [("Account.secret", {})]
