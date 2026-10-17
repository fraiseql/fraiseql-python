"""Tests for `fraiseql migrate` paths that need no database."""

import re
from pathlib import Path

from click.testing import CliRunner

from fraiseql.cli.commands.migrate import migrate


def test_create_writes_timestamped_migration(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        migrate, ["create", "add_user_preferences", "--migrations-dir", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    [migration_file] = tmp_path.glob("*.py")
    assert re.fullmatch(r"\d{14}_add_user_preferences\.py", migration_file.name)
    source = migration_file.read_text()
    assert "class AddUserPreferences(Migration):" in source
    assert f'version = "{migration_file.name[:14]}"' in source


def test_status_lists_python_and_sql_migrations_when_database_is_unreachable(
    tmp_path: Path,
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "20260101000000_add_gadgets.up.sql").write_text("SELECT 1;")
    (migrations_dir / "20260101000000_add_gadgets.down.sql").write_text("SELECT 1;")
    (migrations_dir / "20260102000000_add_widgets.py").write_text("")
    config = tmp_path / "local.yaml"
    # Port 1 refuses connections immediately
    config.write_text(
        "name: local\ninclude_dirs: []\nexclude_dirs: []\n"
        "database:\n  host: 127.0.0.1\n  port: 1\n  database: x\n  user: x\n  password: x\n"
    )

    result = CliRunner().invoke(
        migrate, ["status", "--migrations-dir", str(migrations_dir), "--config", str(config)]
    )

    assert result.exit_code == 0, result.output
    assert "Could not connect to database" in result.output
    assert "add_gadgets" in result.output
    assert "add_widgets" in result.output
    assert "Total: 2 migrations" in result.output
