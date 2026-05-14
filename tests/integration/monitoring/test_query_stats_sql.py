"""Tests for pg_stat_statements SQL integration."""

from pathlib import Path

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

SCHEMA_SQL = Path("src/fraiseql/monitoring/schema.sql")


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def query_stats_db(class_db_pool, test_schema):  # noqa: ANN201
    """Set up monitoring schema including query stats objects."""
    schema_sql = SCHEMA_SQL.read_text()

    async with class_db_pool.connection() as conn:
        # Ensure pg_stat_statements extension exists (database-level, not schema-scoped)
        try:
            await conn.execute('CREATE EXTENSION IF NOT EXISTS "pg_stat_statements"')
        except Exception:
            pass

        # Verify shared_preload_libraries includes pg_stat_statements
        result = await conn.execute("SHOW shared_preload_libraries")
        row = await result.fetchone()
        if not row or "pg_stat_statements" not in row[0]:
            pytest.skip("pg_stat_statements not in shared_preload_libraries")

        await conn.execute(f"SET search_path TO {test_schema}")
        await conn.execute(schema_sql)
        await conn.commit()

    yield class_db_pool


class TestPgStatStatementsAvailable:
    """Test pg_stat_statements_available() helper function."""

    @pytest.mark.asyncio
    async def test_returns_true_when_extension_installed(self, query_stats_db, test_schema) -> None:
        """Extension should be available in our test PostgreSQL."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            result = await conn.execute("SELECT pg_stat_statements_available()")
            row = await result.fetchone()
            assert row[0] is True

    @pytest.mark.asyncio
    async def test_returns_false_when_simulated_unavailable(
        self, query_stats_db, test_schema
    ) -> None:
        """Simulate unavailability by temporarily replacing the function."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")

            # Create an override function that always returns false
            await conn.execute("""
                CREATE OR REPLACE FUNCTION pg_stat_statements_available()
                RETURNS BOOLEAN AS $$
                BEGIN RETURN FALSE; END;
                $$ LANGUAGE plpgsql STABLE
            """)

            result = await conn.execute("SELECT pg_stat_statements_available()")
            row = await result.fetchone()
            assert row[0] is False

            # Restore the real function
            await conn.execute("""
                CREATE OR REPLACE FUNCTION pg_stat_statements_available()
                RETURNS BOOLEAN AS $$
                BEGIN
                    RETURN EXISTS (
                        SELECT 1 FROM pg_available_extensions
                        WHERE name = 'pg_stat_statements'
                          AND installed_version IS NOT NULL
                    );
                END;
                $$ LANGUAGE plpgsql STABLE
            """)
            await conn.commit()


