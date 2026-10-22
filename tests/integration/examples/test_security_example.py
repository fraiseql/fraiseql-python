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

# Every response sets the csrf_token cookie; TestClient keeps it, as a browser
# would, but sends it back over plain HTTP only when it isn't Secure (development)
out = {"headers": dict(client.get("/security-info").headers)}
out |= {
    "anonymous_create": post(CREATE, {}),
    "short_title": post('mutation { createPost(input: {title: "Hi", content: "Long enough content"}) { id } }', AUTH),
    "create": post(CREATE, AUTH),
}
token = client.get("/csrf-token").json()["csrf_token"]
out["create_with_token"] = post(CREATE, {**AUTH, "X-CSRF-Token": token})
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
        env={**_env(), "ENVIRONMENT": environment},
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def _env() -> dict[str, str]:
    import os

    return {k: v for k, v in os.environ.items() if k != "ENVIRONMENT"}


def _error_code(response: dict) -> str:
    return response["body"]["errors"][0]["extensions"]["code"]


def test_development_accepts_the_csrf_cookie() -> None:
    out = _run("development")

    assert _error_code(out["anonymous_create"]) == "UNAUTHENTICATED"
    assert _error_code(out["short_title"]) == "VALIDATION_ERROR"
    assert out["create"]["status"] == 200
    assert out["create"]["body"]["data"]["createPost"]["title"] == "Hello world"
    assert [p["title"] for p in out["posts"]["body"]["data"]["posts"]] == [
        "Hello world",
        "Hello world",
    ]
    assert out["posts"]["body"]["data"]["me"] == {"username": "demo"}
    assert out["headers"]["x-content-type-options"] == "nosniff"


def test_production_requires_a_csrf_token_for_mutations() -> None:
    out = _run("production")

    # The cookie is Secure in production, so over HTTP only the header counts
    assert out["create"]["status"] == 403
    assert _error_code(out["create"]) == "CSRF_PROTECTION_FAILED"
    assert out["anonymous_create"]["status"] == 403
    assert out["create_with_token"]["status"] == 200
    assert out["create_with_token"]["body"]["data"]["createPost"]["title"] == "Hello world"
    assert "strict-transport-security" in out["headers"]
