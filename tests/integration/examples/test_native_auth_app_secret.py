"""``examples/native_auth_app.py`` refuses to start without a signing secret.

It used to fall back to a literal secret, so a copy of the example deployed
without ``JWT_SECRET_KEY`` would sign with a key anyone can read in this repo.
"""

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def native_auth_app():
    spec = importlib.util.spec_from_file_location(
        "native_auth_app_example", _ROOT / "examples" / "native_auth_app.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", [None, "", "   "])
async def test_create_app_fails_without_a_secret(
    native_auth_app, monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET_KEY", value)

    def no_pool(*args, **kwargs):
        raise AssertionError("the secret is checked before connecting")

    monkeypatch.setattr(native_auth_app, "AsyncConnectionPool", no_pool)

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        await native_auth_app.create_app()

