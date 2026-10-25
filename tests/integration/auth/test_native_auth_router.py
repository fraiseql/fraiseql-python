"""The native auth REST router over HTTP, against PostgreSQL."""

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from fraiseql.auth.native import apply_native_auth_schema
from fraiseql.auth.native.router import auth_router

pytestmark = [pytest.mark.integration, pytest.mark.database]

PASSWORD = "Str0ng!Passw0rd"


@pytest_asyncio.fixture
async def client(class_db_pool, test_schema, monkeypatch) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("JWT_SECRET_KEY", "a-configured-secret-key-for-tests")
    await apply_native_auth_schema(class_db_pool, schema=test_schema)

    app = FastAPI()
    app.state.db_pool = class_db_pool  # a psycopg AsyncConnectionPool
    app.state.test_schema = test_schema
    app.include_router(auth_router, prefix="/auth")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestNativeAuthRouterOnAPsycopgPool:
    async def test_register_login_and_me(self, client) -> None:
        body = {"email": "ada@example.com", "password": PASSWORD, "name": "Ada"}
        registered = await client.post("/auth/register", json=body)
        assert registered.status_code == 201, registered.text

        login = await client.post(
            "/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]

        me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200, me.text
        assert me.json()["email"] == "ada@example.com"

    async def test_wrong_password_is_refused(self, client) -> None:
        body = {"email": "bob@example.com", "password": PASSWORD, "name": "Bob"}
        assert (await client.post("/auth/register", json=body)).status_code == 201

        login = await client.post(
            "/auth/login", json={"email": "bob@example.com", "password": "Wr0ng!Passw0rd"}
        )
        assert login.status_code == 401
