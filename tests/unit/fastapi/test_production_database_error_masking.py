"""With environment="production", a database error reaches the client as a generic error.

A psycopg error's message carries the failing SQL (``LINE 1: SELECT ...``) and
relation names. Both the single-field (unified executor) and the multi-field
(Rust merge) paths used to return it verbatim in production.
"""

from contextlib import asynccontextmanager

import psycopg.errors
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.errors.masking import is_database_error
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.schema_builder import SchemaRegistry

SQL_TEXT = 'relation "tb_secret" does not exist\nLINE 1: SELECT "data"::text FROM "tb_secret"'


@asynccontextmanager
async def noop_lifespan(app: FastAPI):
    yield


@fraiseql.type
class Gadget:
    id: int


@fraiseql.query
async def gadgets(info) -> list[Gadget]:
    return [Gadget(id=1)]


@fraiseql.query
async def broken_gadgets(info) -> list[Gadget]:
    raise psycopg.errors.UndefinedTable(SQL_TEXT)


@fraiseql.query
async def raised_gadgets(info) -> list[Gadget]:
    # str() of a server-side RAISE holds DETAIL, HINT and CONTEXT after the message
    raise psycopg.errors.RaiseException(
        "out of stock\nDETAIL:  sku 42\nCONTEXT:  PL/pgSQL function app.fn_secret() line 3"
    )


@fraiseql.query
async def refused_gadgets(info) -> list[Gadget]:
    raise ValueError("gadgets are closed today")


@pytest.fixture(autouse=True)
def clear_registry():
    from fraiseql.core.graphql_type import _graphql_type_cache

    SchemaRegistry.get_instance().clear()
    _graphql_type_cache.clear()
    yield
    SchemaRegistry.get_instance().clear()
    _graphql_type_cache.clear()


def _post(environment: str, query: str) -> dict:
    config = FraiseQLConfig(
        database_url="postgresql://test:test@localhost/test", environment=environment
    )
    app = create_fraiseql_app(
        config=config,
        types=[Gadget],
        queries=[gadgets, broken_gadgets, raised_gadgets, refused_gadgets],
        lifespan=noop_lifespan,
    )
    with TestClient(app) as client:
        return client.post("/graphql", json={"query": query}).json()


@pytest.mark.parametrize(
    "query",
    ["{ brokenGadgets { id } }", "{ gadgets { id } brokenGadgets { id } }"],
    ids=["single-field", "multi-field"],
)
def test_production_hides_database_error(query: str) -> None:
    body = _post("production", query)

    assert "tb_secret" not in str(body)
    [error] = body["errors"]
    assert error["message"] == "Internal server error"
    assert error["extensions"] == {"code": "INTERNAL_SERVER_ERROR"}
    assert error["path"] == ["brokenGadgets"]


@pytest.mark.parametrize(
    "query",
    ["{ brokenGadgets { id } }", "{ gadgets { id } brokenGadgets { id } }"],
    ids=["single-field", "multi-field"],
)
def test_development_keeps_database_error(query: str) -> None:
    body = _post("development", query)

    [error] = body["errors"]
    assert error["message"] == SQL_TEXT


@pytest.mark.parametrize(
    "query",
    ["{ refusedGadgets { id } }", "{ gadgets { id } refusedGadgets { id } }"],
    ids=["single-field", "multi-field"],
)
def test_production_keeps_other_resolver_errors(query: str) -> None:
    body = _post("production", query)

    [error] = body["errors"]
    assert error["message"] == "gadgets are closed today"


@pytest.mark.parametrize(
    "query",
    ["{ raisedGadgets { id } }", "{ gadgets { id } raisedGadgets { id } }"],
    ids=["single-field", "multi-field"],
)
def test_production_keeps_the_message_a_function_raises(query: str) -> None:
    body = _post("production", query)

    assert "fn_secret" not in str(body)
    [error] = body["errors"]
    assert error["message"] == "out of stock"
    assert error["path"] == ["raisedGadgets"]


def test_is_database_error_follows_the_cause_chain() -> None:
    try:
        try:
            raise psycopg.errors.UniqueViolation("duplicate key")
        except psycopg.Error as db_error:
            raise RuntimeError("wrapped") from db_error
    except RuntimeError as wrapped:
        assert is_database_error(wrapped)

    assert not is_database_error(ValueError("nope"))
    assert not is_database_error(None)


@pytest.mark.parametrize(("environment", "leaks"), [("production", False), ("development", True)])
def test_unified_executor_failure_message(monkeypatch, environment: str, leaks: bool) -> None:
    """An exception escaping execution is answered generically in production."""
    from fraiseql.execution import unified_executor

    async def explode(*args, **kwargs):
        raise RuntimeError(SQL_TEXT)

    monkeypatch.setattr(unified_executor, "execute_graphql", explode)
    body = _post(environment, "{ gadgets { id } }")

    [error] = body["errors"]
    assert ("tb_secret" in error["message"]) is leaks
