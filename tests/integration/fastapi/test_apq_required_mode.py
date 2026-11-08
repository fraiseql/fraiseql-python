"""apq_mode='required' runs only the persisted queries the server already knows.

A client must not be able to get a new query approved by sending its text with its hash
(the APQ registration request): in required mode that request is refused unless the hash
is already stored, and a stored hash runs the stored text, not the text sent with it.
"""

import hashlib
from collections.abc import Iterator
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.middleware.apq_caching import clear_backend_cache, get_apq_backend
from fraiseql.storage.apq_store import clear_storage, get_persisted_query

pytestmark = pytest.mark.integration


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


def _sha(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()


def _apq_body(sha256_hash: str, query: str | None = None) -> dict:
    body: dict = {"extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha256_hash}}}
    if query is not None:
        body["query"] = query
    return body


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

    def _make(**config_kwargs) -> tuple[FraiseQLConfig, FastAPI]:
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test", auth_enabled=False, **config_kwargs
        )
        app = create_fraiseql_app(config=config, queries=[hello], lifespan=_noop_lifespan)
        return config, app

    return _make


def _post(app: FastAPI, body: dict, path: str = "/graphql") -> dict:
    with (
        patch("fraiseql.fastapi.dependencies.get_db_pool", return_value=MagicMock()),
        TestClient(app) as client,
    ):
        result = client.post(path, json=body).json()
    result.pop("extensions", None)  # execution metadata (development)
    return result


def test_required_mode_refuses_to_register_an_unknown_hash(make_app) -> None:
    config, app = make_app(apq_mode="required")
    query = '{ hello(name: "unapproved") }'

    result = _post(app, _apq_body(_sha(query), query))

    assert "data" not in result
    assert result["errors"][0]["extensions"]["code"] == "PERSISTED_QUERY_NOT_IN_LIST"
    assert result["errors"][0]["message"] == "PersistedQueryNotInList"
    # Nothing was stored: the next hash-only request is still unknown.
    assert get_apq_backend(config).get_persisted_query(_sha(query)) is None
    assert get_persisted_query(_sha(query)) is None
    again = _post(app, _apq_body(_sha(query)))
    assert again["errors"][0]["extensions"]["code"] == "PERSISTED_QUERY_NOT_FOUND"


def test_required_mode_runs_a_registered_hash_sent_with_its_query(make_app) -> None:
    config, app = make_app(apq_mode="required")
    query = '{ hello(name: "approved") }'
    get_apq_backend(config).register_queries([query])

    assert _post(app, _apq_body(_sha(query), query)) == {"data": {"hello": "Hello, approved!"}}
    assert _post(app, _apq_body(_sha(query))) == {"data": {"hello": "Hello, approved!"}}


def test_required_mode_never_runs_the_text_sent_with_a_known_hash(make_app) -> None:
    config, app = make_app(apq_mode="required")
    approved = '{ hello(name: "approved") }'
    get_apq_backend(config).register_queries([approved])

    result = _post(app, _apq_body(_sha(approved), '{ hello(name: "swapped") }'))

    # The text doesn't match the hash: refused (see test_apq_hash_mismatch.py)
    assert "data" not in result
    assert result["errors"][0]["message"] == "provided sha does not match query"


def test_optional_mode_still_registers_on_first_request(make_app) -> None:
    config, app = make_app(apq_mode="optional")
    query = '{ hello(name: "new") }'

    assert _post(app, _apq_body(_sha(query), query)) == {"data": {"hello": "Hello, new!"}}
    assert get_apq_backend(config).get_persisted_query(_sha(query)) == query
    assert _post(app, _apq_body(_sha(query))) == {"data": {"hello": "Hello, new!"}}


def test_required_mode_refuses_the_rust_endpoint(make_app) -> None:
    _, app = make_app(apq_mode="required", enable_rust_endpoint=True)

    result = _post(app, {"query": "{ hello }"}, path="/graphql/rust")

    assert result["errors"][0]["extensions"]["code"] == "ARBITRARY_QUERY_NOT_ALLOWED"
