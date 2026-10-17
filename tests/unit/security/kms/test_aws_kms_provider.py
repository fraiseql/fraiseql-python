"""Tests for AWS KMS provider."""

from unittest.mock import MagicMock, patch

import pytest

from fraiseql.security.kms.domain.base import BaseKMSProvider
from fraiseql.security.kms.infrastructure.aws_kms import (
    AWSKMSConfig,
    AWSKMSProvider,
)


class TestAWSKMSConfig:
    """Tests for AWSKMSConfig."""

    def test_default_region(self):
        """Default region should be us-east-1."""
        config = AWSKMSConfig()
        assert config.region_name == "us-east-1"

    def test_custom_region(self):
        """Custom region should be respected."""
        config = AWSKMSConfig(region_name="eu-west-1")
        assert config.region_name == "eu-west-1"

    def test_default_profile(self):
        """Default profile should be None."""
        config = AWSKMSConfig()
        assert config.profile_name is None

    def test_custom_profile(self):
        """Custom profile should be respected."""
        config = AWSKMSConfig(profile_name="my-profile")
        assert config.profile_name == "my-profile"


class TestAWSKMSProvider:
    """Tests for AWSKMSProvider."""

    @pytest.fixture
    def config(self):
        return AWSKMSConfig(region_name="us-east-1")

    @pytest.fixture
    def provider(self, config):
        return AWSKMSProvider(config)

    def test_extends_base_provider(self, provider):
        """Should extend BaseKMSProvider."""
        assert isinstance(provider, BaseKMSProvider)

    def test_provider_name(self, provider):
        """Provider name should be 'aws'."""
        assert provider.provider_name == "aws"

    @pytest.mark.asyncio
    async def test_do_encrypt_calls_aws_kms_api(self, provider):
        """_do_encrypt should call AWS KMS encrypt API."""
        with (
            patch("fraiseql.security.kms.infrastructure.aws_kms.boto3") as mock_boto3,
            patch("fraiseql.security.kms.infrastructure.aws_kms.BOTO3_AVAILABLE", True),
        ):
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_boto3.Session.return_value = mock_session
            mock_session.client.return_value = mock_client

            mock_response = {
                "CiphertextBlob": b"encrypted-data",
                "KeyId": "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012",
            }
            mock_client.encrypt.return_value = mock_response

            _ciphertext, algo = await provider._do_encrypt(
                b"plaintext",
                "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                {"purpose": "test"},
            )

            mock_client.encrypt.assert_called_once()
            assert algo == "SYMMETRIC_DEFAULT"

    @pytest.mark.asyncio
    async def test_do_decrypt_calls_aws_kms_api(self, provider):
        """_do_decrypt should call AWS KMS decrypt API."""
        with (
            patch("fraiseql.security.kms.infrastructure.aws_kms.boto3") as mock_boto3,
            patch("fraiseql.security.kms.infrastructure.aws_kms.BOTO3_AVAILABLE", True),
        ):
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_boto3.Session.return_value = mock_session
            mock_session.client.return_value = mock_client

            mock_response = {
                "Plaintext": b"decrypted-data",
                "KeyId": "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012",
            }
            mock_client.decrypt.return_value = mock_response

            result = await provider._do_decrypt(
                b"encrypted-data",
                "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                {},
            )

            mock_client.decrypt.assert_called_once()
            assert result == b"decrypted-data"

    @pytest.mark.asyncio
    async def test_do_generate_data_key_calls_aws_kms_api(self, provider):
        """_do_generate_data_key should call AWS KMS generate_data_key API."""
        with (
            patch("fraiseql.security.kms.infrastructure.aws_kms.boto3") as mock_boto3,
            patch("fraiseql.security.kms.infrastructure.aws_kms.BOTO3_AVAILABLE", True),
        ):
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_boto3.Session.return_value = mock_session
            mock_session.client.return_value = mock_client

            mock_response = {
                "Plaintext": b"plaintext-key-32-bytes!!!!!",
                "CiphertextBlob": b"encrypted-key-blob",
                "KeyId": "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012",
            }
            mock_client.generate_data_key.return_value = mock_response

            plaintext_key, encrypted_key = await provider._do_generate_data_key(
                "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                {"purpose": "test"},
            )

            mock_client.generate_data_key.assert_called_once()
            assert plaintext_key == b"plaintext-key-32-bytes!!!!!"
            assert encrypted_key == b"encrypted-key-blob"
