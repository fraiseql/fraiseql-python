"""``examples/security/secure_graphql_api.py`` has no built-in signing secret.

It used to fall back to a literal key in every environment, so a production
deployment without ``SECRET_KEY`` signed with a key published in this repository.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "security" / "secure_graphql_api.py"

_LOAD = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("secure_graphql_api", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.SECRET_KEY)
"""


def _load(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _LOAD, str(_EXAMPLE)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **env},
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_outside_development_a_missing_secret_fails(environment: str) -> None:
    result = _load({"ENVIRONMENT": environment, "SECRET_KEY": " "})
    assert result.returncode != 0
    assert "Set SECRET_KEY" in result.stderr


def test_development_gets_a_random_key_per_process() -> None:
    first = _load({"ENVIRONMENT": "development"})
    second = _load({"ENVIRONMENT": "development"})
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip() != second.stdout.strip()
    assert "change-in-production" not in first.stdout


def test_a_configured_secret_is_used() -> None:
    result = _load({"ENVIRONMENT": "production", "SECRET_KEY": "s3cr3t-from-the-environment"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "s3cr3t-from-the-environment"
