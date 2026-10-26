"""The ``postgresql`` APQ backend's lookups don't block the event loop.

The backend interface is synchronous and the ``postgresql`` backend runs a query per
lookup, so the ``/graphql`` route runs its calls in a worker thread
(``APQStorageBackend.blocking_io``). Each test's backend lookup waits for an event that
only another coroutine sets: it is set while the lookup waits only if the event loop
keeps running during the lookup.
"""

import asyncio
import hashlib
import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import fraiseql
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.middleware.apq_caching import clear_backend_cache
from fraiseql.storage.apq_store import clear_storage
from fraiseql.storage.backends.memory import MemoryAPQBackend
from fraiseql.storage.backends.postgresql import PostgreSQLAPQBackend

pytestmark = pytest.mark.integration

QUERY = '{ hello(name: "loop") }'
HASH = hashlib.sha256(QUERY.encode()).hexdigest()


class _GatedBackend(PostgreSQLAPQBackend):
    """A ``postgresql`` backend whose database calls wait for ``release``."""

    def __init__(self) -> None:
        super().__init__({"auto_create_tables": False}, database_url="postgresql://unused/x")
        self.started = threading.Event()
        self.release = threading.Event()
        self.released_in_time: list[bool] = []
        self.stored: dict[str, str] = {}

    def _wait(self) -> None:
        self.release.clear()
        self.started.set()
        # On the event loop, nothing can set ``release``: the wait times out.
        self.released_in_time.append(self.release.wait(timeout=2))

    def _fetch_one(self, sql: str, params: tuple | None = None) -> tuple | None:
        self._wait()
        if params and "FROM" in sql and "queries" in sql and params[0] in self.stored:
            return (self.stored[params[0]],)
        return None

    def _execute_query(self, sql: str, params: tuple | None = None) -> None:
        self._wait()
        if params and "INSERT INTO apq_queries" in sql:
            self.stored[params[0]] = params[1]


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


@pytest.fixture(autouse=True)
def _clean_apq_state() -> Iterator[None]:
    clear_backend_cache()
    clear_storage()
    yield
    clear_backend_cache()
    clear_storage()


@pytest.fixture
def app(clear_registry) -> FastAPI:
    @fraiseql.query
    def hello(info, name: str = "World") -> str:
        return f"Hello, {name}!"

    config = FraiseQLConfig(
        database_url="postgresql://localhost/unused",
        auth_enabled=False,
        apq_cache_responses=True,
    )
    return create_fraiseql_app(config=config, queries=[hello], lifespan=_noop_lifespan)


async def _post_while_releasing(app: FastAPI, backend: Any, body: dict) -> dict:
    """POST ``body``; a concurrent coroutine sets ``backend.release`` whenever a call waits."""

    async def release_each_call() -> None:
        while True:
            if backend.started.is_set():
                backend.started.clear()
                backend.release.set()
            await asyncio.sleep(0.001)

    with (
        patch("fraiseql.middleware.apq_caching.get_apq_backend", return_value=backend),
        patch("fraiseql.fastapi.dependencies.get_db_pool", return_value=MagicMock()),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            releaser = asyncio.create_task(release_each_call())
            try:
                response = await client.post("/graphql", json=body)
            finally:
                releaser.cancel()
    return response.json()


def _body(*, with_query: bool) -> dict:
    body: dict = {"extensions": {"persistedQuery": {"version": 1, "sha256Hash": HASH}}}
    if with_query:
        body["query"] = QUERY
    return body


async def test_a_lookup_of_an_unknown_hash_does_not_block_the_event_loop(app) -> None:
    backend = _GatedBackend()
    result = await _post_while_releasing(app, backend, _body(with_query=False))

    assert result["errors"][0]["extensions"]["code"] == "PERSISTED_QUERY_NOT_FOUND"
    assert backend.released_in_time
    assert all(backend.released_in_time)


async def test_registering_and_caching_a_query_does_not_block_the_event_loop(app) -> None:
    backend = _GatedBackend()
    result = await _post_while_releasing(app, backend, _body(with_query=True))

    assert result["data"] == {"hello": "Hello, loop!"}
    assert backend.stored == {HASH: QUERY}
    assert backend.released_in_time
    assert all(backend.released_in_time)


async def test_a_stored_query_runs_by_hash(app) -> None:
    backend = _GatedBackend()
    backend.stored[HASH] = QUERY
    result = await _post_while_releasing(app, backend, _body(with_query=False))

    assert result["data"] == {"hello": "Hello, loop!"}
    assert all(backend.released_in_time)


def test_only_backends_that_do_io_are_moved_off_the_loop() -> None:
    assert PostgreSQLAPQBackend.blocking_io is True
    assert MemoryAPQBackend.blocking_io is False
