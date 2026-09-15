"""Regression tests for issue #534.

``session_variables`` (#310) never reached PostgreSQL on the standard router, for two
independent reasons:

* the per-request context returned by ``context_getter`` was merged into the GraphQL
  context but never into ``FraiseQLRepository.context``, which is what
  ``_set_session_variables()`` reads;
* ``find()``, ``find_one()``, ``count()`` and the other read helpers took a pool
  connection and queried it without ever calling ``_set_session_variables()``.

Forwarding the built-in keys as well exposed two latent crashes in
``_set_session_variables()``: ``user_id`` without ``roles`` ran an ``is_super_admin``
lookup that PostgreSQL rejects as a syntax error (aborting the transaction), and
``roles`` given as ``list[str]`` (``UserContext.roles``) raised ``AttributeError``.

The end-to-end check against a real PostgreSQL lives in
``tests/integration/fastapi/test_issue_534_session_variables_e2e.py``.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Any, Self
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.db import FraiseQLRepository
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.fastapi.dependencies import set_db_pool, set_fraiseql_config
from fraiseql.fastapi.routers import create_graphql_router
from fraiseql.gql.schema_builder import build_fraiseql_schema

pytestmark = pytest.mark.unit

STARTED_AT = "set_config('fraiseql.started_at', clock_timestamp()::text, true)"
SESSION_PREFIX = "SELECT set_config("
PIPELINE = "<rust pipeline>"


class _Config:
    """Minimal stand-in for ``FraiseQLConfig`` carrying ``session_variables``."""

    def __init__(self, session_variables: dict[str, str]) -> None:
        self.session_variables = session_variables


class _Cursor:
    """Cursor that records every statement on its connection's shared log."""

    description = (("total",),)

    def __init__(self, log: list[tuple[Any, Any]]) -> None:
        self._log = log

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, statement: Any, params: Any = None) -> None:
        self._log.append((statement if isinstance(statement, str) else "<query>", params))

    async def fetchone(self) -> tuple[int]:
        return (0,)

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return []


class _Connection:
    def __init__(self) -> None:
        self.log: list[tuple[Any, Any]] = []

    def cursor(self, *_: object, **__: object) -> _Cursor:
        return _Cursor(self.log)


class _Pool:
    """Pool that always hands out the same recording connection."""

    def __init__(self) -> None:
        self.conn = _Connection()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_Connection]:
        yield self.conn


async def _fake_pipeline(conn: _Connection, *_: object, **__: object) -> list[Any]:
    conn.log.append((PIPELINE, None))
    return []


def _pairs(params: list[str] | None) -> list[tuple[str, str]]:
    """Pair up the flat ``set_config`` bind parameters into ``(name, value)``."""
    params = params or []
    return list(zip(params[::2], params[1::2], strict=True))


async def _session_statement(context: dict[str, Any]) -> tuple[str, list[tuple[str, str]]]:
    """Run ``_set_session_variables`` and return its only statement with paired params."""
    conn = _Connection()
    await FraiseQLRepository(pool=_Pool(), context=context)._set_session_variables(conn.cursor())
    assert len(conn.log) == 1, f"expected one round trip, got {conn.log}"
    statement, params = conn.log[0]
    return statement, _pairs(params)


# ---------------------------------------------------------------------------
# _set_session_variables: one statement, no crash on real-world context shapes
# ---------------------------------------------------------------------------


class TestSetSessionVariables:
    @pytest.mark.asyncio
    async def test_user_id_without_roles_does_not_query_user_roles(self) -> None:
        """No ``user_roles`` lookup: PostgreSQL rejects it and aborts the transaction."""
        statement, pairs = await _session_statement({"user_id": "u1"})

        assert "user_roles" not in statement
        assert ("app.user_id", "u1") in pairs
        assert ("app.is_super_admin", "false") in pairs

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("roles", "expected"),
        [
            (["super_admin"], "true"),
            (["viewer"], "false"),
            ([{"name": "super_admin"}], "true"),
            ([{"name": "viewer"}], "false"),
        ],
    )
    async def test_roles_as_strings_or_dicts(self, roles: list[Any], expected: str) -> None:
        """``UserContext.roles`` is ``list[str]``; the dict shape keeps working."""
        _, pairs = await _session_statement({"user_id": "u1", "roles": roles})

        assert ("app.is_super_admin", expected) in pairs

    @pytest.mark.asyncio
    async def test_none_values_are_not_forwarded(self) -> None:
        """A ``None`` context value is absent, never the string ``'None'``."""
        context = {
            "config": _Config({"locale": "app.locale"}),
            "tenant_id": None,
            "contact_id": None,
            "user_id": None,
            "locale": None,
        }
        statement, pairs = await _session_statement(context)

        assert pairs == []
        assert statement == f"SELECT {STARTED_AT}"

    @pytest.mark.asyncio
    async def test_every_setting_goes_in_one_statement(self) -> None:
        """Built-ins, then configured variables, then ``started_at`` — one round trip."""
        context = {
            "config": _Config({"locale": "app.locale", "timezone": "app.timezone"}),
            "tenant_id": "t1",
            "contact_id": "c1",
            "user_id": "u1",
            "roles": ["viewer"],
            "locale": "fr-FR",
            "timezone": "Europe/Paris",
        }
        statement, pairs = await _session_statement(context)

        assert pairs == [
            ("app.tenant_id", "t1"),
            ("app.contact_id", "c1"),
            ("app.user_id", "u1"),
            ("app.is_super_admin", "false"),
            ("app.locale", "fr-FR"),
            ("app.timezone", "Europe/Paris"),
        ]
        assert statement == "SELECT " + ", ".join(
            ["set_config(%s, %s, true)"] * len(pairs) + [STARTED_AT]
        )


