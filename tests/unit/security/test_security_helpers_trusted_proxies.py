"""``setup_production_security`` / ``setup_development_security`` pass ``trusted_proxies`` on.

Since 1.31.1 the rate limiter keys on the socket peer unless proxies are trusted;
``setup_security`` takes ``trusted_proxies`` but the two shortcuts did not, so an
app behind a proxy using them could not say which proxy to believe.
"""

import pytest
from fastapi import FastAPI

from fraiseql import security


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    seen: list[dict] = []

    def record(**kwargs) -> dict:
        seen.append(kwargs)
        return {}

    monkeypatch.setattr(security, "setup_security", record)
    return seen


def test_production_passes_trusted_proxies(calls: list[dict]) -> None:
    security.setup_production_security(
        FastAPI(),
        secret_key="k",
        domain="api.example.com",
        trusted_origins={"https://app.example.com"},
        trusted_proxies=["10.0.0.0/8"],
    )
    assert calls[0]["trusted_proxies"] == ["10.0.0.0/8"]


def test_development_passes_trusted_proxies(calls: list[dict]) -> None:
    security.setup_development_security(FastAPI(), secret_key="k", trusted_proxies="127.0.0.1")
    assert calls[0]["trusted_proxies"] == "127.0.0.1"


def test_without_them_none_are_trusted(calls: list[dict]) -> None:
    security.setup_production_security(FastAPI(), secret_key="k", domain="d", trusted_origins=set())
    security.setup_development_security(FastAPI(), secret_key="k")
    assert [call["trusted_proxies"] for call in calls] == [None, None]
