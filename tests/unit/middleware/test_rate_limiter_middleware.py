"""RateLimiterMiddleware answers a request over the limit itself, through an app."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fraiseql.middleware.rate_limiter import (
    InMemoryRateLimiter,
    RateLimitConfig,
    RateLimiterMiddleware,
)


def _client(config: RateLimitConfig) -> TestClient:
    app = FastAPI()

    @app.post("/graphql")
    async def graphql_endpoint():
        return {"data": {"ok": True}}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    app.add_middleware(RateLimiterMiddleware, rate_limiter=InMemoryRateLimiter(config))
    # A 500 must show as a response, not as an exception raised in the test
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client() -> TestClient:
    return _client(RateLimitConfig(requests_per_minute=2, burst_size=2))


def test_requests_within_limit_pass_with_headers(client):
    response = client.post("/graphql", json={"query": "{ ok }"})
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "2"
    assert response.headers["X-RateLimit-Remaining"] == "1"


def test_request_over_limit_gets_429_with_retry_after(client):
    for _ in range(2):
        assert client.post("/graphql", json={"query": "{ ok }"}).status_code == 200

    response = client.post("/graphql", json={"query": "{ ok }"})

    assert response.status_code == 429
    retry_after = int(response.headers["Retry-After"])
    assert 0 < retry_after <= 60
    assert response.json()["detail"].startswith("Rate limit exceeded")
    assert response.headers["X-RateLimit-Remaining"] == "0"


def test_health_is_not_limited(client):
    for _ in range(3):
        client.post("/graphql", json={"query": "{ ok }"})
    assert client.get("/health").status_code == 200


def test_disabled_config_does_not_limit():
    client = _client(RateLimitConfig(enabled=False, requests_per_minute=1, burst_size=1))
    assert all(client.post("/graphql", json={}).status_code == 200 for _ in range(3))


def test_blacklisted_client_gets_403():
    client = _client(RateLimitConfig(blacklist=["testclient"]))
    response = client.post("/graphql", json={"query": "{ ok }"})
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}
