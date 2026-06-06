"""Mutation-resolver operation enforcement (issue #362, phase 2)."""

from __future__ import annotations

from typing import Any

import pytest
from graphql import graphql

import fraiseql
from fraiseql.gql.builders import SchemaRegistry
from fraiseql.gql.schema_builder import build_fraiseql_schema

_ran: list[str] = []


@fraiseql.type
class Widget:
    id: int
    name: str


async def _widgets(info) -> list[Widget]:
    return []


@fraiseql.mutation
async def make_widget(info, name: str) -> Widget:
    _ran.append(name)
    return Widget(id=1, name=name)


def make_widget_sync(info, name: str) -> Widget:
    _ran.append(name)
    return Widget(id=1, name=name)


class DenyAll:
    async def authorize_operation(self, **_: Any) -> bool:
        return False


class AllowAll:
    async def authorize_operation(self, **_: Any) -> bool:
        return True


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


def _build(*, authorizer, sync: bool = False):
    mutation = make_widget_sync if sync else make_widget
    return build_fraiseql_schema(
        query_types=[Widget, _widgets],
        mutation_resolvers=[mutation],
        authorizer=authorizer,
    )


_MUTATION = 'mutation { makeWidget(name: "x") { id name } }'
_MUTATION_SYNC = 'mutation { makeWidgetSync(name: "x") { id name } }'


async def test_deny_all_blocks_async_mutation() -> None:
    schema = _build(authorizer=DenyAll())
    result = await graphql(schema, _MUTATION)
    assert result.errors
    assert len(result.errors) == 1
    assert result.errors[0].extensions["code"] == "FORBIDDEN"
    assert _ran == [], "mutation body ran despite deny"


async def test_deny_all_blocks_sync_mutation() -> None:
    schema = _build(authorizer=DenyAll(), sync=True)
    result = await graphql(schema, _MUTATION_SYNC)
    assert result.errors
    assert result.errors[0].extensions["code"] == "FORBIDDEN"
    assert _ran == [], "sync mutation body ran despite deny"


async def test_allow_all_runs_async_mutation() -> None:
    schema = _build(authorizer=AllowAll())
    result = await graphql(schema, _MUTATION)
    assert not result.errors
    assert result.data["makeWidget"] == {"id": 1, "name": "x"}
    assert _ran == ["x"]


async def test_allow_all_runs_sync_mutation() -> None:
    schema = _build(authorizer=AllowAll(), sync=True)
    result = await graphql(schema, _MUTATION_SYNC)
    assert not result.errors
    assert result.data["makeWidgetSync"] == {"id": 1, "name": "x"}
    assert _ran == ["x"]


async def test_no_authorizer_matches_baseline() -> None:
    schema = _build(authorizer=None)
    result = await graphql(schema, _MUTATION)
    assert not result.errors
    assert result.data["makeWidget"] == {"id": 1, "name": "x"}
    assert _ran == ["x"]
