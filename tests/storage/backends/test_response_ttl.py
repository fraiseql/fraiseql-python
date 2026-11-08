"""``apq_response_cache_ttl``: cached APQ responses expire."""

import uuid

import psycopg
import pytest

from fraiseql.fastapi import FraiseQLConfig
from fraiseql.storage.backends import memory as memory_module
from fraiseql.storage.backends.factory import create_apq_backend
from fraiseql.storage.backends.memory import MemoryAPQBackend
from fraiseql.storage.backends.postgresql import PostgreSQLAPQBackend

RESPONSE = {"data": {"hello": "x"}}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(memory_module.time, "monotonic", clock)
    return clock


def test_memory_response_expires_after_ttl(clock) -> None:
    backend = MemoryAPQBackend(response_ttl=60)
    backend.store_cached_response("h", RESPONSE, context={"tenant_id": "t"})

    clock.now += 59
    assert backend.get_cached_response("h", context={"tenant_id": "t"}) == RESPONSE
    clock.now += 1
    assert backend.get_cached_response("h", context={"tenant_id": "t"}) is None
    assert backend.get_storage_stats()["cached_responses"] == 0


def test_memory_response_ttl_zero_never_expires(clock) -> None:
    backend = MemoryAPQBackend(response_ttl=0)
    backend.store_cached_response("h", RESPONSE)

    clock.now += 10**9
    assert backend.get_cached_response("h") == RESPONSE


def test_factory_passes_apq_response_cache_ttl() -> None:
    config = FraiseQLConfig(
        database_url="postgresql://localhost/test",
        apq_response_cache_ttl=42,
    )
    assert create_apq_backend(config)._response_ttl == 42

    pg_config = FraiseQLConfig(
        database_url="postgresql://localhost/test",
        apq_storage_backend="postgresql",
        apq_response_cache_ttl=42,
    )
    assert create_apq_backend(pg_config)._response_ttl == 42


@pytest.mark.integration
@pytest.mark.database
def test_postgresql_response_expires_after_ttl(postgres_url) -> None:
    prefix = f"apq_ttl_{uuid.uuid4().hex[:8]}_"
    backend = PostgreSQLAPQBackend(
        {"table_prefix": prefix}, database_url=postgres_url, response_ttl=60
    )
    try:
        backend.store_cached_response("h", RESPONSE)
        assert backend.get_cached_response("h") == RESPONSE

        with psycopg.connect(postgres_url, autocommit=True) as conn:
            conn.execute(f"UPDATE {prefix}responses SET updated_at = NOW() - interval '61 seconds'")
        assert backend.get_cached_response("h") is None
    finally:
        backend.close()
        with psycopg.connect(postgres_url, autocommit=True) as conn:
            conn.execute(f"DROP TABLE IF EXISTS {prefix}queries, {prefix}responses")
