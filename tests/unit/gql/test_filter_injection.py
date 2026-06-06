"""Resolver writes authorization filters into the repository context (issue #362, phase 5)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from graphql import graphql

import fraiseql
from fraiseql.gql.builders import SchemaRegistry
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.security.authorization import AuthorizationDecision

_received: dict[str, Any] = {}


class _FakeDB:
    def __init__(self) -> None:
        self.context: dict[str, Any] = {}


@fraiseql.type
class Widget:
    id: int
    name: str


@fraiseql.query
async def things(info, **kwargs) -> list[Widget]:
    _received.clear()
    _received.update(kwargs)
    return []


@fraiseql.query
async def alpha(info) -> list[Widget]:
    return []


@fraiseql.query
async def beta(info) -> list[Widget]:
    return []


class PerFieldAuthorizer:
    """Scopes ``alpha`` to a tenant; leaves ``beta`` unscoped."""

    async def authorize_operation(self, *, operation_name: str, **_: Any) -> AuthorizationDecision:
        if operation_name == "alpha":
            return AuthorizationDecision.allow(filters={"tenant_id": "tA"})
        return AuthorizationDecision.allow()


@fraiseql.mutation
async def do_thing(info, name: str) -> Widget:
    _received.clear()
    return Widget(id=1, name=name)


class AllowWithFilters:
    async def authorize_operation(self, **_: Any) -> AuthorizationDecision:
        return AuthorizationDecision.allow(filters={"tenant_id": "t1"})


class AllowNoFilters:
    async def authorize_operation(self, **_: Any) -> bool:
        return True


@pytest.fixture(autouse=True)
def _clean_registry():
    registry = SchemaRegistry.get_instance()
    registry.clear()
    from fraiseql.core.graphql_type import _graphql_type_cache

    _graphql_type_cache.clear()
    _received.clear()
    yield
    registry.clear()
    _graphql_type_cache.clear()
    _received.clear()


async def test_query_filters_written_to_repo_context() -> None:
    schema = build_fraiseql_schema(query_types=[Widget, things], authorizer=AllowWithFilters())
    db = _FakeDB()
    result = await graphql(schema, "{ things { id } }", context_value={"db": db})
    assert not result.errors
    assert db.context["_fraiseql_auth_filters"]["things"] == {"tenant_id": "t1"}
    # The user function never receives a mandatory_filters kwarg — filters ride context.
    assert "mandatory_filters" not in _received


async def test_query_allow_no_filters_writes_nothing() -> None:
    schema = build_fraiseql_schema(query_types=[Widget, things], authorizer=AllowNoFilters())
    db = _FakeDB()
    result = await graphql(schema, "{ things { id } }", context_value={"db": db})
    assert not result.errors
    assert "_fraiseql_auth_filters" not in db.context


async def test_multi_root_scopes_do_not_leak() -> None:
    # Two root fields in one request: alpha is scoped, beta is not. Each field's scope
    # is keyed by its own field name, so beta never inherits alpha's tenant filter.
    schema = build_fraiseql_schema(
        query_types=[Widget, alpha, beta], authorizer=PerFieldAuthorizer()
    )
    db = _FakeDB()
    result = await graphql(schema, "{ alpha { id } beta { id } }", context_value={"db": db})
    assert not result.errors
    buckets = db.context.get("_fraiseql_auth_filters", {})
    assert buckets.get("alpha") == {"tenant_id": "tA"}
    assert "beta" not in buckets


async def test_mutation_filters_ignored_and_warned(caplog) -> None:
    schema = build_fraiseql_schema(
        query_types=[Widget, things],
        mutation_resolvers=[do_thing],
        authorizer=AllowWithFilters(),
    )
    db = _FakeDB()
    with caplog.at_level(logging.WARNING):
        result = await graphql(
            schema, 'mutation { doThing(name: "x") { id name } }', context_value={"db": db}
        )
    assert not result.errors
    assert result.data["doThing"] == {"id": 1, "name": "x"}
    # Mutations have no row-scoping semantics: filters are ignored, not written.
    assert "_fraiseql_auth_filters" not in db.context
    assert any("filter" in record.message.lower() for record in caplog.records)
