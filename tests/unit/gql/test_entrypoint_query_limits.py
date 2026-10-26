"""Depth and complexity limits on the entry points outside the FastAPI router.

``GraphNoteRouter`` (plain Starlette HTTP) and the WebSocket subscription transport
take the limits from a ``FraiseQLConfig`` or an explicit ``QueryLimits``, and check
them before executing, as ``fraiseql.fastapi.routers`` does.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from graphql import build_schema
from starlette.testclient import TestClient

from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.graphql_entrypoint import GraphNoteRouter
from fraiseql.gql.query_limits import QueryLimits
from fraiseql.subscriptions.websocket import (
    GraphQLWSMessage,
    MessageType,
    SubscriptionManager,
    WebSocketConnection,
)

_SCHEMA = build_schema(
    """
    type Node {
      name: String
      parent: Node
    }
    type Query {
      node: Node
    }
    type Subscription {
      node: Node
    }
    """
)


async def _events() -> AsyncIterator[dict[str, Any]]:
    yield {"node": {"name": "a", "parent": {"name": "b", "parent": None}}}


async def _node_events(*_args: Any, **_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
    # A coroutine, as the subscription builder makes it: subscribe() is then awaitable.
    return _events()


_SCHEMA.subscription_type.fields["node"].subscribe = _node_events  # type: ignore[union-attr]
_SCHEMA.subscription_type.fields["node"].resolve = lambda event, _info: event["node"]  # type: ignore[union-attr]
_SCHEMA.query_type.fields["node"].resolve = lambda *_: {"name": "a", "parent": None}  # type: ignore[union-attr]

_DEEP = "{ node { parent { parent { parent { name } } } } }"  # depth 4
_SHALLOW = "{ node { parent { name } } }"  # depth 2
_DEEP_SUBSCRIPTION = "subscription { node { parent { parent { parent { name } } } } }"
_SHALLOW_SUBSCRIPTION = "subscription { node { parent { name } } }"
_INTROSPECTION = "{ __schema { types { fields { type { ofType { ofType { name } } } } } } }"


def _config(**kwargs: Any) -> FraiseQLConfig:
    return FraiseQLConfig(database_url="postgresql://localhost/test", **kwargs)


class TestGraphNoteRouter:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"config": _config(max_query_depth=3)},
            {"query_limits": QueryLimits(max_depth=3)},
        ],
        ids=["config", "query_limits"],
    )
    def test_a_query_deeper_than_the_limit_is_rejected(self, kwargs: dict[str, Any]) -> None:
        client = TestClient(GraphNoteRouter(_SCHEMA, **kwargs))
        response = client.post("/graphql", json={"query": _DEEP})
        body = response.json()
        assert "data" not in body
        assert body["errors"][0]["extensions"]["code"] == "QUERY_TOO_DEEP"

    def test_get_requests_are_checked_too(self) -> None:
        client = TestClient(GraphNoteRouter(_SCHEMA, query_limits=QueryLimits(max_depth=3)))
        response = client.get("/graphql", params={"query": _DEEP})
        assert response.json()["errors"][0]["extensions"]["code"] == "QUERY_TOO_DEEP"

    def test_complexity_limit_from_config(self) -> None:
        config = _config(complexity_enabled=True, complexity_max_score=2)
        client = TestClient(GraphNoteRouter(_SCHEMA, config=config))
        response = client.post("/graphql", json={"query": _SHALLOW})
        assert response.json()["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"

    def test_a_query_within_the_limit_runs(self) -> None:
        client = TestClient(GraphNoteRouter(_SCHEMA, query_limits=QueryLimits(max_depth=3)))
        response = client.post("/graphql", json={"query": _SHALLOW})
        assert response.json() == {"data": {"node": {"parent": None}}}

    def test_introspection_is_not_counted(self) -> None:
        client = TestClient(GraphNoteRouter(_SCHEMA, query_limits=QueryLimits(max_depth=1)))
        response = client.post("/graphql", json={"query": _INTROSPECTION})
        assert "errors" not in response.json()

    def test_no_limit_by_default(self) -> None:
        client = TestClient(GraphNoteRouter(_SCHEMA))
        response = client.post("/graphql", json={"query": _DEEP})
        assert "errors" not in response.json()


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


async def _subscribe(connection: WebSocketConnection, query: str) -> list[dict[str, Any]]:
    connection.schema = _SCHEMA
    await connection._handle_subscribe(
        GraphQLWSMessage(type=MessageType.SUBSCRIBE, id="1", payload={"query": query})
    )
    task = connection.subscriptions.get("1")
    if task is not None:
        await asyncio.wait_for(task, timeout=5)
    return connection.websocket.sent


class TestWebSocketSubscriptions:
    async def test_a_subscription_deeper_than_the_limit_is_rejected(self) -> None:
        connection = WebSocketConnection(_FakeWebSocket(), query_limits=QueryLimits(max_depth=3))
        sent = await _subscribe(connection, _DEEP_SUBSCRIPTION)
        assert len(sent) == 1
        assert sent[0]["type"] == MessageType.ERROR
        assert sent[0]["payload"]["errors"][0]["extensions"]["code"] == "QUERY_TOO_DEEP"
        assert connection.subscriptions == {}

    async def test_a_subscription_within_the_limit_runs(self) -> None:
        connection = WebSocketConnection(_FakeWebSocket(), query_limits=QueryLimits(max_depth=3))
        sent = await _subscribe(connection, _SHALLOW_SUBSCRIPTION)
        assert sent[0]["type"] == MessageType.DATA
        assert sent[0]["payload"] == {"data": {"node": {"parent": {"name": "b"}}}}

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"config": _config(max_query_depth=3)},
            {"query_limits": QueryLimits(max_depth=3)},
        ],
        ids=["config", "query_limits"],
    )
    async def test_the_manager_passes_its_limits_to_each_connection(
        self, kwargs: dict[str, Any]
    ) -> None:
        manager = SubscriptionManager(**kwargs)
        manager.schema = _SCHEMA
        connection = await manager.add_connection(_FakeWebSocket())
        sent = await _subscribe(connection, _DEEP_SUBSCRIPTION)
        assert sent[0]["payload"]["errors"][0]["extensions"]["code"] == "QUERY_TOO_DEEP"

    async def test_no_limit_by_default(self) -> None:
        manager = SubscriptionManager()
        manager.schema = _SCHEMA
        connection = await manager.add_connection(_FakeWebSocket())
        sent = await _subscribe(connection, _DEEP_SUBSCRIPTION)
        assert sent[0]["type"] == MessageType.DATA
