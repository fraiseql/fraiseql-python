"""End-to-end tests for `fraiseql migrate` against PostgreSQL.

Each test gets its own database and runs once per environment-file format:
the `database_url` that `fraiseql migrate init` writes now, and the
`database:` mapping it wrote before, which existing projects still have and
confiture's `Environment` doesn't accept on its own.
"""

import uuid
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from click.testing import CliRunner, Result
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from fraiseql.cli.commands.migrate import migrate

pytestmark = [pytest.mark.integration, pytest.mark.database]

PYTHON_MIGRATION = """
from confiture.models.migration import Migration


class AddWidgets(Migration):
    version = "20260102000000"
    name = "add_widgets"

    def up(self) -> None:
        self.execute("CREATE TABLE widgets (id int PRIMARY KEY)")

    def down(self) -> None:
        self.execute("DROP TABLE widgets")
"""


@pytest.fixture
def migrate_db(postgres_url: str) -> Generator[str]:
    """A fresh, empty database; yields its connection URL."""
    db_name = f"migrate_cli_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(postgres_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
    yield urlsplit(postgres_url)._replace(path=f"/{db_name}").geturl()
    with psycopg.connect(postgres_url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db_name))
        )


@pytest.fixture(params=["database_url", "database_mapping"])
def project(request: pytest.FixtureRequest, tmp_path: Path, migrate_db: str) -> tuple[Path, Path]:
    """(migrations_dir, config_file) for a project pointed at `migrate_db`."""
    params = conninfo_to_dict(migrate_db)
    migrations_dir = tmp_path / "db" / "migrations"
    migrations_dir.mkdir(parents=True)
    config = tmp_path / "db" / "environments" / "local.yaml"
    config.parent.mkdir(parents=True)
    if request.param == "database_url":
        connection = f"database_url: {migrate_db}"
    else:
        connection = f"""database:
  host: {params.get("host", "localhost")}
  port: {params.get("port", 5432)}
  database: {params["dbname"]}
  user: {params.get("user", "postgres")}
  password: {params.get("password", "")}"""
    config.write_text(f"name: local\ninclude_dirs: []\nexclude_dirs: []\n{connection}\n")
    return migrations_dir, config


def _run(args: list[str], project: tuple[Path, Path], user_input: str | None = None) -> Result:
    migrations_dir, config = project
    return CliRunner().invoke(
        migrate,
        [*args, "--migrations-dir", str(migrations_dir), "--config", str(config)],
        input=user_input,
    )


def _table_exists(db_url: str, table: str) -> bool:
    with psycopg.connect(db_url) as conn:
        return conn.execute("SELECT to_regclass(%s) IS NOT NULL", (table,)).fetchone()[0]


def test_sql_migration_up_status_down(project: tuple[Path, Path], migrate_db: str) -> None:
    """A pending `.up.sql` migration used to crash `migrate up` (it was loaded as Python)."""
    migrations_dir, _ = project
    (migrations_dir / "20260101000000_add_gadgets.up.sql").write_text(
        "CREATE TABLE gadgets (id int PRIMARY KEY);"
    )
    (migrations_dir / "20260101000000_add_gadgets.down.sql").write_text("DROP TABLE gadgets;")

    result = _run(["up"], project)
    assert result.exit_code == 0, result.output
    assert "Successfully applied 1 migration(s)" in result.output
    assert _table_exists(migrate_db, "gadgets")

    result = _run(["status"], project)
    assert result.exit_code == 0, result.output
    assert "add_gadgets" in result.output
    assert "1 applied, 0 pending" in result.output

    result = _run(["down"], project, user_input="y\n")
    assert result.exit_code == 0, result.output
    assert "Successfully rolled back 1 migration(s)" in result.output
    assert not _table_exists(migrate_db, "gadgets")


def test_mixed_migrations_apply_in_order_and_respect_target(
    project: tuple[Path, Path], migrate_db: str
) -> None:
    migrations_dir, _ = project
    (migrations_dir / "20260101000000_add_gadgets.up.sql").write_text(
        "CREATE TABLE gadgets (id int PRIMARY KEY);"
    )
    (migrations_dir / "20260101000000_add_gadgets.down.sql").write_text("DROP TABLE gadgets;")
    (migrations_dir / "20260102000000_add_widgets.py").write_text(PYTHON_MIGRATION)

    result = _run(["up", "--target", "20260101000000"], project)
    assert result.exit_code == 0, result.output
    assert _table_exists(migrate_db, "gadgets")
    assert not _table_exists(migrate_db, "widgets")

    result = _run(["status"], project)
    assert "1 applied, 1 pending" in result.output

    result = _run(["up"], project)
    assert result.exit_code == 0, result.output
    assert "Successfully applied 1 migration(s)" in result.output
    assert _table_exists(migrate_db, "widgets")

    result = _run(["up"], project)
    assert result.exit_code == 0, result.output
    assert "No pending migrations" in result.output

    result = _run(["down", "--steps", "2"], project, user_input="y\n")
    assert result.exit_code == 0, result.output
    assert "Successfully rolled back 2 migration(s)" in result.output
    assert not _table_exists(migrate_db, "widgets")
    assert not _table_exists(migrate_db, "gadgets")


def test_created_migration_applies(project: tuple[Path, Path]) -> None:
    """`migrate create` writes a migration confiture can load and apply."""
    result = _run_create("add_things", project)
    assert result.exit_code == 0, result.output

    result = _run(["up"], project)
    assert result.exit_code == 0, result.output
    assert "Successfully applied 1 migration(s)" in result.output


def test_failed_migration_exits_nonzero(project: tuple[Path, Path]) -> None:
    migrations_dir, _ = project
    (migrations_dir / "20260101000000_broken.up.sql").write_text("CREATE TABLE (;")

    result = _run(["up"], project)
    assert result.exit_code != 0
    assert "Successfully applied" not in result.output


def test_down_cancelled_keeps_migration(project: tuple[Path, Path], migrate_db: str) -> None:
    migrations_dir, _ = project
    (migrations_dir / "20260101000000_add_gadgets.up.sql").write_text(
        "CREATE TABLE gadgets (id int PRIMARY KEY);"
    )
    (migrations_dir / "20260101000000_add_gadgets.down.sql").write_text("DROP TABLE gadgets;")
    assert _run(["up"], project).exit_code == 0

    result = _run(["down"], project, user_input="n\n")
    assert result.exit_code == 0, result.output
    assert "Rollback cancelled" in result.output
    assert _table_exists(migrate_db, "gadgets")


def _run_create(name: str, project: tuple[Path, Path]) -> Result:
    migrations_dir, _ = project
    return CliRunner().invoke(migrate, ["create", name, "--migrations-dir", str(migrations_dir)])
