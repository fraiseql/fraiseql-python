"""Fixtures for the RBAC integration tests."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from fraiseql.db import FraiseQLRepository

MIGRATIONS = Path(__file__).parents[4] / "src" / "fraiseql" / "enterprise" / "migrations"


@pytest_asyncio.fixture
async def rbac_pool(postgres_url, test_schema) -> AsyncIterator[AsyncConnectionPool]:
    """A pool whose connections all use the class's schema, with 002_rbac_tables.sql applied."""
    pool = AsyncConnectionPool(
        postgres_url,
        min_size=1,
        max_size=3,
        open=False,
        kwargs={"options": f"-c search_path={test_schema},public"},
    )
    await pool.open()
    async with pool.connection() as conn:
        await conn.execute((MIGRATIONS / "002_rbac_tables.sql").read_text())
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def rbac_repo(rbac_pool) -> FraiseQLRepository:
    return FraiseQLRepository(rbac_pool)
