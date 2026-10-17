"""Database migration management commands.

`up`, `down` and `status` delegate to confiture's `MigratorSession`
(`Migrator.from_config`), which loads both `.py` and `.up.sql` migrations and
takes confiture's migration lock, checksum checks and safety gates. Only that
public, contract-tested surface is used, so it works across every confiture
release fraiseql allows (see fraiseql/confiture#737).
"""

from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import click
import yaml
from confiture.config.environment import Environment
from confiture.core.migrator import Migrator
from rich.console import Console
from rich.table import Table

console = Console()


def _database_url(database: dict[str, Any]) -> str:
    """Build a database URL from a `database:` mapping, with confiture's old defaults."""
    user = quote(str(database.get("user", "postgres")), safe="")
    password = quote(str(database.get("password", "")), safe="")
    credentials = f"{user}:{password}" if password else user
    host = database.get("host", "localhost")
    port = database.get("port", 5432)
    name = quote(str(database.get("database", "postgres")), safe="")
    return f"postgresql://{credentials}@{host}:{port}/{name}"


def _open_session(config_path: Path, migrations_path: Path) -> Any:
    """Open a confiture `MigratorSession` for an environment file.

    `fraiseql migrate init` used to write the connection as a `database:` mapping
    (host, port, ...), which confiture's `Environment` doesn't accept: it needs
    `database_url`. Such files are converted here, so existing projects keep
    working; any other file is handed to confiture as is.
    """
    data = yaml.safe_load(config_path.read_text()) or {}
    if "database_url" not in data and isinstance(data.get("database"), dict):
        environment = {key: value for key, value in data.items() if key != "database"}
        environment["database_url"] = _database_url(data["database"])
        return Migrator.from_config(Environment(**environment), migrations_dir=migrations_path)
    return Migrator.from_config(config_path, migrations_dir=migrations_path)


def _migration_files(migrations_path: Path) -> list[Path]:
    """Python and SQL (`.up.sql`) migration files, in version order."""
    return sorted([*migrations_path.glob("*.py"), *migrations_path.glob("*.up.sql")])


def _split_migration_filename(migration_file: Path) -> tuple[str, str]:
    """Split `<version>_<name>.py` or `<version>_<name>.up.sql` into (version, name)."""
    stem = migration_file.name.removesuffix(".up.sql").removesuffix(".py")
    version, _, name = stem.partition("_")
    return version, name or stem


@click.group()
def migrate() -> None:
    """Database migration management.

    Manage database schema migrations using confiture, integrated
    seamlessly with FraiseQL projects.
    """


