"""PostgreSQLRevocationStore: revoke_all_user_tokens revokes the user's live tokens."""

import time
import uuid

import pytest
import pytest_asyncio

from fraiseql.auth.token_revocation import (
    PostgreSQLRevocationStore,
    RevocationConfig,
    TokenRevocationService,
)

pytestmark = [pytest.mark.integration, pytest.mark.database]


@pytest_asyncio.fixture(loop_scope="class")
async def store(class_db_pool):
    table = f"tb_token_revocation_{uuid.uuid4().hex[:8]}"
    yield PostgreSQLRevocationStore(class_db_pool, table_name=table)
    async with class_db_pool.connection() as conn:
        await conn.execute(f"DROP TABLE IF EXISTS {table}")
        await conn.commit()


@pytest.mark.asyncio(loop_scope="class")
class TestPostgreSQLRevokeAll:
    async def test_revoke_all_revokes_tokens_issued_before(self, store) -> None:
        service = TokenRevocationService(store, RevocationConfig())
        alice = {"sub": "alice", "jti": "a1", "iat": int(time.time()) - 60}
        no_iat = {"sub": "alice", "jti": "a2"}
        bob = {"sub": "bob", "jti": "b1", "iat": int(time.time()) - 60}
        assert not await service.is_token_revoked(alice)
        assert not await service.is_token_revoked(no_iat)

        await service.revoke_all_user_tokens("alice")

        assert await service.is_token_revoked(alice)
        assert await service.is_token_revoked(no_iat)
        assert not await service.is_token_revoked(bob)
        later = {"sub": "alice", "jti": "a3", "iat": int(time.time()) + 1}
        assert not await service.is_token_revoked(later)

    async def test_a_later_revoke_all_moves_the_cutoff(self, store) -> None:
        await store.revoke_all_user_tokens("alice")
        first = await store.revoked_before("alice")
        assert first is not None
        assert first == pytest.approx(time.time(), abs=5)

        await store.revoke_all_user_tokens("alice")

        assert await store.revoked_before("alice") >= first
        assert await store.revoked_before("bob") is None
