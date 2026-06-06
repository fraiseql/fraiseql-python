"""Subscription-resolver operation enforcement (issue #364, phase 1).

Subscriptions are operations, so the PEP gates them once, at subscribe time, before
the event stream is created. These tests drive the built ``subscribe`` resolver
directly — the same resolver graphql-core's ``subscribe`` invokes on the websocket
path (``websocket.py:256``).
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator  # noqa: TC003 — runtime hint for get_type_hints
from types import SimpleNamespace
from typing import Any

import pytest
from graphql import GraphQLError

import fraiseql
from fraiseql.gql.builders import SchemaRegistry
from fraiseql.gql.schema_builder import build_fraiseql_schema

_yields: list[str] = []


@fraiseql.type
class Tick:
    id: int
    label: str


async def _ticks(info) -> list[Tick]:
    return []


@fraiseql.subscription
async def ticks(info) -> AsyncGenerator[Tick]:
    _yields.append("ticks")
    yield Tick(id=1, label="a")


class DenyAll:
    async def authorize_operation(self, **_: Any) -> bool:
        return False


class AllowAll:
    async def authorize_operation(self, **_: Any) -> bool:
        return True


class Boom:
    async def authorize_operation(self, **_: Any) -> bool:
        raise RuntimeError("authorizer exploded")


@pytest.fixture(autouse=True)
def _clean_registry():
    registry = SchemaRegistry.get_instance()
    registry.clear()
    from fraiseql.core.graphql_type import _graphql_type_cache

    _graphql_type_cache.clear()
    _yields.clear()
    yield
    registry.clear()
    _graphql_type_cache.clear()
    _yields.clear()


def _subscribe_resolver(authorizer: Any):
    schema = build_fraiseql_schema(
        query_types=[Tick, _ticks],
        subscription_resolvers=[ticks],
        authorizer=authorizer,
    )
    field = next(iter(schema.subscription_type.fields.values()))
    return field.subscribe


_INFO = SimpleNamespace(context={}, field_name="ticks")


async def _drain(stream: Any) -> list[Any]:
    return [value async for value in stream]


async def test_deny_blocks_subscribe_and_stream() -> None:
    """A deny decision raises at subscribe time; the generator body never runs."""
    subscribe = _subscribe_resolver(DenyAll())
    with pytest.raises(GraphQLError) as exc:
        await subscribe(None, _INFO)
    assert exc.value.extensions["code"] == "FORBIDDEN"
    assert _yields == [], "subscription body ran despite deny"


async def test_raising_authorizer_denies_fail_closed() -> None:
    """A raising authorizer is normalized to a FORBIDDEN deny (shared fail-closed core)."""
    subscribe = _subscribe_resolver(Boom())
    with pytest.raises(GraphQLError) as exc:
        await subscribe(None, _INFO)
    assert exc.value.extensions["code"] == "FORBIDDEN"
    assert _yields == []


async def test_allow_streams_values() -> None:
    """An allow decision returns the inner stream and values flow through unchanged."""
    subscribe = _subscribe_resolver(AllowAll())
    stream = await subscribe(None, _INFO)
    assert inspect.isasyncgen(stream)
    values = await _drain(stream)
    assert [v.label for v in values] == ["a"]
    assert _yields == ["ticks"]


async def test_no_authorizer_streams_unchanged() -> None:
    """With no authorizer the stream is byte-for-byte today's behavior (no enforcement)."""
    subscribe = _subscribe_resolver(None)
    stream = await subscribe(None, _INFO)
    values = await _drain(stream)
    assert [v.label for v in values] == ["a"]
    assert _yields == ["ticks"]
