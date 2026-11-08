"""The rate limiters key on the socket peer unless it is a trusted proxy.

``X-Forwarded-For`` is a request header: a client that reaches the app directly
must not be able to pick a new rate-limit key on every request by changing it.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from fraiseql.auth.native.factory import add_security_middleware
from fraiseql.auth.native.middleware import RateLimitMiddleware as NativeRateLimitMiddleware
from fraiseql.security.client_ip import TrustedProxies, get_client_ip
from fraiseql.security.rate_limiting import (
    GraphQLRateLimiter,
    RateLimit,
    RateLimitStore,
    setup_rate_limiting,
)

pytestmark = pytest.mark.unit


def _request(peer: str | None, headers: list[tuple[str, str]] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers or []],
        "client": (peer, 1234) if peer else None,
    }
    return Request(scope)


class TestGetClientIp:
    def test_without_trusted_proxies_uses_socket_peer(self) -> None:
        request = _request(
            "203.0.113.7", [("X-Forwarded-For", "1.2.3.4"), ("X-Real-IP", "5.6.7.8")]
        )
        assert get_client_ip(request) == "203.0.113.7"

    def test_untrusted_peer_headers_are_ignored(self) -> None:
        trusted = TrustedProxies(["10.0.0.0/8"])
        request = _request("203.0.113.7", [("X-Forwarded-For", "1.2.3.4")])
        assert get_client_ip(request, trusted) == "203.0.113.7"

    def test_trusted_peer_uses_right_most_untrusted_hop(self) -> None:
        trusted = TrustedProxies(["10.0.0.0/8", "192.168.1.5"])
        # A forged left-most entry, then the real client, then a trusted inner proxy.
        request = _request("10.1.2.3", [("X-Forwarded-For", "6.6.6.6, 198.51.100.9, 192.168.1.5")])
        assert get_client_ip(request, trusted) == "198.51.100.9"

    def test_repeated_header_lines_are_joined(self) -> None:
        trusted = TrustedProxies("10.0.0.1")
        request = _request(
            "10.0.0.1", [("X-Forwarded-For", "6.6.6.6"), ("X-Forwarded-For", "198.51.100.9")]
        )
        assert get_client_ip(request, trusted) == "198.51.100.9"

    def test_ports_and_ipv6_brackets_are_stripped(self) -> None:
        trusted = TrustedProxies(["10.0.0.1", "2001:db8::/32"])
        request = _request(
            "10.0.0.1", [("X-Forwarded-For", "198.51.100.9:5000, [2001:db8::1]:443")]
        )
        assert get_client_ip(request, trusted) == "198.51.100.9"

    def test_all_hops_trusted_gives_left_most(self) -> None:
        trusted = TrustedProxies(["10.0.0.0/8"])
        request = _request("10.0.0.1", [("X-Forwarded-For", "10.9.9.9, 10.0.0.2")])
        assert get_client_ip(request, trusted) == "10.9.9.9"

    def test_trusted_peer_without_forwarded_for_uses_real_ip(self) -> None:
        trusted = TrustedProxies(["10.0.0.1"])
        assert get_client_ip(_request("10.0.0.1", [("X-Real-IP", "198.51.100.9")]), trusted) == (
            "198.51.100.9"
        )
        assert get_client_ip(_request("10.0.0.1"), trusted) == "10.0.0.1"

    def test_no_peer(self) -> None:
        assert get_client_ip(_request(None, [("X-Forwarded-For", "1.2.3.4")])) == "unknown"

    @pytest.mark.parametrize("bad", ["*", "not-an-ip", "10.0.0.0/99"])
    def test_invalid_entries_are_refused(self, bad: str) -> None:
        with pytest.raises(ValueError, match="trusted_proxies"):
            TrustedProxies([bad])

    def test_coerce(self) -> None:
        assert TrustedProxies.coerce(None) is None
        assert TrustedProxies.coerce([]) is None
        assert TrustedProxies.coerce("") is None
        assert "10.1.1.1" in TrustedProxies.coerce("10.0.0.0/8, 192.168.0.1")


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/test")
    async def endpoint() -> dict:
        return {}

    @app.post("/auth/login")
    async def login() -> dict:
        return {}

    @app.post("/graphql")
    async def graphql() -> dict:
        return {"data": {}}

    return app


def _statuses(client: TestClient, method: str, path: str, n: int, **kwargs: object) -> list[int]:
    return [
        client.request(
            method, path, headers={"X-Forwarded-For": f"198.51.100.{i}"}, **kwargs
        ).status_code
        for i in range(n)
    ]


class TestSetupRateLimitingClientIp:
    def test_rotating_forwarded_for_does_not_bypass_limit(self) -> None:
        app = _app()
        setup_rate_limiting(app, custom_rules=[], default_limit=RateLimit(requests=2, window=60))
        statuses = _statuses(TestClient(app), "GET", "/test", 4)
        assert statuses == [200, 200, 429, 429]

    def test_graphql_limits_ignore_rotating_forwarded_for(self) -> None:
        app = _app()
        setup_rate_limiting(app, custom_rules=[], default_limit=RateLimit(requests=1000, window=60))
        statuses = _statuses(
            TestClient(app), "POST", "/graphql", 22, json={"query": "mutation { x }"}
        )
        # The mutation limit (20 per minute) applies to the one real client.
        assert statuses[:20] == [200] * 20
        assert statuses[20:] == [429, 429]

    def test_trusted_proxy_limits_each_forwarded_client(self) -> None:
        app = _app()
        setup_rate_limiting(
            app,
            custom_rules=[],
            default_limit=RateLimit(requests=1, window=60),
            trusted_proxies=["10.0.0.0/8"],
        )
        client = TestClient(app, client=("10.0.0.5", 1234))
        assert _statuses(client, "GET", "/test", 3) == [200, 200, 200]
        again = client.get("/test", headers={"X-Forwarded-For": "198.51.100.0"})
        assert again.status_code == 429

    def test_graphql_rate_limiter_accepts_trusted_proxies(self) -> None:
        limiter = GraphQLRateLimiter(RateLimitStore(), trusted_proxies=["10.0.0.1"])
        request = _request("10.0.0.1", [("X-Forwarded-For", "198.51.100.9")])
        assert limiter._get_client_ip(request) == "198.51.100.9"


class TestNativeAuthRateLimitClientIp:
    def test_rotating_forwarded_for_does_not_bypass_auth_limit(self) -> None:
        app = _app()
        app.add_middleware(NativeRateLimitMiddleware, auth_requests_per_minute=2)
        statuses = _statuses(TestClient(app), "POST", "/auth/login", 4)
        assert statuses == [200, 200, 429, 429]

    def test_add_security_middleware_passes_trusted_proxies(self) -> None:
        app = _app()
        add_security_middleware(
            app,
            secret_key="k" * 32,
            enable_security_headers=False,
            rate_limit_auth_requests_per_minute=1,
            trusted_proxies=["10.0.0.0/8"],
        )
        client = TestClient(app, client=("10.0.0.5", 1234))
        assert _statuses(client, "POST", "/auth/login", 3) == [200, 200, 200]


def test_setup_security_refuses_bad_trusted_proxies() -> None:
    """A bad entry raises; setup_security must not log it and run without a limiter."""
    from fraiseql.security import setup_security

    with pytest.raises(ValueError, match="trusted_proxies"):
        setup_security(_app(), secret_key="k" * 32, trusted_proxies=["*"])
