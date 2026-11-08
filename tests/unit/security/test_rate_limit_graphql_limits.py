"""The GraphQL per-operation and per-cost limits can be set, not only read."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fraiseql.security.rate_limiting import (
    GraphQLRateLimiter,
    RateLimit,
    RateLimitStore,
    setup_rate_limiting,
)

pytestmark = pytest.mark.unit


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/graphql")
    async def graphql() -> dict:
        return {"data": {}}

    return app


def _post(client: TestClient, query: str, n: int) -> list[int]:
    return [client.post("/graphql", json={"query": query}).status_code for _ in range(n)]


def test_operation_limits_override_one_type() -> None:
    app = _app()
    setup_rate_limiting(
        app, graphql_operation_limits={"mutation": RateLimit(requests=1, window=60)}
    )
    client = TestClient(app)
    assert _post(client, "mutation { x }", 2) == [200, 429]
    # The other types keep their defaults.
    assert _post(client, "{ x }", 3) == [200, 200, 200]


def test_complexity_limits_override_one_tier() -> None:
    app = _app()
    setup_rate_limiting(app, graphql_complexity_limits={"low": RateLimit(requests=2, window=60)})
    assert _post(TestClient(app), "{ x }", 3) == [200, 200, 429]


def test_defaults_are_unchanged_and_not_shared() -> None:
    first = GraphQLRateLimiter(RateLimitStore(), operation_limits={"query": RateLimit(1, 60)})
    second = GraphQLRateLimiter(RateLimitStore())
    assert first.operation_limits["query"].requests == 1
    assert second.operation_limits["query"].requests == 100
    assert second.operation_limits["mutation"].requests == 20
    assert second.complexity_limits["high"].requests == 20


@pytest.mark.parametrize(
    ("kwarg", "key"), [("operation_limits", "mutations"), ("complexity_limits", "extreme")]
)
def test_unknown_keys_are_refused(kwarg: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        GraphQLRateLimiter(RateLimitStore(), **{kwarg: {key: RateLimit(1, 60)}})
