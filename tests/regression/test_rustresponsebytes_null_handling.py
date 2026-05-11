"""Regression test for RustResponseBytes null handling bug.

When a query resolver returns None (no data found) and uses the Rust pipeline,
GraphQL should not throw a type error about RustResponseBytes.

This test reproduces the bug where:
1. A query resolver has return type `User | None`
2. The resolver calls `db.find_one()` on a non-existent record
3. Rust pipeline returns RustResponseBytes containing {"data":{"field":[]}}
4. GraphQL sees RustResponseBytes object instead of None
5. Type validation fails: "Expected User|None, got RustResponseBytes"

Expected behavior after fix:
- find_one() should detect null result and return Python None
- GraphQL should accept None for nullable field
- No type errors should occur

GitHub Issue: RustResponseBytes NULL Handling Bug
"""

import pytest
from graphql import graphql

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.db import FraiseQLRepository, _is_rust_response_null
from fraiseql.gql.builders.registry import SchemaRegistry
from fraiseql.gql.schema_builder import build_fraiseql_schema

pytestmark = [pytest.mark.integration, pytest.mark.database]


class TestRustResponseBytesNullHandling:
    """Test RustResponseBytes null handling in GraphQL queries."""

    @pytest.mark.asyncio
    async def test_rustresponsebytes_null_returns_none_not_error(
        self, class_db_pool, test_schema, clear_registry_class
    ) -> None:
        """Test that query returning None doesn't cause RustResponseBytes type error.

        REPRODUCES THE BUG:
        - Query resolver returns None (via db.find_one on non-existent record)
        - Rust pipeline wraps null in RustResponseBytes
        - GraphQL should handle this gracefully, not throw type error

        EXPECTED AFTER FIX:
        - find_one() detects {"data":{"field":[]}} and returns Python None
        - GraphQL accepts None for nullable field
        - Query succeeds with data: {testUserNullable: null}
        """
        # Clear registry to avoid conflicts
        registry = SchemaRegistry.get_instance()
        registry.clear()

        # Define test types within test function
        @fraiseql.type
        class TestUser:
            """Test user type for null handling regression test."""

            id: str
            name: str

        @fraiseql.query
        async def test_user_nullable(info) -> TestUser | None:
            """Query that can return None - simulates user lookup that finds nothing.

            This query intentionally searches for a non-existent record to trigger
            the null handling bug.
            """
            db = info.context["db"]

            # Query for a user that doesn't exist
            # This will return RustResponseBytes containing {"data":{"testUserNullable":[]}}
            result = await db.find_one(
                "test_users",
                mandatory_filters={"id": "00000000-0000-0000-0000-000000000000"},
            )
            return result

        # Build schema
        schema = build_fraiseql_schema()

        # Setup: Create test table
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute("DROP TABLE IF EXISTS test_users CASCADE")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_users (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL
                )
            """
            )
            # Don't insert any data - we want None result

        # Wrap pool in FraiseQLRepository
        db = FraiseQLRepository(class_db_pool)

        # Execute query
        query = """
        query {
            testUserNullable {
                id
                name
            }
        }
        """

        result = await graphql(schema=schema, source=query, context_value={"db": db})

        # BUG (before fix): This currently fails with:
        # "Expected value of type 'TestUser' but got: <RustResponseBytes instance>."
        #
        # The error occurs because:
        # 1. find_one() returns RustResponseBytes(b'{"data":{"testUserNullable":[]}}')
        # 2. Resolver returns this RustResponseBytes object
        # 3. GraphQL type system sees RustResponseBytes, not None or TestUser
        # 4. Type validation fails

        # Check for the specific RustResponseBytes error (bug signature)
        errors = result.errors or []
        rustresponse_errors = [err for err in errors if "RustResponseBytes" in str(err.message)]

        # EXPECTED AFTER FIX: No RustResponseBytes type errors
        assert not rustresponse_errors, (
            f"Should not have RustResponseBytes type error (bug detected): {rustresponse_errors}"
        )

        # EXPECTED AFTER FIX: Query succeeds with null result
        assert result.data is not None, f"Query should succeed, got errors: {errors}"
        assert result.data["testUserNullable"] is None, (
            f"Should return null for non-existent record, got: {result.data}"
        )

        # Cleanup
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute("DROP TABLE IF EXISTS test_users CASCADE")

        registry.clear()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.database
async def test_rustresponsebytes_non_null_still_works(postgres_url) -> None:
    """Test that non-null results still return RustResponseBytes (not None).

    This ensures the null detection doesn't incorrectly identify non-null
    responses as null. We verify that RustResponseBytes is returned for
    actual data (the router handles converting it to JSON).

    Note: This test uses postgres_url directly (not class-scoped fixtures)
    since it's a standalone function test, not part of a test class.
    """
    import psycopg_pool

    from fraiseql.core.rust_pipeline import RustResponseBytes
    from fraiseql.db import _table_metadata

    # Clear any existing metadata for test_users from previous tests
    # to avoid using stale jsonb_column settings
    _table_metadata.pop("test_users", None)

    # Create a temporary pool for this test
    pool = psycopg_pool.AsyncConnectionPool(
        postgres_url,
        min_size=1,
        max_size=2,
        open=False,
    )
    await pool.open()

    try:
        # Wrap pool in FraiseQLRepository
        db = FraiseQLRepository(pool)

        # Setup: Create table and insert test data
        async with pool.connection() as conn:
            await conn.execute("DROP TABLE IF EXISTS test_users CASCADE")
            await conn.execute(
                """
                CREATE TABLE test_users (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL
                )
            """
            )
            await conn.execute(
                """
                INSERT INTO test_users (id, name)
                VALUES ('550e8400-e29b-41d4-a716-446655440000', 'Alice')
            """
            )

        # Call find_one() directly (bypassing GraphQL)
        result = await db.find_one(
            "test_users",
            mandatory_filters={"id": "550e8400-e29b-41d4-a716-446655440000"},
        )

        # Should return RustResponseBytes (not None)
        assert result is not None, "Non-null query should not return None"
        assert isinstance(result, RustResponseBytes), (
            f"Should return RustResponseBytes, got: {type(result)}"
        )

        # Verify the content is not the null pattern
        assert not _is_rust_response_null(result), "Non-null data should not be detected as null"

        # Cleanup
        async with pool.connection() as conn:
            await conn.execute("DROP TABLE IF EXISTS test_users CASCADE")

    finally:
        await pool.close()
