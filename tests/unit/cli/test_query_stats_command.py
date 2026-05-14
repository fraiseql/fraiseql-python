"""Unit tests for fraiseql query-stats CLI command."""

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from fraiseql.cli.commands.query_stats import query_stats
from fraiseql.monitoring.query_stats import QueryStatsSnapshot

SAMPLE_STATS = [
    QueryStatsSnapshot(
        queryid=111,
        query_preview="SELECT u.id, u.name FROM users WHERE id = $1",
        calls=4521,
        total_exec_time_ms=12340.5,
        mean_exec_time_ms=2.73,
        min_exec_time_ms=0.01,
        max_exec_time_ms=50.0,
        rows_returned=4521,
        shared_blks_hit=9000,
        shared_blks_read=100,
        cache_hit_ratio=98.9,
    ),
    QueryStatsSnapshot(
        queryid=222,
        query_preview="SELECT p.*, u.name FROM posts JOIN users ON ...",
        calls=1203,
        total_exec_time_ms=8901.2,
        mean_exec_time_ms=7.40,
        min_exec_time_ms=1.0,
        max_exec_time_ms=100.0,
        rows_returned=12030,
        shared_blks_hit=500,
        shared_blks_read=200,
        cache_hit_ratio=71.4,
    ),
]


def _mock_pool_and_collector(stats=None, available=True, reset_error=None):
    """Patch AsyncConnectionPool and init_query_stats for CLI testing."""
    mock_collector = MagicMock()
    mock_collector.is_available = AsyncMock(return_value=available)
    mock_collector.get_stats = AsyncMock(return_value=stats or [])
    if reset_error:
        mock_collector.reset_stats = AsyncMock(side_effect=reset_error)
    else:
        mock_collector.reset_stats = AsyncMock()

    mock_pool_cls = MagicMock()
    mock_pool = AsyncMock()
    mock_pool_cls.return_value = mock_pool

    patches = [
        patch(
            "fraiseql.cli.commands.query_stats.init_query_stats",
            return_value=mock_collector,
        ),
        patch(
            "psycopg_pool.AsyncConnectionPool",
            mock_pool_cls,
        ),
    ]
    return patches, mock_collector


class TestQueryStatsDisplay:
    """Test query-stats display mode."""

    def test_displays_table_with_data(self) -> None:
        patches, _collector = _mock_pool_and_collector(stats=SAMPLE_STATS)
        runner = CliRunner()
        with patches[0], patches[1]:
            result = runner.invoke(
                query_stats,
                ["--database-url", "postgresql://localhost/testdb"],
            )
        assert result.exit_code == 0
        assert "Query Statistics" in result.output
        assert "SELECT u.id" in result.output
        assert "4,521" in result.output
        assert "total_exec_time" in result.output

    def test_displays_cache_hit_ratio(self) -> None:
        patches, _collector = _mock_pool_and_collector(stats=SAMPLE_STATS)
        runner = CliRunner()
        with patches[0], patches[1]:
            result = runner.invoke(
                query_stats,
                ["--database-url", "postgresql://localhost/testdb"],
            )
        assert result.exit_code == 0
        assert "98.9%" in result.output
        assert "71.4%" in result.output

    def test_respects_top_n(self) -> None:
        patches, collector = _mock_pool_and_collector(stats=[SAMPLE_STATS[0]])
        runner = CliRunner()
        with patches[0], patches[1]:
            result = runner.invoke(
                query_stats,
                [
                    "--database-url", "postgresql://localhost/testdb",
                    "--top-n", "5",
                ],
            )
        assert result.exit_code == 0
        collector.get_stats.assert_called_once_with(
            top_n=5, order_by="total_exec_time"
        )

    def test_respects_order_by(self) -> None:
        patches, collector = _mock_pool_and_collector(stats=[])
        runner = CliRunner()
        with patches[0], patches[1]:
            result = runner.invoke(
                query_stats,
                [
                    "--database-url", "postgresql://localhost/testdb",
                    "--order-by", "mean_exec_time",
                ],
            )
        assert result.exit_code == 0
        collector.get_stats.assert_called_once_with(
            top_n=20, order_by="mean_exec_time"
        )

    def test_empty_results_message(self) -> None:
        patches, _collector = _mock_pool_and_collector(stats=[])
        runner = CliRunner()
        with patches[0], patches[1]:
            result = runner.invoke(
                query_stats,
                ["--database-url", "postgresql://localhost/testdb"],
            )
        assert result.exit_code == 0
        assert "No query statistics available" in result.output

    def test_masks_password_in_output(self) -> None:
        patches, _collector = _mock_pool_and_collector(stats=[])
        runner = CliRunner()
        with patches[0], patches[1]:
            result = runner.invoke(
                query_stats,
                ["--database-url", "postgresql://user:secret@localhost/db"],
            )
        assert result.exit_code == 0
        assert "secret" not in result.output
        assert "***" in result.output


class TestQueryStatsUnavailable:
    """Test graceful handling when extension is unavailable."""

    def test_prints_warning_when_unavailable(self) -> None:
        patches, _collector = _mock_pool_and_collector(available=False)
        runner = CliRunner()
        with patches[0], patches[1]:
            result = runner.invoke(
                query_stats,
                ["--database-url", "postgresql://localhost/testdb"],
            )
        assert result.exit_code == 1
        assert "pg_stat_statements" in result.output


class TestQueryStatsReset:
    """Test --reset flag."""

    def test_reset_with_confirmation(self) -> None:
        patches, collector = _mock_pool_and_collector()
        runner = CliRunner()
        with patches[0], patches[1]:
            result = runner.invoke(
                query_stats,
                [
                    "--database-url", "postgresql://localhost/testdb",
                    "--reset",
                ],
                input="y\n",
            )
        assert result.exit_code == 0
        assert "reset" in result.output.lower()
        collector.reset_stats.assert_called_once()

    def test_reset_cancelled(self) -> None:
        patches, collector = _mock_pool_and_collector()
        runner = CliRunner()
        with patches[0], patches[1]:
            result = runner.invoke(
                query_stats,
                [
                    "--database-url", "postgresql://localhost/testdb",
                    "--reset",
                ],
                input="n\n",
            )
        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()
        collector.reset_stats.assert_not_called()

    def test_reset_error_handling(self) -> None:
        from fraiseql.core.exceptions import FraiseQLError

        patches, _collector = _mock_pool_and_collector(
            reset_error=FraiseQLError("insufficient privileges")
        )
        runner = CliRunner()
        with patches[0], patches[1]:
            result = runner.invoke(
                query_stats,
                [
                    "--database-url", "postgresql://localhost/testdb",
                    "--reset",
                ],
                input="y\n",
            )
        assert result.exit_code == 1
        assert "insufficient privileges" in result.output


class TestQueryStatsRequiresUrl:
    """Test that --database-url is required."""

    def test_fails_without_database_url(self) -> None:
        runner = CliRunner()
        result = runner.invoke(query_stats, [])
        assert result.exit_code != 0
        assert "database-url" in result.output.lower() or "required" in result.output.lower()
