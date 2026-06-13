"""End-to-end field-level authorization on the resolver-bypass paths (issue #366).

``@fraise_type(authorize_fields=[...])`` installs a per-field gate on ``GraphQLField.resolve``.
The Rust merge / passthrough / TurboRouter / ``POST /graphql/rust`` / APQ-cache paths never
invoke that resolver, so the gate would silently fail open. These tests drive the bypass paths
that need no live database or Rust extension (APQ cache hit, ``/graphql/rust`` with a mocked
pipeline, and ``TurboRouter`` directly) and assert the gate now holds — each would serve the
gated field before the fix.
"""

from __future__ import annotations

import asyncio
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
from fraiseql.fastapi.turbo import TurboQuery, TurboRegistry, TurboRouter
from fraiseql.gql.builders import SchemaRegistry
from fraiseql.gql.schema_builder import build_fraiseql_schema

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.integration

_GATED_QUERY = "{ account { secret } }"
_UNGATED_QUERY = "{ account { name } }"


@fraiseql.type(authorize_fields=["secret"])
class Account:
    """Account whose ``secret`` field is automatically gated."""

    id: int
    name: str

    @fraiseql.field
    def secret(self) -> str | None:
        return "classified"


@fraiseql.query
async def account(info) -> Account:
    return Account(id=1, name="acme")


class DenySecretField:
    """Allows every operation; denies only the ``Account.secret`` field check."""

    async def authorize_operation(
        self, *, operation_type: str, operation_name: str, **_: Any
    ) -> bool:
        if operation_type == "field":
            return operation_name != "Account.secret"
        return True


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


def _build_app(*, enable_rust_endpoint: bool = False) -> FastAPI:
    config = FraiseQLConfig(
        database_url="postgresql://test:test@localhost/test",
        environment="development",
        apq_cache_responses=True,
        enable_rust_endpoint=enable_rust_endpoint,
    )
    app = create_fraiseql_app(
        config=config,
        types=[Account],
        queries=[account],
        lifespan=_noop_lifespan,
    )
    SchemaRegistry.get_instance().set_default_authorizer(DenySecretField())
    return app


def _is_forbidden(body: dict[str, Any]) -> bool:
    errors = body.get("errors") or []
    return any(
        (e.get("extensions") or {}).get("code") == "FIELD_AUTHORIZATION_ERROR" for e in errors
    )


def test_apq_cache_hit_enforces_field_gate() -> None:
    """A cached APQ response for a query selecting a gated field is not served on deny."""
    from fraiseql.middleware.apq_caching import compute_response_cache_key, get_apq_backend

    config = FraiseQLConfig(
        database_url="postgresql://test:test@localhost/test",
        environment="development",
        apq_cache_responses=True,
    )
    app = create_fraiseql_app(
        config=config, types=[Account], queries=[account], lifespan=_noop_lifespan
    )
    SchemaRegistry.get_instance().set_default_authorizer(DenySecretField())

    sha = hashlib.sha256(_GATED_QUERY.encode()).hexdigest()
    leaked = {"data": {"account": {"secret": "LEAKED"}}}
    backend = get_apq_backend(config)
    backend.store_persisted_query(sha, _GATED_QUERY)
    backend.store_cached_response(compute_response_cache_key(sha), leaked)

    with TestClient(app) as client:
        body = client.post(
            "/graphql",
            json={"extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}}},
        ).json()

    assert _is_forbidden(body), "expected FIELD_AUTHORIZATION_ERROR on the APQ cache path"
    assert body.get("data", {}).get("account") != {"secret": "LEAKED"}, "gated field leaked"


def test_rust_endpoint_enforces_field_gate() -> None:
    """The /graphql/rust path denies a gated field before invoking the Rust pipeline."""
    app = _build_app(enable_rust_endpoint=True)

    calls: list[Any] = []

    async def _spy(*args: Any, **kwargs: Any) -> bytes:
        calls.append((args, kwargs))
        return b'{"data": {"account": {"secret": "LEAKED"}}}'

    with mock.patch("fraiseql._fraiseql_rs.execute_graphql_query", new=_spy):
        with TestClient(app) as client:
            response = client.post("/graphql/rust", json={"query": _GATED_QUERY})
        body = response.json()

    assert _is_forbidden(body), "expected FIELD_AUTHORIZATION_ERROR on the /graphql/rust path"
    assert calls == [], "Rust pipeline ran despite a denied gated field"


def test_rust_endpoint_allows_ungated_field() -> None:
    """The /graphql/rust path still serves a query that selects no gated field."""
    app = _build_app(enable_rust_endpoint=True)

    calls: list[Any] = []

    async def _spy(*args: Any, **kwargs: Any) -> bytes:
        calls.append((args, kwargs))
        return b'{"data": {"account": {"name": "acme"}}}'

    with mock.patch("fraiseql._fraiseql_rs.execute_graphql_query", new=_spy):
        with TestClient(app) as client:
            response = client.post("/graphql/rust", json={"query": _UNGATED_QUERY})
        body = response.json()

    assert not _is_forbidden(body)
    assert len(calls) == 1, "Rust pipeline should run for an ungated query"


class _SpyDB:
    def __init__(self) -> None:
        self.context: dict[str, Any] = {}
        self.tx_calls = 0

    async def run_in_transaction(self, fn: Any) -> list[dict[str, Any]]:
        self.tx_calls += 1
        return [{"result": {"name": "acme"}}]

    async def _set_session_variables(self, cursor: Any) -> None:
        return None


def _turbo_router_with(query: str) -> tuple[TurboRouter, _SpyDB]:
    schema = build_fraiseql_schema(query_types=[Account, account], authorizer=DenySecretField())
    registry = TurboRegistry()
    registry.register(
        TurboQuery(graphql_query=query, sql_template="SELECT 1 AS result", param_mapping={})
    )
    router = TurboRouter(registry, default_authorizer=DenySecretField(), schema=schema)
    return router, _SpyDB()


async def test_turbo_enforces_field_gate_before_db() -> None:
    router, spy = _turbo_router_with(_GATED_QUERY)
    with pytest.raises(GraphQLError) as exc:
        await router.execute(_GATED_QUERY, {}, {"db": spy})
    assert (exc.value.extensions or {}).get("code") == "FIELD_AUTHORIZATION_ERROR"
    assert spy.tx_calls == 0, "turbo touched the database despite a denied gated field"


async def test_turbo_allows_ungated_field() -> None:
    router, spy = _turbo_router_with(_UNGATED_QUERY)
    await router.execute(_UNGATED_QUERY, {}, {"db": spy})
    assert spy.tx_calls == 1


def test_turbo_without_schema_skips_field_gate() -> None:
    """A TurboRouter built without a schema cannot resolve the selection set → field gate off.

    This preserves the existing direct-construction behavior; field gating on the turbo path is
    opt-in via the ``schema`` argument (wired automatically inside ``create_graphql_router``).
    """
    SchemaRegistry.get_instance().clear()
    build_fraiseql_schema(query_types=[Account, account], authorizer=DenySecretField())
    registry = TurboRegistry()
    registry.register(
        TurboQuery(graphql_query=_GATED_QUERY, sql_template="SELECT 1 AS result", param_mapping={})
    )
    router = TurboRouter(registry, default_authorizer=DenySecretField())  # no schema
    spy = _SpyDB()
    asyncio.run(router.execute(_GATED_QUERY, {}, {"db": spy}))
    assert spy.tx_calls == 1
