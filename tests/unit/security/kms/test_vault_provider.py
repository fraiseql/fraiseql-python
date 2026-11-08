"""Tests for Vault KMS provider."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.security.kms.domain.base import BaseKMSProvider
from fraiseql.security.kms.infrastructure.vault import (
    VaultConfig,
    VaultKMSProvider,
)


class TestVaultConfig:
    """Tests for VaultConfig."""

    def test_default_mount_path(self):
        """Default mount path should be 'transit'."""
        config = VaultConfig(
            vault_addr="http://localhost:8200",
            token="test-token",
        )
        assert config.mount_path == "transit"

    def test_api_url_construction(self):
        """Should construct correct API URL."""
        config = VaultConfig(
            vault_addr="http://localhost:8200",
            token="test-token",
        )
        expected = "http://localhost:8200/v1/transit/encrypt/my-key"
        assert config.api_url("encrypt/my-key") == expected


class TestVaultKMSProvider:
    """Tests for VaultKMSProvider."""

    @pytest.fixture
    def config(self):
        return VaultConfig(
            vault_addr="http://localhost:8200",
            token="test-token",
        )

    @pytest.fixture
    def provider(self, config):
        return VaultKMSProvider(config)

    def test_extends_base_provider(self, provider):
        """Should extend BaseKMSProvider."""
        assert isinstance(provider, BaseKMSProvider)

    def test_provider_name(self, provider):
        """Provider name should be 'vault'."""
        assert provider.provider_name == "vault"

    @pytest.mark.asyncio
    async def test_do_encrypt_calls_vault_api(self, provider):
        """_do_encrypt should call Vault transit/encrypt endpoint."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "data": {"ciphertext": "vault:v1:encrypted-base64-data"}
            }
            mock_response.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_response

            _ciphertext, algo = await provider._do_encrypt(
                b"plaintext",
                "my-key",
                {"purpose": "test"},
            )

            mock_client.post.assert_called_once()
            assert algo == "aes256-gcm96"

    @pytest.mark.asyncio
    async def test_do_decrypt_calls_vault_api(self, provider):
        """_do_decrypt should call Vault transit/decrypt endpoint."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = MagicMock()
            plaintext_b64 = base64.b64encode(b"decrypted").decode()
            mock_response.json.return_value = {"data": {"plaintext": plaintext_b64}}
            mock_response.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_response

            result = await provider._do_decrypt(
                b"vault:v1:ciphertext",
                "my-key",
                {},
            )

            assert result == b"decrypted"
