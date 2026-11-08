"""revoke_all_user_tokens revokes every token the user holds, not only known ones.

A token is revoked when it was issued (``iat``) before the user's last "revoke
all"; once such a cutoff exists, a token of that user without ``iat`` is revoked
too.
"""

import time

import pytest

from fraiseql.auth.token_revocation import (
    InMemoryRevocationStore,
    RevocationConfig,
    TokenRevocationService,
)


def _token(sub: str, jti: str | None, iat: float | None) -> dict:
    payload: dict = {"sub": sub}
    if jti is not None:
        payload["jti"] = jti
    if iat is not None:
        payload["iat"] = int(iat)
    return payload


@pytest.fixture
def store() -> InMemoryRevocationStore:
    return InMemoryRevocationStore()


@pytest.fixture
def service(store) -> TokenRevocationService:
    return TokenRevocationService(store, RevocationConfig())


@pytest.mark.asyncio
async def test_tokens_issued_before_are_revoked(service) -> None:
    alice = _token("alice", "a1", time.time() - 60)
    bob = _token("bob", "b1", time.time() - 60)
    assert not await service.is_token_revoked(alice)

    await service.revoke_all_user_tokens("alice")

    assert await service.is_token_revoked(alice)
    assert not await service.is_token_revoked(bob)


@pytest.mark.asyncio
async def test_tokens_issued_after_stay_valid(service) -> None:
    await service.revoke_all_user_tokens("alice")

    assert not await service.is_token_revoked(_token("alice", "a2", time.time() + 1))


@pytest.mark.asyncio
async def test_a_token_without_iat_is_revoked_once_a_cutoff_exists(service) -> None:
    token = _token("alice", "a1", None)
    assert not await service.is_token_revoked(token)

    await service.revoke_all_user_tokens("alice")

    assert await service.is_token_revoked(token)


@pytest.mark.asyncio
async def test_a_token_without_jti_is_revoked_too(service) -> None:
    token = _token("alice", None, time.time() - 60)

    await service.revoke_all_user_tokens("alice")

    assert await service.is_token_revoked(token)


@pytest.mark.asyncio
async def test_a_later_revoke_all_moves_the_cutoff(service, store, monkeypatch) -> None:
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now - 3600)
    await service.revoke_all_user_tokens("alice")
    monkeypatch.setattr(time, "time", lambda: now)
    middle = _token("alice", "a1", now - 60)
    assert not await service.is_token_revoked(middle)

    await service.revoke_all_user_tokens("alice")

    assert await service.is_token_revoked(middle)
    assert await store.revoked_before("alice") == pytest.approx(now)


@pytest.mark.asyncio
async def test_the_cutoff_expires_with_the_revocation_ttl(service, store, monkeypatch) -> None:
    now = time.time()
    await service.revoke_all_user_tokens("alice")
    token = _token("alice", "a1", now - 60)
    assert await service.is_token_revoked(token)

    monkeypatch.setattr(time, "time", lambda: now + 86400 + 1)

    assert not await service.is_token_revoked(token)
    assert await store.revoked_before("alice") is None


@pytest.mark.asyncio
async def test_cleanup_removes_expired_cutoffs(service, store, monkeypatch) -> None:
    now = time.time()
    await service.revoke_all_user_tokens("alice")

    monkeypatch.setattr(time, "time", lambda: now + 86400 + 1)

    assert await store.cleanup_expired() == 1
    assert await store.cleanup_expired() == 0


@pytest.mark.asyncio
async def test_a_store_without_revoked_before_still_checks_token_ids() -> None:
    class TokenIdStore:
        def __init__(self) -> None:
            self.revoked: set[str] = set()

        async def revoke_token(self, token_id: str, user_id: str) -> None:
            self.revoked.add(token_id)

        async def is_revoked(self, token_id: str) -> bool:
            return token_id in self.revoked

        async def revoke_all_user_tokens(self, user_id: str) -> None:
            pass

    service = TokenRevocationService(TokenIdStore(), RevocationConfig())
    token = _token("alice", "a1", time.time() - 60)
    await service.revoke_token(token)

    assert await service.is_token_revoked(token)
    assert not await service.is_token_revoked(_token("alice", "a2", None))
