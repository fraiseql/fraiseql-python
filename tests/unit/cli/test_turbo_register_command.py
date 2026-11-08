"""`fraiseql turbo register` with a root field that takes no arguments.

graphql-core 3.3 leaves an absent argument list as `None`, not an empty list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from fraiseql.cli.commands.turbo import turbo
from fraiseql.fastapi.turbo import TurboRegistry
from fraiseql.turbo.registration import TurboRegistration

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "query",
    [
        "query GetUsers { users { id name } }",
        "query GetUsers($limit: Int) { users(limit: $limit) { id name } }",
    ],
)
def test_register_from_graphql_with_and_without_arguments(query: str) -> None:
    result = TurboRegistration(TurboRegistry()).register_from_graphql(query, {"users": "v_user"})

    assert result.success, result.error
    assert result.query_hash


def test_register_command_accepts_a_root_field_without_arguments(tmp_path: Path) -> None:
    query_file = tmp_path / "users.graphql"
    query_file.write_text("query GetUsers { users { id name } }\n")
    output = tmp_path / "results.json"

    result = CliRunner().invoke(turbo, ["register", str(query_file), "-o", str(output)])

    assert result.exit_code == 0, result.output
    assert "Registration complete: 1/1 successful" in result.output
    assert json.loads(output.read_text())[0]["error"] is None
