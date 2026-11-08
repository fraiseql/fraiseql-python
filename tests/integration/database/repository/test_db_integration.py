"""Integration tests for FraiseQLRepository with real PostgreSQL.

🚀 Uses FraiseQL's UNIFIED CONTAINER system - see database_conftest.py
Each test runs in its own committed schema that is cleaned up automatically.
"""

import asyncio

import pytest
import pytest_asyncio
from psycopg.sql import SQL, Composed, Identifier

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403
from tests.unit.utils.schema_utils import (
    SchemaQualifiedQueryBuilder,
    build_select_query,
)

from fraiseql.db import DatabaseQuery, FraiseQLRepository

pytestmark = [pytest.mark.integration, pytest.mark.database]


@pytest.mark.database
class TestFraiseQLRepositoryIntegration:
    """Integration test suite for FraiseQLRepository with real database."""

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def test_data(self, class_db_pool, test_schema) -> str:
        """Create test tables and data with committed changes."""
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")

            # Create users table
            await conn.execute(
                """
                CREATE TABLE users (
                    id SERIAL PRIMARY KEY,
                    data JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Insert test data
            await conn.execute(
                """
                INSERT INTO users (data) VALUES
                ('{"name": "John Doe", "email": "john@example.com", "active": true}'::jsonb),
                ('{"name": "Jane Smith", "email": "jane@example.com", "active": true}'::jsonb),
                ('{"name": "Bob Wilson", "email": "bob@example.com", "active": false}'::jsonb)
            """
            )

            # Create posts table
            await conn.execute(
                """
                CREATE TABLE posts (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    data JSONB NOT NULL DEFAULT '{}'::jsonb,
                    published_at TIMESTAMP
                )
            """
            )

            await conn.execute(
                """
                INSERT INTO posts (user_id, data, published_at) VALUES
                (1, '{"title": "First Post", "content": "Hello World"}'::jsonb, '2024-01-01'),
                (1, '{"title": "Second Post", "content": "More content"}'::jsonb, '2024-01-02'),
                (2, '{"title": "Jane''s Post", "content": "Jane''s thoughts"}'::jsonb, NULL)
            """
            )

            # Commit the changes so they're visible to other connections
            await conn.commit()

        # Return the schema name for use in queries
        return test_schema

    @pytest.mark.asyncio
    async def test_run_simple_query(self, class_db_pool, test_schema, test_data) -> None:
        """Test running a simple SQL query."""
        schema = test_data  # test_data fixture now returns the schema name
        repository = FraiseQLRepository(pool=class_db_pool)

        # Example using the new query builder utility
        statement = (
            SchemaQualifiedQueryBuilder(schema)
            .select("id", "data->>'name' as name")
            .from_table("users")
            .order_by("id")
            .build()
        )

        query = DatabaseQuery(statement=statement, params={}, fetch_result=True)
        result = await repository.run(query)

        # Assertions
        assert len(result) == 3
        assert result[0]["name"] == "John Doe"
        assert result[1]["name"] == "Jane Smith"
        assert result[2]["name"] == "Bob Wilson"

    @pytest.mark.asyncio
    async def test_run_query_with_params(self, class_db_pool, test_schema, test_data) -> None:
        """Test running a query with parameters."""
        schema = test_data  # test_data fixture now returns the schema name
        repository = FraiseQLRepository(pool=class_db_pool)
        query = DatabaseQuery(
            statement=SQL(
                """SELECT id, data->>'email' as email FROM {}.users """
                """WHERE data->>'email' = %(email)s"""
            ).format(Identifier(schema)),
            params={"email": "jane@example.com"},
            fetch_result=True,
        )
        result = await repository.run(query)

        # Assertions
        assert len(result) == 1
        assert result[0]["email"] == "jane@example.com"

    @pytest.mark.asyncio
    async def test_run_composed_query(self, class_db_pool, test_schema, test_data) -> None:
        """Test running a Composed SQL query."""
        schema = test_data  # test_data fixture now returns the schema name
        repository = FraiseQLRepository(pool=class_db_pool)
        query = DatabaseQuery(
            statement=Composed(
                [
                    SQL("SELECT id, data FROM "),
                    Identifier(schema, "users"),
                    SQL(" WHERE (data->>'active')::boolean = %(active)s"),
                ]
            ),
            params={"active": True},
            fetch_result=True,
        )
        result = await repository.run(query)

        # Assertions
        assert len(result) == 2
        active_names = [r["data"]["name"] for r in result]
        assert "John Doe" in active_names
        assert "Jane Smith" in active_names

    @pytest.mark.asyncio
    async def test_run_insert_returning(self, class_db_pool, test_schema, test_data) -> None:
        """Test running an INSERT with RETURNING clause."""
        schema = test_data  # test_data fixture now returns the schema name
        repository = FraiseQLRepository(pool=class_db_pool)
        query = DatabaseQuery(
            statement=SQL(
                """INSERT INTO {}.users (data) VALUES (%(data)s::jsonb) RETURNING id, data"""
            ).format(Identifier(schema)),
            params={"data": '{"name": "New User", "email": "new@example.com", "active": true}'},
            fetch_result=True,
        )
        result = await repository.run(query)

        # Assertions
        assert len(result) == 1
        assert result[0]["data"]["name"] == "New User"
        assert isinstance(result[0]["id"], int)

    @pytest.mark.asyncio
    async def test_run_update_query(self, class_db_pool, test_schema, test_data) -> None:
        """Test running an UPDATE query."""
        schema = test_data  # test_data fixture now returns the schema name
        repository = FraiseQLRepository(pool=class_db_pool)

        # Update Bob's status to active
        update_query = DatabaseQuery(
            statement=Composed(
                [
                    SQL("UPDATE "),
                    Identifier(schema, "users"),
                    SQL(" SET data = jsonb_set(data, '{active}', 'true') "),
                    SQL("WHERE data->>'name' = %(name)s"),
                ]
            ),
            params={"name": "Bob Wilson"},
            fetch_result=False,
        )
        await repository.run(update_query)

        # Verify the update
        verify_query = DatabaseQuery(
            statement=SQL("SELECT data FROM {}.users WHERE data->>'name' = %(name)s").format(
                Identifier(schema)
            ),
            params={"name": "Bob Wilson"},
            fetch_result=True,
        )
        result = await repository.run(verify_query)

        # Assertions
        assert len(result) == 1
        assert result[0]["data"]["active"] is True

    @pytest.mark.asyncio
    async def test_run_delete_query(self, class_db_pool, test_schema, test_data) -> None:
        """Test running a DELETE query."""
        schema = test_data  # test_data fixture now returns the schema name
        repository = FraiseQLRepository(pool=class_db_pool)

        # Count total and inactive users before deletion
        total_before_query = DatabaseQuery(
            statement=SQL("SELECT COUNT(*) as count FROM {}.users").format(Identifier(schema)),
            params={},
            fetch_result=True,
        )
        total_before = await repository.run(total_before_query)
        total_count_before = int(total_before[0]["count"])

        count_inactive_query = DatabaseQuery(
            statement=SQL(
                "SELECT COUNT(*) as count FROM {}.users WHERE NOT (data->>'active')::boolean"
            ).format(Identifier(schema)),
            params={},
            fetch_result=True,
        )
        inactive_before = await repository.run(count_inactive_query)
        inactive_count_before = int(inactive_before[0]["count"])

        # Delete inactive users
        delete_query = DatabaseQuery(
            statement=SQL("DELETE FROM {}.users WHERE NOT (data->>'active')::boolean").format(
                Identifier(schema)
            ),
            params={},
            fetch_result=False,
        )
        await repository.run(delete_query)

        # Verify no inactive users remain
        inactive_after = await repository.run(count_inactive_query)
        inactive_count_after = int(inactive_after[0]["count"])

        # Verify total users decreased by the number of inactive users
        total_after = await repository.run(total_before_query)
        total_count_after = int(total_after[0]["count"])

        # Assertions
        assert inactive_count_after == 0  # No inactive users should remain
        # Total should be the initial total minus the inactive users that were deleted
        expected_total = total_count_before - inactive_count_before
        assert total_count_after == expected_total

    @pytest.mark.asyncio
    async def test_run_join_query(self, class_db_pool, test_schema, test_data) -> None:
        """Test running a JOIN query."""
        schema = test_data  # test_data fixture now returns the schema name
        repository = FraiseQLRepository(pool=class_db_pool)
        query = DatabaseQuery(
            statement=SQL(
                """
                SELECT
                    u.data->>'name' as user_name,
                    p.data->>'title' as post_title,
                    p.published_at
                FROM {0}.users u
                JOIN {0}.posts p ON u.id = p.user_id
                WHERE p.published_at IS NOT NULL
                ORDER BY p.published_at
            """
            ).format(Identifier(schema)),
            params={},
            fetch_result=True,
        )
        result = await repository.run(query)

        # Assertions
        assert len(result) == 2
        assert result[0]["user_name"] == "John Doe"
        assert result[0]["post_title"] == "First Post"
        assert result[1]["post_title"] == "Second Post"

    @pytest.mark.asyncio
    async def test_transaction_behavior(self, class_db_pool, test_schema) -> None:
        """Test transaction behavior with the unified container system."""
        # Create table and insert data, then release connection
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")

            # Create minimal test table within our transaction
            await conn.execute(
                """
                CREATE TABLE test_tx (
                    id SERIAL PRIMARY KEY,
                    value TEXT
                )
            """
            )

            # Insert data that will be visible within this test
            await conn.execute("INSERT INTO test_tx (value) VALUES ('test_value')")

            # Commit so it's visible to the pool connections
            await conn.commit()

        # Now use repository with fresh connection (avoids pool exhaustion)
        repository = FraiseQLRepository(pool=class_db_pool)
        query = DatabaseQuery(
            statement=SQL("SELECT * FROM {}.test_tx").format(Identifier(test_schema)),
            params={},
            fetch_result=True,
        )
        result = await repository.run(query)

        assert len(result) == 1
        assert result[0]["value"] == "test_value"

        # After this test, the schema will be dropped automatically
        # and the table will not exist for other tests

    @pytest.mark.asyncio
    async def test_jsonb_operators(self, class_db_pool, test_schema, test_data) -> None:
        """Test JSONB operators in queries."""
        schema = test_data  # test_data fixture now returns the schema name
        repository = FraiseQLRepository(pool=class_db_pool)

        # Test @> operator (contains)
        contains_query = DatabaseQuery(
            statement=SQL("SELECT * FROM {}.users WHERE data @> %(filter)s::jsonb").format(
                Identifier(schema)
            ),
            params={"filter": '{"active": true}'},
            fetch_result=True,
        )
        active_users = await repository.run(contains_query)

        # Test ? operator (key exists)
        has_email_query = DatabaseQuery(
            statement=SQL("SELECT * FROM {}.users WHERE data ? 'email'").format(Identifier(schema)),
            params={},
            fetch_result=True,
        )
        users_with_email = await repository.run(has_email_query)

        # Dynamic assertions - count expected results
        active_count_query = DatabaseQuery(
            statement=SQL(
                "SELECT COUNT(*) as count FROM {}.users WHERE (data->>'active')::boolean = true"
            ).format(Identifier(schema)),
            params={},
            fetch_result=True,
        )
        active_count_result = await repository.run(active_count_query)
        expected_active = int(active_count_result[0]["count"])

        email_count_query = DatabaseQuery(
            statement=SQL("SELECT COUNT(*) as count FROM {}.users WHERE data ? 'email'").format(
                Identifier(schema)
            ),
            params={},
            fetch_result=True,
        )
        email_count_result = await repository.run(email_count_query)
        expected_email = int(email_count_result[0]["count"])

        # Assertions
        assert len(active_users) == expected_active
        assert len(users_with_email) == expected_email

    @pytest.mark.asyncio
    async def test_aggregate_query(self, class_db_pool, test_schema, test_data) -> None:
        """Test aggregate functions with JSONB."""
        schema = test_data  # test_data fixture now returns the schema name
        repository = FraiseQLRepository(pool=class_db_pool)

        # Query actual counts from database for dynamic assertions
        active_count_query = DatabaseQuery(
            statement=SQL(
                "SELECT COUNT(*) as count FROM {}.users WHERE (data->>'active')::boolean = true"
            ).format(Identifier(schema)),
            params={},
            fetch_result=True,
        )
        active_count_result = await repository.run(active_count_query)
        expected_active_count = int(active_count_result[0]["count"])  # type: ignore

        inactive_count_query = DatabaseQuery(
            statement=SQL(
                "SELECT COUNT(*) as count FROM {}.users WHERE (data->>'active')::boolean = false"
            ).format(Identifier(schema)),
            params={},
            fetch_result=True,
        )
        inactive_count_result = await repository.run(inactive_count_query)
        expected_inactive_count = int(inactive_count_result[0]["count"])  # type: ignore

        # Get all user names grouped by active status for verification
        names_query = DatabaseQuery(
            statement=SQL(
                "SELECT (data->>'active')::boolean as active, jsonb_agg(data->>'name') as names "
                "FROM {}.users GROUP BY (data->>'active')::boolean"
            ).format(Identifier(schema)),
            params={},
            fetch_result=True,
        )
        names_result = await repository.run(names_query)

        # Example using build_select_query utility for complex queries with GROUP BY
        statement = build_select_query(
            schema=schema,
            table="users",
            columns=[
                """(data->>'active')::boolean as active""",
                """COUNT(*) as count""",
                """jsonb_agg(data->>'name') as names""",
            ],
            group_by=["(data->>'active')::boolean"],
        )

        query = DatabaseQuery(statement=statement, params={}, fetch_result=True)
        result = await repository.run(query)

        # Dynamic assertions based on actual database state
        expected_groups = (1 if expected_active_count > 0 else 0) + (
            1 if expected_inactive_count > 0 else 0
        )
        assert len(result) == expected_groups

        # Verify each group that should exist
        if expected_active_count > 0:
            active_group = next(r for r in result if r["active"] is True)  # type: ignore
            assert active_group["count"] == expected_active_count  # type: ignore
            # Verify names match database
            expected_active_names = next(r for r in names_result if r["active"] is True)["names"]  # type: ignore
            assert set(active_group["names"]) == set(expected_active_names)  # type: ignore

        if expected_inactive_count > 0:
            inactive_group = next(r for r in result if r["active"] is False)  # type: ignore
            assert inactive_group["count"] == expected_inactive_count  # type: ignore
            # Verify names match database
            expected_inactive_names = next(r for r in names_result if r["active"] is False)["names"]  # type: ignore
            assert set(inactive_group["names"]) == set(expected_inactive_names)  # type: ignore

    @pytest.mark.asyncio
    async def test_connection_pool_concurrency(self, class_db_pool, test_schema, test_data) -> None:
        """Test concurrent queries using the connection pool."""
        schema = test_data  # test_data fixture now returns the schema name
        repository = FraiseQLRepository(pool=class_db_pool)

        async def run_query(email: str) -> None:
            query = DatabaseQuery(
                statement=SQL("SELECT * FROM {}.users WHERE data->>'email' = %(email)s").format(
                    Identifier(schema)
                ),
                params={"email": email},
                fetch_result=True,
            )
            return await repository.run(query)

        # Run multiple queries concurrently
        results = await asyncio.gather(
            run_query("john@example.com"),
            run_query("jane@example.com"),
            run_query("bob@example.com"),
            run_query("nonexistent@example.com"),
        )

        # Assertions
        assert len(results[0]) == 1  # John
        assert len(results[1]) == 1  # Jane
        assert len(results[2]) == 1  # Bob
        assert len(results[3]) == 0  # Nonexistent

    @pytest.mark.asyncio
    async def test_error_handling(self, class_db_pool, test_schema) -> None:
        """Test error handling in repository."""
        repository = FraiseQLRepository(pool=class_db_pool)

        # Test with invalid SQL
        invalid_query = DatabaseQuery(
            statement=SQL("SELECT * FROM nonexistent_table"), params={}, fetch_result=True
        )

        with pytest.raises(Exception) as exc_info:
            await repository.run(invalid_query)

        # Should be a database error
        assert "nonexistent_table" in str(exc_info.value)
