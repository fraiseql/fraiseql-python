"""The ``postgresql`` APQ storage backend against a real PostgreSQL, through the HTTP app.

Persisted queries registered by one app must be in the database, so another app (another
instance, or the same one after a restart) finds them.
"""

import hashlib
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.middleware.apq_caching import clear_backend_cache, get_apq_backend
from fraiseql.storage.apq_store import clear_storage
from fraiseql.storage.backends.postgresql import PostgreSQLAPQBackend

pytestmark = [pytest.mark.integration, pytest.mark.database]


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


def _apq_body(query: str, *, with_query: bool = True) -> dict:
    sha = hashlib.sha256(query.encode()).hexdigest()
    body: dict = {"extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}}}
    if with_query:
        body["query"] = query
    return body


@pytest.fixture
def table_prefix(postgres_url) -> Iterator[str]:
    prefix = f"apq_{uuid.uuid4().hex[:8]}_"
    yield prefix
    with psycopg.connect(postgres_url, autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {prefix}queries, {prefix}responses")


@pytest.fixture
def make_app(clear_registry, postgres_url, table_prefix):
    @fraiseql.query
    def hello(info, name: str = "World") -> str:
        return f"Hello, {name}!"

    created: list[FraiseQLConfig] = []

    def _make(**config_kwargs) -> tuple[FraiseQLConfig, FastAPI]:
        # A fresh backend per app, as in a new process.
        clear_backend_cache()
        clear_storage()
        config = FraiseQLConfig(
            database_url=postgres_url,
            auth_enabled=False,
            apq_storage_backend="postgresql",
            apq_backend_config={"table_prefix": table_prefix},
            **config_kwargs,
        )
        created.append(config)
        return config, create_fraiseql_app(config=config, queries=[hello], lifespan=_noop_lifespan)

    yield _make
    for config in created:
        backend = get_apq_backend(config)
        if isinstance(backend, PostgreSQLAPQBackend):
            backend.close()
    clear_backend_cache()
    clear_storage()


def _post(app: FastAPI, body: dict) -> dict:
    with (
        patch("fraiseql.fastapi.dependencies.get_db_pool", return_value=MagicMock()),
        TestClient(app) as client,
    ):
        result = client.post("/graphql", json=body).json()
    result.pop("extensions", None)  # execution metadata (development)
    return result


def test_registered_query_is_stored_in_postgresql(make_app, postgres_url, table_prefix) -> None:
    _, app = make_app()
    query = '{ hello(name: "pg") }'

    assert _post(app, _apq_body(query)) == {"data": {"hello": "Hello, pg!"}}

    with psycopg.connect(postgres_url) as conn:
        rows = conn.execute(f"SELECT hash, query FROM {table_prefix}queries").fetchall()
    assert rows == [(hashlib.sha256(query.encode()).hexdigest(), query)]


def test_another_app_finds_a_query_registered_by_the_first(make_app) -> None:
    query = '{ hello(name: "shared") }'
    _, first = make_app()
    _post(first, _apq_body(query))

    _, second = make_app()  # new backend, empty process memory

    assert _post(second, _apq_body(query, with_query=False)) == {
        "data": {"hello": "Hello, shared!"}
    }


def test_required_mode_runs_queries_stored_in_postgresql(make_app) -> None:
    query = '{ hello(name: "approved") }'
    config, _ = make_app()
    get_apq_backend(config).register_queries([query])

    _, app = make_app(apq_mode="required")

    assert _post(app, _apq_body(query, with_query=False)) == {"data": {"hello": "Hello, approved!"}}


def test_cached_response_round_trips_with_tenants(postgres_url, table_prefix) -> None:
    backend = PostgreSQLAPQBackend({"table_prefix": table_prefix}, database_url=postgres_url)
    try:
        backend.store_cached_response("h1", {"data": {"v": "global"}})
        backend.store_cached_response("h1", {"data": {"v": "a"}}, context={"tenant_id": "a"})
        backend.store_cached_response("h1", {"data": {"v": "a2"}}, context={"tenant_id": "a"})

        assert backend.get_cached_response("h1") == {"data": {"v": "global"}}
        assert backend.get_cached_response("h1", context={"tenant_id": "a"}) == {
            "data": {"v": "a2"}
        }
        assert backend.get_cached_response("h1", context={"tenant_id": "b"}) is None
    finally:
        backend.close()


def test_backend_does_not_connect_until_used() -> None:
    backend = PostgreSQLAPQBackend({}, database_url="postgresql://nobody@127.0.0.1:1/none")

    assert backend._pool is None


def test_response_cache_is_stored_in_postgresql(make_app, postgres_url, table_prefix) -> None:
    query = '{ hello(name: "cached") }'
    _, app = make_app(apq_cache_responses=True)
    _post(app, _apq_body(query))

    with psycopg.connect(postgres_url) as conn:
        rows = conn.execute(f"SELECT hash, response FROM {table_prefix}responses").fetchall()
    assert rows == [
        (hashlib.sha256(query.encode()).hexdigest(), {"data": {"hello": "Hello, cached!"}})
    ]

    _, other_instance = make_app(apq_cache_responses=True)
    assert _post(other_instance, _apq_body(query, with_query=False)) == {
        "data": {"hello": "Hello, cached!"}
    }


def test_concurrent_first_calls_from_worker_threads_create_the_tables_once(
    postgres_url, table_prefix
) -> None:
    """The route calls the backend in worker threads: the first calls may race."""
    from concurrent.futures import ThreadPoolExecutor

    backend = PostgreSQLAPQBackend({"table_prefix": table_prefix}, database_url=postgres_url)
    queries = [f'{{ hello(name: "t{i}") }}' for i in range(8)]
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda q: backend.register_queries([q]), queries))
    finally:
        backend.close()

    with psycopg.connect(postgres_url) as conn:
        stored = {row[0] for row in conn.execute(f"SELECT query FROM {table_prefix}queries")}
    assert stored == set(queries)
