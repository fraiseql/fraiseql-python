"""Subscriptions over a real Starlette WebSocket.

The other transport tests use a stand-in socket. Here a FastAPI endpoint hands
its ``WebSocket`` to ``SubscriptionManager`` the way ``examples/websocket_fastapi.py``
does, so the connection reads and writes through Starlette's own API.
"""

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

import fraiseql
from fraiseql import build_fraiseql_schema, subscription
from fraiseql.subscriptions import SubscriptionManager

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clear_registry")]


def _app() -> FastAPI:
    @fraiseql.query
    async def ping(info) -> str:
        return "pong"

    @subscription
    async def countdown(info) -> AsyncGenerator[int]:
        for n in (3, 2, 1):
            yield n

    manager = SubscriptionManager()
    manager.schema = build_fraiseql_schema(query_types=[ping], subscription_resolvers=[countdown])
    app = FastAPI()

    @app.websocket("/graphql-ws")
    async def endpoint(websocket: WebSocket) -> None:
        await websocket.accept(subprotocol="graphql-transport-ws")
        connection = await manager.add_connection(
            websocket, subprotocol="graphql-transport-ws", context={}
        )
        try:
            await connection.handle()
        finally:
            await manager.remove_connection(connection.connection_id)

    return app


def test_graphql_transport_ws_streams_a_subscription() -> None:
    with (
        TestClient(_app()) as client,
        client.websocket_connect("/graphql-ws", subprotocols=["graphql-transport-ws"]) as ws,
    ):
        ws.send_json({"type": "connection_init", "payload": {}})
        assert ws.receive_json() == {"type": "connection_ack"}

        ws.send_json(
            {"id": "1", "type": "subscribe", "payload": {"query": "subscription { countdown }"}}
        )
        received = [ws.receive_json() for _ in range(4)]

    assert received == [
        {"id": "1", "type": "next", "payload": {"data": {"countdown": 3}}},
        {"id": "1", "type": "next", "payload": {"data": {"countdown": 2}}},
        {"id": "1", "type": "next", "payload": {"data": {"countdown": 1}}},
        {"id": "1", "type": "complete"},
    ]