@migrate.command()
@click.argument("path", type=click.Path(), default=".")
def init(path: str) -> None:
    """Initialize migrations in a FraiseQL project.

    Creates the necessary directory structure for database migrations,
    schema files, and environment configurations.

    Examples:
        fraiseql migrate init
        fraiseql migrate init ./my-project
    """
    try:
        project_path = Path(path)

        # Create directory structure
        db_dir = project_path / "db"
        schema_dir = db_dir / "schema"
        seeds_dir = db_dir / "seeds"
        migrations_dir = db_dir / "migrations"
        environments_dir = db_dir / "environments"

        # Check if already initialized
        if db_dir.exists():
            console.print(
                "[yellow]⚠️  Migration directory already exists. "
                "Some files may be overwritten.[/yellow]"
            )
            if not click.confirm("Continue?"):
                return

        # Create directories
        schema_dir.mkdir(parents=True, exist_ok=True)
        (seeds_dir / "common").mkdir(parents=True, exist_ok=True)
        (seeds_dir / "development").mkdir(parents=True, exist_ok=True)
        (seeds_dir / "test").mkdir(parents=True, exist_ok=True)
        migrations_dir.mkdir(parents=True, exist_ok=True)
        environments_dir.mkdir(parents=True, exist_ok=True)

        # Create example schema directory structure
        (schema_dir / "00_common").mkdir(exist_ok=True)
        (schema_dir / "10_tables").mkdir(exist_ok=True)

        # Create example extensions file
        example_extensions = schema_dir / "00_common" / "extensions.sql"
        example_extensions.write_text(
            """-- PostgreSQL extensions for FraiseQL
-- Add commonly used extensions here

-- UUID support
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Full-text search
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- LTree for hierarchical data (if using FraiseQL LTree types)
-- CREATE EXTENSION IF NOT EXISTS "ltree";
"""
        )

        # Create example table
        example_table = schema_dir / "10_tables" / "example.sql"
        example_table.write_text(
            """-- Example table
-- Replace with your actual FraiseQL schema

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create a JSONB view for FraiseQL (zero N+1 queries pattern)
CREATE OR REPLACE VIEW v_user AS
SELECT jsonb_build_object(
    'id', id,
    'username', username,
    'email', email,
    'createdAt', created_at,
    'updatedAt', updated_at
) AS data
FROM users;
"""
        )

        # Create example seed file
        example_seed = seeds_dir / "common" / "00_example.sql"
        example_seed.write_text(
            """-- Common seed data
-- These records are included in all non-production environments

-- Example: Test users for development
-- INSERT INTO users (username, email) VALUES
--     ('admin', 'admin@example.com'),
--     ('developer', 'dev@example.com'),
--     ('tester', 'test@example.com')
-- ON CONFLICT (username) DO NOTHING;
"""
        )

        # Create local environment config
        local_config = environments_dir / "local.yaml"
        local_config.write_text(
            """# Local development environment configuration for FraiseQL

name: local
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
exclude_dirs: []

database_url: postgresql://postgres:postgres@localhost:5432/fraiseql_local
"""
        )

        # Create README
        readme = db_dir / "README.md"
        readme.write_text(
            """# FraiseQL Database Schema

This directory contains your FraiseQL database schema and migrations.

## Directory Structure

- `schema/` - DDL files organized by category
  - `00_common/` - Extensions, types, functions
  - `10_tables/` - Table definitions and JSONB views
- `migrations/` - Python migration files
- `environments/` - Environment-specific configurations
- `seeds/` - Seed data for different environments

## Quick Start

1. Edit schema files in `schema/`
2. Create migrations: `fraiseql migrate create "add_feature"`
3. Apply migrations: `fraiseql migrate up`
4. Check status: `fraiseql migrate status`

## FraiseQL Best Practices

- Use JSONB views (v_*) for optimal GraphQL performance
- Follow the zero N+1 queries pattern
- Use CASCADE invalidation for result caching
- Store relationships in JSONB for sub-millisecond queries

## Learn More

- [FraiseQL Documentation](https://github.com/fraiseql/fraiseql)
- [Confiture Migration Tool](https://github.com/fraiseql/confiture)
"""
        )

        console.print("[green]✅ FraiseQL migrations initialized successfully![/green]")
        console.print(f"\n📁 Created structure in: {project_path.absolute()}")
        console.print("\n📝 Next steps:")
        console.print("  1. Edit your schema files in db/schema/")
        console.print("  2. Configure environments in db/environments/")
        console.print("  3. Run 'fraiseql migrate create' to create migrations")

    except Exception as e:
        console.print(f"[red]❌ Error initializing migrations: {e}[/red]")
        raise click.ClickException(str(e))


