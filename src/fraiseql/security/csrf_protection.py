"""CSRF protection middleware for FraiseQL applications."""

import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from graphql import GraphQLError, OperationDefinitionNode, parse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class CSRFTokenStorage(Enum):
    """CSRF token storage methods."""

    COOKIE = "cookie"
    SESSION = "session"
    HEADER = "header"


@dataclass
class CSRFConfig:
    """CSRF protection configuration."""

    secret_key: str
    token_name: str = "csrf_token"
    header_name: str = "X-CSRF-Token"
    cookie_name: str = "csrf_token"
    cookie_secure: bool = True
    cookie_httponly: bool = True
    cookie_samesite: str = "strict"
    token_timeout: int = 3600  # 1 hour
    require_for_mutations: bool = True
    require_for_subscriptions: bool = False
    storage: CSRFTokenStorage = CSRFTokenStorage.COOKIE
    exempt_paths: set[str] = None
    check_referrer: bool = True
    trusted_origins: set[str] = None


class CSRFTokenGenerator:
    """Generates and validates CSRF tokens."""

    def __init__(self, secret_key: str, timeout: int = 3600) -> None:
        self.secret_key = secret_key.encode() if isinstance(secret_key, str) else secret_key
        self.timeout = timeout

    def generate_token(self, session_id: str | None = None) -> str:
        """Generate a CSRF token."""
        # Create a random token
        random_token = secrets.token_urlsafe(32)

        # Add timestamp
        timestamp = str(int(time.time()))

        # Create payload
        payload = f"{random_token}:{timestamp}"
        if session_id:
            payload = f"{session_id}:{payload}"

        # Create signature
        signature = hmac.new(
            self.secret_key,
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        # Return token as base64
        token_data = f"{payload}:{signature}"
        return secrets.base64.urlsafe_b64encode(token_data.encode()).decode()

    def validate_token(self, token: str, session_id: str | None = None) -> bool:
        """Validate a CSRF token."""
        try:
            # Decode token
            token_data = secrets.base64.urlsafe_b64decode(token.encode()).decode()

            # Split components
            parts = token_data.split(":")
            if len(parts) < 3:
                return False

            if session_id and len(parts) == 4:
                # Token includes session ID
                stored_session, random_token, timestamp, signature = parts
                if stored_session != session_id:
                    return False
                payload = f"{stored_session}:{random_token}:{timestamp}"
            else:
                # Token without session ID
                random_token, timestamp, signature = parts[-3:]
                if session_id:
                    payload = f"{session_id}:{random_token}:{timestamp}"
                else:
                    payload = f"{random_token}:{timestamp}"

            # Verify signature
            expected_signature = hmac.new(
                self.secret_key,
                payload.encode(),
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_signature):
                return False

            # Check timeout
            token_time = int(timestamp)
            return time.time() - token_time <= self.timeout

        except (ValueError, TypeError, UnicodeDecodeError):
            return False


def _origin_of(url: str) -> str:
    """Return the ``scheme://host[:port]`` origin of a URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _lookup_persisted_query(sha256_hash: str) -> str | None:
    """Return the stored document for an APQ hash, as the GraphQL router finds it."""
    from fraiseql.fastapi.dependencies import get_fraiseql_config
    from fraiseql.storage.apq_store import get_persisted_query

    config = get_fraiseql_config()
    if config is not None:
        from fraiseql.middleware.apq_caching import get_apq_backend

        document = get_apq_backend(config).get_persisted_query(sha256_hash)
        if document:
            return document
    return get_persisted_query(sha256_hash)


class GraphQLCSRFValidator:
    """CSRF validation specifically for GraphQL operations."""

    def __init__(self, config: CSRFConfig) -> None:
        self.config = config
        self.token_generator = CSRFTokenGenerator(
            config.secret_key,
            config.token_timeout,
        )

    def _extract_operation_type(self, request_body: Any) -> str | None:
        """Extract operation type from GraphQL request.

        The document is parsed, so comments and fragments before the operation don't
        hide it. A document with any mutation is a mutation, whichever operation
        ``operationName`` selects; then subscription, then query. A batched body
        (a list) takes the strongest type of its entries.

        Returns:
            The operation type, ``"unknown"`` for a document that can't be parsed or
            looked up, or None when the request carries no document to execute.
        """
        if isinstance(request_body, list):
            types = {self._extract_operation_type(entry) for entry in request_body}
            for operation_type in ("unknown", "mutation", "subscription", "query"):
                if operation_type in types:
                    return operation_type
            return None
        if not isinstance(request_body, dict):
            return None

        query = request_body.get("query")
        if not query:
            try:
                query = self._persisted_document(request_body)
            except Exception:
                logger.warning("CSRF check: could not look up persisted query", exc_info=True)
                return "unknown"
        if not query:
            return None
        if not isinstance(query, str):
            return "unknown"

        try:
            document = parse(query, no_location=True)
        except (GraphQLError, TypeError):
            return "unknown"

        operations = {
            definition.operation.value
            for definition in document.definitions
            if isinstance(definition, OperationDefinitionNode)
        }
        for operation_type in ("mutation", "subscription", "query"):
            if operation_type in operations:
                return operation_type
        return None

    def _persisted_document(self, request_body: dict) -> str | None:
        """Return the stored document an APQ hash-only request will execute."""
        extensions = request_body.get("extensions")
        if not isinstance(extensions, dict):
            return None
        persisted = extensions.get("persistedQuery")
        if not isinstance(persisted, dict):
            return None
        sha256_hash = persisted.get("sha256Hash")
        if not isinstance(sha256_hash, str) or not sha256_hash.strip():
            return None
        return _lookup_persisted_query(sha256_hash)

    def _requires_csrf_protection(self, operation_type: str) -> bool:
        """Check if operation type requires CSRF protection."""
        if operation_type == "mutation":
            return self.config.require_for_mutations
        if operation_type == "subscription":
            return self.config.require_for_subscriptions
        if operation_type == "unknown":
            return self.config.require_for_mutations or self.config.require_for_subscriptions
        return False

    def _validate_origin(self, request: Request) -> JSONResponse | None:
        """Reject a request whose Origin (or, without one, Referer) isn't trusted.

        Applies when ``check_referrer`` is on and ``trusted_origins`` is set. A request
        with neither header passes: browsers send ``Origin`` on cross-origin POSTs, and
        clients outside a browser may send neither.
        """
        if not self.config.check_referrer or not self.config.trusted_origins:
            return None

        origin = request.headers.get("Origin")
        if origin is None:
            referrer = request.headers.get("Referer")
            if not referrer:
                return None
            origin = _origin_of(referrer)

        if origin not in self.config.trusted_origins:
            return self._create_csrf_error_response("Untrusted origin")
        return None

    def _get_csrf_token_from_request(self, request: Request) -> str | None:
        """Extract the CSRF token the client sent.

        The token counts only in the header or in the GraphQL variables. The
        ``csrf_token`` cookie doesn't: the browser attaches it to every request.
        """
        # Try header first
        token = request.headers.get(self.config.header_name)
        if token:
            return token

        # Try body for GraphQL variables
        if hasattr(request, "_csrf_token_from_body"):
            return request._csrf_token_from_body

        return None

    def _get_session_id(self, request: Request) -> str | None:
        """Get session ID from request."""
        # Try to get from request state (set by session middleware)
        session_id = getattr(request.state, "session_id", None)
        if session_id:
            return session_id

        # Try to get from session cookie
        return request.cookies.get("session_id")

    async def validate_graphql_csrf(
        self,
        request: Request,
        request_body: dict,
    ) -> JSONResponse | None:
        """Validate CSRF for GraphQL request."""
        operation_type = self._extract_operation_type(request_body)

        if not operation_type or not self._requires_csrf_protection(operation_type):
            return None

        origin_error = self._validate_origin(request)
        if origin_error:
            return origin_error

        # Extract CSRF token from GraphQL variables if present
        variables = request_body.get("variables") if isinstance(request_body, dict) else None
        if isinstance(variables, dict):
            csrf_token_from_vars = variables.get(self.config.token_name)
            if isinstance(csrf_token_from_vars, str) and csrf_token_from_vars:
                request._csrf_token_from_body = csrf_token_from_vars

        # Get CSRF token
        csrf_token = self._get_csrf_token_from_request(request)
        if not csrf_token:
            return self._create_csrf_error_response(
                "CSRF token is required for mutations",
            )

        # Validate token
        session_id = self._get_session_id(request)
        if not self.token_generator.validate_token(csrf_token, session_id):
            return self._create_csrf_error_response(
                "Invalid or expired CSRF token",
            )

        return None

    async def validate_request(
        self,
        request: Request,
        request_body: dict | None = None,
    ) -> bool:
        """Validate CSRF for a request and return boolean result.

        This is a simplified interface for testing and basic validation.

        Args:
            request: The HTTP request
            request_body: Optional GraphQL request body

        Returns:
            True if validation passes, False if it fails
        """
        # If no request body provided, assume this is a simple request validation
        if request_body is None:
            # For non-GraphQL requests, just validate the token exists and is valid
            csrf_token = self._get_csrf_token_from_request(request)
            if not csrf_token:
                return False

            session_id = self._get_session_id(request)
            return self.token_generator.validate_token(csrf_token, session_id)

        # For GraphQL requests, use the full validation logic
        result = await self.validate_graphql_csrf(request, request_body)
        return result is None  # None means success, JSONResponse means error

    def _create_csrf_error_response(self, message: str) -> JSONResponse:
        """Create CSRF error response for GraphQL."""
        return JSONResponse(
            status_code=403,
            content={
                "errors": [
                    {
                        "message": message,
                        "extensions": {
                            "code": "CSRF_PROTECTION_FAILED",
                        },
                    },
                ],
            },
        )


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for CSRF protection."""

    def __init__(
        self,
        app: FastAPI,
        config: CSRFConfig,
        graphql_path: str = "/graphql",
    ) -> None:
        super().__init__(app)
        self.config = config
        self.graphql_path = graphql_path
        self.token_generator = CSRFTokenGenerator(
            config.secret_key,
            config.token_timeout,
        )
        self.graphql_validator = GraphQLCSRFValidator(config)

        # Initialize exempt paths
        if self.config.exempt_paths is None:
            self.config.exempt_paths = {
                "/health",
                "/ready",
                "/metrics",
                "/docs",
                "/openapi.json",
                "/redoc",
            }

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Apply CSRF protection to requests."""
        # Skip exempt paths
        if request.url.path in self.config.exempt_paths:
            return await call_next(request)

        # A GraphQL GET can carry a mutation in its query string
        if request.url.path == self.graphql_path and request.method == "GET":
            csrf_error = await self._validate_graphql_get(request)
            if csrf_error:
                return csrf_error

        # Skip for safe methods (GET, HEAD, OPTIONS)
        if request.method in ["GET", "HEAD", "OPTIONS"]:
            response = await call_next(request)
            # Add CSRF token to response for future use
            await self._add_csrf_token_to_response(request, response)
            return response

        # Special handling for GraphQL
        if request.url.path == self.graphql_path and request.method == "POST":
            return await self._handle_graphql_request(request, call_next)

        # Check CSRF for other POST/PUT/DELETE requests
        if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
            csrf_error = await self._validate_csrf(request)
            if csrf_error:
                return csrf_error

        response = await call_next(request)
        await self._add_csrf_token_to_response(request, response)
        return response

    async def _handle_graphql_request(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Handle GraphQL-specific CSRF protection."""
        try:
            # Parse request body
            body = await request.body()
            request_body = json.loads(body) if body else {}

            # Restore body for downstream processing
            async def receive() -> dict[str, Any]:
                return {"type": "http.request", "body": body}

            request._receive = receive

            # Validate CSRF for GraphQL
            csrf_error = await self.graphql_validator.validate_graphql_csrf(
                request,
                request_body,
            )
            if csrf_error:
                return csrf_error

        except (json.JSONDecodeError, UnicodeDecodeError):
            # If we can't parse the body, apply general CSRF validation
            csrf_error = await self._validate_csrf(request)
            if csrf_error:
                return csrf_error

        response = await call_next(request)
        await self._add_csrf_token_to_response(request, response)
        return response

    async def _validate_graphql_get(self, request: Request) -> JSONResponse | None:
        """Validate CSRF for a GraphQL operation sent as GET query parameters."""
        query = request.query_params.get("query")
        if not query:
            return None
        request_body: dict[str, Any] = {"query": query}
        variables = request.query_params.get("variables")
        if variables:
            try:
                request_body["variables"] = json.loads(variables)
            except json.JSONDecodeError:
                pass
        return await self.graphql_validator.validate_graphql_csrf(request, request_body)

    async def _validate_csrf(self, request: Request) -> JSONResponse | None:
        """Validate CSRF token for non-GraphQL requests."""
        # Check referrer if enabled
        if self.config.check_referrer:
            referrer_error = self._validate_referrer(request)
            if referrer_error:
                return referrer_error

        # Get CSRF token
        csrf_token = self._get_csrf_token(request)
        if not csrf_token:
            return self._create_error_response("CSRF token is required")

        # Validate token
        session_id = self._get_session_id(request)
        if not self.token_generator.validate_token(csrf_token, session_id):
            return self._create_error_response("Invalid or expired CSRF token")

        return None

    def _validate_referrer(self, request: Request) -> JSONResponse | None:
        """Validate request referrer."""
        referrer = request.headers.get("Referer")
        if not referrer:
            return self._create_error_response("Missing referrer header")

        # Check if referrer is from trusted origin
        if self.config.trusted_origins:
            referrer_origin = self._extract_origin(referrer)
            if referrer_origin not in self.config.trusted_origins:
                return self._create_error_response("Untrusted referrer")

        return None

    def _extract_origin(self, url: str) -> str:
        """Extract origin from URL."""
        return _origin_of(url)

    def _get_csrf_token(self, request: Request) -> str | None:
        """Get CSRF token from request.

        Only the header counts. The ``csrf_token`` cookie doesn't: the browser
        attaches it to every request.
        """
        # Note: We can't await form() in a sync method, so we skip form data checking
        return request.headers.get(self.config.header_name)

    def _get_session_id(self, request: Request) -> str | None:
        """Get session ID from request."""
        session_id = getattr(request.state, "session_id", None)
        if session_id:
            return session_id

        return request.cookies.get("session_id")

    async def _add_csrf_token_to_response(self, request: Request, response: Response) -> None:
        """Add CSRF token to response."""
        if self.config.storage == CSRFTokenStorage.COOKIE:
            # Generate new token
            session_id = self._get_session_id(request)
            csrf_token = self.token_generator.generate_token(session_id)

            # Set cookie
            response.set_cookie(
                key=self.config.cookie_name,
                value=csrf_token,
                secure=self.config.cookie_secure,
                httponly=self.config.cookie_httponly,
                samesite=self.config.cookie_samesite,
                max_age=self.config.token_timeout,
            )

    def _create_error_response(self, message: str) -> JSONResponse:
        """Create CSRF error response."""
        return JSONResponse(
            status_code=403,
            content={
                "error": "CSRF Protection Failed",
                "message": message,
            },
        )


# CSRF token endpoint for SPA applications
class CSRFTokenEndpoint:
    """Endpoint to provide CSRF tokens for SPA applications."""

    def __init__(self, config: CSRFConfig) -> None:
        self.config = config
        self.token_generator = CSRFTokenGenerator(
            config.secret_key,
            config.token_timeout,
        )

    async def get_csrf_token(self, request: Request) -> dict:
        """Get CSRF token for the current session."""
        session_id = self._get_session_id(request)
        csrf_token = self.token_generator.generate_token(session_id)

        return {
            "csrf_token": csrf_token,
            "token_name": self.config.token_name,
            "header_name": self.config.header_name,
        }

    def _get_session_id(self, request: Request) -> str | None:
        """Get session ID from request."""
        session_id = getattr(request.state, "session_id", None)
        if session_id:
            return session_id

        return request.cookies.get("session_id")


# Convenience functions


def setup_csrf_protection(
    app: FastAPI,
    secret_key: str,
    config: CSRFConfig | None = None,
    graphql_path: str = "/graphql",
) -> CSRFProtectionMiddleware:
    """Set up CSRF protection middleware with sensible defaults."""
    if config is None:
        config = CSRFConfig(secret_key=secret_key)

    middleware = CSRFProtectionMiddleware(
        app=app,
        config=config,
        graphql_path=graphql_path,
    )

    app.add_middleware(
        CSRFProtectionMiddleware,
        config=config,
        graphql_path=graphql_path,
    )

    # Add CSRF token endpoint
    csrf_endpoint = CSRFTokenEndpoint(config)

    @app.get("/csrf-token")
    async def get_csrf_token(request: Request) -> dict[str, Any]:
        """Get CSRF token for SPA applications."""
        return await csrf_endpoint.get_csrf_token(request)

    return middleware


def create_production_csrf_config(
    secret_key: str,
    trusted_origins: set[str],
) -> CSRFConfig:
    """Create production-ready CSRF configuration."""
    return CSRFConfig(
        secret_key=secret_key,
        cookie_secure=True,
        cookie_httponly=True,
        cookie_samesite="strict",
        token_timeout=3600,
        require_for_mutations=True,
        require_for_subscriptions=False,
        storage=CSRFTokenStorage.COOKIE,
        check_referrer=True,
        trusted_origins=trusted_origins,
        exempt_paths={
            "/health",
            "/ready",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc",
        },
    )


def create_development_csrf_config(secret_key: str) -> CSRFConfig:
    """Create development-friendly CSRF configuration."""
    return CSRFConfig(
        secret_key=secret_key,
        cookie_secure=False,  # Allow HTTP in development
        cookie_httponly=True,
        cookie_samesite="lax",  # More permissive for development
        token_timeout=3600,
        require_for_mutations=True,
        require_for_subscriptions=False,
        storage=CSRFTokenStorage.COOKIE,
        check_referrer=False,  # Disable referrer check in development
        trusted_origins={"http://localhost:3000", "http://localhost:8080"},
        exempt_paths={
            "/health",
            "/ready",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc",
        },
    )
