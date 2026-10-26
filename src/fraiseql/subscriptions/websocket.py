"""WebSocket connection handling for GraphQL subscriptions."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from graphql import GraphQLSchema, parse, subscribe
from graphql.execution import ExecutionResult

from fraiseql.core.exceptions import WebSocketError
from fraiseql.fastapi.json_encoder import clean_unset_values
from fraiseql.gql.query_limits import QueryLimits

if TYPE_CHECKING:
    from fraiseql.fastapi.config import FraiseQLConfig

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """WebSocket connection states."""

    CONNECTING = "connecting"
    READY = "ready"
    CLOSING = "closing"
    CLOSED = "closed"


class SubProtocol(Enum):
    """Supported WebSocket subprotocols."""

    GRAPHQL_WS = "graphql-ws"  # Legacy Apollo protocol
    GRAPHQL_TRANSPORT_WS = "graphql-transport-ws"  # New protocol


class MessageType:
    """GraphQL WebSocket message types."""

    # Client -> Server
    CONNECTION_INIT = "connection_init"
    CONNECTION_TERMINATE = "connection_terminate"  # Legacy
    SUBSCRIBE = "subscribe"
    COMPLETE = "complete"
    PING = "ping"

    # Server -> Client
    CONNECTION_ACK = "connection_ack"
    CONNECTION_ERROR = "connection_error"
    NEXT = "next"  # graphql-transport-ws
    DATA = "data"  # graphql-ws (legacy)
    ERROR = "error"
    COMPLETE_SERVER = "complete"
    PONG = "pong"

    # Aliases for compatibility
    START = "start"  # Legacy alias for subscribe
    STOP = "stop"  # Legacy alias for complete


@dataclass
class GraphQLWSMessage:
    """GraphQL WebSocket message."""

    type: str
    id: str | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for sending."""
        result = {"type": self.type}
        if self.id is not None:
            result["id"] = self.id
        if self.payload is not None:
            result["payload"] = self.payload
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphQLWSMessage":
        """Create from received dictionary."""
        msg_type = data.get("type")
        if not msg_type:
            msg = "Message type is required"
            raise ValueError(msg)

        # Handle legacy message types
        if msg_type == MessageType.START:
            msg_type = MessageType.SUBSCRIBE
        elif msg_type == MessageType.STOP:
            msg_type = MessageType.COMPLETE

        return cls(type=msg_type, id=data.get("id"), payload=data.get("payload"))