@migrate.command()
@click.argument("name")
@click.option(
    "--migrations-dir",
    type=click.Path(),
    default="db/migrations",
    help="Migrations directory",
)
def create(name: str, migrations_dir: str) -> None:
    """Create a new migration file.

    Creates an empty migration template with the given name.
    Use snake_case for the migration name.

    Examples:
        fraiseql migrate create add_user_preferences
        fraiseql migrate create update_post_schema
    """
    try:
        migrations_path = Path(migrations_dir)
        migrations_path.mkdir(parents=True, exist_ok=True)

        # Same version and class-name scheme as confiture's own generator
        version = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
        class_name = "".join(word.capitalize() for word in name.split("_"))
        filename = f"{version}_{name}.py"
        filepath = migrations_path / filename

        # Create template
        template = f'''"""Migration: {name}

Version: {version}
Generated by FraiseQL CLI
"""

from confiture.models.migration import Migration


class {class_name}(Migration):
    """Migration: {name}."""

    version = "{version}"
    name = "{name}"

    def up(self) -> None:
        """Apply migration.

        Add your SQL statements here to apply the migration.
        """
        # Example:
        # self.execute("""
        #     CREATE TABLE new_table (
        #         id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        #         name TEXT NOT NULL
        #     );
        # """)
        #
        # self.execute("""
        #     CREATE OR REPLACE VIEW v_new_table AS
        #     SELECT jsonb_build_object(
        #         'id', id,
        #         'name', name
        #     ) AS data
        #     FROM new_table;
        # """)
        pass

    def down(self) -> None:
        """Rollback migration.

        Add your SQL statements here to rollback the migration.
        """
        # Example:
        # self.execute("DROP VIEW IF EXISTS v_new_table;")
        # self.execute("DROP TABLE IF EXISTS new_table;")
        pass
'''

        filepath.write_text(template)

        console.print("[green]✅ Migration created successfully![/green]")
        click.echo(f"\n📄 File: {filepath.absolute()}")
        console.print("\n✏️  Edit the migration file to add your SQL statements.")
        console.print("💡 Remember to create JSONB views (v_*) for FraiseQL types!")

    except Exception as e:
        console.print(f"[red]❌ Error creating migration: {e}[/red]")
        raise click.ClickException(str(e))


