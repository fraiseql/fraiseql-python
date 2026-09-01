"""The `fraiseql init` -> `fraiseql dev` first-run path.

These cover the four commands a new user types before anything else:

    fraiseql init demo && cd demo && fraiseql dev

Every failure mode here was reproduced by hand against a generated project
before the test was written.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from fraiseql.cli.commands.dev import dev
from fraiseql.cli.commands.init import init


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project(runner: CliRunner, _in_tmp_cwd: None) -> Path:
    """A generated project on disk, as `fraiseql init demo` leaves it."""
    result = runner.invoke(init, ["demo", "--no-git"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return Path("demo").resolve()


@pytest.fixture(autouse=True)
def _in_tmp_cwd(runner: CliRunner, tmp_path: Path):
    """Run each test in a scratch directory, with os.environ restored after.

    `fraiseql dev` calls load_dotenv(), which mutates the real process
    environment; without this the .env written here would leak into the rest
    of the suite.
    """
    saved = os.environ.copy()
    try:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _env_vars(project: Path) -> dict[str, str]:
    """Parse the generated .env, ignoring commented-out lines."""
    values = {}
    for raw in (project / ".env").read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


class TestDevServerImports:
    """`fraiseql dev` must be able to import the project it is run inside."""

    def test_dev_puts_the_project_root_on_sys_path(self, tmp_path: Path) -> None:
        """Without this, uvicorn.run() raises `No module named 'src'`.

        The uvicorn *CLI* inserts the app dir into sys.path; uvicorn.run()
        only does so when handed `app_dir`.
        """
        Path("pyproject.toml").write_text("[project]\nname = 'demo'\n")
        fake_uvicorn = MagicMock()

        with patch("fraiseql.cli.commands.dev.uvicorn", fake_uvicorn):
            CliRunner().invoke(dev, ["--no-reload"], catch_exceptions=False)

        assert fake_uvicorn.run.called, "uvicorn.run was never invoked"
        kwargs = fake_uvicorn.run.call_args.kwargs
        assert kwargs.get("app_dir") == str(Path.cwd()), (
            "dev must hand uvicorn the project root, or the string app target "
            f"{kwargs.get('app_dir')!r} cannot be imported"
        )


class TestDatabaseUrlVariable:
    """The variable `init` writes must be the variable the app reads."""

    def test_env_variable_is_the_one_main_py_reads(self, project: Path) -> None:
        env = _env_vars(project)
        main = (project / "src" / "main.py").read_text()

        read_vars = set(re.findall(r"getenv\(\s*[\"']([A-Z_]+)[\"']", main))
        assert read_vars, "src/main.py reads no environment variable at all"
        assert read_vars <= set(env), (
            f"src/main.py reads {sorted(read_vars - set(env))} but .env defines "
            f"{sorted(env)} - the URL in .env is silently ignored"
        )

    def test_generated_readme_names_a_variable_that_exists(self, project: Path) -> None:
        readme = (project / "README.md").read_text()
        env = _env_vars(project)
        assert "FRAISEQL_DATABASE_URL" in env
        assert not re.search(r"(?<!FRAISEQL_)\bDATABASE_URL\b", readme), (
            "README tells the user to edit a variable .env does not contain"
        )


class TestGeneratedPyproject:
    """A generated project must resolve to v1, on a Python v1 supports."""

    def test_fraiseql_dependency_is_pinned_below_v2(self, project: Path) -> None:
        data = tomllib.loads((project / "pyproject.toml").read_text())
        deps = data["project"]["dependencies"]
        pin = next((d for d in deps if d.startswith("fraiseql")), None)
        assert pin is not None, f"no fraiseql dependency in {deps}"
        assert "<2" in pin, (
            f"{pin!r} is unpinned - `pip install -e .` installs v2 from PyPI, "
            "which is a different framework"
        )

    def test_requires_python_matches_v1(self, project: Path) -> None:
        data = tomllib.loads((project / "pyproject.toml").read_text())
        assert data["project"]["requires-python"] == ">=3.13,<3.14"


class TestFirstQueryIsNotBlocked:
    """Nothing may stand between the user and their first query."""

    def test_dev_auth_is_not_enabled_by_default(self, project: Path) -> None:
        """An active dev-auth password makes every /graphql request a 401."""
        assert "FRAISEQL_DEV_AUTH_PASSWORD" not in _env_vars(project), (
            "generated .env enables DevAuthMiddleware, so the first query "
            "returns 401 Development authentication required"
        )

    def test_serves_a_query_with_no_database_running(self, project: Path) -> None:
        """The whole point: four commands, one working query, no Postgres."""
        probe = project / "_probe.py"
        probe.write_text(
            "import json\n"
            "from fastapi.testclient import TestClient\n"
            "from src.main import app\n"
            "with TestClient(app) as c:\n"
            "    r = c.post('/graphql', json={'query': '{ users { id name } }'})\n"
            "    print('PROBE', r.status_code, json.dumps(r.json()))\n"
        )
        result = subprocess.run(
            [sys.executable, "_probe.py"],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        line = next(
            (ln for ln in result.stdout.splitlines() if ln.startswith("PROBE")),
            None,
        )
        assert line is not None, (
            f"generated app never answered\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr[-3000:]}"
        )
        _, status, payload = line.split(" ", 2)
        body = json.loads(payload)
        assert status == "200", f"{status}: {payload}"
        assert "errors" not in body, f"query errored: {body['errors']}"
        assert body["data"] == {"users": []}


class TestMigrationLayout:
    """`fraiseql init` and `fraiseql migrate` must agree with each other."""

    def test_migrations_live_where_migrate_init_puts_them(self, project: Path) -> None:
        assert (project / "db" / "migrations").is_dir(), (
            "init creates migrations/ but `fraiseql migrate init` uses db/migrations/"
        )

    def test_readme_does_not_tell_users_to_run_the_group(self, project: Path) -> None:
        """`fraiseql migrate` is a click group - it prints help and exits."""
        readme = (project / "README.md").read_text()
        assert not re.search(r"`?fraiseql migrate`?\s*$", readme, re.MULTILINE), (
            "README says `fraiseql migrate`, which only prints help; "
            "the real commands are `migrate init` and `migrate up`"
        )


class TestShippedDatabase:
    """Real data must be one command away, not an assumed prerequisite."""

    def test_ships_a_compose_file(self, project: Path) -> None:
        compose = project / "docker-compose.yml"
        assert compose.exists(), "no docker-compose.yml - `docker compose up -d` fails"
        assert "postgres" in compose.read_text()

    def test_compose_database_matches_the_env_url(self, project: Path) -> None:
        """Starting the shipped Postgres must satisfy the shipped URL."""
        compose = (project / "docker-compose.yml").read_text()
        url = _env_vars(project)["FRAISEQL_DATABASE_URL"]
        parsed = re.match(
            r"postgresql://(?P<user>[^:]+):(?P<password>[^@]+)@[^:/]+"
            r":(?P<port>\d+)/(?P<db>\w+)",
            url,
        )
        assert parsed, f"{url!r} is not a full URL, so compose cannot match it"
        for key, value in parsed.groupdict().items():
            assert value in compose, f"compose does not set {key}={value} from .env"

    def test_published_port_avoids_a_local_postgres(self, project: Path) -> None:
        """5432 is taken on any machine that already runs PostgreSQL."""
        url = _env_vars(project)["FRAISEQL_DATABASE_URL"]
        port = int(re.search(r":(\d+)/", url).group(1))
        assert port != 5432, (
            "publishing 5432 means `docker compose up -d` fails with "
            "'port is already allocated' for anyone running PostgreSQL locally"
        )

    def test_ships_schema_sql_creating_the_queried_view(self, project: Path) -> None:
        sql = "\n".join(p.read_text() for p in project.glob("db/schema/*.sql"))
        assert sql.strip(), "no db/schema/*.sql - the shipped Postgres boots empty"
        assert "v_user" in sql, "schema does not create the view main.py queries"


class TestUnreachableDatabaseDiagnostic:
    """A missing database is one line, not a flood of pool tracebacks."""

    def test_dev_warns_once_and_still_starts(self, tmp_path: Path) -> None:
        Path("pyproject.toml").write_text("[project]\nname = 'demo'\n")
        Path(".env").write_text(
            "FRAISEQL_DATABASE_URL=postgresql://fraiseql:fraiseql@localhost:5432/demo\n"
        )
        fake_uvicorn = MagicMock()

        with (
            patch("fraiseql.cli.commands.dev.uvicorn", fake_uvicorn),
            patch(
                "fraiseql.cli.commands.dev._database_is_reachable",
                return_value=False,
            ),
        ):
            result = CliRunner().invoke(dev, ["--no-reload"], catch_exceptions=False)

        assert "docker compose up -d" in result.output, (
            f"no actionable diagnostic for an unreachable database:\n{result.output}"
        )
        assert fake_uvicorn.run.called, "dev must still start without a database"
