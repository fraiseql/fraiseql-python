"""APQ cached-passthrough authorization gate (issue #362, phase 4 part C)."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.schema_builder import SchemaRegistry
from fraiseql.middleware.apq_caching import compute_response_cache_key, get_apq_backend

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.integration

_QUERY = "{ widgets { id } }"
_CACHED = {"data": {"widgets": [{"id": 99}]}}


@fraiseql.type
class Widget:
    id: int
    name: str


@fraiseql.query
async def widgets(info) -> list[Widget]:
    return [Widget(id=1, name="live")]


class DenyAll:
    async def authorize_operation(self, **_: Any) -> bool:
        return False


class AllowAll:
    async def authorize_operation(self, **_: Any) -> bool:
        return True


class AllowWithFilters:
    async def authorize_operation(self, **_: Any) -> Any:
        from fraiseql.security.authorization import AuthorizationDecision

        return AuthorizationDecision.allow(filters={"tenant_id": "t1"})


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


@pytest.fixture(autouse=True)
def _clean_registry():
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
    registry.clear()
    _graphql_type_cache.clear()
    deps._db_pool = None
    deps._auth_provider = None
    deps._fraiseql_config = None
    app_mod._global_turbo_registry = None


def _build_app_and_seed_cache() -> tuple[FastAPI, str]:
    config = FraiseQLConfig(
        database_url="postgresql://test:test@localhost/test",
        environment="development",
        apq_cache_responses=True,
    )
    app = create_fraiseql_app(
        config=config, types=[Widget], queries=[widgets], lifespan=_noop_lifespan
    )
    sha = hashlib.sha256(_QUERY.encode()).hexdigest()
    backend = get_apq_backend(config)
    backend.store_persisted_query(sha, _QUERY)
    backend.store_cached_response(compute_response_cache_key(sha), dict(_CACHED))
    return app, sha


def _apq_request(sha: str) -> dict[str, Any]:
    return {"extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}}}


def test_deny_all_blocks_apq_cache_hit() -> None:
    app, sha = _build_app_and_seed_cache()
    SchemaRegistry.get_instance().set_default_authorizer(DenyAll())
    with TestClient(app) as c:
        body = c.post("/graphql", json=_apq_request(sha)).json()
    assert body["errors"][0]["extensions"]["code"] == "FORBIDDEN"
    assert "data" not in body or body.get("data") is None


def test_allow_all_serves_cached_response() -> None:
    app, sha = _build_app_and_seed_cache()
    SchemaRegistry.get_instance().set_default_authorizer(AllowAll())
    with TestClient(app) as c:
        body = c.post("/graphql", json=_apq_request(sha)).json()
    assert body["data"]["widgets"] == [{"id": 99}]


def test_no_authorizer_serves_cached_response() -> None:
    app, sha = _build_app_and_seed_cache()
    with TestClient(app) as c:
        body = c.post("/graphql", json=_apq_request(sha)).json()
    assert body["data"]["widgets"] == [{"id": 99}]


def test_allow_with_filters_skips_cache_and_falls_through() -> None:
    app, sha = _build_app_and_seed_cache()
    SchemaRegistry.get_instance().set_default_authorizer(AllowWithFilters())
    with TestClient(app) as c:
        body = c.post("/graphql", json=_apq_request(sha)).json()
    # Cache is bypassed (its baked id=99 is NOT served); normal execution runs the
    # live resolver instead (id=1). Either way the cached blob must not be returned.
    widgets_data = (body.get("data") or {}).get("widgets")
    assert widgets_data != [{"id": 99}]
