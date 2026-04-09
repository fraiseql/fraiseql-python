"""Tests for FastAPI dependencies — issue #325."""

import pytest

from fraiseql.auth.base import (
    AuthenticationError,
    AuthProvider,
    InvalidTokenError,
    TokenExpiredError,
    UserContext,
)
from fraiseql.fastapi import dependencies


class FakeAuthProvider(AuthProvider):
    """Auth provider that raises configurable exceptions."""

    def __init__(self, exception: Exception | None = None, user: UserContext | None = None):
        self._exception = exception
        self._user = user

    async def get_user_from_token(self, token: str) -> UserContext:
        if self._exception:
            raise self._exception
        if self._user:
            return self._user
        msg = "No user configured"
        raise AuthenticationError(msg)

    async def validate_token(self, token: str) -> dict:
        return {}


@pytest.fixture(autouse=True)
def _reset_auth_provider():
    """Reset auth provider after each test."""
    original = dependencies._auth_provider
    yield
    dependencies._auth_provider = original


@pytest.mark.asyncio
async def test_returns_none_on_authentication_error():
    """Auth errors should result in None (unauthenticated)."""
    dependencies._auth_provider = FakeAuthProvider(exception=AuthenticationError("bad token"))
    result = await dependencies.get_current_user_optional(token="some-token")
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_token_expired():
    """Expired token should result in None."""
    dependencies._auth_provider = FakeAuthProvider(exception=TokenExpiredError("expired"))
    result = await dependencies.get_current_user_optional(token="some-token")
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_invalid_token():
    """Invalid token should result in None."""
    dependencies._auth_provider = FakeAuthProvider(exception=InvalidTokenError("invalid"))
    result = await dependencies.get_current_user_optional(token="some-token")
    assert result is None


@pytest.mark.asyncio
async def test_propagates_permission_error():
    """PermissionError (non-auth) should NOT be caught."""
    dependencies._auth_provider = FakeAuthProvider(exception=PermissionError("log file"))
    with pytest.raises(PermissionError, match="log file"):
        await dependencies.get_current_user_optional(token="some-token")


@pytest.mark.asyncio
async def test_propagates_connection_error():
    """ConnectionError (non-auth) should NOT be caught."""
    dependencies._auth_provider = FakeAuthProvider(exception=ConnectionError("JWKS unreachable"))
    with pytest.raises(ConnectionError, match="JWKS unreachable"):
        await dependencies.get_current_user_optional(token="some-token")


@pytest.mark.asyncio
async def test_propagates_runtime_error():
    """RuntimeError (non-auth) should NOT be caught."""
    dependencies._auth_provider = FakeAuthProvider(exception=RuntimeError("misconfigured"))
    with pytest.raises(RuntimeError, match="misconfigured"):
        await dependencies.get_current_user_optional(token="some-token")


@pytest.mark.asyncio
async def test_returns_none_when_no_token():
    """No token should return None without touching the provider."""
    dependencies._auth_provider = FakeAuthProvider(exception=RuntimeError("should not be called"))
    result = await dependencies.get_current_user_optional(token=None)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_no_provider():
    """No auth provider configured should return None."""
    dependencies._auth_provider = None
    result = await dependencies.get_current_user_optional(token="some-token")
    assert result is None
