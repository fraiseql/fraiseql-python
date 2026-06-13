"""FraiseQL CLI main entry point."""

import sys

import click

from fraiseql import __version__

from .commands import (
    check,
    dev,
    doctor,
    generate,
    init_command,
    migrate,
    query_stats,
    sbom,
    sql,
    turbo,
    validate_mutation_return_command,
)


@click.group()
@click.version_option(version=__version__, prog_name="fraiseql")
def cli() -> None:
    """FraiseQL - Production-ready GraphQL API framework for PostgreSQL.

    A comprehensive GraphQL framework with CQRS architecture, type-safe mutations,
    JSONB optimization, and enterprise-grade features like conflict resolution,
    authentication, caching, and FastAPI integration.
    """


# Register commands
cli.add_command(init_command)
cli.add_command(dev)
cli.add_command(doctor)
cli.add_command(generate)
cli.add_command(check)
cli.add_command(sql)
cli.add_command(turbo)
cli.add_command(migrate)
cli.add_command(sbom.sbom_cli)
cli.add_command(query_stats)
cli.add_command(validate_mutation_return_command)


def main() -> None:
    """Main entry point for the CLI."""
    try:
        cli()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
