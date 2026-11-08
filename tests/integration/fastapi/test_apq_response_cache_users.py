"""The APQ response cache never serves one user's response to another user.

An authenticated request's cached response is keyed by its user id as well as the hash,
the variables and the tenant; an authenticated request without a usable user id is not
cached at all.
"""

import hashlib
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.auth.base import UserContext
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.middleware.apq_caching import (
    clear_backend_cache,
    compute_response_cache_key,
    response_cache_user_id,
)
from fraiseql.storage.apq_store import clear_storage

pytestmark = pytest.mark.integration

QUERY = "{ whoami }"
HASH = hashlib.sha256(QUERY.encode()).hexdigest()


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


async def _context(request: Request) -> dict[str, Any]:
    """Same tenant for everyone; the user comes from a test header."""
    user_header = request.headers.get("x-test-user")
    if user_header is None:
        user = None
    elif user_header == "no-id":
        user = {"email": "someone@example.com"}  # authenticated, no stable id
    else:
        user = UserContext(user_id=user_header)
    return {"user": user, "authenticated": user is not None, "tenant_id": "t1"}


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
def app(clear_registry, calls) -> FastAPI:
    @fraiseql.query
    def whoami(info) -> str:
        user = info.context.get("user")
        name = getattr(user, "user_id", None) or "anonymous"
        calls.append(name)
        return name

    config = FraiseQLConfig(
        database_url="postgresql://localhost/test",
        auth_enabled=False,
        apq_cache_responses=True,
    )
    return create_fraiseql_app(
        config=config, queries=[whoami], context_getter=_context, lifespan=_noop_lifespan
    )


def _requests(app: FastAPI, *requests: tuple[str | None, bool]) -> list[dict]:
    """Send (user, with_query) APQ requests; return the bodies."""
    results = []
    with (
        patch("fraiseql.fastapi.dependencies.get_db_pool", return_value=MagicMock()),
        TestClient(app) as client,
    ):
        for user, with_query in requests:
            body: dict = {"extensions": {"persistedQuery": {"version": 1, "sha256Hash": HASH}}}
            if with_query:
                body["query"] = QUERY
            headers = {"x-test-user": user} if user is not None else {}
            result = client.post("/graphql", json=body, headers=headers).json()
            result.pop("extensions", None)  # execution metadata (development)
            results.append(result)
    return results


def test_one_users_cached_response_is_not_served_to_another(app, calls) -> None:
    a_first, b, a_again = _requests(app, ("alice", True), ("bob", False), ("alice", False))

    assert a_first == {"data": {"whoami": "alice"}}
    assert b == {"data": {"whoami": "bob"}}
    assert a_again == {"data": {"whoami": "alice"}}
    assert calls == ["alice", "bob"]  # alice's second request came from her own cache entry


def test_authenticated_request_without_user_id_is_not_cached(app, calls) -> None:
    _requests(app, ("no-id", True), ("no-id", False))

    assert calls == ["anonymous", "anonymous"]


def test_anonymous_requests_still_share_the_cache(app, calls) -> None:
    first, second = _requests(app, (None, True), (None, False))

    assert first == second == {"data": {"whoami": "anonymous"}}
    assert calls == ["anonymous"]


def test_user_id_from_context() -> None:
    assert response_cache_user_id({"user": None}) == (True, None)
    assert response_cache_user_id({}) == (True, None)
    assert response_cache_user_id({"user": UserContext(user_id="u1")}) == (True, "u1")
    assert response_cache_user_id({"user": {"user_id": 7}}) == (True, "7")
    assert response_cache_user_id({"user": {"sub": "auth0|x"}}) == (True, "auth0|x")
    assert response_cache_user_id({"user": {"email": "e"}}) == (False, None)
    assert response_cache_user_id({"user": None, "authenticated": True}) == (False, None)


def test_anonymous_key_is_unchanged_and_user_keys_differ() -> None:
    assert compute_response_cache_key(HASH) == HASH
    assert compute_response_cache_key(HASH, user_id="a") != compute_response_cache_key(
        HASH, user_id="b"
    )
    assert compute_response_cache_key(HASH, user_id="a") != HASH
