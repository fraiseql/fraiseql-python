"""Auth0ProviderWithRevocation validates with Auth0, then rejects revoked tokens.

Its validate_token stored ``super().validate_token`` as the "original" check.
Through the MRO (Auth0ProviderWithRevocation -> TokenRevocationMixin ->
Auth0Provider) that is the mixin's own validate_token, which calls the
"original" again: every token, valid or not, ended in RecursionError.

Auth0's signature check (Auth0Provider.validate_token) is replaced here by a
lookup of fake tokens; what is tested is the provider around it.
"""

import pytest

from fraiseql.auth import Auth0ProviderWithRevocation
from fraiseql.auth.auth0 import Auth0Provider
from fraiseql.auth.base import InvalidTokenError
from fraiseql.auth.token_revocation import (
    InMemoryRevocationStore,
    RevocationConfig,
    TokenRevocationService,
)

_PAYLOADS = {
    "alice-1": {"sub": "alice", "jti": "a1", "email": "alice@example.com"},
    "alice-2": {"sub": "alice", "jti": "a2", "email": "alice@example.com"},
}


@pytest.fixture
def auth0_accepts_fake_tokens(monkeypatch):
    async def validate_token(self, token: str) -> dict:
        if token not in _PAYLOADS:
            raise InvalidTokenError("bad signature")
        return dict(_PAYLOADS[token])

    monkeypatch.setattr(Auth0Provider, "validate_token", validate_token)


@pytest.fixture
def provider(auth0_accepts_fake_tokens):
    service = TokenRevocationService(InMemoryRevocationStore(), RevocationConfig())
    return Auth0ProviderWithRevocation(
        domain="example.auth0.com",
        api_identifier="https://api.example.com",
        revocation_service=service,
    )


@pytest.mark.asyncio
async def test_valid_token_returns_its_payload(provider) -> None:
    assert await provider.validate_token("alice-1") == _PAYLOADS["alice-1"]


@pytest.mark.asyncio
async def test_invalid_token_is_rejected_by_auth0(provider) -> None:
    with pytest.raises(InvalidTokenError, match="bad signature"):
        await provider.validate_token("forged")


@pytest.mark.asyncio
async def test_logged_out_token_is_rejected(provider) -> None:
    await provider.logout(await provider.validate_token("alice-1"))

    with pytest.raises(InvalidTokenError, match="revoked"):
        await provider.validate_token("alice-1")
    # Another token of the same user is unaffected
    assert await provider.validate_token("alice-2") == _PAYLOADS["alice-2"]


@pytest.mark.asyncio
async def test_user_from_revoked_token_is_an_authentication_error(provider) -> None:
    user = await provider.get_user_from_token("alice-1")
    assert user.user_id == "alice"

    await provider.logout(await provider.validate_token("alice-1"))

    # get_current_user_optional turns AuthenticationError into "not authenticated"
    with pytest.raises(InvalidTokenError):
        await provider.get_user_from_token("alice-1")


@pytest.mark.asyncio
async def test_without_a_revocation_service_it_is_auth0_alone(
    auth0_accepts_fake_tokens,
) -> None:
    provider = Auth0ProviderWithRevocation(
        domain="example.auth0.com", api_identifier="https://api.example.com"
    )

    assert await provider.validate_token("alice-1") == _PAYLOADS["alice-1"]
