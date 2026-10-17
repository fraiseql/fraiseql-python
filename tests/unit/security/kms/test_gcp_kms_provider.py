"""Tests for GCP Cloud KMS provider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.security.kms.domain.base import BaseKMSProvider
from fraiseql.security.kms.infrastructure.gcp_kms import (
    GCPKMSConfig,
    GCPKMSProvider,
)


class TestGCPKMSConfig:
    def test_key_path_construction(self):
        config = GCPKMSConfig(
            project_id="my-project",
            location="global",
            key_ring="my-keyring",
        )
        expected = "projects/my-project/locations/global/keyRings/my-keyring/cryptoKeys/my-key"
        assert config.key_path("my-key") == expected

    def test_key_version_path(self):
        config = GCPKMSConfig(
            project_id="my-project",
            location="us-east1",
            key_ring="prod-keys",
        )
        expected = "projects/my-project/locations/us-east1/keyRings/prod-keys/cryptoKeys/api-key/cryptoKeyVersions/1"
        assert config.key_version_path("api-key", "1") == expected


class TestGCPKMSProvider:
    @pytest.fixture
    def config(self):
        return GCPKMSConfig(
            project_id="my-project",
            location="global",
            key_ring="my-keyring",
        )

    def test_extends_base_provider(self, config):
        with (
            patch("fraiseql.security.kms.infrastructure.gcp_kms.GCP_KMS_AVAILABLE", True),
            patch("fraiseql.security.kms.infrastructure.gcp_kms.kms_v1"),
        ):
            provider = GCPKMSProvider(config)
            assert isinstance(provider, BaseKMSProvider)

    def test_provider_name(self, config):
        with (
            patch("fraiseql.security.kms.infrastructure.gcp_kms.GCP_KMS_AVAILABLE", True),
            patch("fraiseql.security.kms.infrastructure.gcp_kms.kms_v1"),
        ):
            provider = GCPKMSProvider(config)
            assert provider.provider_name == "gcp"

    @pytest.mark.asyncio
    async def test_do_encrypt_calls_gcp_api(self, config):
        """_do_encrypt should call GCP Cloud KMS encrypt endpoint."""
        with (
            patch("fraiseql.security.kms.infrastructure.gcp_kms.GCP_KMS_AVAILABLE", True),
            patch("fraiseql.security.kms.infrastructure.gcp_kms.kms_v1") as mock_kms,
            patch("fraiseql.security.kms.infrastructure.gcp_kms.types"),
            patch("fraiseql.security.kms.infrastructure.gcp_kms.gcp_exceptions"),
        ):
            mock_client = AsyncMock()
            mock_kms.KeyManagementServiceAsyncClient.return_value = mock_client

            mock_response = MagicMock()
            mock_response.ciphertext = b"encrypted-data"
            mock_client.encrypt.return_value = mock_response

            provider = GCPKMSProvider(config)
            ciphertext, algo = await provider._do_encrypt(
                b"plaintext",
                "my-key",
                {"purpose": "test"},
            )

            mock_client.encrypt.assert_called_once()
            assert ciphertext == b"encrypted-data"
            assert algo == "GOOGLE_SYMMETRIC_ENCRYPTION"

    @pytest.mark.asyncio
    async def test_do_decrypt_calls_gcp_api(self, config):
        """_do_decrypt should call GCP Cloud KMS decrypt endpoint."""
        with (
            patch("fraiseql.security.kms.infrastructure.gcp_kms.GCP_KMS_AVAILABLE", True),
            patch("fraiseql.security.kms.infrastructure.gcp_kms.kms_v1") as mock_kms,
            patch("fraiseql.security.kms.infrastructure.gcp_kms.types"),
            patch("fraiseql.security.kms.infrastructure.gcp_kms.gcp_exceptions"),
        ):
            mock_client = AsyncMock()
            mock_kms.KeyManagementServiceAsyncClient.return_value = mock_client

            mock_response = MagicMock()
            mock_response.plaintext = b"decrypted-data"
            mock_client.decrypt.return_value = mock_response

            provider = GCPKMSProvider(config)
            result = await provider._do_decrypt(
                b"ciphertext",
                "my-key",
                {},
            )

            assert result == b"decrypted-data"
