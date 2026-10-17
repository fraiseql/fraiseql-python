"""Shared fixtures for all integration tests."""

import psycopg_pool
import pytest

from fraiseql.gql.builders import SchemaRegistry


@pytest.fixture(scope="class")
async def meta_test_pool(postgres_url):
    """Shared database pool for integration tests.

    Scope: class (one pool per test class)
    """
    pool = psycopg_pool.AsyncConnectionPool(
        postgres_url,
        min_size=1,
        max_size=5,  # Increased for concurrent tests
        timeout=30,
        open=False,
    )
    await pool.open()
    await pool.wait()

    yield pool

    await pool.close()


@pytest.fixture(scope="class")
def meta_test_schema():
    """Shared schema registry for integration tests.

    This registry is cleared before each test class to ensure isolation.
    Individual tests should register their own types/queries/mutations.
    """
    registry = SchemaRegistry.get_instance()
    registry.clear()  # Start fresh
    return registry
