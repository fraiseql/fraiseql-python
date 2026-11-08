"""``apq_queries_dir``: the operations in its files are pre-registered persisted queries."""

import hashlib
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.middleware.apq_caching import clear_backend_cache
from fraiseql.storage.apq_store import clear_storage

pytestmark = pytest.mark.integration


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


def _hash_only(query: str) -> dict:
    sha = hashlib.sha256(query.encode()).hexdigest()
    return {"extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}}}


@pytest.fixture(autouse=True)
def _clean_apq_state() -> Iterator[None]:
    clear_backend_cache()
    clear_storage()
    yield
    clear_backend_cache()
    clear_storage()


@pytest.fixture
def make_app(clear_registry):
    @fraiseql.query
    def hello(info, name: str = "World") -> str:
        return f"Hello, {name}!"

    def _make(**config_kwargs) -> FastAPI:
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test", auth_enabled=False, **config_kwargs
        )
        return create_fraiseql_app(config=config, queries=[hello], lifespan=_noop_lifespan)

    return _make


def _post(app: FastAPI, body: dict) -> dict:
    with (
        patch("fraiseql.fastapi.dependencies.get_db_pool", return_value=MagicMock()),
        TestClient(app) as client,
    ):
        result = client.post("/graphql", json=body).json()
    result.pop("extensions", None)  # execution metadata (development)
    return result


def test_required_mode_runs_the_operations_of_apq_queries_dir(make_app, tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "greet.graphql").write_text(
        'query Greet { hello(name: "dir") }\n\nquery Plain { hello }\n'
    )
    app = make_app(apq_mode="required", apq_queries_dir=str(tmp_path))

    assert _post(app, _hash_only('query Greet { hello(name: "dir") }')) == {
        "data": {"hello": "Hello, dir!"}
    }
    assert _post(app, _hash_only("query Plain { hello }")) == {"data": {"hello": "Hello, World!"}}
    unknown = _post(app, _hash_only('query Other { hello(name: "x") }'))
    assert unknown["errors"][0]["extensions"]["code"] == "PERSISTED_QUERY_NOT_FOUND"


def test_missing_apq_queries_dir_fails_at_startup(make_app, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="apq_queries_dir"):
        make_app(apq_mode="required", apq_queries_dir=str(tmp_path / "missing"))
