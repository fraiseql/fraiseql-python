"""CLI command for inspecting pg_stat_statements query performance data."""

import asyncio
import sys

import click

from fraiseql.monitoring.query_stats import (
    QueryStatsSnapshot,
    init_query_stats,
)

ORDER_BY_CHOICES = click.Choice(
    ["total_exec_time", "mean_exec_time", "calls", "cache_hit_ratio"]
)


def _format_duration(ms: float) -> str:
    """Format milliseconds into a human-readable string."""
    if ms >= 1000:
        return f"{ms / 1000:,.2f}s"
    return f"{ms:,.2f}ms"


def _format_cache_hit(ratio: float) -> str:
    """Format cache hit ratio with color coding."""
    text = f"{ratio:.1f}%"
    if ratio < 90:
        return click.style(text, fg="red")
    if ratio < 95:
        return click.style(text, fg="yellow")
    return click.style(text, fg="green")


def _print_stats_table(
    stats: list[QueryStatsSnapshot],
    order_by: str,
    database_url: str,
) -> None:
    """Print formatted query statistics table."""
    click.echo(
        f"\nFraiseQL Query Statistics "
        f"(ordered by {order_by})"
    )
    click.echo(f"Database: {_mask_password(database_url)}\n")

    if not stats:
        click.echo("No query statistics available yet.")
        return

    # Header
    click.echo(
        f"{'#':>3}  {'Query':<50}  {'Calls':>8}  "
        f"{'Total':>12}  {'Mean':>10}  "
        f"{'Cache Hit':>10}  {'Rows':>10}"
    )
    click.echo("-" * 112)

    # Rows
    for i, s in enumerate(stats, 1):
        preview = s.query_preview[:48]
        if len(s.query_preview) > 48:
            preview += ".."
        click.echo(
            f"{i:>3}  {preview:<50}  {s.calls:>8,}  "
            f"{_format_duration(s.total_exec_time_ms):>12}  "
            f"{_format_duration(s.mean_exec_time_ms):>10}  "
            f"{_format_cache_hit(s.cache_hit_ratio):>10}  "
            f"{s.rows_returned:>10,}"
        )

    # Footer
    total_blks_hit = sum(s.shared_blks_hit for s in stats)
    total_blks_read = sum(s.shared_blks_read for s in stats)
    if total_blks_hit + total_blks_read > 0:
        overall_ratio = total_blks_hit / (total_blks_hit + total_blks_read) * 100
    else:
        overall_ratio = 100.0

    click.echo(
        f"\n{len(stats)} tracked query pattern(s) | "
        f"Overall cache hit ratio: {_format_cache_hit(overall_ratio)}"
    )


def _mask_password(url: str) -> str:
    """Mask password in database URL for display."""
    if "://" not in url:
        return url
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.password:
            return url.replace(f":{parsed.password}@", ":***@")
    except Exception:
        pass
    return url


async def _run_query_stats(
    database_url: str,
    top_n: int,
    order_by: str,
) -> None:
    """Async implementation of query-stats display."""
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        database_url, min_size=1, max_size=2, open=False
    )
    await pool.open()

    try:
        collector = init_query_stats(pool)

        if not await collector.is_available():
            click.echo(
                click.style(
                    "pg_stat_statements extension is not available.\n"
                    "Install it with: CREATE EXTENSION pg_stat_statements;\n"
                    "Note: shared_preload_libraries must include "
                    "'pg_stat_statements' (requires server restart).",
                    fg="yellow",
                ),
                err=True,
            )
            sys.exit(1)

        stats = await collector.get_stats(top_n=top_n, order_by=order_by)
        _print_stats_table(stats, order_by, database_url)
    finally:
        await pool.close()


async def _run_reset(database_url: str) -> None:
    """Async implementation of query-stats reset."""
    from psycopg_pool import AsyncConnectionPool

    from fraiseql.core.exceptions import FraiseQLError

    pool = AsyncConnectionPool(
        database_url, min_size=1, max_size=2, open=False
    )
    await pool.open()

    try:
        collector = init_query_stats(pool)
        await collector.reset_stats()
        click.echo(
            click.style(
                "Query statistics have been reset.",
                fg="green",
            )
        )
    except FraiseQLError as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)
    finally:
        await pool.close()


@click.command("query-stats")
@click.option(
    "--top-n",
    default=20,
    show_default=True,
    help="Number of queries to display.",
)
@click.option(
    "--order-by",
    default="total_exec_time",
    show_default=True,
    type=ORDER_BY_CHOICES,
    help="Metric to sort results by.",
)
@click.option(
    "--database-url",
    envvar="DATABASE_URL",
    required=True,
    help="PostgreSQL connection string.",
)
@click.option(
    "--reset",
    is_flag=True,
    default=False,
    help="Reset all query statistics counters.",
)
def query_stats(
    top_n: int,
    order_by: str,
    database_url: str,
    reset: bool,
) -> None:
    """Display pg_stat_statements query performance data.

    Shows the top queries by execution time, call count, or cache hit ratio.
    Requires the pg_stat_statements extension to be installed and loaded.

    Examples:
        fraiseql query-stats --database-url postgresql://localhost/mydb

        fraiseql query-stats --top-n 10 --order-by mean_exec_time

        fraiseql query-stats --reset
    """
    if reset:
        if not click.confirm("Reset all query statistics?"):
            click.echo("Cancelled.")
            return
        asyncio.run(_run_reset(database_url))
    else:
        asyncio.run(
            _run_query_stats(database_url, top_n, order_by)
        )