class WebSocketConnection:
    """Manages a single WebSocket connection."""

    def __init__(
        self,
        websocket: Any,
        connection_id: str | None = None,
        subprotocol: SubProtocol = SubProtocol.GRAPHQL_WS,
        connection_init_timeout: float = 10.0,
        keep_alive_interval: float = 30.0,
        query_limits: QueryLimits | None = None,
    ) -> None:
        """Set up a connection; ``query_limits`` bounds each subscription's depth/complexity."""
        self.websocket = websocket
        self.connection_id = connection_id or str(uuid4())
        self.subprotocol = subprotocol
        self.connection_init_timeout = connection_init_timeout
        self.keep_alive_interval = keep_alive_interval

        self.state = ConnectionState.CONNECTING
        self.schema: GraphQLSchema | None = None
        self.context: dict[str, Any] = {}
        self.subscriptions: dict[str, asyncio.Task] = {}
        self.connection_params: dict[str, Any] | None = None
        self.query_limits = query_limits
        self.initialized_at: datetime | None = None

        self._keep_alive_task: asyncio.Task | None = None
        self._message_queue: asyncio.Queue = asyncio.Queue()

    async def handle(self) -> None:
        """Handle the WebSocket connection lifecycle."""
        try:
            # Wait for connection_init
            await self._wait_for_connection_init()

            # Start keep-alive if needed
            if self.keep_alive_interval > 0:
                self._keep_alive_task = asyncio.create_task(self._keep_alive())

            # Main message loop
            await self._message_loop()

        except asyncio.CancelledError:
            logger.info("Connection %s cancelled", self.connection_id)
        except Exception as e:
            logger.exception("Connection %s error", self.connection_id)
            await self._send_error(None, str(e))
        finally:
            await self._cleanup()

    async def _wait_for_connection_init(self) -> None:
        """Wait for connection_init message."""
        timeout = self.connection_init_timeout
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            try:
                # Wait for message with timeout
                remaining = deadline - asyncio.get_event_loop().time()
                message = await asyncio.wait_for(self._receive_message(), timeout=remaining)

                if message.type == MessageType.CONNECTION_INIT:
                    self.connection_params = message.payload or {}
                    self.initialized_at = datetime.now(UTC)

                    # Send connection_ack
                    await self.send_message(GraphQLWSMessage(type=MessageType.CONNECTION_ACK))

                    self.state = ConnectionState.READY
                    logger.info("Connection %s initialized", self.connection_id)
                    return
                # Unexpected message before init
                await self._close(
                    code=4400,
                    reason="Connection initialisation must be first message",
                )
                return

            except TimeoutError:
                await self._close(code=4408, reason="Connection initialisation timeout")
                raise

    async def _message_loop(self) -> None:
        """Main message processing loop."""
        while self.state == ConnectionState.READY:
            try:
                message = await self._receive_message()
                await self._handle_message(message)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if "disconnect" in str(e).lower():
                    # Normal disconnect
                    break
                logger.exception("Message handling error")
                await self._send_error(None, str(e))

    async def _receive_message(self) -> GraphQLWSMessage:
        """Receive and parse a message."""
        raw_message = await self.websocket.receive()

        # Handle disconnect
        if raw_message.get("type") == "websocket.disconnect":
            self.state = ConnectionState.CLOSING
            msg = "Client disconnected"
            raise WebSocketError(msg)

        # Parse message
        text = raw_message.get("text", "")
        try:
            data = json.loads(text)
            return GraphQLWSMessage.from_dict(data)
        except (json.JSONDecodeError, ValueError) as e:
            msg = f"Invalid message format: {e}"
            raise WebSocketError(msg) from e

    async def send_message(self, message: GraphQLWSMessage) -> None:
        """Send a message to the client."""
        if self.state not in (ConnectionState.READY, ConnectionState.CONNECTING):
            return

        try:
            await self.websocket.send(json.dumps(message.to_dict()))
        except Exception:
            logger.exception("Failed to send message")
            self.state = ConnectionState.CLOSING
            raise

    async def _handle_message(self, message: GraphQLWSMessage) -> None:
        """Handle incoming message based on type."""
        handlers = {
            MessageType.SUBSCRIBE: self._handle_subscribe,
            MessageType.COMPLETE: self._handle_complete,
            MessageType.CONNECTION_TERMINATE: self._handle_terminate,
            MessageType.PING: self._handle_ping,
        }

        handler = handlers.get(message.type)
        if handler:
            await handler(message)
        else:
            logger.warning("Unknown message type: %s", message.type)

    async def _handle_subscribe(self, message: GraphQLWSMessage) -> None:
        """Handle subscription request."""
        if not message.id:
            await self._send_error(None, "Subscription ID is required")
            return

        if message.id in self.subscriptions:
            await self._send_error(message.id, f"Subscription {message.id} already exists")
            return

        try:
            # Parse query
            query = message.payload.get("query", "")
            variables = message.payload.get("variables", {})
            operation_name = message.payload.get("operationName")

            # Depth and complexity limits, before execution (introspection is not counted).
            if self.query_limits is not None and query and self.schema is not None:
                limit_error = self.query_limits.check(self.schema, query, operation_name, variables)
                if limit_error is not None:
                    await self._send_error(message.id, limit_error)
                    return

            document = parse(query)

            # Execute subscription
            result = await subscribe(
                self.schema,
                document,
                root_value=None,
                context_value=self.context,
                variable_values=variables,
                operation_name=operation_name,
            )

            if isinstance(result, AsyncIterator):
                # Start subscription task
                task = asyncio.create_task(self._handle_subscription_generator(message.id, result))
                self.subscriptions[message.id] = task
            else:
                # Single error result
                await self._send_error(message.id, result)

        except Exception as e:
            logger.exception("Subscription error")
            await self._send_error(message.id, str(e))

    async def _handle_subscription_generator(
        self,
        subscription_id: str,
        result_iterator: AsyncIterator[ExecutionResult],
    ) -> None:
        """Handle subscription result generator."""
        try:
            async for result in result_iterator:
                if result.errors:
                    await self._send_error(subscription_id, result.errors)
                else:
                    # Send data
                    msg_type = (
                        MessageType.NEXT
                        if self.subprotocol == SubProtocol.GRAPHQL_TRANSPORT_WS
                        else MessageType.DATA
                    )

                    await self.send_message(
                        GraphQLWSMessage(
                            type=msg_type,
                            id=subscription_id,
                            payload={"data": result.data},
                        ),
                    )

            # Send complete
            await self.send_message(
                GraphQLWSMessage(type=MessageType.COMPLETE_SERVER, id=subscription_id),
            )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Subscription %s error", subscription_id)
            await self._send_error(subscription_id, str(e))
        finally:
            # Clean up
            self.subscriptions.pop(subscription_id, None)

    async def _handle_complete(self, message: GraphQLWSMessage) -> None:
        """Handle subscription completion request."""
        if message.id and message.id in self.subscriptions:
            task = self.subscriptions.pop(message.id)
            task.cancel()
            logger.info("Subscription %s completed", message.id)

    async def _handle_terminate(self, message: GraphQLWSMessage) -> None:
        """Handle connection termination request."""
        self.state = ConnectionState.CLOSING
        await self._close(code=1000, reason="Client requested termination")

    async def _handle_ping(self, message: GraphQLWSMessage) -> None:
        """Handle ping message."""
        await self.send_message(GraphQLWSMessage(type=MessageType.PONG, payload=message.payload))

    async def _send_error(self, subscription_id: str | None, error: Any) -> None:
        """Send error message."""
        if isinstance(error, str):
            payload = {"errors": [{"message": error}]}
        elif isinstance(error, list):
            # List of GraphQL errors
            payload = {
                "errors": [
                    {
                        "message": e.message,
                        "extensions": (
                            clean_unset_values(e.extensions)
                            if hasattr(e, "extensions") and e.extensions
                            else {}
                        ),
                    }
                    for e in error
                ],
            }
        else:
            # Single error or other type
            payload = (
                clean_unset_values(error)
                if isinstance(error, dict)
                else {"errors": [{"message": str(error)}]}
            )

        await self.send_message(
            GraphQLWSMessage(type=MessageType.ERROR, id=subscription_id, payload=payload),
        )

    async def _keep_alive(self) -> None:
        """Send periodic keep-alive pings."""
        while self.state == ConnectionState.READY:
            try:
                await asyncio.sleep(self.keep_alive_interval)

                # Send ping
                await self.send_message(
                    GraphQLWSMessage(
                        type=MessageType.PING,
                        payload={"timestamp": datetime.now(UTC).isoformat()},
                    ),
                )

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Keep-alive error")
                break

    async def _close(self, code: int = 1000, reason: str = "") -> None:
        """Close the WebSocket connection."""
        if self.state == ConnectionState.CLOSED:
            return

        self.state = ConnectionState.CLOSING

        try:
            await self.websocket.close(code=code, reason=reason)
        except Exception:
            logger.exception("Error closing WebSocket")

        self.state = ConnectionState.CLOSED

    async def _cleanup(self) -> None:
        """Clean up resources."""
        # Cancel keep-alive
        if self._keep_alive_task:
            self._keep_alive_task.cancel()

        # Cancel all subscriptions
        for task in self.subscriptions.values():
            task.cancel()

        # Wait for cancellations
        if self.subscriptions:
            await asyncio.gather(*self.subscriptions.values(), return_exceptions=True)

        self.subscriptions.clear()
        self.state = ConnectionState.CLOSED

        logger.info("Connection %s cleaned up", self.connection_id)


