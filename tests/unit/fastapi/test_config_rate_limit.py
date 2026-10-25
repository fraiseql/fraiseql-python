"""The rate_limit_* settings of FraiseQLConfig, end to end through create_fraiseql_app."""

import pytest
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.gql.schema_builder import SchemaRegistry
from fraiseql.middleware.rate_limiter import RateLimiterMiddleware

QUERY = {"query": "{ ping }"}


@pytest.fixture(autouse=True)
def clear_registry():
    SchemaRegistry.get_instance().clear()
    yield
    SchemaRegistry.get_instance().clear()


def _app(**settings):
    @fraiseql.query
    async def ping(info) -> str:
        return "pong"

    config = FraiseQLConfig(database_url="postgresql://localhost/unused", **settings)
    return create_fraiseql_app(config=config, queries=[ping], production=False)


def _has_rate_limiter(app) -> bool:
    return any(m.cls is RateLimiterMiddleware for m in app.user_middleware)


def test_rate_limiting_is_off_by_default():
    assert FraiseQLConfig(database_url="postgresql://localhost/unused").rate_limit_enabled is False
    app = _app()
    assert not _has_rate_limiter(app)
    with TestClient(app) as client:
        assert all(client.post("/graphql", json=QUERY).status_code == 200 for _ in range(15))


def test_enabled_limits_graphql_requests_per_minute():
    app = _app(rate_limit_enabled=True, rate_limit_requests_per_minute=3, rate_limit_burst_size=3)
    with TestClient(app) as client:
        statuses = [client.post("/graphql", json=QUERY).status_code for _ in range(4)]
        assert statuses == [200, 200, 200, 429]

        limited = client.post("/graphql", json=QUERY)
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) >= 1

        # Health checks are never limited
        assert client.get("/health").status_code == 200


def test_successful_responses_carry_rate_limit_headers():
    app = _app(rate_limit_enabled=True, rate_limit_requests_per_minute=5, rate_limit_burst_size=5)
    with TestClient(app) as client:
        response = client.post("/graphql", json=QUERY)
    assert response.status_code == 200
    assert response.json()["data"] == {"ping": "pong"}
    assert response.headers["X-RateLimit-Limit"] == "5"
    assert response.headers["X-RateLimit-Remaining"] == "4"


def test_hour_limit_applies():
    app = _app(
        rate_limit_enabled=True,
        rate_limit_requests_per_minute=100,
        rate_limit_requests_per_hour=2,
        rate_limit_burst_size=1,
    )
    with TestClient(app) as client:
        statuses = [client.post("/graphql", json=QUERY).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]


def test_whitelisted_client_is_not_limited():
    # TestClient connects from the address "testclient"
    app = _app(
        rate_limit_enabled=True,
        rate_limit_requests_per_minute=1,
        rate_limit_burst_size=1,
        rate_limit_whitelist=["testclient"],
    )
    with TestClient(app) as client:
        assert all(client.post("/graphql", json=QUERY).status_code == 200 for _ in range(5))


def test_blacklisted_client_is_rejected():
    app = _app(rate_limit_enabled=True, rate_limit_blacklist=["testclient"])
    with TestClient(app) as client:
        assert client.post("/graphql", json=QUERY).status_code == 403


def test_enabled_from_environment(monkeypatch):
    monkeypatch.setenv("FRAISEQL_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("FRAISEQL_RATE_LIMIT_REQUESTS_PER_MINUTE", "1")
    monkeypatch.setenv("FRAISEQL_RATE_LIMIT_BURST_SIZE", "1")
    app = _app()
    with TestClient(app) as client:
        statuses = [client.post("/graphql", json=QUERY).status_code for _ in range(2)]
    assert statuses == [200, 429]
