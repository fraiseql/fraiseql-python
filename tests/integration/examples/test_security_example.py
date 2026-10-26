"""examples/security/secure_graphql_api.py runs as its README describes (#574).

The example reads ENVIRONMENT at import and registers its types globally, so
each scenario runs in its own process. Its posts live in memory: no database.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.examples

_ROOT = Path(__file__).resolve().parents[3]

# Runs the example's app through TestClient and prints one JSON line per request
_RUN = """
import json, sys
sys.path.insert(0, sys.argv[1])
from fastapi.testclient import TestClient
import secure_graphql_api as example

AUTH = {"Authorization": "Bearer valid-token"}
CREATE = 'mutation { createPost(input: {title: "Hello world", content: "Long enough content", published: true}) { id title } }'

client = TestClient(example.app)
client.__enter__()  # run the lifespan: fraiseql opens its (unused) pool there

def post(query, headers):
    r = client.post("/graphql", json={"query": query}, headers=headers)
    return {"status": r.status_code, "body": r.json()}

# Every response sets the csrf_token cookie and TestClient sends it back, as a
# browser would; mutations still need the token in the X-CSRF-Token header
out = {"headers": dict(client.get("/security-info").headers)}
CSRF = {"X-CSRF-Token": client.get("/csrf-token").json()["csrf_token"]}
out |= {
    "anonymous_create": post(CREATE, CSRF),
    "short_title": post('mutation { createPost(input: {title: "Hi", content: "Long enough content"}) { id } }', {**AUTH, **CSRF}),
    "create": post(CREATE, AUTH),
    "create_with_token": post(CREATE, {**AUTH, **CSRF}),
}
out["posts"] = post("{ posts { title } me { username } }", AUTH)
client.__exit__(None, None, None)
print(json.dumps(out))
"""


def _run(environment: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _RUN, str(_ROOT / "examples" / "security")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=_ROOT,
        # Outside development the example refuses to start without SECRET_KEY
        env={**_env(), "ENVIRONMENT": environment, "SECRET_KEY": "test-only-secret"},
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def _env() -> dict[str, str]:
    import os

    return {k: v for k, v in os.environ.items() if k != "ENVIRONMENT"}


def _error_code(response: dict) -> str:
    return response["body"]["errors"][0]["extensions"]["code"]


@pytest.mark.parametrize("environment", ["development", "production"])
def test_mutations_require_a_csrf_token(environment: str) -> None:
    out = _run(environment)

    assert out["create"]["status"] == 403
    assert _error_code(out["create"]) == "CSRF_PROTECTION_FAILED"
    assert _error_code(out["anonymous_create"]) == "UNAUTHENTICATED"
    assert _error_code(out["short_title"]) == "VALIDATION_ERROR"
    assert out["create_with_token"]["status"] == 200
    assert out["create_with_token"]["body"]["data"]["createPost"]["title"] == "Hello world"
    assert [p["title"] for p in out["posts"]["body"]["data"]["posts"]] == ["Hello world"]
    assert out["posts"]["body"]["data"]["me"] == {"username": "demo"}
    assert out["headers"]["x-content-type-options"] == "nosniff"
    if environment == "production":
        assert "strict-transport-security" in out["headers"]