class SubscriptionManager:
    """Manages all WebSocket subscription connections."""

    def __init__(
        self,
        *,
        config: "FraiseQLConfig | None" = None,
        query_limits: QueryLimits | None = None,
    ) -> None:
        """Set up the manager.

        Args:
            config: Optional ``FraiseQLConfig`` whose ``max_query_depth`` and
                ``complexity_*`` settings limit each subscription, as in the HTTP router.
            query_limits: Explicit limits; they take precedence over ``config``.
                With neither, subscriptions are not limited.
        """
        self.connections: dict[str, WebSocketConnection] = {}
        self.schema: GraphQLSchema | None = None
        if query_limits is None and config is not None:
            query_limits = QueryLimits.from_config(config)
        self.query_limits = query_limits
        self._lock = asyncio.Lock()

    async def add_connection(
        self,
        websocket: Any,
        subprotocol: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> WebSocketConnection:
        """Add a new WebSocket connection."""
        # Determine subprotocol
        if subprotocol == "graphql-transport-ws":
            protocol = SubProtocol.GRAPHQL_TRANSPORT_WS
        else:
            protocol = SubProtocol.GRAPHQL_WS

        # Create connection
        connection = WebSocketConnection(
            websocket=websocket, subprotocol=protocol, query_limits=self.query_limits
        )

        # Set schema and context
        connection.schema = self.schema
        connection.context = context or {}

        # Register connection
        async with self._lock:
            self.connections[connection.connection_id] = connection

        logger.info("Added connection %s", connection.connection_id)
        return connection

    async def remove_connection(self, connection_id: str) -> None:
        """Remove a connection."""
        async with self._lock:
            connection = self.connections.pop(connection_id, None)

        if connection:
            await connection._cleanup()
            logger.info("Removed connection %s", connection_id)

    async def broadcast(
        self,
        message: GraphQLWSMessage,
        subscription_id: str | None = None,
        filter_fn: Any | None = None,
    ) -> None:
        """Broadcast message to all connections."""
        # Get active connections
        async with self._lock:
            connections = list(self.connections.values())

        # Send to each connection
        tasks = []
        for conn in connections:
            if conn.state != ConnectionState.READY:
                continue

            if filter_fn and not filter_fn(conn):
                continue

            if subscription_id and subscription_id not in conn.subscriptions:
                continue

            tasks.append(conn.send_message(message))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close_all(self) -> None:
        """Close all connections."""
        async with self._lock:
            connections = list(self.connections.values())
            self.connections.clear()

        # Close all connections
        tasks = [conn._close() for conn in connections]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("Closed all connections")
