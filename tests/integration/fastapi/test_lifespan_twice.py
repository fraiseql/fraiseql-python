"""An app's lifespan can run twice: each startup opens a pool the queries then use.

The default lifespan closed its pool on shutdown but left it set as the global
pool, and the next startup kept an existing pool rather than open one, so after
a first ``with TestClient(app)`` every query failed on the closed pool. A pool
left behind like that also hid that an app passed with ``app=`` never opened
one. The global is now cleared on shutdown, when it is still the pool the
lifespan set.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.sql import SQL

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.db import DatabaseQuery
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.dependencies import get_db_pool, set_db_pool

pytestmark = [pytest.mark.integration, pytest.mark.database]


@fraiseql.type
class Ping:
    answer: int


async def ping(info) -> Ping:
    rows = await info.context["db"].run(DatabaseQuery(SQL("SELECT 42 AS answer"), {}))
    return Ping(answer=rows[0]["answer"])


def _ask(client: TestClient) -> dict:
    body = client.post("/graphql", json={"query": "{ ping { answer } }"}).json()
    return {key: value for key, value in body.items() if key != "extensions"}


def _app(postgres_url: str, **kwargs) -> FastAPI:
    fraiseql.query(ping)
    return create_fraiseql_app(database_url=postgres_url, types=[Ping], production=False, **kwargs)


@pytest.mark.parametrize("lifespan_kind", ["default", "user", "existing_app"])
def test_each_startup_opens_a_pool(clear_registry, postgres_url, lifespan_kind) -> None:
    @asynccontextmanager
    async def user_lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield

    kwargs = {
        "default": {},
        "user": {"lifespan": user_lifespan},
        "existing_app": {"app": FastAPI()},
    }[lifespan_kind]
    app = _app(postgres_url, **kwargs)

    for _ in range(2):
        with TestClient(app) as client:
            assert _ask(client) == {"data": {"ping": {"answer": 42}}}
        with pytest.raises(RuntimeError, match="Database pool not initialized"):
            get_db_pool()


async def test_a_pool_set_beforehand_is_kept(clear_registry, postgres_url, class_db_pool) -> None:
    """A pool the caller set (a test fixture's) is used, and left open and set."""
    set_db_pool(class_db_pool)
    app = _app(postgres_url)

    for _ in range(2):
        with TestClient(app) as client:
            assert _ask(client) == {"data": {"ping": {"answer": 42}}}

    assert get_db_pool() is class_db_pool
    assert not class_db_pool.closed
