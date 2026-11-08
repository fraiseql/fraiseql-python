"""@app.on_event("startup") / ("shutdown") handlers run on a fraiseql app.

create_fraiseql_app gives the FastAPI app a lifespan, and Starlette ignores the
on_event handlers of an app with a lifespan: setup registered that way never ran.
"""

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app

pytestmark = pytest.mark.usefixtures("clear_registry")


@fraiseql.type
class Ping:
    ok: bool


async def ping(info) -> Ping:
    return Ping(ok=True)


@pytest.fixture
def no_pool(monkeypatch):
    """Skip the database pool the lifespan opens: these handlers need none."""

    async def fake_pool(*args, **kwargs):
        class Pool:
            async def close(self) -> None:
                pass

        return Pool()

    monkeypatch.setattr("fraiseql.fastapi.app.create_db_pool", fake_pool)
    from fraiseql.fastapi.dependencies import set_db_pool

    set_db_pool(None)
    yield
    set_db_pool(None)


@pytest.mark.parametrize("own_lifespan", [False, True])
def test_on_event_handlers_run(no_pool, own_lifespan) -> None:
    calls = []

    @asynccontextmanager
    async def lifespan(app):
        calls.append("lifespan start")
        yield
        calls.append("lifespan end")

    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[Ping],
        queries=[fraiseql.query(ping)],
        production=False,
        lifespan=lifespan if own_lifespan else None,
    )

    @app.on_event("startup")
    async def started() -> None:
        calls.append("startup")

    @app.on_event("shutdown")
    def stopped() -> None:
        calls.append("shutdown")

    with TestClient(app):
        assert "startup" in calls
        assert "shutdown" not in calls

    assert calls[-1] == "shutdown" or calls[-2:] == ["shutdown", "lifespan end"]
    assert calls.count("startup") == 1
    assert calls.count("shutdown") == 1
