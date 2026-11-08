"""docs/tutorials/python-blog-api.md runs as written.

The tutorial's SQL blocks are applied to a fresh database, its Python blocks
become app.py, and its Part 4 GraphQL operations run in order through
TestClient, with the ids pasted in as a reader would. The app registers its
types globally, so it runs in its own process.
"""

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.database]

_TUTORIAL = Path(__file__).resolve().parents[3] / "docs" / "tutorials" / "python-blog-api.md"

_FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.MULTILINE | re.DOTALL)

# Runs app.py through TestClient and prints one JSON line with every response
_RUN = """
import json, sys
sys.path.insert(0, sys.argv[1])
from fastapi.testclient import TestClient
import app

operations = json.loads(sys.argv[2])
ids = {}
out = []
with TestClient(app.app) as client:
    for operation in operations:
        for placeholder, value in ids.items():
            operation = operation.replace(placeholder, value)
        body = client.post("/graphql", json={"query": operation}).json()
        out.append(body)
        data = body.get("data") or {}
        if (data.get("createAuthor") or {}).get("author"):
            ids["PASTE-AUTHOR-ID-HERE"] = data["createAuthor"]["author"]["id"]
        if (data.get("createPost") or {}).get("post"):
            ids["PASTE-POST-ID-HERE"] = data["createPost"]["post"]["id"]
    for check in json.loads(sys.argv[3]):
        out.append(client.post("/graphql", json={"query": check}).json())
print(json.dumps(out))
"""

# Run after the tutorial's operations: what the tutorial says about where,
# orderBy and errors
_CHECKS = [
    "{ authors(limit: 1) { name } }",
    "{ authors(orderBy: {createdAt: ASC}, limit: 1) { name } }",
    '{ authors(where: {name: {eq: "Alice Smith"}}) { name createdAt } }',
    "{ posts(published: false) { title } }",
    """mutation {
      createPost(input: {title: "t", content: "c",
                         authorId: "00000000-0000-0000-0000-000000000000"}) {
        ... on CreatePostSuccess { post { id } }
        ... on MutationError { status message code }
      }
    }""",
]


def _blocks(language: str, start: str, end: str) -> list[str]:
    text = _TUTORIAL.read_text()
    part = text[text.index(start) : text.index(end)]
    return [body for lang, body in _FENCE.findall(part) if lang == language]


def _without_typename(value):
    if isinstance(value, dict):
        return {k: _without_typename(v) for k, v in value.items() if k != "__typename"}
    if isinstance(value, list):
        return [_without_typename(v) for v in value]
    return value


@pytest.fixture
def blog_database(postgres_url):
    name = f"blog_tutorial_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(postgres_url, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {name}")
    url = urlunparse(urlparse(postgres_url)._replace(path=f"/{name}"))
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            for sql in _blocks("sql", "## Part 1", "### Step 1.5"):
                conn.execute(sql)
            # A second author, created before the tutorial's, for the sort checks
            conn.execute(
                "INSERT INTO tb_author (name, email, created_at) "
                "VALUES ('Bob Early', 'bob@example.com', now() - interval '1 day')"
            )
        yield url
    finally:
        with psycopg.connect(postgres_url, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def test_tutorial_runs_end_to_end(blog_database, tmp_path) -> None:
    app_source = "\n\n".join(_blocks("python", "## Part 2", "## Part 4"))
    (tmp_path / "app.py").write_text(app_source)
    operations = _blocks("graphql", "## Part 4", "## Part 5")
    assert len(operations) == 6

    result = subprocess.run(
        [sys.executable, "-c", _RUN, str(tmp_path), json.dumps(operations), json.dumps(_CHECKS)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "DATABASE_URL": blog_database},
    )
    assert result.returncode == 0, result.stderr[-3000:]
    out = json.loads(result.stdout.strip().splitlines()[-1])
    for body in out:
        assert "errors" not in body, body
    # The Rust pipeline adds __typename to every object, selected or not
    data = [_without_typename(body["data"]) for body in out]
    author, post, posts, one_post, comment, comments, *checks = data
    newest, oldest, named, drafts, missing = checks

    assert author["createAuthor"]["author"]["name"] == "Alice Smith"
    assert author["createAuthor"]["message"] == "Author created"
    assert post["createPost"]["post"]["author"] == {"name": "Alice Smith"}
    assert [p["title"] for p in posts["posts"]] == ["Getting Started with GraphQL"]
    assert posts["posts"][0]["author"] == {"name": "Alice Smith", "email": "alice@example.com"}
    assert posts["posts"][0]["createdAt"]
    assert one_post["post"]["published"] is True
    assert comment["addComment"]["comment"]["author"] == {"name": "Alice Smith"}
    assert [c["content"] for c in comments["postComments"]] == ["Great article!"]

    assert newest["authors"] == [{"name": "Alice Smith"}]
    assert oldest["authors"] == [{"name": "Bob Early"}]
    assert [a["name"] for a in named["authors"]] == ["Alice Smith"]
    assert drafts["posts"] == []
    assert missing["createPost"] == {
        "status": "not_found:author",
        "message": "author not found",
        "code": 404,
    }
