"""APQ response cache (``apq_cache_responses=True``) through the HTTP app.

The response of an executed APQ query must be stored, whichever execution path built it,
so the next hash-only request with the same variables is answered from the cache.
"""

import hashlib
from collections.abc import Iterator
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import Response

import fraiseql
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.middleware.apq_caching import (
    clear_backend_cache,
    compute_response_cache_key,
    get_apq_backend,
    store_executed_response,
)
from fraiseql.storage.apq_store import clear_storage
from fraiseql.storage.backends.memory import MemoryAPQBackend

pytestmark = pytest.mark.integration

QUERY = "query Greet($name: String) { hello(name: $name) }"
HASH = hashlib.sha256(QUERY.encode()).hexdigest()


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


def _apq_body(variables: dict, *, with_query: bool) -> dict:
    body: dict = {
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": HASH}},
        "variables": variables,
    }
    if with_query:
        body["query"] = QUERY
    return body


@pytest.fixture(autouse=True)
def _clean_apq_state() -> Iterator[None]:
    clear_backend_cache()
    clear_storage()
    yield
    clear_backend_cache()
    clear_storage()


@pytest.fixture
def calls() -> list[str]:
    return []


@pytest.fixture
def make_app(clear_registry, calls):
    @fraiseql.query
    def hello(info, name: str = "World") -> str:
        calls.append(name)
        return f"Hello, {name}!"

    def _make(**config_kwargs) -> tuple[FraiseQLConfig, FastAPI]:
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test", auth_enabled=False, **config_kwargs
        )
        return config, create_fraiseql_app(config=config, queries=[hello], lifespan=_noop_lifespan)

    return _make


def _post_all(app: FastAPI, *bodies: dict) -> list[dict]:
    results = []
    with (
        patch("fraiseql.fastapi.dependencies.get_db_pool", return_value=MagicMock()),
        TestClient(app) as client,
    ):
        for body in bodies:
            result = client.post("/graphql", json=body).json()
            result.pop("extensions", None)  # execution metadata (development)
            results.append(result)
    return results


def test_hash_only_request_is_served_from_the_cache(make_app, calls) -> None:
    config, app = make_app(apq_cache_responses=True)

    first, second = _post_all(
        app,
        _apq_body({"name": "a"}, with_query=True),
        _apq_body({"name": "a"}, with_query=False),
    )

    assert first == second == {"data": {"hello": "Hello, a!"}}
    assert calls == ["a"]  # the second request did not run the resolver
    cached = get_apq_backend(config).get_cached_response(
        compute_response_cache_key(HASH, {"name": "a"})
    )
    assert cached == {"data": {"hello": "Hello, a!"}}


def test_other_variables_are_not_served_from_the_cache(make_app, calls) -> None:
    _, app = make_app(apq_cache_responses=True)

    _, other = _post_all(
        app,
        _apq_body({"name": "a"}, with_query=True),
        _apq_body({"name": "b"}, with_query=False),
    )

    assert other == {"data": {"hello": "Hello, b!"}}
    assert calls == ["a", "b"]


def test_nothing_is_cached_when_response_caching_is_off(make_app, calls) -> None:
    config, app = make_app(apq_cache_responses=False)

    _post_all(
        app,
        _apq_body({"name": "a"}, with_query=True),
        _apq_body({"name": "a"}, with_query=False),
    )

    assert calls == ["a", "a"]
    assert get_apq_backend(config).get_storage_stats()["cached_responses"] == 0


def _config() -> FraiseQLConfig:
    return FraiseQLConfig(database_url="postgresql://localhost/test", apq_cache_responses=True)


def test_rust_bytes_response_is_cached() -> None:
    backend = MemoryAPQBackend()
    result = Response(content=b'{"data":{"hello":"Hello, a!"}}', media_type="application/json")

    store_executed_response(
        result, hash_value=HASH, backend=backend, query_text=QUERY, config=_config()
    )

    assert backend.get_cached_response(HASH) == {"data": {"hello": "Hello, a!"}}


def test_mutation_response_is_not_cached() -> None:
    backend = MemoryAPQBackend()
    mutation = "mutation { createThing { id } }"

    store_executed_response(
        {"data": {"createThing": {"id": 1}}},
        hash_value="m",
        backend=backend,
        query_text=mutation,
        config=_config(),
    )

    assert backend.get_cached_response("m") is None


def test_execution_metadata_is_not_cached() -> None:
    backend = MemoryAPQBackend()

    store_executed_response(
        {"data": {"hello": "x"}, "extensions": {"execution": {"time_ms": 1}}},
        hash_value=HASH,
        backend=backend,
        query_text=QUERY,
        config=_config(),
    )

    assert backend.get_cached_response(HASH) == {"data": {"hello": "x"}}
