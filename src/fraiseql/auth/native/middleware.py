"""Security middleware for native authentication."""

import hashlib
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any, Optional

from fastapi import FastAPI, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from fraiseql.security.client_ip import TrustedProxies, get_client_ip


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to responses.

    Adds essential security headers to protect against common attacks:
    - X-Content-Type-Options: Prevent MIME sniffing
    - X-Frame-Options: Prevent clickjacking
    - X-XSS-Protection: XSS protection for older browsers
    - Strict-Transport-Security: Force HTTPS
    - Content-Security-Policy: Prevent various injection attacks
    """

    def __init__(
        self,
        app: FastAPI,
        hsts_max_age: int = 31536000,  # 1 year
        include_subdomains: bool = True,
        csp_policy: Optional[str] = None,
        frame_options: str = "DENY",
        content_type_options: str = "nosniff",
        referrer_policy: str = "strict-origin-when-cross-origin",
        permissions_policy: Optional[str] = None,
    ) -> None:
        super().__init__(app)
        self.hsts_max_age = hsts_max_age
        self.include_subdomains = include_subdomains
        self.csp_policy = csp_policy or (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; "
            "img-src 'self' data: https:; "
            "connect-src 'self';"
        )

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Process request and add security headers to response.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware in the chain

        Returns:
            Response with security headers added
        """
        response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = self.csp_policy

        # Add HSTS header for HTTPS requests
        if request.url.scheme == "https":
            hsts_header = f"max-age={self.hsts_max_age}"
            if self.include_subdomains:
                hsts_header += "; includeSubDomains"
            response.headers["Strict-Transport-Security"] = hsts_header

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiting middleware.

    This is a basic rate limiter suitable for single-instance deployments.
    For production multi-instance deployments, consider Redis-based rate limiting.
    """

    def __init__(
        self,
        app: FastAPI,
        requests_per_minute: int = 60,
        burst_requests: int = 10,
        auth_requests_per_minute: int = 5,  # Stricter limit for auth endpoints
        burst_auth_requests: int = 2,
        redis_client: Any = None,
        redis_url: Optional[str] = None,
        redis_ttl: int = 3600,
        trusted_proxies: list[str] | str | None = None,
    ) -> None:
        super().__init__(app)
        # The socket peer is the client unless it is one of these proxies, whose
        # X-Forwarded-For is then believed (see fraiseql.security.client_ip).
        self.trusted_proxies = TrustedProxies.coerce(trusted_proxies)
        self.requests_per_minute = requests_per_minute
        self.burst_requests = burst_requests
        self.auth_requests_per_minute = auth_requests_per_minute
        self.cleanup_interval = 60  # Clean up every minute

        # In-memory storage: {client_ip: [(timestamp, endpoint_type), ...]}
        self.request_counts: dict[str, list] = defaultdict(list)
        self.last_cleanup = time.time()

    def _get_client_ip(self, request: Request) -> str:
        """Return the client IP: the socket peer, unless it is a trusted proxy."""
        return get_client_ip(request, self.trusted_proxies)

    def _is_auth_endpoint(self, path: str) -> bool:
        """Check if the request path is an authentication endpoint."""
        auth_paths = [
            "/auth/login",
            "/auth/register",
            "/auth/refresh",
            "/auth/forgot-password",
            "/auth/reset-password",
        ]
        return any(path.startswith(auth_path) for auth_path in auth_paths)

    def _cleanup_old_entries(self) -> None:
        """Remove entries older than the rate limit window."""
        if time.time() - self.last_cleanup < self.cleanup_interval:
            return

        current_time = time.time()
        cutoff_time = current_time - 60  # Keep last minute of data

        for ip in list(self.request_counts.keys()):
            # Filter out old entries
            self.request_counts[ip] = [
                (timestamp, endpoint_type)
                for timestamp, endpoint_type in self.request_counts[ip]
                if timestamp > cutoff_time
            ]

            # Remove empty entries
            if not self.request_counts[ip]:
                del self.request_counts[ip]

        self.last_cleanup = current_time

    def _check_rate_limit(self, client_ip: str, is_auth_endpoint: bool) -> bool:
        """Check if request should be rate limited."""
        current_time = time.time()
        window_start = current_time - 60  # 1 minute window

        # Get requests in the current window
        recent_requests = [
            (timestamp, endpoint_type)
            for timestamp, endpoint_type in self.request_counts[client_ip]
            if timestamp > window_start
        ]

        # Count requests by type
        total_requests = len(recent_requests)
        auth_requests = sum(1 for _, endpoint_type in recent_requests if endpoint_type == "auth")

        # Check limits
        if is_auth_endpoint:
            if auth_requests >= self.auth_requests_per_minute:
                return True  # Rate limited
        elif total_requests >= self.requests_per_minute:
            return True  # Rate limited

        # Check burst limit (recent requests in last 10 seconds)
        burst_window = current_time - 10
        burst_requests = sum(1 for timestamp, _ in recent_requests if timestamp > burst_window)
        if burst_requests >= self.burst_requests:
            return True  # Rate limited

        return False  # Allow request

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Apply rate limiting to incoming requests.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware in the chain

        Returns:
            Response or 429 error if rate limit exceeded
        """
        # Clean up old entries periodically
        self._cleanup_old_entries()

        client_ip = self._get_client_ip(request)
        is_auth_endpoint = self._is_auth_endpoint(request.url.path)

        # Check rate limit
        if self._check_rate_limit(client_ip, is_auth_endpoint):
            # Add rate limit headers
            response = Response(
                content='{"detail":"Rate limit exceeded"}',
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                media_type="application/json",
            )
            response.headers["X-RateLimit-Limit"] = str(
                self.auth_requests_per_minute if is_auth_endpoint else self.requests_per_minute
            )
            response.headers["X-RateLimit-Remaining"] = "0"
            response.headers["Retry-After"] = "60"
            return response

        # Record the request
        current_time = time.time()
        endpoint_type = "auth" if is_auth_endpoint else "general"
        self.request_counts[client_ip].append((current_time, endpoint_type))

        # Process request
        response = await call_next(request)

        # Add rate limit headers to successful responses
        recent_requests = [
            (timestamp, ep_type)
            for timestamp, ep_type in self.request_counts[client_ip]
            if timestamp > current_time - 60
        ]

        if is_auth_endpoint:
            auth_count = sum(1 for _, ep_type in recent_requests if ep_type == "auth")
            remaining = max(0, self.auth_requests_per_minute - auth_count)
            response.headers["X-RateLimit-Limit"] = str(self.auth_requests_per_minute)
        else:
            remaining = max(0, self.requests_per_minute - len(recent_requests))
            response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)

        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """CSRF protection middleware for state-changing requests.

    This middleware protects against Cross-Site Request Forgery attacks
    by validating CSRF tokens on POST, PUT, DELETE, PATCH requests.
    """

    def __init__(
        self,
        app: FastAPI,
        secret_key: str,
        cookie_name: str = "csrf_token",
        header_name: str = "X-CSRF-Token",
        exempt_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.secret_key = secret_key.encode()
        self.cookie_name = cookie_name
        self.header_name = header_name
        self.exempt_paths = exempt_paths or [
            "/docs",  # FastAPI docs
            "/openapi.json",  # OpenAPI spec
            "/health",  # Health check
        ]

    def _generate_csrf_token(self, session_data: str = "") -> str:
        """Generate a CSRF token."""
        timestamp = str(int(time.time()))
        data = f"{session_data}:{timestamp}".encode()
        signature = hashlib.hmac.new(self.secret_key, data, hashlib.sha256).hexdigest()
        return f"{timestamp}:{signature}"

    def _validate_csrf_token(self, token: str, session_data: str = "") -> bool:
        """Validate a CSRF token."""
        try:
            timestamp_str, signature = token.split(":", 1)
            timestamp = int(timestamp_str)

            # Check if token is not too old (1 hour)
            if time.time() - timestamp > 3600:
                return False

            # Verify signature
            data = f"{session_data}:{timestamp_str}".encode()
            expected_signature = hashlib.hmac.new(self.secret_key, data, hashlib.sha256).hexdigest()

            return signature == expected_signature

        except (ValueError, TypeError):
            return False

    def _should_check_csrf(self, request: Request) -> bool:
        """Determine if CSRF check is needed for this request."""
        # Only check state-changing methods
        if request.method not in ["POST", "PUT", "DELETE", "PATCH"]:
            return False

        # Skip exempt paths
        path = request.url.path
        if any(path.startswith(exempt_path) for exempt_path in self.exempt_paths):
            return False

        # Skip if Content-Type suggests API usage (not browser)
        content_type = request.headers.get("Content-Type", "")
        if content_type.startswith("application/json") and not request.headers.get("Origin"):
            return False

        return True

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Validate CSRF tokens for state-changing requests.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware in the chain

        Returns:
            Response or 403 error if CSRF validation fails
        """
        if self._should_check_csrf(request):
            # Get CSRF token from header or form data
            csrf_token = request.headers.get(self.header_name)

            if not csrf_token and hasattr(request, "_json"):
                # Try to get from form data for form submissions
                body = await request.json()
                csrf_token = body.get("csrf_token")

            # Get session data for validation (could be user ID from JWT)
            session_data = ""
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                # Extract user info from token for CSRF validation
                # This is a simplified approach - in practice, you might want to
                # decode the JWT to get user ID
                session_data = auth_header

            # Validate CSRF token
            if not csrf_token or not self._validate_csrf_token(csrf_token, session_data):
                return Response(
                    content='{"detail":"CSRF token missing or invalid"}',
                    status_code=status.HTTP_403_FORBIDDEN,
                    media_type="application/json",
                )

        response = await call_next(request)

        # Add CSRF token to responses for browser requests
        if request.headers.get("Accept", "").find("text/html") != -1:
            csrf_token = self._generate_csrf_token()
            response.set_cookie(
                key=self.cookie_name,
                value=csrf_token,
                secure=request.url.scheme == "https",
                httponly=False,  # Need to be accessible to JavaScript
                samesite="strict",
            )

        return response
