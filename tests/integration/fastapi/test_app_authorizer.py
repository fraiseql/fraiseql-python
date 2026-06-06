"""End-to-end app-level authorization wiring (issue #362, phase 6)."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from graphql import GraphQLError

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.builders import SchemaRegistry

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.integration

_ran: list[str] = []


@fraiseql.type
class Widget:
    id: int
    name: str


@fraiseql.query
async def widgets(info) -> list[Widget]:
    _ran.append("widgets")
    return [Widget(id=1, name="live")]


@fraiseql.mutation
async def make_widget(info, name: str) -> Widget:
    _ran.append("make_widget")
    return Widget(id=2, name=name)


class DenyAll:
    async def authorize_operation(self, **_: Any) -> bool:
        return False


class AllowAll:
    async def authorize_operation(self, **_: Any) -> bool:
        return True


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


async def _user_ctx(request) -> dict[str, Any]:
    return {"user": {"id": "u1", "permissions": [], "roles": []}}


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
    _ran.clear()
    yield
    registry.clear()
    _graphql_type_cache.clear()
    deps._db_pool = None
    deps._auth_provider = None
    deps._fraiseql_config = None
    app_mod._global_turbo_registry = None
    _ran.clear()


def _build_app(*, authorizer=None, apq=False) -> FastAPI:
    config = FraiseQLConfig(
        database_url="postgresql://test:test@localhost/test",
        environment="development",
        apq_cache_responses=apq,
    )
    return create_fraiseql_app(
        config=config,
        types=[Widget],
        queries=[widgets],
        mutations=[make_widget],
        lifespan=_noop_lifespan,
        context_getter=_user_ctx,
        authorizer=authorizer,
    )


def _is_forbidden(body: dict[str, Any]) -> bool:
    return any(
        (e.get("extensions") or {}).get("code") == "FORBIDDEN" for e in (body.get("errors") or [])
    )


# --- Cycle 1: app-level gate, end to end -------------------------------------------


def test_deny_all_blocks_query_and_mutation() -> None:
    app = _build_app(authorizer=DenyAll())
    with TestClient(app) as c:
        q = c.post("/graphql", json={"query": "{ widgets { id } }"}).json()
        m = c.post("/graphql", json={"query": 'mutation { makeWidget(name: "x") { id } }'}).json()
    assert _is_forbidden(q)
    assert _is_forbidden(m)
    assert _ran == []


def test_allow_all_runs_query_and_mutation() -> None:
    app = _build_app(authorizer=AllowAll())
    with TestClient(app) as c:
        q = c.post("/graphql", json={"query": "{ widgets { id name } }"}).json()
        m = c.post("/graphql", json={"query": 'mutation { makeWidget(name: "x") { id } }'}).json()
    assert not _is_forbidden(q)
    assert not _is_forbidden(m)
    assert "widgets" in _ran
    assert "make_widget" in _ran


def test_no_authorizer_is_baseline() -> None:
    app = _build_app()
    with TestClient(app) as c:
        q = c.post("/graphql", json={"query": "{ widgets { id } }"}).json()
    assert not _is_forbidden(q)
    assert "widgets" in _ran


# --- Cycle 2: bypass paths gated through the app ------------------------------------


def test_rust_endpoint_gated_through_app() -> None:
    app = _build_app(authorizer=DenyAll())
    calls: list[Any] = []

    async def _spy(*a: Any, **k: Any) -> bytes:
        calls.append(1)
        return b'{"data": {}}'

    with mock.patch("fraiseql._fraiseql_rs.execute_graphql_query", new=_spy), TestClient(app) as c:
        body = c.post("/graphql/rust", json={"query": "{ widgets { id } }"}).json()
    assert _is_forbidden(body)
    assert calls == []


def test_apq_cache_hit_gated_through_app() -> None:
    from fraiseql.middleware.apq_caching import compute_response_cache_key, get_apq_backend

    config = FraiseQLConfig(
        database_url="postgresql://test:test@localhost/test",
        environment="development",
        apq_cache_responses=True,
    )
    app = create_fraiseql_app(
        config=config,
        types=[Widget],
        queries=[widgets],
        mutations=[make_widget],
        lifespan=_noop_lifespan,
        context_getter=_user_ctx,
        authorizer=DenyAll(),
    )
    query = "{ widgets { id } }"
    sha = hashlib.sha256(query.encode()).hexdigest()
    backend = get_apq_backend(config)
    backend.store_persisted_query(sha, query)
    backend.store_cached_response(
        compute_response_cache_key(sha), {"data": {"widgets": [{"id": 99}]}}
    )

    with TestClient(app) as c:
        body = c.post(
            "/graphql",
            json={"extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}}},
        ).json()
    assert _is_forbidden(body)
    assert (body.get("data") or {}).get("widgets") != [{"id": 99}]


def test_turbo_router_wired_with_app_authorizer() -> None:
    # TurboRouter sources its gate from the registry default authorizer at construction;
    # create_fraiseql_app installs the app authorizer there.
    deny = DenyAll()
    _build_app(authorizer=deny)
    assert SchemaRegistry.get_instance().default_authorizer is deny


# --- Cycle 3: survives hot-reload (real reload against a container) -----------------


@pytest.mark.database
@pytest.mark.asyncio
async def test_authorizer_survives_hot_reload(postgres_url) -> None:
    deny = DenyAll()
    config = FraiseQLConfig(database_url=postgres_url, environment="development")
    app = create_fraiseql_app(
        database_url=postgres_url,  # refresh_schema reads this top-level value
        config=config,
        types=[Widget],
        queries=[widgets],
        mutations=[make_widget],
        lifespan=_noop_lifespan,
        authorizer=deny,
    )
    assert SchemaRegistry.get_instance().default_authorizer is deny

    # A naive rebuild without re-threading would reset the registry slot to None.
    await app.refresh_schema()

    # The reload re-applies the configured authorizer to the registry slot that every
    # gate reads, so the guard is not lost on schema rebuild.
    assert SchemaRegistry.get_instance().default_authorizer is deny


# --- Cycle 4: legacy registry-rewrite migration still works ------------------------


@pytest.mark.asyncio
async def test_legacy_registry_rewrite_still_enforced() -> None:
    # The pre-#362 pattern wrapped resolvers via the private registry before building the
    # schema. With no app-level authorizer the new enforce wrap is a no-op and composes
    # around whatever resolver is present at build time — so the legacy guard still fires.
    from graphql import graphql

    from fraiseql.gql.schema_builder import build_fraiseql_schema

    registry = SchemaRegistry.get_instance()
    registry.clear()
    from fraiseql.core.graphql_type import _graphql_type_cache

    _graphql_type_cache.clear()

    @fraiseql.mutation
    async def legacy_mut(info, name: str) -> Widget:
        _ran.append("legacy_mut")
        return Widget(id=3, name=name)

    async def guarded(info, name: str) -> Widget:
        raise GraphQLError("legacy guard", extensions={"code": "FORBIDDEN"})

    # Legacy migration: overwrite the registry slot before the schema is built.
    registry._mutations["legacy_mut"] = guarded

    schema = build_fraiseql_schema(query_types=[Widget, widgets])

    result = await graphql(schema, 'mutation { legacyMut(name: "x") { id } }')
    assert result.errors
    assert result.errors[0].extensions["code"] == "FORBIDDEN"
    assert "legacy_mut" not in _ran
