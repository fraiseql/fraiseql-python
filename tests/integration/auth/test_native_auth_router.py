"""The native auth REST router over HTTP, against PostgreSQL."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from fraiseql import query
from fraiseql.auth.native import (
    TokenManager,
    apply_native_auth_schema,
    create_native_auth_provider,
    get_native_auth_router,
)
from fraiseql.auth.native.router import auth_router
from fraiseql.fastapi import create_fraiseql_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.database,
    pytest.mark.usefixtures("clear_registry"),
]

PASSWORD = "Str0ng!Passw0rd"
CONFIGURED_KEY = "a-configured-secret-key-for-tests"
# The key get_token_manager() used when JWT_SECRET_KEY was unset (before 1.31.0).
OLD_BUILT_IN_KEY = "test-secret-key-change-in-production"


@query
async def ping(info) -> str:
    return "pong"


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _register(client: httpx.AsyncClient, email: str) -> dict:
    body = {"email": email, "password": PASSWORD, "name": "Test User"}
    response = await client.post("/auth/register", json=body)
    assert response.status_code == 201, response.text
    return response.json()


@pytest_asyncio.fixture
async def provider(class_db_pool, test_schema, monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    await apply_native_auth_schema(class_db_pool, schema=test_schema)
    return await create_native_auth_provider(
        class_db_pool, schema=test_schema, secret_key=CONFIGURED_KEY
    )


@pytest_asyncio.fixture
async def client(provider) -> AsyncIterator[httpx.AsyncClient]:
    """An app with the router bound to the provider, as the docs set it up."""
    app = FastAPI()
    app.include_router(get_native_auth_router(provider), prefix="/auth")
    async with _client(app) as c:
        yield c


class TestNativeAuthRouterWithItsProvider:
    async def test_register_login_and_me(self, client, provider) -> None:
        await _register(client, "ada@example.com")

        login = await client.post(
            "/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]

        me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200, me.text
        assert me.json()["email"] == "ada@example.com"

        # The provider that guards /graphql accepts the router's tokens.
        user = await provider.get_user_from_token(token)
        assert user.email == "ada@example.com"

    async def test_wrong_password_is_refused(self, client) -> None:
        await _register(client, "bob@example.com")

        login = await client.post(
            "/auth/login", json={"email": "bob@example.com", "password": "Wr0ng!Passw0rd"}
        )
        assert login.status_code == 401

    async def test_token_signed_with_the_old_built_in_key_is_refused(self, client) -> None:
        user_id = (await _register(client, "carol@example.com"))["user"]["id"]
        forged = TokenManager(secret_key=OLD_BUILT_IN_KEY).generate_tokens(user_id)

        me = await client.get(
            "/auth/me", headers={"Authorization": f"Bearer {forged['access_token']}"}
        )
        assert me.status_code == 401

        refreshed = await client.post(
            "/auth/refresh", json={"refresh_token": forged["refresh_token"]}
        )
        assert refreshed.status_code == 401

    async def test_the_provider_key_wins_over_jwt_secret_key(self, client, monkeypatch) -> None:
        monkeypatch.setenv("JWT_SECRET_KEY", "another-key-from-the-environment")
        user_id = (await _register(client, "dan@example.com"))["user"]["id"]
        other = TokenManager(secret_key="another-key-from-the-environment")

        me = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {other.generate_tokens(user_id)['access_token']}"},
        )
        assert me.status_code == 401


class TestNativeAuthRouterWithCreateFraiseqlApp:
    async def test_router_uses_the_apps_native_provider(self, provider, postgres_url) -> None:
        """The documented setup: create_fraiseql_app(auth=provider), then the router."""
        app = create_fraiseql_app(database_url=postgres_url, queries=[ping], auth=provider)
        app.include_router(get_native_auth_router(), prefix="/auth")

        async with _client(app) as c:
            user_id = (await _register(c, "erin@example.com"))["user"]["id"]
            login = await c.post(
                "/auth/login", json={"email": "erin@example.com", "password": PASSWORD}
            )
            assert login.status_code == 200, login.text
            token = login.json()["access_token"]
            assert (
                await c.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            ).status_code == 200

            forged = TokenManager(secret_key=OLD_BUILT_IN_KEY).generate_tokens(user_id)
            me = await c.get(
                "/auth/me", headers={"Authorization": f"Bearer {forged['access_token']}"}
            )
            assert me.status_code == 401


class TestNativeAuthRouterWithoutAKey:
    def test_get_native_auth_router_refuses_to_start(self, monkeypatch) -> None:
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
            get_native_auth_router()

    async def test_unconfigured_router_answers_no_request(self, monkeypatch) -> None:
        """The bare router, included without a provider or key, signs and accepts nothing."""
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

        class _Pool:
            @asynccontextmanager
            async def connection(self):
                yield None

        app = FastAPI()
        app.state.db_pool = _Pool()
        app.include_router(auth_router, prefix="/auth")
        forged = TokenManager(secret_key=OLD_BUILT_IN_KEY).generate_tokens(
            "00000000-0000-0000-0000-000000000001"
        )

        async with _client(app) as c:
            me = await c.get(
                "/auth/me", headers={"Authorization": f"Bearer {forged['access_token']}"}
            )
            refreshed = await c.post(
                "/auth/refresh", json={"refresh_token": forged["refresh_token"]}
            )
        assert me.status_code == 500
        assert refreshed.status_code == 500
        assert "not configured" in me.json()["detail"]


def test_token_manager_refuses_an_empty_key() -> None:
    with pytest.raises(ValueError, match="secret"):
        TokenManager(secret_key="")
