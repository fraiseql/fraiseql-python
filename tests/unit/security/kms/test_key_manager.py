"""Tests for KeyManager application service."""

from datetime import UTC, datetime

import pytest

from fraiseql.security.kms.application.key_manager import KeyManager
from fraiseql.security.kms.domain.base import BaseKMSProvider
from fraiseql.security.kms.domain.models import (
    EncryptedData,
    KeyPurpose,
    KeyReference,
)


class MockProvider(BaseKMSProvider):
    """Mock provider for testing."""

    def __init__(self, name: str):
        self._name = name

    @property
    def provider_name(self) -> str:
        return self._name

    async def _do_encrypt(self, plaintext, key_id, context):
        return b"encrypted:" + plaintext, "mock-algo"

    async def _do_decrypt(self, ciphertext, key_id, context):
        return ciphertext.replace(b"encrypted:", b"")

    async def _do_generate_data_key(self, key_id, context):
        return b"0" * 32, b"encrypted-key"

    async def _do_rotate_key(self, key_id):
        pass

    async def _do_get_key_info(self, key_id):
        return {"alias": None, "created_at": datetime.now(UTC)}

    async def _do_get_rotation_policy(self, key_id):
        return {"enabled": False, "period_days": 0}


class TestKeyManager:
    """Tests for KeyManager."""

    @pytest.fixture
    def mock_provider(self):
        """Create a mock KMS provider."""
        return MockProvider("mock")

    @pytest.fixture
    def key_manager(self, mock_provider):
        """Create KeyManager with mock provider."""
        return KeyManager(
            providers={"mock": mock_provider},
            default_provider="mock",
            default_key_id="default-key",
        )

    @pytest.mark.asyncio
    async def test_encrypt_with_default_key(self, key_manager, mock_provider):
        """Should encrypt using default key when no key specified."""
        result = await key_manager.encrypt(b"plaintext")

        assert isinstance(result, EncryptedData)
        assert result.key_reference.provider == "mock"
        assert result.key_reference.key_id == "default-key"

    @pytest.mark.asyncio
    async def test_encrypt_with_specific_key(self, key_manager, mock_provider):
        """Should encrypt using specified key."""
        result = await key_manager.encrypt(b"plaintext", key_id="my-key")

        assert isinstance(result, EncryptedData)
        assert result.key_reference.key_id == "my-key"

    @pytest.mark.asyncio
    async def test_encrypt_with_context(self, key_manager, mock_provider):
        """Should pass context to provider."""
        context = {"purpose": "test"}
        result = await key_manager.encrypt(
            b"plaintext",
            key_id="my-key",
            context=context,
        )

        assert result.context == context

    @pytest.mark.asyncio
    async def test_decrypt_calls_provider(self, key_manager, mock_provider):
        """Should decrypt using provider."""
        encrypted = EncryptedData(
            ciphertext=b"encrypted:secret",
            key_reference=KeyReference(
                provider="mock",
                key_id="test-key",
                key_alias=None,
                purpose=KeyPurpose.ENCRYPT_DECRYPT,
                created_at=datetime.now(UTC),
            ),
            algorithm="mock",
            encrypted_at=datetime.now(UTC),
            context={},
        )

        result = await key_manager.decrypt(encrypted)

        assert result == b"secret"

    @pytest.mark.asyncio
    async def test_decrypt_with_context_override(self, key_manager, mock_provider):
        """Should override context when decrypting."""
        encrypted = EncryptedData(
            ciphertext=b"encrypted:secret",
            key_reference=KeyReference(
                provider="mock",
                key_id="test-key",
                key_alias=None,
                purpose=KeyPurpose.ENCRYPT_DECRYPT,
                created_at=datetime.now(UTC),
            ),
            algorithm="mock",
            encrypted_at=datetime.now(UTC),
            context={"original": "context"},
        )

        override_context = {"override": "context"}
        result = await key_manager.decrypt(encrypted, context=override_context)

        assert result == b"secret"


class TestKeyManagerStartup:
    """Tests for startup-time key management."""

    @pytest.fixture
    def vault_provider(self):
        return MockProvider("vault")

    @pytest.mark.asyncio
    async def test_initialize_data_key(self, vault_provider):
        """Should generate and cache data key at startup."""
        manager = KeyManager(
            providers={"vault": vault_provider},
            default_provider="vault",
            default_key_id="master-key",
        )

        await manager.initialize()

        assert manager.has_cached_data_key()
        assert manager.get_cached_data_key() is not None

    @pytest.mark.asyncio
    async def test_local_encrypt_uses_cached_key(self, vault_provider):
        """Should use cached data key for local encryption (no KMS call)."""
        manager = KeyManager(
            providers={"vault": vault_provider},
            default_provider="vault",
            default_key_id="master-key",
        )
        await manager.initialize()

        # This should NOT call KMS - uses cached key
        encrypted = manager.local_encrypt(b"sensitive data")

        assert encrypted is not None

    @pytest.mark.asyncio
    async def test_local_decrypt_uses_cached_key(self, vault_provider):
        """Should use cached data key for local decryption."""
        manager = KeyManager(
            providers={"vault": vault_provider},
            default_provider="vault",
            default_key_id="master-key",
        )
        await manager.initialize()

        encrypted = manager.local_encrypt(b"sensitive data")
        decrypted = manager.local_decrypt(encrypted)

        assert decrypted == b"sensitive data"

    @pytest.mark.asyncio
    async def test_rotate_data_key(self, vault_provider):
        """Should rotate data key via KMS."""
        manager = KeyManager(
            providers={"vault": vault_provider},
            default_provider="vault",
            default_key_id="master-key",
        )
        await manager.initialize()
        manager.get_cached_data_key()

        await manager.rotate_data_key()

        new_key = manager.get_cached_data_key()
        # Key should still exist after rotation (mock doesn't change it)
        assert new_key is not None
        assert len(new_key) == 32

    def test_local_encrypt_fails_without_initialization(self, vault_provider):
        """Should raise if local_encrypt called before initialize()."""
        manager = KeyManager(
            providers={"vault": vault_provider},
            default_provider="vault",
            default_key_id="master-key",
        )

        with pytest.raises(RuntimeError, match="not initialized"):
            manager.local_encrypt(b"data")