# ---------------------------------------------------------------------------
# Read paths: session variables on the connection that runs the query
# ---------------------------------------------------------------------------

Read = Callable[[FraiseQLRepository], Awaitable[Any]]

_READS: dict[str, Read] = {
    "find": lambda repo: repo.find("v_label"),
    "find_one": lambda repo: repo.find_one("v_label"),
    "count": lambda repo: repo.count("v_label"),
    "exists": lambda repo: repo.exists("v_label"),
    "sum": lambda repo: repo.sum("v_label", "total"),
    "avg": lambda repo: repo.avg("v_label", "total"),
    "min": lambda repo: repo.min("v_label", "total"),
    "max": lambda repo: repo.max("v_label", "total"),
    "distinct": lambda repo: repo.distinct("v_label", "name"),
    "pluck": lambda repo: repo.pluck("v_label", "name"),
    "aggregate": lambda repo: repo.aggregate("v_label", {"total": "COUNT(*)"}),
    "batch_exists": lambda repo: repo.batch_exists("v_label", ["a", "b"]),
}


async def _run_read(read: Read, context: dict[str, Any]) -> list[tuple[Any, Any]]:
    pool = _Pool()
    with patch("fraiseql.db.execute_via_rust_pipeline", new=_fake_pipeline):
        await read(FraiseQLRepository(pool=pool, context=context))
    return pool.conn.log


class TestReadPathsApplySessionVariables:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", list(_READS))
    async def test_session_variables_precede_the_read_on_its_connection(self, name: str) -> None:
        """The ``set_config`` batch runs first, on the connection the read then uses."""
        context = {"config": _Config({"locale": "app.locale"}), "locale": "fr-FR"}
        log = await _run_read(_READS[name], context)

        assert len(log) == 2, log
        statement, params = log[0]
        assert statement.startswith(SESSION_PREFIX)
        assert ("app.locale", "fr-FR") in _pairs(params)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", list(_READS))
    async def test_no_extra_round_trip_without_session_context(self, name: str) -> None:
        """Apps that map no session variables pay nothing on the read path."""
        log = await _run_read(_READS[name], {"config": _Config({})})

        assert len(log) == 1, log
        assert not str(log[0][0]).startswith(SESSION_PREFIX)


# ---------------------------------------------------------------------------
# Request context reaches the repository through the router
# ---------------------------------------------------------------------------

_seen_repository_context: dict[str, Any] = {}


@fraiseql.query
async def session_probe(info) -> str:
    """Record what the request's repository sees, without touching the database."""
    _seen_repository_context.clear()
    _seen_repository_context.update(info.context["db"].context)
    return "ok"


class TestRequestContextReachesRepository:
    def test_adopt_copies_only_session_keys(self) -> None:
        """Built-ins and configured keys are copied; ``user`` and the rest are not."""
        repo = FraiseQLRepository(
            pool=_Pool(), context={"config": _Config({"locale": "app.locale"})}
        )
        user = object()
        repo._adopt_session_context(
            {
                "tenant_id": "t1",
                "contact_id": "c1",
                "user_id": "u1",
                "roles": ["viewer"],
                "locale": "fr-FR",
                "user": user,
                "db": repo,
                "is_viewer": True,
            }
        )

        assert {k: v for k, v in repo.context.items() if k != "config"} == {
            "tenant_id": "t1",
            "contact_id": "c1",
            "user_id": "u1",
            "roles": ["viewer"],
            "locale": "fr-FR",
        }

    @pytest.fixture
    def app(self) -> Iterator[FastAPI]:
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost:5432/test",
            environment="development",
            session_variables={"locale": "app.locale"},
        )
        set_db_pool(MagicMock())
        set_fraiseql_config(config)

        async def context_getter(request) -> dict[str, Any]:
            return {"locale": "fr-FR", "tenant_id": "t1", "user_id": "u1"}

        schema = build_fraiseql_schema(query_types=[session_probe])
        fastapi_app = FastAPI()
        fastapi_app.include_router(
            create_graphql_router(schema=schema, config=config, context_getter=context_getter)
        )
        yield fastapi_app
        set_db_pool(None)
        set_fraiseql_config(None)

    def test_context_getter_values_reach_repository_context(self, app: FastAPI) -> None:
        """The reporter's setup: ``context_getter`` returns the configured ``locale``."""
        response = TestClient(app).post("/graphql", json={"query": "{ sessionProbe }"})

        assert response.status_code == 200, response.text
        assert response.json()["data"] == {"sessionProbe": "ok"}
        assert _seen_repository_context.get("locale") == "fr-FR"
        assert _seen_repository_context["tenant_id"] == "t1"
        assert _seen_repository_context["user_id"] == "u1"
