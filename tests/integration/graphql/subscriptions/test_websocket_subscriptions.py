"""Tests for WebSocket subscription transport."""

import asyncio
import contextlib
import json
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from fraiseql.subscriptions.websocket import (
    ConnectionState,
    GraphQLWSMessage,
    MessageType,
    SubProtocol,
    SubscriptionManager,
    WebSocketConnection,
)

pytestmark = pytest.mark.integration


class MockWebSocket:
    """Mock WebSocket for testing."""

    def __init__(self) -> None:
        self.sent_messages = []
        self.closed = False
        self.close_code = None
        self.close_reason = None
        self._receive_queue = asyncio.Queue()

    async def send_text(self, message: str) -> None:
        """Mock sending a text frame, as Starlette's ``WebSocket.send_text``."""
        if self.closed:
            msg = "WebSocket is closed"
            raise RuntimeError(msg)
        self.sent_messages.append(json.loads(message))

    async def receive(self) -> dict[str, Any]:
        """Mock receiving a message."""
        if self.closed:
            msg = "WebSocket is closed"
            raise RuntimeError(msg)
        return await self._receive_queue.get()

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Mock closing the connection."""
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    async def accept(self, subprotocol: str | None = None) -> None:
        """Mock accepting the connection."""
        self.subprotocol = subprotocol

    def add_incoming_message(self, message: dict[str, Any]) -> None:
        """Add a message to be received."""
        self._receive_queue.put_nowait({"type": "websocket.receive", "text": json.dumps(message)})

    def add_disconnect(self) -> None:
        """Add a disconnect message."""
        self._receive_queue.put_nowait({"type": "websocket.disconnect", "code": 1000})


@pytest.mark.asyncio
class TestWebSocketConnection:
    """Test WebSocket connection handling."""

    async def test_connection_init(self) -> None:
        """Test connection initialization."""
        ws = MockWebSocket()
        conn = WebSocketConnection(ws, subprotocol=SubProtocol.GRAPHQL_WS)

        assert conn.state == ConnectionState.CONNECTING
        assert conn.subprotocol == SubProtocol.GRAPHQL_WS
        assert conn.connection_id is not None
        assert len(conn.subscriptions) == 0

    @pytest.mark.asyncio
    async def test_graphql_ws_handshake(self) -> None:
        """Test GraphQL-WS protocol handshake."""
        ws = MockWebSocket()
        conn = WebSocketConnection(ws, subprotocol=SubProtocol.GRAPHQL_WS)

        # Send connection_init
        ws.add_incoming_message(
            {"type": MessageType.CONNECTION_INIT, "payload": {"auth": "token123"}}
        )

        # Start handling
        handle_task = asyncio.create_task(conn.handle())

        # Wait for connection_ack
        await asyncio.sleep(0.1)

        assert len(ws.sent_messages) == 1
        assert ws.sent_messages[0]["type"] == MessageType.CONNECTION_ACK
        assert conn.state == ConnectionState.READY

        # Clean up
        ws.add_disconnect()
        await handle_task

    @pytest.mark.asyncio
    async def test_graphql_transport_ws_handshake(self) -> None:
        """Test GraphQL-Transport-WS protocol handshake."""
        ws = MockWebSocket()
        conn = WebSocketConnection(ws, subprotocol=SubProtocol.GRAPHQL_TRANSPORT_WS)

        # Send connection_init
        ws.add_incoming_message({"type": MessageType.CONNECTION_INIT, "payload": {}})

        # Start handling
        handle_task = asyncio.create_task(conn.handle())

        # Wait for connection_ack
        await asyncio.sleep(0.1)

        assert len(ws.sent_messages) == 1
        assert ws.sent_messages[0]["type"] == MessageType.CONNECTION_ACK
        assert conn.state == ConnectionState.READY

        # Clean up
        ws.add_disconnect()
        await handle_task

    @pytest.mark.asyncio
    async def test_subscription_flow(self) -> None:
        """Test complete subscription flow."""
        ws = MockWebSocket()
        conn = WebSocketConnection(ws, subprotocol=SubProtocol.GRAPHQL_WS)

        # Mock schema and execution
        mock_schema = Mock()
        mock_subscribe_fn = AsyncMock()

        # Create async generator for subscription
        from graphql.execution import ExecutionResult

        async def subscription_generator() -> None:
            yield ExecutionResult(data={"counter": 1})
            yield ExecutionResult(data={"counter": 2})
            yield ExecutionResult(data={"counter": 3})

        mock_subscribe_fn.return_value = subscription_generator()

        with patch("fraiseql.subscriptions.websocket.subscribe", mock_subscribe_fn):
            conn.schema = mock_schema

            # Send connection_init
            ws.add_incoming_message({"type": MessageType.CONNECTION_INIT})

            # Send subscription
            ws.add_incoming_message(
                {
                    "id": "sub1",
                    "type": MessageType.SUBSCRIBE,
                    "payload": {"query": "subscription { counter }", "variables": {}},
                }
            )

            # Start handling
            handle_task = asyncio.create_task(conn.handle())

            # Wait for messages
            await asyncio.sleep(0.2)

            # Check messages
            messages = [msg for msg in ws.sent_messages if msg.get("id") == "sub1"]

            # Filter out non-data messages
            data_messages = [
                msg for msg in messages if msg["type"] in (MessageType.NEXT, MessageType.DATA)
            ]

            assert len(data_messages) >= 3
            assert all(
                msg["type"] == MessageType.DATA for msg in data_messages
            )  # graphql-ws uses DATA
            assert data_messages[0]["payload"]["data"]["counter"] == 1
            assert data_messages[1]["payload"]["data"]["counter"] == 2
            assert data_messages[2]["payload"]["data"]["counter"] == 3

            # Clean up
            conn.state = ConnectionState.CLOSING
            handle_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await handle_task

    @pytest.mark.asyncio
    async def test_subscription_error_handling(self) -> None:
        """Test subscription error handling."""
        ws = MockWebSocket()
        conn = WebSocketConnection(ws, subprotocol=SubProtocol.GRAPHQL_WS)

        # Mock schema and execution with error
        mock_schema = Mock()
        mock_subscribe_fn = AsyncMock()
        mock_subscribe_fn.side_effect = Exception("Subscription failed")

        with patch("fraiseql.subscriptions.websocket.subscribe", mock_subscribe_fn):
            conn.schema = mock_schema

            # Initialize connection
            ws.add_incoming_message({"type": MessageType.CONNECTION_INIT})

            # Send invalid subscription
            ws.add_incoming_message(
                {
                    "id": "sub1",
                    "type": MessageType.SUBSCRIBE,
                    "payload": {"query": "subscription { invalid }", "variables": {}},
                }
            )

            # Start handling
            handle_task = asyncio.create_task(conn.handle())

            # Wait for error
            await asyncio.sleep(0.1)

            # Check error message
            error_messages = [
                msg for msg in ws.sent_messages if msg.get("type") == MessageType.ERROR
            ]
            assert len(error_messages) == 1
            assert error_messages[0]["id"] == "sub1"
            assert "Subscription failed" in str(error_messages[0]["payload"])

            # Clean up
            ws.add_disconnect()
            await handle_task

    @pytest.mark.asyncio
    async def test_ping_pong(self) -> None:
        """Test ping/pong keep-alive."""
        ws = MockWebSocket()
        conn = WebSocketConnection(ws, subprotocol=SubProtocol.GRAPHQL_WS)

        # Initialize connection
        ws.add_incoming_message({"type": MessageType.CONNECTION_INIT})

        # Send ping
        ws.add_incoming_message({"type": MessageType.PING})

        # Start handling
        handle_task = asyncio.create_task(conn.handle())

        # Wait for pong
        await asyncio.sleep(0.1)

        # Check pong response
        pong_messages = [msg for msg in ws.sent_messages if msg.get("type") == MessageType.PONG]
        assert len(pong_messages) == 1

        # Clean up
        ws.add_disconnect()
        await handle_task

    @pytest.mark.asyncio
    async def test_connection_timeout(self) -> None:
        """Test connection initialization timeout."""
        ws = MockWebSocket()
        conn = WebSocketConnection(
            ws, subprotocol=SubProtocol.GRAPHQL_WS, connection_init_timeout=0.1
        )

        # Don't send connection_init
        handle_task = asyncio.create_task(conn.handle())

        # Wait for timeout
        await asyncio.sleep(0.2)

        # Check connection was closed
        assert ws.closed
        assert ws.close_code == 4408
        assert "Connection initialisation timeout" in ws.close_reason

        with contextlib.suppress(TimeoutError):
            await handle_task


@pytest.mark.asyncio
class TestSubscriptionManager:
    """Test subscription manager."""

    async def test_manager_initialization(self) -> None:
        """Test manager initialization."""
        manager = SubscriptionManager()

        assert len(manager.connections) == 0
        assert manager.schema is None

    @pytest.mark.asyncio
    async def test_add_remove_connection(self) -> None:
        """Test adding and removing connections."""
        manager = SubscriptionManager()
        ws = MockWebSocket()

        # Add connection
        conn = await manager.add_connection(ws, subprotocol="graphql-ws")
        assert conn.connection_id in manager.connections
        assert len(manager.connections) == 1

        # Remove connection
        await manager.remove_connection(conn.connection_id)
        assert conn.connection_id not in manager.connections
        assert len(manager.connections) == 0

    @pytest.mark.asyncio
    async def test_broadcast(self) -> None:
        """Test broadcasting to multiple connections."""
        manager = SubscriptionManager()

        # Add multiple connections
        connections = []
        for _i in range(3):
            ws = MockWebSocket()
            conn = await manager.add_connection(ws, subprotocol="graphql-ws")
            conn.state = ConnectionState.READY  # Mark as ready
            connections.append((ws, conn))

        # Broadcast message
        message = GraphQLWSMessage(
            type=MessageType.NEXT,
            id="broadcast1",
            payload={"data": {"announcement": "Hello everyone!"}},
        )

        # Add subscription to each connection
        for _ws, conn in connections:
            conn.subscriptions["broadcast1"] = Mock()  # Mock subscription task

        await manager.broadcast(message, subscription_id="broadcast1")

        # Check all connections received the message
        for ws, _conn in connections:
            assert len(ws.sent_messages) == 1
            assert ws.sent_messages[0]["type"] == MessageType.NEXT
            assert ws.sent_messages[0]["payload"]["data"]["announcement"] == "Hello everyone!"

    @pytest.mark.asyncio
    async def test_connection_cleanup_on_error(self) -> None:
        """Test connection cleanup when error occurs."""
        manager = SubscriptionManager()
        ws = MockWebSocket()

        # Add connection
        conn = await manager.add_connection(ws, subprotocol="graphql-ws")
        conn_id = conn.connection_id
        conn.state = ConnectionState.READY

        # Simulate connection error
        ws.closed = True

        # Try to send message (should fail)
        with pytest.raises(RuntimeError):
            await conn.send_message(GraphQLWSMessage(type=MessageType.PING))

        # Manually remove connection (in real app, handle() would do this)
        await manager.remove_connection(conn_id)

        # Connection should be removed
        assert conn_id not in manager.connections

    @pytest.mark.asyncio
    async def test_protocol_selection(self) -> None:
        """Test WebSocket subprotocol selection."""
        manager = SubscriptionManager()

        # Test graphql-ws protocol
        ws1 = (MockWebSocket(),)
        conn1 = await manager.add_connection(ws1, subprotocol="graphql-ws")
        assert conn1.subprotocol == SubProtocol.GRAPHQL_WS

        # Test graphql-transport-ws protocol
        ws2 = (MockWebSocket(),)
        conn2 = await manager.add_connection(ws2, subprotocol="graphql-transport-ws")
        assert conn2.subprotocol == SubProtocol.GRAPHQL_TRANSPORT_WS

        # Test no protocol (default)
        ws3 = (MockWebSocket(),)
        conn3 = await manager.add_connection(ws3, subprotocol=None)
        assert conn3.subprotocol == SubProtocol.GRAPHQL_WS

    @pytest.mark.asyncio
    async def test_concurrent_subscriptions(self) -> None:
        """Test handling multiple concurrent subscriptions."""
        manager = SubscriptionManager()
        ws = MockWebSocket()

        # Add connection
        conn = await manager.add_connection(ws, subprotocol="graphql-ws")
        conn.state = ConnectionState.READY

        # Mock schema
        mock_schema = Mock()
        conn.schema = mock_schema

        # Create multiple subscription tasks
        subscription_ids = ["sub1", "sub2", "sub3"]

        from graphql.execution import ExecutionResult

        for sub_id in subscription_ids:

            async def sub_generator(sub_id=sub_id):  # Capture sub_id
                for i in range(3):
                    yield ExecutionResult(data={sub_id: i})
                    await asyncio.sleep(0.01)

            task = asyncio.create_task(conn._handle_subscription_generator(sub_id, sub_generator()))
            conn.subscriptions[sub_id] = task

        # Wait for subscriptions to complete
        await asyncio.sleep(0.1)

        # Check messages were sent for each subscription
        for sub_id in subscription_ids:
            sub_messages = [msg for msg in ws.sent_messages if msg.get("id") == sub_id]
            assert len(sub_messages) >= 3
            # graphql-ws uses DATA instead of NEXT
            assert all(msg["type"] == MessageType.DATA for msg in sub_messages[:3])


class TestGraphQLWSMessage:
    """Test GraphQL WS message handling."""

    def test_message_serialization(self) -> None:
        """Test message serialization."""
        msg = GraphQLWSMessage(
            type=MessageType.NEXT, id="sub1", payload={"data": {"hello": "world"}}
        )

        serialized = msg.to_dict()
        assert serialized["type"] == "next"
        assert serialized["id"] == "sub1"
        assert serialized["payload"]["data"]["hello"] == "world"

    def test_message_deserialization(self) -> None:
        """Test message deserialization."""
        data = {
            "type": "subscribe",
            "id": "sub1",
            "payload": {"query": "subscription { test }", "variables": {"id": 123}},
        }

        msg = GraphQLWSMessage.from_dict(data)
        assert msg.type == MessageType.SUBSCRIBE
        assert msg.id == "sub1"
        assert msg.payload["query"] == "subscription { test }"
        assert msg.payload["variables"]["id"] == 123

    def test_invalid_message_type(self) -> None:
        """Test invalid message type handling."""
        # Invalid message types are now accepted but kept as-is
        msg = GraphQLWSMessage.from_dict({"type": "invalid_type", "id": "sub1"})
        assert msg.type == "invalid_type"
        assert msg.id == "sub1"
