"""An APQ request whose query doesn't hash to its sha256Hash is refused, and nothing is stored.

Otherwise a client could store any text under the hash of a query other clients use
(hash-only requests would then run that text, and its response could be cached).
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

LEGIT = '{ hello(name: "legit") }'
LEGIT_HASH = hashlib.sha256(LEGIT.encode()).hexdigest()
POISON = '{ hello(name: "poison") }'


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


def _body(sha256_hash: str, query: str | None = None) -> dict:
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
        return config, create_fraiseql_app(config=config, queries=[hello], lifespan=_noop_lifespan)

    return _make


def _post_all(app: FastAPI, *bodies: dict) -> list[tuple[int, dict]]:
    results = []
    with (
        patch("fraiseql.fastapi.dependencies.get_db_pool", return_value=MagicMock()),
        TestClient(app) as client,
    ):
        for body in bodies:
            response = client.post("/graphql", json=body)
            result = response.json()
            result.pop("extensions", None)  # execution metadata (development)
            results.append((response.status_code, result))
    return results


def _assert_mismatch(status: int, result: dict) -> None:
    assert status == 400
    assert "data" not in result
    assert result["errors"][0]["message"] == "provided sha does not match query"
    assert result["errors"][0]["extensions"]["code"] == "BAD_REQUEST"


@pytest.mark.parametrize("mode", ["optional", "required"])
def test_mismatched_hash_is_refused_and_not_stored(make_app, mode) -> None:
    config, app = make_app(apq_mode=mode)

    [(status, result)] = _post_all(app, _body(LEGIT_HASH, POISON))

    _assert_mismatch(status, result)
    assert get_apq_backend(config).get_persisted_query(LEGIT_HASH) is None
    assert get_persisted_query(LEGIT_HASH) is None


def test_registered_hash_cannot_be_poisoned(make_app) -> None:
    _, app = make_app(apq_mode="optional", apq_cache_responses=True)

    (_, registered), (status, poisoned), (_, hash_only) = _post_all(
        app, _body(LEGIT_HASH, LEGIT), _body(LEGIT_HASH, POISON), _body(LEGIT_HASH)
    )

    assert registered == {"data": {"hello": "Hello, legit!"}}
    _assert_mismatch(status, poisoned)
    assert hash_only == {"data": {"hello": "Hello, legit!"}}


def test_required_mode_known_hash_with_other_text_is_refused(make_app) -> None:
    config, app = make_app(apq_mode="required")
    get_apq_backend(config).register_queries([LEGIT])

    [(status, result)] = _post_all(app, _body(LEGIT_HASH, POISON))

    _assert_mismatch(status, result)
    assert get_apq_backend(config).get_persisted_query(LEGIT_HASH) == LEGIT


def test_matching_hash_still_registers(make_app) -> None:
    _, app = make_app(apq_mode="optional")

    (_, first), (_, second) = _post_all(app, _body(LEGIT_HASH, LEGIT), _body(LEGIT_HASH))

    assert first == second == {"data": {"hello": "Hello, legit!"}}
