"""``SigningKeyManager`` has no built-in key.

Without ``AUDIT_SIGNING_KEY`` it used ``"test-key-for-testing"``, so ``verify()``
accepted a signature that anyone reading this repository could make.
"""

import pytest

from fraiseql.enterprise.crypto.signing import SigningKeyManager, sign_event


def test_without_a_configured_key_nothing_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUDIT_SIGNING_KEY", raising=False)
    manager = SigningKeyManager()

    forged = sign_event("event-hash", "test-key-for-testing")

    assert manager.current_key is None
    assert not manager.verify("event-hash", forged)
    with pytest.raises(ValueError, match="No signing key"):
        manager.sign("event-hash")


def test_a_configured_key_signs_and_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIT_SIGNING_KEY", "configured-key")
    manager = SigningKeyManager()

    assert manager.verify("event-hash", manager.sign("event-hash"))
    assert not manager.verify("event-hash", sign_event("event-hash", "test-key-for-testing"))
