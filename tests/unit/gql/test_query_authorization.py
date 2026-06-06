"""Query-resolver operation enforcement (issue #362, phase 3)."""

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


async def widgets(info) -> list[Widget]:
    _ran.append("async")
    return [Widget(id=1, name="a")]


def widgets_sync(info) -> list[Widget]:
    _ran.append("sync")
    return [Widget(id=1, name="a")]


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
    query = widgets_sync if sync else widgets
    return build_fraiseql_schema(query_types=[Widget, query], authorizer=authorizer)


async def test_deny_all_blocks_async_query() -> None:
    schema = _build(authorizer=DenyAll())
    result = await graphql(schema, "{ widgets { id name } }")
    assert result.errors
    assert len(result.errors) == 1
    assert result.errors[0].extensions["code"] == "FORBIDDEN"
    assert _ran == []


async def test_deny_all_blocks_sync_query() -> None:
    schema = _build(authorizer=DenyAll(), sync=True)
    result = await graphql(schema, "{ widgetsSync { id name } }")
    assert result.errors
    assert result.errors[0].extensions["code"] == "FORBIDDEN"
    assert _ran == []


async def test_allow_all_runs_query() -> None:
    schema = _build(authorizer=AllowAll())
    result = await graphql(schema, "{ widgets { id name } }")
    assert not result.errors
    assert result.data["widgets"] == [{"id": 1, "name": "a"}]
    assert _ran == ["async"]


async def test_no_authorizer_matches_baseline() -> None:
    schema = _build(authorizer=None)
    result = await graphql(schema, "{ widgets { id name } }")
    assert not result.errors
    assert result.data["widgets"] == [{"id": 1, "name": "a"}]
    assert _ran == ["async"]


async def test_pagination_validation_still_fires_before_enforcement() -> None:
    # Validation runs before enforcement: a bad limit errors with the pagination
    # message (not FORBIDDEN), and the resolver body never runs.
    schema = _build(authorizer=AllowAll())
    result = await graphql(schema, "{ widgets(limit: -1) { id } }")
    assert result.errors
    assert "limit must be non-negative" in result.errors[0].message
    assert _ran == []