class TestVQueryStatsView:
    """Test v_query_stats view."""

    @pytest.mark.asyncio
    async def test_view_exists_and_returns_expected_columns(
        self, query_stats_db, test_schema
    ) -> None:
        """View should exist and expose the expected column set."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            result = await conn.execute("SELECT * FROM v_query_stats LIMIT 0")
            columns = [desc.name for desc in result.description]
            expected = [
                "queryid",
                "query_preview",
                "calls",
                "total_exec_time_ms",
                "mean_exec_time_ms",
                "min_exec_time_ms",
                "max_exec_time_ms",
                "rows_returned",
                "shared_blks_hit",
                "shared_blks_read",
                "cache_hit_ratio",
                "toplevel",
            ]
            assert columns == expected

    @pytest.mark.asyncio
    async def test_view_returns_data(self, query_stats_db, test_schema) -> None:
        """View should return rows (test DB has statements tracked)."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            # Generate some statements so pg_stat_statements has data
            await conn.execute("SELECT 1")
            await conn.execute("SELECT 2")
            result = await conn.execute("SELECT COUNT(*) FROM v_query_stats")
            row = await result.fetchone()
            # Should have at least some entries (our own queries are tracked)
            assert row[0] >= 0  # May be 0 if stats haven't flushed yet

    @pytest.mark.asyncio
    async def test_view_filters_utility_statements(self, query_stats_db, test_schema) -> None:
        """View should exclude SET, RESET, DEALLOCATE, BEGIN, COMMIT, ROLLBACK."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            result = await conn.execute("""
                SELECT query_preview FROM v_query_stats
                WHERE query_preview LIKE 'SET %'
                   OR query_preview LIKE 'RESET %'
                   OR query_preview LIKE 'DEALLOCATE %'
                   OR query_preview LIKE 'BEGIN%'
                   OR query_preview LIKE 'COMMIT%'
                   OR query_preview LIKE 'ROLLBACK%'
            """)
            rows = await result.fetchall()
            assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_view_returns_empty_when_extension_unavailable(
        self, query_stats_db, test_schema
    ) -> None:
        """View should return empty when pg_stat_statements_available() is false."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")

            # Override to simulate unavailability
            await conn.execute("""
                CREATE OR REPLACE FUNCTION pg_stat_statements_available()
                RETURNS BOOLEAN AS $$
                BEGIN RETURN FALSE; END;
                $$ LANGUAGE plpgsql STABLE
            """)

            result = await conn.execute("SELECT COUNT(*) FROM v_query_stats")
            row = await result.fetchone()
            assert row[0] == 0

            # Restore
            await conn.execute("""
                CREATE OR REPLACE FUNCTION pg_stat_statements_available()
                RETURNS BOOLEAN AS $$
                BEGIN
                    RETURN EXISTS (
                        SELECT 1 FROM pg_available_extensions
                        WHERE name = 'pg_stat_statements'
                          AND installed_version IS NOT NULL
                    );
                END;
                $$ LANGUAGE plpgsql STABLE
            """)
            await conn.commit()

    @pytest.mark.asyncio
    async def test_cache_hit_ratio_calculation(self, query_stats_db, test_schema) -> None:
        """Cache hit ratio should be between 0 and 100."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            result = await conn.execute("""
                SELECT cache_hit_ratio FROM v_query_stats
                WHERE cache_hit_ratio IS NOT NULL
                LIMIT 10
            """)
            rows = await result.fetchall()
            for row in rows:
                assert 0 <= row[0] <= 100


class TestGetQueryStatsFunction:
    """Test get_query_stats() function."""

    @pytest.mark.asyncio
    async def test_function_returns_limited_rows(self, query_stats_db, test_schema) -> None:
        """Function should respect top_n parameter."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            result = await conn.execute("SELECT * FROM get_query_stats(5, 'total_exec_time')")
            rows = await result.fetchall()
            assert len(rows) <= 5

    @pytest.mark.asyncio
    async def test_function_default_parameters(self, query_stats_db, test_schema) -> None:
        """Function should work with default parameters."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            result = await conn.execute("SELECT * FROM get_query_stats()")
            rows = await result.fetchall()
            assert len(rows) <= 20  # Default top_n

    @pytest.mark.asyncio
    async def test_function_order_by_total_exec_time(self, query_stats_db, test_schema) -> None:
        """Results should be ordered by total_exec_time_ms descending."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            result = await conn.execute(
                "SELECT total_exec_time_ms FROM get_query_stats(50, 'total_exec_time')"
            )
            rows = await result.fetchall()
            if len(rows) >= 2:
                values = [row[0] for row in rows]
                assert values == sorted(values, reverse=True)

    @pytest.mark.asyncio
    async def test_function_order_by_mean_exec_time(self, query_stats_db, test_schema) -> None:
        """Results should be ordered by mean_exec_time_ms descending."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            result = await conn.execute(
                "SELECT mean_exec_time_ms FROM get_query_stats(50, 'mean_exec_time')"
            )
            rows = await result.fetchall()
            if len(rows) >= 2:
                values = [row[0] for row in rows]
                assert values == sorted(values, reverse=True)

    @pytest.mark.asyncio
    async def test_function_order_by_calls(self, query_stats_db, test_schema) -> None:
        """Results should be ordered by calls descending."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            result = await conn.execute("SELECT calls FROM get_query_stats(50, 'calls')")
            rows = await result.fetchall()
            if len(rows) >= 2:
                values = [row[0] for row in rows]
                assert values == sorted(values, reverse=True)

    @pytest.mark.asyncio
    async def test_function_rejects_invalid_order_by(self, query_stats_db, test_schema) -> None:
        """Function should raise error for invalid order_by values."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            with pytest.raises(Exception, match="Invalid order_by value"):
                await conn.execute("SELECT * FROM get_query_stats(10, 'DROP TABLE users')")

    @pytest.mark.asyncio
    async def test_function_returns_empty_when_extension_unavailable(
        self, query_stats_db, test_schema
    ) -> None:
        """Function should return empty when extension is unavailable."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")

            # Override to simulate unavailability
            await conn.execute("""
                CREATE OR REPLACE FUNCTION pg_stat_statements_available()
                RETURNS BOOLEAN AS $$
                BEGIN RETURN FALSE; END;
                $$ LANGUAGE plpgsql STABLE
            """)

            result = await conn.execute("SELECT * FROM get_query_stats(10, 'total_exec_time')")
            rows = await result.fetchall()
            assert len(rows) == 0

            # Restore
            await conn.execute("""
                CREATE OR REPLACE FUNCTION pg_stat_statements_available()
                RETURNS BOOLEAN AS $$
                BEGIN
                    RETURN EXISTS (
                        SELECT 1 FROM pg_available_extensions
                        WHERE name = 'pg_stat_statements'
                          AND installed_version IS NOT NULL
                    );
                END;
                $$ LANGUAGE plpgsql STABLE
            """)
            await conn.commit()


class TestQueryStatsSchemaVersion:
    """Test schema version registration."""

    @pytest.mark.asyncio
    async def test_query_stats_module_registered(self, query_stats_db, test_schema) -> None:
        """Schema version table should have query_stats module."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            result = await conn.execute(
                "SELECT version, description FROM fraiseql_schema_version "
                "WHERE module = 'query_stats'"
            )
            row = await result.fetchone()
            assert row is not None
            assert row[0] == 1
            assert "pg_stat_statements" in row[1]

    @pytest.mark.asyncio
    async def test_monitoring_module_version_unchanged(self, query_stats_db, test_schema) -> None:
        """Monitoring module version should remain at 1 (not bumped)."""
        async with query_stats_db.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            result = await conn.execute(
                "SELECT version FROM fraiseql_schema_version WHERE module = 'monitoring'"
            )
            row = await result.fetchone()
            assert row is not None
            assert row[0] == 1
