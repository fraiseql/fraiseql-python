"""`/graphql/rust` bypass-path authorization gate (issue #362, phase 4 part B)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.schema_builder import SchemaRegistry

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.integration


@fraiseql.type
class Widget:
    id: int
    name: str


@fraiseql.query
async def widgets(info) -> list[Widget]:
    return [Widget(id=1, name="a")]


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


def _build_app() -> FastAPI:
    config = FraiseQLConfig(
        database_url="postgresql://test:test@localhost/test",
        environment="development",
        enable_rust_endpoint=True,  # opt-in route under test (issue #365)
    )
    return create_fraiseql_app(
        config=config,
        types=[Widget],
        queries=[widgets],
        lifespan=_noop_lifespan,
    )


def _spy():
    calls: list[Any] = []

    async def _execute(*args: Any, **kwargs: Any) -> bytes:
        calls.append((args, kwargs))
        return b'{"data": {"widgets": []}}'

    return calls, _execute


def test_deny_all_blocks_rust_endpoint_no_rust_call() -> None:
    app = _build_app()
    SchemaRegistry.get_instance().set_default_authorizer(DenyAll())
    calls, spy = _spy()
    with mock.patch("fraiseql._fraiseql_rs.execute_graphql_query", new=spy), TestClient(app) as c:
        response = c.post("/graphql/rust", json={"query": "{ widgets { id } }"})
    body = response.json()
    assert body["errors"][0]["extensions"]["code"] == "FORBIDDEN"
    assert calls == [], "Rust pipeline was invoked despite a deny-all authorizer"


def test_allow_all_invokes_rust_endpoint() -> None:
    app = _build_app()
    SchemaRegistry.get_instance().set_default_authorizer(AllowAll())
    calls, spy = _spy()
    with mock.patch("fraiseql._fraiseql_rs.execute_graphql_query", new=spy), TestClient(app) as c:
        response = c.post("/graphql/rust", json={"query": "{ widgets { id } }"})
    assert response.status_code == 200
    assert len(calls) == 1


def test_no_authorizer_keeps_today_behavior() -> None:
    app = _build_app()
    calls, spy = _spy()
    with mock.patch("fraiseql._fraiseql_rs.execute_graphql_query", new=spy), TestClient(app) as c:
        c.post("/graphql/rust", json={"query": "{ widgets { id } }"})
    assert len(calls) == 1


def test_filters_on_rust_warn_and_do_not_scope(caplog) -> None:
    app = _build_app()
    SchemaRegistry.get_instance().set_default_authorizer(AllowWithFilters())
    calls, spy = _spy()
    with (
        caplog.at_level(logging.WARNING),
        mock.patch("fraiseql._fraiseql_rs.execute_graphql_query", new=spy),
        TestClient(app) as c,
    ):
        c.post("/graphql/rust", json={"query": "{ widgets { id } }"})
    # Rust still runs (no per-row scoping), but the filter limitation is logged.
    assert len(calls) == 1
    assert any("filter" in record.message.lower() for record in caplog.records)
