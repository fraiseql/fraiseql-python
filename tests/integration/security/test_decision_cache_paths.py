"""Decision caching across execution paths (issue #367, phase 2).

Caching must memoize identical authorization *decisions* on the live paths (the resolver
path and the resolver-bypass gates) without ever weakening the fail-closed contract proven
by ``test_authorization_paths.py``. Note that only the *decision* is cached — the resolver /
Rust pipeline still runs on every request.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.schema_builder import SchemaRegistry
from fraiseql.security.decision_cache import AuthorizationCacheConfig

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.integration

_executions: list[str] = []


@fraiseql.type
class Widget:
    """Widget type for decision-cache path testing."""

    id: int
    name: str


@fraiseql.query
async def widgets(info) -> list[Widget]:
    """Return widgets (records execution)."""
    _executions.append("widgets")
    return [Widget(id=1, name="w")]


class CountingAuthorizer:
    """Counts invocations; returns a fixed result (bool or AuthorizationDecision)."""

    def __init__(self, *, result: Any = True) -> None:
        self.calls = 0
        self._result = result

    async def authorize_operation(self, **_: Any) -> Any:
        self.calls += 1
        return self._result


class RaisingAuthorizer:
    """Always raises — a transient PDP error that must never be cached."""

    def __init__(self) -> None:
        self.calls = 0

    async def authorize_operation(self, **_: Any) -> bool:
        self.calls += 1
        raise RuntimeError("PDP down")


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    """No-op lifespan so the app needs no live database."""
    yield


async def _ctx_with_user(_request: Any) -> dict[str, Any]:
    """Inject an identified principal so the cache engages."""
    return {"user": {"id": "u1"}}


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate the singleton registry (and global deps) around each test."""
    registry = SchemaRegistry.get_instance()
    registry.clear()
    from fraiseql.core.graphql_type import _graphql_type_cache

    _graphql_type_cache.clear()

    import fraiseql.fastapi.app as app_mod
    import fraiseql.fastapi.dependencies as deps

    deps._db_pool = None
    deps._auth_provider = None
    deps._fraiseql_config = None
    app_mod._global_turbo_registry = None

    yield

    _executions.clear()
    registry.clear()
    _graphql_type_cache.clear()
    deps._db_pool = None
    deps._auth_provider = None
    deps._fraiseql_config = None
    app_mod._global_turbo_registry = None


def _cache_config() -> AuthorizationCacheConfig:
    return AuthorizationCacheConfig(
        principal_key=lambda ctx: (ctx.get("user") or {}).get("id"),
        ttl_seconds=60.0,
    )


def _build_app(*, authorizer: Any, cache: bool = True, rust: bool = False) -> FastAPI:
    config = FraiseQLConfig(
        database_url="postgresql://test:test@localhost/test",
        environment="development",
        enable_rust_endpoint=rust,
    )
    return create_fraiseql_app(
        config=config,
        types=[Widget],
        queries=[widgets],
        lifespan=_noop_lifespan,
        context_getter=_ctx_with_user,
        authorizer=authorizer,
        authorization_cache=_cache_config() if cache else None,
    )


def _is_forbidden(body: dict[str, Any]) -> bool:
    return any(
        (e.get("extensions") or {}).get("code") == "FORBIDDEN" for e in (body.get("errors") or [])
    )


# --- Cycle 1: resolver path memoizes the decision -------------------------------------


def test_resolver_path_caches_identical_query_decisions() -> None:
    auth = CountingAuthorizer()
    app = _build_app(authorizer=auth)
    with TestClient(app) as client:
        for _ in range(2):
            body = client.post("/graphql", json={"query": "{ widgets { id name } }"}).json()
            assert not body.get("errors")
    assert auth.calls == 1, "second identical query should be served from the decision cache"
    # The resolver runs on every request; only the *decision* is cached.
    assert _executions == ["widgets", "widgets"]


def test_deny_decision_cached_blocks_second_identical_query() -> None:
    auth = CountingAuthorizer(result=False)
    app = _build_app(authorizer=auth)
    with TestClient(app) as client:
        for _ in range(2):
            body = client.post("/graphql", json={"query": "{ widgets { id } }"}).json()
            assert _is_forbidden(body)
    assert auth.calls == 1, "a clean deny is cached and re-enforced without re-invoking"
    assert _executions == [], "resolver never runs on deny"


def test_no_cache_invokes_authorizer_every_request() -> None:
    auth = CountingAuthorizer()
    app = _build_app(authorizer=auth, cache=False)
    with TestClient(app) as client:
        for _ in range(2):
            client.post("/graphql", json={"query": "{ widgets { id } }"})
    assert auth.calls == 2, "with no cache configured, behavior is exactly today's"


# --- Cycle 2: bypass path honors the same cache ---------------------------------------


def test_rust_bypass_path_honors_cache() -> None:
    auth = CountingAuthorizer()
    app = _build_app(authorizer=auth, rust=True)

    calls: list[Any] = []

    async def _spy(*_a: Any, **_k: Any) -> bytes:
        calls.append(1)
        return b'{"data": {"widgets": []}}'

    with mock.patch("fraiseql._fraiseql_rs.execute_graphql_query", new=_spy), TestClient(app) as c:
        for _ in range(2):
            c.post("/graphql/rust", json={"query": "{ widgets { id } }"})
    assert auth.calls == 1, "the /graphql/rust gate honors the same decision cache"
    assert len(calls) == 2, "Rust still runs each call; only the decision is cached"


# --- Cycle 3: caching never weakens fail-closed ---------------------------------------


def test_raising_authorizer_never_cached_stays_denied() -> None:
    auth = RaisingAuthorizer()
    app = _build_app(authorizer=auth)
    with TestClient(app) as client:
        for _ in range(2):
            body = client.post("/graphql", json={"query": "{ widgets { id } }"}).json()
            assert _is_forbidden(body)
    assert auth.calls == 2, "a raising authorizer must not be cached (re-invoked each request)"
    assert _executions == [], "resolver never runs when the authorizer raises"
