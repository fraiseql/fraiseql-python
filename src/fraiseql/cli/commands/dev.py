"""Development server command."""

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import click

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    import uvicorn
except ImportError:
    uvicorn = None

CONNECT_TIMEOUT_SECONDS = 2


def _redact_password(database_url: str) -> str:
    """Return the URL with any password replaced by ``***``."""
    parts = urlsplit(database_url)
    if not parts.password:
        return database_url
    userinfo = f"{parts.username}:***" if parts.username else "***"
    netloc = f"{userinfo}@{parts.hostname}"
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))


def _database_is_reachable(database_url: str) -> bool:
    """Open and immediately close one connection, to see if the server answers.

    A false negative here is harmless: it only suppresses a hint.
    """
    try:
        import psycopg
    except ImportError:
        return True

    try:
        with psycopg.connect(database_url, connect_timeout=CONNECT_TIMEOUT_SECONDS):
            return True
    except (psycopg.Error, OSError, ValueError):
        return False


def _warn_if_database_unreachable() -> None:
    """Say once, in one line, that there is no database - then get out of the way.

    Without this the only signal is the connection pool retrying forever, which
    buries the actual cause under a wall of identical tracebacks.
    """
    database_url = os.environ.get("FRAISEQL_DATABASE_URL")
    if not database_url or _database_is_reachable(database_url):
        return

    click.echo(f"⚠️  No database reachable at {_redact_password(database_url)}")
    click.echo("   Start the one this project ships with: docker compose up -d")
    click.echo("   Until then queries resolve to empty results.\n")


@click.command()
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to bind to",
)
@click.option(
    "--port",
    default=8000,
    type=int,
    help="Port to bind to",
)
@click.option(
    "--reload/--no-reload",
    default=True,
    help="Enable auto-reload on code changes",
)
@click.option(
    "--app",
    default="src.main:app",
    help="Application import path (module:attribute)",
)
def dev(host: str, port: int, reload: bool, app: str) -> None:
    """Start the FraiseQL development server.

    This runs your application with uvicorn, with hot-reloading
    enabled by default for development.
    """
    # Check if we're in a FraiseQL project
    if not Path("pyproject.toml").exists():
        click.echo("Error: Not in a FraiseQL project directory", err=True)
        click.echo("Run 'fraiseql init' to create a new project", err=True)
        msg = "Not in a FraiseQL project directory"
        raise click.ClickException(msg)

    # Load .env file if it exists
    env_file = Path(".env")
    if env_file.exists() and load_dotenv is not None:
        click.echo("📋 Loading environment from .env file")
        load_dotenv(str(env_file))

    click.echo("🚀 Starting FraiseQL development server...")
    click.echo(f"   GraphQL API: http://{host}:{port}/graphql")
    click.echo(f"   Interactive GraphiQL: http://{host}:{port}/graphql")

    if reload:
        click.echo("   Auto-reload: enabled")

    click.echo("\n   Press CTRL+C to stop\n")

    _warn_if_database_unreachable()

    # Check if uvicorn is available
    if uvicorn is None:
        click.echo("Error: uvicorn not installed. Run 'pip install uvicorn'", err=True)
        msg = "uvicorn not installed"
        raise click.ClickException(msg)

    # `app` is an import string, and uvicorn.run() - unlike the uvicorn CLI -
    # does not put the working directory on sys.path by itself. Without app_dir
    # the default target "src.main:app" fails with "No module named 'src'".
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
        app_dir=str(Path.cwd()),
    )