@migrate.command()
@click.option(
    "--migrations-dir",
    type=click.Path(),
    default="db/migrations",
    help="Migrations directory",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    default="db/environments/local.yaml",
    help="Configuration file",
)
def status(migrations_dir: str, config: str) -> None:
    """Show migration status.

    Displays which migrations are applied vs pending.

    Examples:
        fraiseql migrate status
        fraiseql migrate status --config db/environments/production.yaml
    """
    try:
        migrations_path = Path(migrations_dir)

        if not migrations_path.exists():
            console.print("[yellow]No migrations directory found.[/yellow]")
            console.print(f"Expected: {migrations_path.absolute()}")
            console.print("\n💡 Run 'fraiseql migrate init' to get started")
            return

        migration_files = _migration_files(migrations_path)

        if not migration_files:
            console.print("[yellow]No migrations found.[/yellow]")
            console.print("\n💡 Run 'fraiseql migrate create <name>' to create one")
            return

        # (version, name, status) per migration; status is None when the database
        # can't be reached and only the files are known
        rows: list[tuple[str, str, str | None]] = []
        config_path = Path(config)

        if config_path.exists():
            try:
                with _open_session(config_path, migrations_path) as session:
                    result = session.status()
                rows = [(m.version, m.name, m.status) for m in result.migrations]
            except Exception as e:
                console.print(f"[yellow]⚠️  Could not connect to database: {e}[/yellow]")
                console.print("[yellow]Showing file list only (status unknown)[/yellow]\n")

        if not rows:
            rows = [(*_split_migration_filename(f), None) for f in migration_files]

        # Display migrations in a table
        table = Table(title="FraiseQL Migrations")
        table.add_column("Version", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Status", style="yellow")

        status_labels = {
            "applied": "[green]✅ applied[/green]",
            "pending": "[yellow]⏳ pending[/yellow]",
        }
        for version, name, migration_status in rows:
            if migration_status is None:
                status_text = "unknown"
            else:
                status_text = status_labels.get(migration_status, migration_status)
            table.add_row(version, name, status_text)

        console.print(table)
        console.print(f"\n📊 Total: {len(rows)} migrations", end="")
        if any(migration_status is not None for _, _, migration_status in rows):
            applied_count = sum(1 for *_, s in rows if s == "applied")
            pending_count = sum(1 for *_, s in rows if s == "pending")
            console.print(f" ({applied_count} applied, {pending_count} pending)")
        else:
            console.print()

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise click.ClickException(str(e))


@migrate.command()
@click.option(
    "--migrations-dir",
    type=click.Path(),
    default="db/migrations",
    help="Migrations directory",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    default="db/environments/local.yaml",
    help="Configuration file",
)
@click.option(
    "--target",
    help="Target migration version (applies all if not specified)",
)
def up(migrations_dir: str, config: str, target: str | None) -> None:
    """Apply pending migrations.

    Applies all pending migrations up to the target version (or all if no target).

    Examples:
        fraiseql migrate up
        fraiseql migrate up --target 003
        fraiseql migrate up --config db/environments/production.yaml
    """
    try:
        migrations_path = Path(migrations_dir)
        config_path = Path(config)

        if not config_path.exists():
            console.print(f"[red]❌ Config file not found: {config}[/red]")
            console.print("\n💡 Run 'fraiseql migrate init' to create it")
            raise click.ClickException(f"Config file not found: {config}")

        with _open_session(config_path, migrations_path) as session:
            result = session.up(target=target)

        for migration in result.migrations_applied:
            console.print(
                f"[cyan]⚡ Applied {migration.version}_{migration.name}[/cyan] [green]✅[/green]"
            )
        for version in result.skipped:
            console.print(f"[yellow]⏭️  Skipped {version}[/yellow]")

        if not result.success:
            raise click.ClickException(result.error_summary or "Migration failed")

        if not result.migrations_applied:
            console.print("[green]✅ No pending migrations. Database is up to date.[/green]")
            return

        console.print(
            f"\n[green]✅ Successfully applied "
            f"{len(result.migrations_applied)} migration(s)![/green]"
        )
        console.print("\n💡 Your FraiseQL schema is up to date!")

    except Exception as e:
        console.print(f"[red]❌ Error applying migrations: {e}[/red]")
        raise click.ClickException(str(e))


@migrate.command()
@click.option(
    "--migrations-dir",
    type=click.Path(),
    default="db/migrations",
    help="Migrations directory",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    default="db/environments/local.yaml",
    help="Configuration file",
)
@click.option(
    "--steps",
    default=1,
    help="Number of migrations to rollback",
)
def down(migrations_dir: str, config: str, steps: int) -> None:
    """Rollback applied migrations.

    Rolls back the last N applied migrations (default: 1).

    Examples:
        fraiseql migrate down
        fraiseql migrate down --steps 3
        fraiseql migrate down --config db/environments/staging.yaml
    """
    try:
        migrations_path = Path(migrations_dir)
        config_path = Path(config)

        if not config_path.exists():
            console.print(f"[red]❌ Config file not found: {config}[/red]")
            raise click.ClickException(f"Config file not found: {config}")

        with _open_session(config_path, migrations_path) as session:
            applied_count = len(session.status().applied)

            if not applied_count:
                console.print("[yellow]⚠️  No applied migrations to rollback.[/yellow]")
                return

            rollback_count = min(steps, applied_count)
            console.print(f"[cyan]📦 Rolling back {rollback_count} migration(s)[/cyan]\n")

            if not click.confirm(f"⚠️  This will rollback {rollback_count} migration(s). Continue?"):
                console.print("[yellow]Rollback cancelled.[/yellow]")
                return

            result = session.down(steps=steps)

        for migration in result.migrations_rolled_back:
            console.print(
                f"[cyan]⚡ Rolled back {migration.version}_{migration.name}[/cyan] "
                "[green]✅[/green]"
            )

        if not result.success:
            raise click.ClickException(result.error or "Rollback failed")

        console.print(
            f"\n[green]✅ Successfully rolled back "
            f"{len(result.migrations_rolled_back)} migration(s)![/green]"
        )

    except Exception as e:
        console.print(f"[red]❌ Error rolling back migrations: {e}[/red]")
        raise click.ClickException(str(e))
