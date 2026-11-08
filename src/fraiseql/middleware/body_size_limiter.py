"""Request body size limiting middleware.

Protects against DoS attacks by rejecting requests that exceed
a configurable body size limit.
"""

from dataclasses import dataclass, field
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestTooLargeError(Exception):
    """Raised when request body exceeds size limit."""

    status_code: int = 413

    def __init__(self, max_size: int, actual_size: int | None = None) -> None:
        self.max_size = max_size
        self.actual_size = actual_size
        self.status_code = 413
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        max_human = _format_bytes(self.max_size)
        if self.actual_size:
            actual_human = _format_bytes(self.actual_size)
            return f"Request body too large: {actual_human} exceeds limit of {max_human}"
        return f"Request body too large: exceeds limit of {max_human}"


def _format_bytes(size: int) -> str:
    """Format bytes as human-readable string."""
    if size >= 1_048_576:
        return f"{size / 1_048_576:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} bytes"


@dataclass
class BodySizeConfig:
    """Configuration for body size limiter.

    Attributes:
        max_body_size: Maximum allowed body size in bytes. Default 1MB.
        exempt_paths: List of paths that bypass the size limit.
        exempt_methods: HTTP methods that bypass the limit.
    """

    max_body_size: int = 1_048_576  # 1MB default
    exempt_paths: list[str] = field(default_factory=list)
    exempt_methods: set[str] = field(default_factory=lambda: {"GET", "HEAD", "OPTIONS"})

    @property
    def human_readable_size(self) -> str:
        """Return max size as human-readable string."""
        return _format_bytes(self.max_body_size)


class SizeLimitedBody:
    """Wrapper that enforces body size limits while streaming.

    SECURITY: This prevents bypass attacks via chunked transfer encoding
    or missing Content-Length headers. The body is measured as it streams.
    """

    def __init__(self, body: Any, max_size: int) -> None:
        self._body = body
        self._max_size = max_size
        self._bytes_read = 0

    async def __aiter__(self):
        async for chunk in self._body:
            self._bytes_read += len(chunk)
            if self._bytes_read > self._max_size:
                raise RequestTooLargeError(
                    max_size=self._max_size,
                    actual_size=self._bytes_read,
                )
            yield chunk


class BodySizeLimiterMiddleware:
    """ASGI middleware that limits request body size.

    Rejects requests that exceed the configured maximum body size
    with HTTP 413 Payload Too Large.

    SECURITY: Enforces limits in two ways:
    1. Fast path: Check Content-Length header if present
    2. Safe path: Read the body and count the bytes received (catches chunked
       transfer and a missing or false Content-Length), stopping at the limit

    A body within the limit is passed on unchanged to the application.
    It is a plain ASGI middleware, not a ``BaseHTTPMiddleware``: replacing the
    receive channel of a ``BaseHTTPMiddleware`` request does not reach the
    application, which then sees an empty body.

    Usage:
        app = FastAPI()
        config = BodySizeConfig(max_body_size=5_000_000)  # 5MB
        app.add_middleware(BodySizeLimiterMiddleware, config=config)
    """

    def __init__(
        self,
        app: ASGIApp,
        config: BodySizeConfig | None = None,
    ) -> None:
        self.app = app
        self.config = config or BodySizeConfig()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check the body size of an HTTP request, then pass it on."""
        if (
            scope["type"] != "http"
            or scope["method"] in self.config.exempt_methods
            or scope["path"] in self.config.exempt_paths
        ):
            await self.app(scope, receive, send)
            return

        # Fast path: Check Content-Length header first (efficient)
        content_length = Headers(scope=scope).get("content-length")
        if content_length:
            try:
                size = int(content_length)
            except ValueError:
                pass
            else:
                if size > self.config.max_body_size:
                    await self._create_error_response(size)(scope, receive, send)
                    return

        # Safe path: Read and measure actual body (catches chunked transfer, missing headers)
        # This is CRITICAL for security - Content-Length can be omitted or spoofed
        chunks: list[bytes] = []
        total_size = 0
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                # Client disconnected before sending the whole body
                return
            chunk = message.get("body", b"")
            total_size += len(chunk)
            if total_size > self.config.max_body_size:
                await self._create_error_response(total_size)(scope, receive, send)
                return
            chunks.append(chunk)
            more_body = message.get("more_body", False)

        await self.app(scope, _replay_body(b"".join(chunks), receive), send)

    def _create_error_response(self, actual_size: int | None = None) -> JSONResponse:
        """Create 413 error response."""
        error = RequestTooLargeError(
            max_size=self.config.max_body_size,
            actual_size=actual_size,
        )
        return JSONResponse(
            status_code=413,
            content={
                "detail": str(error),
                "max_size": self.config.max_body_size,
                "max_size_human": self.config.human_readable_size,
            },
        )


def _replay_body(body: bytes, receive: Receive) -> Receive:
    """Receive channel that hands over ``body`` once, then defers to ``receive``."""
    body_sent = False

    async def replay() -> Message:
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replay
