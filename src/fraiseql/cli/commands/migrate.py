"""Database migration management commands."""

from pathlib import Path

import click
from confiture.core.connection import create_connection, load_config

try:
    from confiture.core.connection import get_migration_class, load_migration_module
except ImportError:
    # confiture 1.16.0 moved these to a private module without a public re-export.
    # Drop this fallback once fraiseql/confiture#737 gives them a public home.
    from confiture.core._migrator.loader import get_migration_class, load_migration_module
from confiture.core.migration_generator import MigrationGenerator
from confiture.core.migrator import Migrator
from rich.console import Console
from rich.table import Table

console = Console()


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

database:
  host: localhost
  port: 5432
  database: fraiseql_local
  user: postgres
  password: postgres
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

        # Generate migration file
        generator = MigrationGenerator(migrations_dir=migrations_path)

        version = generator._get_next_version()
        class_name = generator._to_class_name(name)
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

        # Find migration files
        migration_files = sorted(migrations_path.glob("*.py"))

        if not migration_files:
            console.print("[yellow]No migrations found.[/yellow]")
            console.print("\n💡 Run 'fraiseql migrate create <name>' to create one")
            return

        # Get applied migrations from database
        applied_versions = set()
        config_path = Path(config)

        if config_path.exists():
            try:
                config_data = load_config(config_path)
                conn = create_connection(config_data)
                migrator = Migrator(connection=conn)
                migrator.initialize()
                applied_versions = set(migrator.get_applied_versions())
                conn.close()
            except Exception as e:
                console.print(f"[yellow]⚠️  Could not connect to database: {e}[/yellow]")
                console.print("[yellow]Showing file list only (status unknown)[/yellow]\n")

        # Display migrations in a table
        table = Table(title="FraiseQL Migrations")
        table.add_column("Version", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Status", style="yellow")

        pending_count = 0
        applied_count = 0

        for migration_file in migration_files:
            # Extract version and name from filename
            parts = migration_file.stem.split("_", 1)
            version = parts[0] if len(parts) > 0 else "???"
            name = parts[1] if len(parts) > 1 else migration_file.stem

            # Determine status
            if applied_versions:
                if version in applied_versions:
                    status_text = "[green]✅ applied[/green]"
                    applied_count += 1
                else:
                    status_text = "[yellow]⏳ pending[/yellow]"
                    pending_count += 1
            else:
                status_text = "unknown"

            table.add_row(version, name, status_text)

        console.print(table)
        console.print(f"\n📊 Total: {len(migration_files)} migrations", end="")
        if applied_versions:
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

        # Load configuration
        config_data = load_config(config_path)

        # Create database connection
        conn = create_connection(config_data)

        # Create migrator
        migrator = Migrator(connection=conn)
        migrator.initialize()

        # Find pending migrations
        pending_migrations = migrator.find_pending(migrations_dir=migrations_path)

        if not pending_migrations:
            console.print("[green]✅ No pending migrations. Database is up to date.[/green]")
            conn.close()
            return

        console.print(f"[cyan]📦 Found {len(pending_migrations)} pending migration(s)[/cyan]\n")

        # Apply migrations
        applied_count = 0
        for migration_file in pending_migrations:
            # Load migration module
            module = load_migration_module(migration_file)
            migration_class = get_migration_class(module)

            # Create migration instance
            migration = migration_class(connection=conn)

            # Check target
            if target and migration.version > target:
                console.print(f"[yellow]⏭️  Skipping {migration.version} (after target)[/yellow]")
                break

            # Apply migration
            console.print(
                f"[cyan]⚡ Applying {migration.version}_{migration.name}...[/cyan]", end=" "
            )
            migrator.apply(migration)
            console.print("[green]✅[/green]")
            applied_count += 1

        console.print(f"\n[green]✅ Successfully applied {applied_count} migration(s)![/green]")
        console.print("\n💡 Your FraiseQL schema is up to date!")
        conn.close()

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

        # Load configuration
        config_data = load_config(config_path)

        # Create database connection
        conn = create_connection(config_data)

        # Create migrator
        migrator = Migrator(connection=conn)
        migrator.initialize()

        # Get applied migrations
        applied_versions = migrator.get_applied_versions()

        if not applied_versions:
            console.print("[yellow]⚠️  No applied migrations to rollback.[/yellow]")
            conn.close()
            return

        # Get migrations to rollback (last N)
        versions_to_rollback = applied_versions[-steps:]

        console.print(f"[cyan]📦 Rolling back {len(versions_to_rollback)} migration(s)[/cyan]\n")

        # Confirm rollback
        if not click.confirm(
            f"⚠️  This will rollback {len(versions_to_rollback)} migration(s). Continue?"
        ):
            console.print("[yellow]Rollback cancelled.[/yellow]")
            conn.close()
            return

        # Rollback migrations in reverse order
        rolled_back_count = 0
        for version in reversed(versions_to_rollback):
            # Find migration file
            migration_files = migrator.find_migration_files(migrations_dir=migrations_path)
            migration_file = None
            for mf in migration_files:
                if migrator._version_from_filename(mf.name) == version:
                    migration_file = mf
                    break

            if not migration_file:
                console.print(f"[red]❌ Migration file for version {version} not found[/red]")
                continue

            # Load migration module
            module = load_migration_module(migration_file)
            migration_class = get_migration_class(module)

            # Create migration instance
            migration = migration_class(connection=conn)

            # Rollback migration
            console.print(
                f"[cyan]⚡ Rolling back {migration.version}_{migration.name}...[/cyan]", end=" "
            )
            migrator.rollback(migration)
            console.print("[green]✅[/green]")
            rolled_back_count += 1

        console.print(
            f"\n[green]✅ Successfully rolled back {rolled_back_count} migration(s)![/green]"
        )
        conn.close()

    except Exception as e:
        console.print(f"[red]❌ Error rolling back migrations: {e}[/red]")
        raise click.ClickException(str(e))
