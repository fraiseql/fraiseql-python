"""Automatic field-level authorization opt-in (issue #366).

A type declares which fields to gate via ``@fraise_type(authorize_fields=[...])``; each
listed field is checked with ``operation_type="field"`` and
``operation_name="TypeName.fieldName"`` before its resolver runs, reusing the field-auth
enforcement path. Undeclared fields and apps with no authorizer are unaffected.
"""

from __future__ import annotations

from typing import Any

import pytest
from graphql import graphql

import fraiseql
from fraiseql.gql.builders import SchemaRegistry
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.security import authorize_field

pytestmark = pytest.mark.integration

_executions: list[str] = []


@fraiseql.type(authorize_fields=["secret", "both"])
class Account:
    id: int
    name: str

    @fraiseql.field
    def secret(self) -> str | None:
        _executions.append("secret")
        return "classified"

    @fraiseql.field
    def public(self) -> str | None:
        _executions.append("public")
        return "ok"

    @fraiseql.field
    @authorize_field(lambda info: info.context.get("explicit_ok", False))
    def both(self, info) -> str | None:
        _executions.append("both")
        return "guarded"


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


@pytest.fixture(autouse=True)
def _clean_registry():
    registry = SchemaRegistry.get_instance()
    registry.clear()
    from fraiseql.core.graphql_type import _graphql_type_cache

    _graphql_type_cache.clear()
    _executions.clear()
    yield
    registry.clear()
    _graphql_type_cache.clear()
    _executions.clear()


def _build(*, authorizer: Any) -> Any:
    return build_fraiseql_schema(query_types=[Account, account], authorizer=authorizer)


def _codes(result: Any) -> set[str]:
    return {(e.extensions or {}).get("code") for e in (result.errors or [])}


async def test_declared_field_denied_body_not_run() -> None:
    schema = _build(authorizer=DenyFields())
    result = await graphql(schema, "{ account { secret } }")
    assert "FIELD_AUTHORIZATION_ERROR" in _codes(result)
    assert "secret" not in _executions, "gated field body ran despite a deny"


async def test_undeclared_field_unaffected() -> None:
    schema = _build(authorizer=DenyFields())
    result = await graphql(schema, "{ account { name public } }")
    assert not result.errors
    assert result.data["account"] == {"name": "acme", "public": "ok"}
    assert _executions == ["public"], "the undeclared field is never gated"


async def test_declared_field_allowed_runs() -> None:
    schema = _build(authorizer=AllowAll())
    result = await graphql(schema, "{ account { secret } }")
    assert not result.errors
    assert result.data["account"]["secret"] == "classified"
    assert "secret" in _executions


async def test_no_authorizer_unchanged() -> None:
    schema = _build(authorizer=None)
    result = await graphql(schema, "{ account { secret } }")
    assert not result.errors
    assert result.data["account"]["secret"] == "classified"
    assert "secret" in _executions


async def test_raising_field_authorizer_fail_closed() -> None:
    schema = _build(authorizer=Boom())
    result = await graphql(schema, "{ account { secret } }")
    assert "FIELD_AUTHORIZATION_ERROR" in _codes(result)
    assert "secret" not in _executions


async def test_auto_gate_and_explicit_authorize_field_are_anded() -> None:
    """Both checks run (AND): an allow-all authorizer cannot override an explicit deny."""
    schema = _build(authorizer=AllowAll())
    # explicit @authorize_field denies (explicit_ok defaults False) even though auto allows.
    denied = await graphql(schema, "{ account { both } }", context_value={})
    assert "FIELD_AUTHORIZATION_ERROR" in _codes(denied)
    assert "both" not in _executions
    # both gates pass → the field runs.
    allowed = await graphql(schema, "{ account { both } }", context_value={"explicit_ok": True})
    assert not allowed.errors
    assert allowed.data["account"]["both"] == "guarded"
    assert "both" in _executions
