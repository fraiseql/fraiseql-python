"""``setup_development_security`` has no built-in secret key.

Its default was a literal published in this repository; a process that called it
without a key signed with that one.
"""

import pytest
from fastapi import FastAPI

from fraiseql import security


@pytest.fixture
def secrets_used(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    used: list[str] = []

    def record(**kwargs) -> dict:
        used.append(kwargs["secret_key"])
        return {}

    monkeypatch.setattr(security, "setup_security", record)
    return used


def test_without_a_key_each_call_gets_its_own_random_key(secrets_used: list[str]) -> None:
    security.setup_development_security(FastAPI())
    security.setup_development_security(FastAPI())

    first, second = secrets_used
    assert first != second
    assert len(first) >= 43
    assert "change-in-production" not in first


def test_a_given_key_is_used(secrets_used: list[str]) -> None:
    security.setup_development_security(FastAPI(), secret_key="mine")

    assert secrets_used == ["mine"]
