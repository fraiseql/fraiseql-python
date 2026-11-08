"""HMAC-SHA256 signing utilities for audit event integrity.

FraiseQL Philosophy: "In PostgreSQL Everything"
This module is for VERIFICATION ONLY. Event signing during creation is handled
by PostgreSQL triggers (see migrations/001_audit_tables.sql).

Use this module to:
- Verify signatures from Python
- Testing and development
- Offline signature verification

DO NOT use this module to:
- Sign events during creation (PostgreSQL does this)
- Populate signature fields manually (triggers handle this)
"""

import hashlib
import hmac
import os
from datetime import datetime
from typing import Optional


def sign_event(event_hash: str, secret_key: str) -> str:
    """Generate HMAC-SHA256 signature for event hash.

    NOTE: This is for VERIFICATION ONLY. Production event creation uses
    PostgreSQL's generate_event_signature() function via triggers.

    Args:
        event_hash: SHA-256 hash of event
        secret_key: Secret signing key

    Returns:
        Hex digest of HMAC signature
    """
    return hmac.new(
        key=secret_key.encode("utf-8"), msg=event_hash.encode("utf-8"), digestmod=hashlib.sha256
    ).hexdigest()


def verify_signature(event_hash: str, signature: str, secret_key: str) -> bool:
    """Verify HMAC signature matches event hash.

    Args:
        event_hash: SHA-256 hash of event
        signature: Claimed HMAC signature
        secret_key: Secret signing key

    Returns:
        True if signature is valid
    """
    expected_signature = sign_event(event_hash, secret_key)
    return hmac.compare_digest(signature, expected_signature)


class SigningKeyManager:
    """Manages signing keys with rotation support.

    NOTE: For VERIFICATION ONLY. Production event signing uses PostgreSQL's
    audit_signing_keys table and generate_event_signature() function.

    This class is useful for:
    - Testing and development
    - Offline signature verification
    - Forensic analysis from Python
    """

    def __init__(self) -> None:
        self.current_key: Optional[str] = None
        self.previous_keys: list[tuple[str, datetime]] = []
        self._load_keys()

    def _load_keys(self) -> None:
        """Load signing keys from environment or key vault.

        NOTE: In production, PostgreSQL uses audit_signing_keys table.
        This is for verification/testing only.
        """
        # No default: without AUDIT_SIGNING_KEY nothing signs and nothing verifies
        self.current_key = os.getenv("AUDIT_SIGNING_KEY") or None

    def sign(self, event_hash: str) -> str:
        """Sign event hash with current key.

        NOTE: Use only for testing. Production uses PostgreSQL triggers.
        """
        if not self.current_key:
            raise ValueError("No signing key available")
        return sign_event(event_hash, self.current_key)

    def verify(self, event_hash: str, signature: str) -> bool:
        """Verify signature with current or previous keys.

        This is the primary use case for this class in production:
        verifying signatures from audit logs.
        """
        # Try current key first
        if self.current_key and verify_signature(event_hash, signature, self.current_key):
            return True

        # Try previous keys (for events signed before rotation)
        for key, rotated_at in self.previous_keys:
            if verify_signature(event_hash, signature, key):
                return True

        return False


# Singleton instance
_key_manager: Optional[SigningKeyManager] = None


def get_key_manager() -> SigningKeyManager:
    """Get or create signing key manager singleton."""
    global _key_manager
    if _key_manager is None:
        _key_manager = SigningKeyManager()
    return _key_manager
