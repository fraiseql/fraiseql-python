"""Unit tests for HashiCorp Vault KMS provider using Testcontainers.

These tests use Testcontainers to spin up a real Vault dev server for testing.
"""

import time

import pytest
from testcontainers.core.container import DockerContainer

from fraiseql.security.kms import VaultConfig, VaultKMSProvider

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def vault_container():
    """Start a Vault dev server container for testing.

    Vault dev mode characteristics:
    - Runs entirely in-memory (no persistence)
    - Automatically unsealed
    - Root token: "root"
    - Listens on port 8200
    - Transit engine enabled at /transit by default
    """
    ctx = (
        DockerContainer("hashicorp/vault:latest")
        .with_env("VAULT_DEV_ROOT_TOKEN_ID", "root")
        .with_env("VAULT_DEV_LISTEN_ADDRESS", "0.0.0.0:8200")
        .with_command("server -dev -dev-root-token-id=root")
        .with_bind_ports(8200, 8200)
        .with_exposed_ports(8200)
    )
    try:
        container = ctx.__enter__()
    except Exception as exc:
        pytest.skip(f"Docker container failed to start: {exc}")

    try:
        # Wait for Vault to be ready by checking logs
        max_wait = 30
        start_time = time.time()
        while time.time() - start_time < max_wait:
            logs = container.get_logs()
            if isinstance(logs, tuple):
                logs = logs[0].decode("utf-8") if logs[0] else ""
            elif isinstance(logs, bytes):
                logs = logs.decode("utf-8")

            if "Vault server started" in logs:
                break
            time.sleep(1)

        # Get the mapped port
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8200)

        yield {
            "addr": f"http://{host}:{port}",
            "token": "root",
            "container": container,
        }
    finally:
        ctx.__exit__(None, None, None)


@pytest.fixture
async def vault_provider(vault_container):
    """Create Vault KMS provider connected to test container."""
    import httpx

    config = VaultConfig(
        vault_addr=vault_container["addr"],
        token=vault_container["token"],
        mount_path="transit",
    )

    # Enable transit engine and create some test keys
    headers = {"X-Vault-Token": vault_container["token"]}
    base_url = vault_container["addr"]

    async with httpx.AsyncClient() as client:
        # Enable transit engine at /transit path
        await client.post(
            f"{base_url}/v1/sys/mounts/transit",
            headers=headers,
            json={"type": "transit"},
        )

        # Create test keys that tests will use
        test_keys = [
            "test-unit-key",
            "test-data-key",
            "test-key-1",
            "test-key-2",
            "test-multi-key",
            "test-empty-key",
            "test-large-key",
            "test-context-key",
            "reusable-key",
        ]

        for key in test_keys:
            await client.post(
                f"{base_url}/v1/transit/keys/{key}",
                headers=headers,
            )

    return VaultKMSProvider(config)


class TestVaultKMSProviderContainers:
    """Unit tests for Vault KMS provider using Testcontainers."""

    @pytest.mark.asyncio
    async def test_encrypt_decrypt_roundtrip(self, vault_provider):
        """Test full encryption/decryption cycle with Vault container."""
        test_data = b"Hello, World! This is test data for Vault unit test."
        key_id = "test-unit-key"

        # Encrypt
        encrypted = await vault_provider.encrypt(test_data, key_id=key_id)
        assert encrypted is not None
        assert encrypted.ciphertext != test_data
        assert encrypted.key_reference.key_id == key_id

        # Decrypt
        decrypted = await vault_provider.decrypt(encrypted)
        assert decrypted == test_data

    @pytest.mark.asyncio
    async def test_data_key_generation(self, vault_provider):
        """Test data key generation with Vault container."""
        key_id = "test-data-key"

        # Generate data key
        data_key = await vault_provider.generate_data_key(key_id=key_id)
        assert data_key is not None
        assert data_key.plaintext_key is not None
        assert data_key.encrypted_key is not None
        assert len(data_key.plaintext_key) == 32  # AES-256 key

    @pytest.mark.asyncio
    async def test_different_keys_isolation(self, vault_provider):
        """Test that different keys produce different ciphertexts."""
        test_data = b"Same data, different keys"
        key1 = "test-key-1"
        key2 = "test-key-2"

        encrypted1 = await vault_provider.encrypt(test_data, key_id=key1)
        encrypted2 = await vault_provider.encrypt(test_data, key_id=key2)

        # Different keys should produce different ciphertexts
        assert encrypted1.ciphertext != encrypted2.ciphertext
        assert encrypted1.key_reference.key_id != encrypted2.key_reference.key_id

        # But should decrypt to same plaintext
        decrypted1 = await vault_provider.decrypt(encrypted1)
        decrypted2 = await vault_provider.decrypt(encrypted2)
        assert decrypted1 == decrypted2 == test_data

    @pytest.mark.asyncio
    async def test_multiple_encrypt_operations(self, vault_provider):
        """Test multiple encryption operations with same key."""
        test_data = b"Multiple encryptions"
        key_id = "test-multi-key"

        # Encrypt same data twice
        encrypted1 = await vault_provider.encrypt(test_data, key_id=key_id)
        encrypted2 = await vault_provider.encrypt(test_data, key_id=key_id)

        # Should produce different ciphertexts (due to IV)
        assert encrypted1.ciphertext != encrypted2.ciphertext

        # Both should decrypt correctly
        decrypted1 = await vault_provider.decrypt(encrypted1)
        decrypted2 = await vault_provider.decrypt(encrypted2)
        assert decrypted1 == decrypted2 == test_data

    @pytest.mark.asyncio
    async def test_provider_name(self, vault_provider):
        """Test that provider name is correct."""
        assert vault_provider.provider_name == "vault"

    @pytest.mark.asyncio
    async def test_encrypt_empty_data(self, vault_provider):
        """Test encryption of empty data."""
        test_data = b""
        key_id = "test-empty-key"

        encrypted = await vault_provider.encrypt(test_data, key_id=key_id)
        assert encrypted is not None

        decrypted = await vault_provider.decrypt(encrypted)
        assert decrypted == test_data

    @pytest.mark.asyncio
    async def test_encrypt_large_data(self, vault_provider):
        """Test encryption of larger data."""
        # Vault Transit can handle larger data than AWS KMS
        test_data = b"A" * 100000  # 100KB
        key_id = "test-large-key"

        encrypted = await vault_provider.encrypt(test_data, key_id=key_id)
        assert encrypted is not None

        decrypted = await vault_provider.decrypt(encrypted)
        assert decrypted == test_data

    @pytest.mark.asyncio
    async def test_encrypt_with_context(self, vault_provider):
        """Test encryption with additional context."""
        test_data = b"Data with context"
        key_id = "test-context-key"
        context = {"user_id": "12345", "action": "test"}

        # Encrypt with context
        encrypted = await vault_provider.encrypt(test_data, key_id=key_id, context=context)
        assert encrypted is not None

        # Decrypt should work
        decrypted = await vault_provider.decrypt(encrypted)
        assert decrypted == test_data

    @pytest.mark.asyncio
    async def test_reuse_same_key_multiple_times(self, vault_provider):
        """Test that the same key can be reused for multiple operations."""
        key_id = "reusable-key"

        # Encrypt multiple different messages with same key
        messages = [b"Message 1", b"Message 2", b"Message 3"]
        encrypted_messages = []

        for msg in messages:
            encrypted = await vault_provider.encrypt(msg, key_id=key_id)
            encrypted_messages.append(encrypted)

        # Decrypt all messages
        for original, encrypted in zip(messages, encrypted_messages):
            decrypted = await vault_provider.decrypt(encrypted)
            assert decrypted == original
