"""``include_execution_metadata`` adds the execution timing to responses.

The router added ``extensions.execution`` outside production and never read
``FraiseQLConfig.include_execution_metadata``, so setting it changed nothing.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.builders import SchemaRegistry

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.integration


@fraiseql.query
async def ping(info) -> str:
    return "pong"


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


@pytest.fixture(autouse=True)
def _clean_registry():
    import fraiseql.fastapi.app as app_mod
    import fraiseql.fastapi.dependencies as deps
    from fraiseql.core.graphql_type import _graphql_type_cache

    def _reset() -> None:
        SchemaRegistry.get_instance().clear()
        _graphql_type_cache.clear()
        deps._db_pool = None
        deps._auth_provider = None
        deps._fraiseql_config = None
        app_mod._global_turbo_registry = None

    _reset()
    yield
    _reset()


def _post(**config: Any) -> dict[str, Any]:
    app = create_fraiseql_app(
        config=FraiseQLConfig(database_url="postgresql://test:test@localhost/test", **config),
        queries=[ping],
        lifespan=_noop_lifespan,
    )
    with TestClient(app) as client:
        return client.post("/graphql", json={"query": "{ ping }"}).json()


def test_production_with_the_setting_includes_it() -> None:
    body = _post(environment="production", include_execution_metadata=True)
    assert body["data"] == {"ping": "pong"}
    assert body["extensions"]["execution"]["time_ms"] >= 0


def test_production_without_the_setting_leaves_it_out() -> None:
    body = _post(environment="production")
    assert body["data"] == {"ping": "pong"}
    assert "extensions" not in body


def test_development_includes_it() -> None:
    assert "execution" in _post(environment="development")["extensions"]
