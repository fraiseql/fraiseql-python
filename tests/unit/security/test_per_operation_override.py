"""Per-operation authorizer override (issue #362, phase 3)."""

from __future__ import annotations

from typing import Any

import pytest
from graphql import graphql

import fraiseql
from fraiseql.gql.builders import SchemaRegistry
from fraiseql.gql.schema_builder import build_fraiseql_schema

_ran: list[str] = []


class Deny:
    async def authorize_operation(self, **_: Any) -> bool:
        return False


class Allow:
    async def authorize_operation(self, **_: Any) -> bool:
        return True


@fraiseql.type
class Widget:
    id: int
    name: str


# --- mutations with per-operation overrides ---


@fraiseql.mutation(authorizer=Deny())
async def mut_perop_deny(info, name: str) -> Widget:
    _ran.append("mut_perop_deny")
    return Widget(id=1, name=name)


@fraiseql.mutation(authorizer=Allow())
async def mut_perop_allow(info, name: str) -> Widget:
    _ran.append("mut_perop_allow")
    return Widget(id=1, name=name)


@fraiseql.mutation
async def mut_no_perop(info, name: str) -> Widget:
    _ran.append("mut_no_perop")
    return Widget(id=1, name=name)


# --- queries with per-operation overrides ---


@fraiseql.query(authorizer=Deny())
async def q_perop_deny(info) -> list[Widget]:
    _ran.append("q_perop_deny")
    return []


@fraiseql.query
async def q_no_perop(info) -> list[Widget]:
    _ran.append("q_no_perop")
    return []


@pytest.fixture(autouse=True)
def _clean_registry():
    registry = SchemaRegistry.get_instance()
    registry.clear()
    from fraiseql.core.graphql_type import _graphql_type_cache

    _graphql_type_cache.clear()
    _ran.clear()
    yield
    registry.clear()
    _graphql_type_cache.clear()
    _ran.clear()


async def test_per_op_deny_beats_global_allow() -> None:
    schema = build_fraiseql_schema(
        query_types=[Widget, q_no_perop],
        mutation_resolvers=[mut_perop_deny, mut_no_perop],
        authorizer=Allow(),
    )
    denied = await graphql(schema, 'mutation { mutPeropDeny(name: "x") { id } }')
    assert denied.errors and denied.errors[0].extensions["code"] == "FORBIDDEN"
    assert "mut_perop_deny" not in _ran

    allowed = await graphql(schema, 'mutation { mutNoPerop(name: "x") { id } }')
    assert not allowed.errors
    assert "mut_no_perop" in _ran


async def test_per_op_allow_beats_global_deny() -> None:
    schema = build_fraiseql_schema(
        query_types=[Widget, q_no_perop],
        mutation_resolvers=[mut_perop_allow, mut_no_perop],
        authorizer=Deny(),
    )
    allowed = await graphql(schema, 'mutation { mutPeropAllow(name: "x") { id } }')
    assert not allowed.errors
    assert "mut_perop_allow" in _ran

    denied = await graphql(schema, 'mutation { mutNoPerop(name: "x") { id } }')
    assert denied.errors and denied.errors[0].extensions["code"] == "FORBIDDEN"
    assert "mut_no_perop" not in _ran


async def test_query_per_op_deny_beats_global_allow() -> None:
    schema = build_fraiseql_schema(
        query_types=[Widget, q_perop_deny, q_no_perop],
        authorizer=Allow(),
    )
    denied = await graphql(schema, "{ qPeropDeny { id } }")
    assert denied.errors and denied.errors[0].extensions["code"] == "FORBIDDEN"
    assert "q_perop_deny" not in _ran

    allowed = await graphql(schema, "{ qNoPerop { id } }")
    assert not allowed.errors
    assert "q_no_perop" in _ran


def test_bare_query_decorator_still_works() -> None:
    @fraiseql.query
    async def bare(info) -> list[Widget]:
        return []

    assert hasattr(bare, "__fraiseql_authorizer__")
    assert bare.__fraiseql_authorizer__ is None


def test_query_decorator_call_form_still_works() -> None:
    @fraiseql.query()
    async def called(info) -> list[Widget]:
        return []

    assert hasattr(called, "__fraiseql_authorizer__")
    assert called.__fraiseql_authorizer__ is None
