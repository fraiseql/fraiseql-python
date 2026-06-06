"""Cross-path authorization spec (Issue #362, Phase 0).

This module is the *specification* the operation-authorization work must satisfy:
a single deny-all assertion run across every execution path a GraphQL request can take.
If any path reaches the database/Rust without consulting the configured authorizer, its
case fails here.

Execution-path inventory (verified against the tree on 2026-06-06).
Columns: path | entry point | resolver-honoring? | gate phase.

1. Single-field query   | POST /graphql -> execute_graphql            | yes | P3
2. Mutation             | POST /graphql -> execute_graphql            | yes | P2
3. Multi-field merge    | routers.py:1358 execute_multi_field_query   | yes | P3
                          (field_def.resolve per field, routers.py:867)
4. TurboRouter          | turbo.py:271 TurboRouter.execute            | no  | P4
5. POST /graphql/rust   | routers.py:1626 -> Rust execute_graphql_query | no | P4
6. APQ cache passthrough| routers.py:1280 cache hit                   | no  | P4
7. GET /graphql         | routers.py:1586 -> graphql_endpoint         | 1/3 | P2/P3

Drift note: ``TurboRouter.execute`` is not wired into the live HTTP dispatch in this
release (``UnifiedExecutor`` holds the turbo router for metrics only and always calls
``execute_graphql``). Case 4 therefore exercises ``TurboRouter.execute`` directly as a
unit; the Phase 4 gate is defense-in-depth.

The authorizer is configured through the registry funnel
(``SchemaRegistry.set_default_authorizer``) — the same slot the resolver wrap and the
bypass gates read. Each case is decorated ``xfail(strict=True)`` until its gate lands; the
strict marker turns the case red the moment it starts passing, forcing the xfail to be
removed exactly when its phase completes (and turning any *new* ungated path red).
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncGenerator  # noqa: TC003 — runtime hint for get_type_hints
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.schema_builder import SchemaRegistry, build_fraiseql_schema

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.integration

# Records every resolver body that actually executes. A denied operation must leave this
# empty — the resolver body is what would reach the database, so "body ran" is our proxy
# for "the database was touched" on the resolver-honoring paths.
_executions: list[str] = []


@fraiseql.type
class User:
    """User type for cross-path authorization testing."""

    id: int
    name: str


@fraiseql.type
class Post:
    """Post type for cross-path authorization testing."""

    id: int
    title: str


@fraiseql.query
async def users(info) -> list[User]:
    """Return users (records execution)."""
    _executions.append("users")
    return [User(id=1, name="Alice")]


@fraiseql.query
async def posts(info) -> list[Post]:
    """Return posts (records execution)."""
    _executions.append("posts")
    return [Post(id=101, title="First")]


@fraiseql.mutation
async def create_user(info, name: str) -> User:
    """Create a user (records execution)."""
    _executions.append("create_user")
    return User(id=2, name=name)


@fraiseql.subscription
async def message_stream(info) -> AsyncGenerator[Post]:
    """Stream messages (records execution before the first yield)."""
    _executions.append("message_stream")
    yield Post(id=201, title="streamed")


class DenyAll:
    """A deny-all authorizer: every operation is forbidden."""

    async def authorize_operation(
        self,
        *,
        context: dict[str, Any],
        operation_type: str,
        operation_name: str,
        arguments: dict[str, Any],
    ) -> bool:
        return False


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    """No-op lifespan so the app needs no live database."""
    yield


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


def _build_app() -> FastAPI:
    config = FraiseQLConfig(
        database_url="postgresql://test:test@localhost/test",
        environment="development",
        apq_cache_responses=True,
    )
    return create_fraiseql_app(
        config=config,
        types=[User, Post],
        queries=[users, posts],
        mutations=[create_user],
        lifespan=_noop_lifespan,
    )


def _set_default_authorizer(authorizer: Any) -> None:
    SchemaRegistry.get_instance().set_default_authorizer(authorizer)


def _is_forbidden(body: dict[str, Any]) -> bool:
    errors = body.get("errors") or []
    return any((e.get("extensions") or {}).get("code") == "FORBIDDEN" for e in errors)


# --- per-path runners: each returns (forbidden, executed) ---------------------------


def _run_single_query() -> tuple[bool, bool]:
    _executions.clear()
    app = _build_app()
    _set_default_authorizer(DenyAll())
    with TestClient(app) as client:
        body = client.post("/graphql", json={"query": "{ users { id name } }"}).json()
    return _is_forbidden(body), bool(_executions)


def _run_mutation() -> tuple[bool, bool]:
    _executions.clear()
    app = _build_app()
    _set_default_authorizer(DenyAll())
    with TestClient(app) as client:
        body = client.post(
            "/graphql",
            json={"query": 'mutation { createUser(name: "Bob") { id name } }'},
        ).json()
    return _is_forbidden(body), bool(_executions)


def _run_multi_field() -> tuple[bool, bool]:
    _executions.clear()
    app = _build_app()
    _set_default_authorizer(DenyAll())
    with TestClient(app) as client:
        body = client.post(
            "/graphql",
            json={"query": "{ users { id } posts { id } }"},
        ).json()
    return _is_forbidden(body), bool(_executions)


def _run_get_query() -> tuple[bool, bool]:
    _executions.clear()
    app = _build_app()
    _set_default_authorizer(DenyAll())
    with TestClient(app) as client:
        body = client.get("/graphql", params={"query": "{ users { id } }"}).json()
    return _is_forbidden(body), bool(_executions)


class _SpyDB:
    """Minimal repository stand-in that records transaction execution."""

    def __init__(self) -> None:
        self.context: dict[str, Any] = {}
        self.tx_calls = 0

    async def run_in_transaction(self, fn: Any) -> list[dict[str, Any]]:
        self.tx_calls += 1
        return [{"result": {}}]

    async def _set_session_variables(self, cursor: Any) -> None:  # pragma: no cover
        return None


def _run_turbo() -> tuple[bool, bool]:
    from graphql import GraphQLError

    from fraiseql.fastapi.turbo import TurboQuery, TurboRegistry, TurboRouter

    query = "query { users { id } }"
    registry = TurboRegistry()
    registry.register(TurboQuery(graphql_query=query, sql_template="SELECT 1", param_mapping={}))
    spy = _SpyDB()
    router = TurboRouter(registry, default_authorizer=DenyAll())

    forbidden = False
    try:
        result = asyncio.run(router.execute(query, {}, {"db": spy}))
        if isinstance(result, dict):
            forbidden = _is_forbidden(result)
    except GraphQLError as exc:
        forbidden = (exc.extensions or {}).get("code") == "FORBIDDEN"
    return forbidden, spy.tx_calls > 0


def _run_rust() -> tuple[bool, bool]:
    app = _build_app()
    _set_default_authorizer(DenyAll())

    calls: list[Any] = []

    async def _spy(*args: Any, **kwargs: Any) -> bytes:
        calls.append((args, kwargs))
        return b'{"data": {"users": []}}'

    with mock.patch("fraiseql._fraiseql_rs.execute_graphql_query", new=_spy):
        with TestClient(app) as client:
            response = client.post("/graphql/rust", json={"query": "{ users { id } }"})
        try:
            body = response.json()
        except ValueError:
            body = {}
    return _is_forbidden(body), len(calls) > 0


def _run_apq() -> tuple[bool, bool]:
    import hashlib

    from fraiseql.middleware.apq_caching import compute_response_cache_key, get_apq_backend

    config = FraiseQLConfig(
        database_url="postgresql://test:test@localhost/test",
        environment="development",
        apq_cache_responses=True,
    )
    app = create_fraiseql_app(
        config=config,
        types=[User, Post],
        queries=[users, posts],
        mutations=[create_user],
        lifespan=_noop_lifespan,
    )
    _set_default_authorizer(DenyAll())

    query_text = "{ users { id } }"
    sha = hashlib.sha256(query_text.encode()).hexdigest()
    cached = {"data": {"users": [{"id": 99}]}}

    backend = get_apq_backend(config)
    backend.store_persisted_query(sha, query_text)
    backend.store_cached_response(compute_response_cache_key(sha), cached)

    with TestClient(app) as client:
        body = client.post(
            "/graphql",
            json={"extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}}},
        ).json()

    served_cached = body.get("data", {}).get("users") == [{"id": 99}]
    return _is_forbidden(body), served_cached


def _run_subscription() -> tuple[bool, bool]:
    """Drive the Subscription field's ``subscribe`` directly under a deny-all authorizer.

    Mirrors ``_run_turbo``: exercise the resolver as a unit via ``asyncio.run``. The
    websocket manager (``websocket.py:256``) drives graphql-core's ``subscribe``, which
    invokes this same field resolver, so a single gate here covers the websocket path too.
    """
    from graphql import GraphQLError

    _executions.clear()
    schema = build_fraiseql_schema(
        query_types=[User, Post, users, posts],
        subscription_resolvers=[message_stream],
    )
    _set_default_authorizer(DenyAll())

    field = next(iter(schema.subscription_type.fields.values()))
    subscribe = field.subscribe
    info = SimpleNamespace(context={}, field_name="messageStream")

    async def _drive() -> None:
        # Phase 1 makes ``subscribe`` a plain ``async def``: awaiting it enforces (raising
        # on deny) *before* the inner generator is created. Today it is an async generator
        # function, so calling it returns a generator whose body runs only on iteration.
        result = subscribe(None, info)
        if inspect.isawaitable(result):
            result = await result
        async for _value in result:
            break

    forbidden = False
    try:
        asyncio.run(_drive())
    except GraphQLError as exc:
        forbidden = (exc.extensions or {}).get("code") == "FORBIDDEN"
    return forbidden, bool(_executions)


_CASES = [
    pytest.param(_run_mutation, id="mutation"),  # gated in Phase 2
    pytest.param(_run_single_query, id="single-field-query"),  # gated in Phase 3
    pytest.param(_run_multi_field, id="multi-field-query"),  # gated in Phase 3
    pytest.param(_run_get_query, id="get-query"),  # gated in Phase 3
    pytest.param(_run_turbo, id="turbo"),  # gated in Phase 4 (part A)
    pytest.param(_run_rust, id="graphql-rust"),  # gated in Phase 4 (part B)
    pytest.param(_run_apq, id="apq-cache-hit"),  # gated in Phase 4 (part C)
    pytest.param(_run_subscription, id="subscription"),  # gated in #364 (subscribe-time)
]


@pytest.mark.parametrize("runner", _CASES)
def test_deny_all_blocks_every_path(runner) -> None:
    """A deny-all authorizer forbids the operation and never touches the database."""
    forbidden, executed = runner()
    assert forbidden, "expected a FORBIDDEN error on this path"
    assert not executed, "operation reached the database/Rust despite a deny-all authorizer"


def test_graphql_post_routes_are_a_known_allow_list() -> None:
    """Freeze the set of POST routes under /graphql*.

    A newly added POST route (a potential resolver-bypass) breaks this test until it is
    added to the matrix above *and* gated in the parametrized spec.
    """
    app = _build_app()
    post_routes = {
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/graphql")
        and "POST" in getattr(route, "methods", set())
    }
    assert post_routes == {"/graphql", "/graphql/rust"}
