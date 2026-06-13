"""AWS KMS provider."""

from dataclasses import dataclass

from fraiseql.security.kms.domain.base import BaseKMSProvider
from fraiseql.security.kms.domain.exceptions import (
    DecryptionError,
    EncryptionError,
    KeyNotFoundError,
    ProviderConnectionError,
)

try:
    import boto3
    from botocore.exceptions import ClientError

    BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None
    ClientError = Exception
    BOTO3_AVAILABLE = False


@dataclass
class AWSKMSConfig:
    """Configuration for AWS KMS provider.

    SECURITY CONSIDERATIONS:
    ------------------------
    Authentication:
    - Uses boto3 default credential chain (IAM roles, profiles, env vars)
    - Supports explicit profile_name for development environments
    - Never store AWS credentials in code or config files

    Recommended Production Setup:
    - Use IAM roles on EC2/ECS/EKS
    - Use AWS profiles for development
    - Enable CloudTrail for KMS operations auditing
    - Use KMS key policies for fine-grained access control
    """

    region_name: str = "us-east-1"
    profile_name: str | None = None


class AWSKMSProvider(BaseKMSProvider):
    """AWS Key Management Service provider.

    Uses AWS KMS for encryption/decryption operations.
    Supports envelope encryption via data key generation.

    SECURITY: All operations use authenticated encryption (AES-256-GCM).
    """

    def __init__(self, config: AWSKMSConfig) -> None:
        self.config = config
        self._client = None

    @property
    def provider_name(self) -> str:
        """Provider identifier."""
        return "aws"

    @property
    def client(self) -> "boto3.client":  # type: ignore[name-defined, valid-type]
        """Lazy-loaded boto3 KMS client."""
        if not BOTO3_AVAILABLE:
            raise ImportError(
                "boto3 is required for AWS KMS provider. "
                "Install with: pip install boto3 or uv sync --extra aws"
            )

        if self._client is None:
            session_kwargs = {"region_name": self.config.region_name}
            if self.config.profile_name:
                session_kwargs["profile_name"] = self.config.profile_name

            session = boto3.Session(**session_kwargs)
            self._client = session.client("kms")
        return self._client

    async def _do_encrypt(
        self,
        plaintext: bytes,
        key_id: str,
        context: dict[str, str],
    ) -> tuple[bytes, str]:
        """Encrypt data using AWS KMS."""
        try:
            kwargs = {
                "KeyId": key_id,
                "Plaintext": plaintext,
            }

            # Add encryption context if provided
            if context:
                kwargs["EncryptionContext"] = context

            response = self.client.encrypt(**kwargs)
            return response["CiphertextBlob"], "SYMMETRIC_DEFAULT"

        except ClientError as e:
            self._handle_client_error(e, "encryption")
            # This line should never be reached due to the exception above
            raise RuntimeError("Unreachable code")

    async def _do_decrypt(
        self,
        ciphertext: bytes,
        key_id: str,
        context: dict[str, str],
    ) -> bytes:
        """Decrypt data using AWS KMS."""
        try:
            kwargs = {
                "CiphertextBlob": ciphertext,
            }

            # Add encryption context if provided
            if context:
                kwargs["EncryptionContext"] = context

            response = self.client.decrypt(**kwargs)
            return response["Plaintext"]

        except ClientError as e:
            self._handle_client_error(e, "decryption")
            # This line should never be reached due to the exception above
            raise RuntimeError("Unreachable code")

    async def _do_generate_data_key(
        self,
        key_id: str,
        context: dict[str, str],
    ) -> tuple[bytes, bytes]:
        """Generate a data encryption key using AWS KMS."""
        try:
            kwargs = {
                "KeyId": key_id,
                "KeySpec": "AES_256",  # 32-byte key
            }

            # Add encryption context if provided
            if context:
                kwargs["EncryptionContext"] = context

            response = self.client.generate_data_key(**kwargs)
            return response["Plaintext"], response["CiphertextBlob"]

        except ClientError as e:
            self._handle_client_error(e, "data key generation")
            # This line should never be reached due to the exception above
            raise RuntimeError("Unreachable code")

    async def _do_rotate_key(self, key_id: str) -> None:
        """Rotate the key in AWS KMS."""
        try:
            # AWS KMS automatic key rotation is enabled per key
            # This method enables automatic rotation for the key
            self.client.enable_key_rotation(KeyId=key_id)

        except ClientError as e:
            self._handle_client_error(e, "key rotation")
            # This line should never be reached due to the exception above
            raise RuntimeError("Unreachable code")

    async def _do_get_key_info(self, key_id: str) -> dict:
        """Get key information from AWS KMS."""
        try:
            response = self.client.describe_key(KeyId=key_id)
            key_metadata = response["KeyMetadata"]

            return {
                "alias": self._get_key_alias(key_id),
                "created_at": key_metadata["CreationDate"],
            }

        except ClientError as e:
            self._handle_client_error(e, "key info retrieval")
            # This line should never be reached due to the exception above
            raise RuntimeError("Unreachable code")

    async def _do_get_rotation_policy(self, key_id: str) -> dict:
        """Get key rotation policy from AWS KMS."""
        try:
            response = self.client.get_key_rotation_status(KeyId=key_id)

            # AWS KMS doesn't have explicit rotation schedules like Vault
            # Return based on automatic rotation status
            return {
                "enabled": response["KeyRotationEnabled"],
                "period_days": 365,  # AWS rotates annually when enabled
                "last_rotation": None,  # AWS doesn't expose last rotation time
                "next_rotation": None,  # AWS handles this automatically
            }

        except ClientError as e:
            self._handle_client_error(e, "rotation policy retrieval")
            # This line should never be reached due to the exception above
            raise RuntimeError("Unreachable code")

    def _get_key_alias(self, key_id: str) -> str | None:
        """Get key alias from AWS KMS."""
        try:
            # Try to get aliases for this key
            response = self.client.list_aliases(KeyId=key_id)
            aliases = response["Aliases"]

            # Return the first non-AWS-managed alias
            for alias in aliases:
                if not alias["AliasName"].startswith("alias/aws/"):
                    return alias["AliasName"]

            return None

        except ClientError:
            # If we can't get aliases, return None
            return None

    def _handle_client_error(self, error: Exception, operation: str) -> None:
        """Convert AWS ClientError to domain exceptions."""
        # Handle non-ClientError exceptions (like ImportError for missing boto3)
        if not hasattr(error, "response"):
            raise ProviderConnectionError(
                f"AWS KMS provider error during {operation}: {error}"
            ) from error

        # At this point we know it's a ClientError with response attribute
        error_code = error.response["Error"]["Code"]  # type: ignore[attr-defined]  # ty: ignore[not-subscriptable]

        if error_code in ("NotFoundException", "InvalidKeyId"):
            raise KeyNotFoundError(f"Key not found during {operation}") from error
        if error_code in ("InvalidCiphertextException", "InvalidCiphertext"):
            raise DecryptionError(f"Invalid ciphertext during {operation}") from error
        if error_code == "KMSInvalidStateException":
            raise EncryptionError(f"Key is not in valid state for {operation}") from error
        if error_code in ("AccessDeniedException", "UnauthorizedOperation"):
            raise ProviderConnectionError(f"Access denied during {operation}") from error
        if error_code == "ThrottlingException":
            raise ProviderConnectionError(f"Rate limited during {operation}") from error
        # Generic error for other cases
        raise EncryptionError(f"AWS KMS {operation} failed: {error_code}") from error
