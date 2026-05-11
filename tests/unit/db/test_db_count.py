"""Unit tests for FraiseQLRepository.count() method.

Tests the count() method implementation following TDD methodology.
This test should initially FAIL until the method is implemented.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from fraiseql.db import FraiseQLRepository


class TestFraiseQLRepositoryCount:
    """Test suite for db.count() method."""

    @pytest.fixture
    def mock_pool(self) -> None:
        """Create a mock connection pool."""
        pool = MagicMock()
        connection = MagicMock()
        cursor = MagicMock()

        # Setup async context managers
        pool.connection.return_value.__aenter__ = AsyncMock(return_value=connection)
        pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

        connection.cursor.return_value.__aenter__ = AsyncMock(return_value=cursor)
        connection.cursor.return_value.__aexit__ = AsyncMock(return_value=None)

        # Setup cursor methods
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock()

        return pool, cursor

    @pytest.mark.asyncio
    async def test_count_method_exists(self, mock_pool) -> None:
        """Test that count() method exists on FraiseQLRepository."""
        pool, _ = mock_pool
        db = FraiseQLRepository(pool)

        assert hasattr(db, "count"), "FraiseQLRepository should have count() method"
        assert callable(db.count), "count should be callable"

    @pytest.mark.asyncio
    async def test_count_returns_integer(self, mock_pool) -> None:
        """Test that count() returns an integer."""
        pool, cursor = mock_pool
        cursor.fetchone.return_value = (42,)

        db = FraiseQLRepository(pool)
        result = await db.count("v_users")

        assert isinstance(result, int), f"count() should return int, got {type(result)}"
        assert result == 42

    @pytest.mark.asyncio
    async def test_count_without_filters(self, mock_pool) -> None:
        """Test count() without any filters returns total count."""
        pool, cursor = mock_pool
        cursor.fetchone.return_value = (100,)

        db = FraiseQLRepository(pool)
        result = await db.count("v_products")

        assert result == 100
        cursor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_with_where_clause(self, mock_pool) -> None:
        """Test count() with where filter."""
        pool, cursor = mock_pool
        cursor.fetchone.return_value = (25,)

        db = FraiseQLRepository(pool)
        result = await db.count("v_users", where={"status": {"eq": "active"}})

        assert result == 25
        cursor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_with_tenant_id(self, mock_pool) -> None:
        """Test count() with tenant_id filter."""
        pool, cursor = mock_pool
        cursor.fetchone.return_value = (15,)

        db = FraiseQLRepository(pool, context={"tenant_id": "tenant-123"})
        result = await db.count("v_orders", mandatory_filters={"tenant_id": "tenant-123"})

        assert result == 15

    @pytest.mark.asyncio
    async def test_count_with_multiple_filters(self, mock_pool) -> None:
        """Test count() with multiple where conditions."""
        pool, cursor = mock_pool
        cursor.fetchone.return_value = (5,)

        db = FraiseQLRepository(pool)
        result = await db.count(
            "v_users", where={"status": {"eq": "active"}, "role": {"eq": "admin"}}
        )

        assert result == 5

    @pytest.mark.asyncio
    async def test_count_returns_zero_when_no_results(self, mock_pool) -> None:
        """Test count() returns 0 when no records match."""
        pool, cursor = mock_pool
        cursor.fetchone.return_value = (0,)

        db = FraiseQLRepository(pool)
        result = await db.count("v_users", where={"id": {"eq": "nonexistent"}})

        assert result == 0

    @pytest.mark.asyncio
    async def test_count_returns_zero_when_fetchone_is_none(self, mock_pool) -> None:
        """Test count() returns 0 when cursor.fetchone() returns None."""
        pool, cursor = mock_pool
        cursor.fetchone.return_value = None

        db = FraiseQLRepository(pool)
        result = await db.count("v_empty_view")

        assert result == 0

    @pytest.mark.asyncio
    async def test_count_uses_correct_sql_query(self, mock_pool) -> None:
        """Test that count() generates correct SQL COUNT(*) query."""
        pool, cursor = mock_pool
        cursor.fetchone.return_value = (50,)

        db = FraiseQLRepository(pool)
        await db.count("v_products")

        # Verify SQL contains COUNT(*)
        call_args = cursor.execute.call_args
        assert call_args is not None, "execute should be called"

        # The SQL should be a Composed object or string containing COUNT(*)
        sql_arg = str(call_args[0][0])
        assert "COUNT(*)" in sql_arg.upper(), f"SQL should contain COUNT(*), got: {sql_arg}"

    @pytest.mark.asyncio
    async def test_count_signature_matches_find_api(self, mock_pool) -> None:
        """Test that count() has similar signature to find() for consistency."""
        pool, cursor = mock_pool
        cursor.fetchone.return_value = (10,)

        db = FraiseQLRepository(pool)

        # Should accept same kwargs as find()
        result = await db.count(
            "v_users",
            where={"status": {"eq": "active"}},
            mandatory_filters={"tenant_id": "tenant-123"},
        )

        assert result == 10

    @pytest.mark.asyncio
    async def test_count_with_complex_where_conditions(self, mock_pool) -> None:
        """Test count() with complex GraphQL-style where conditions."""
        pool, cursor = mock_pool
        cursor.fetchone.return_value = (3,)

        db = FraiseQLRepository(pool)
        result = await db.count(
            "v_products", where={"price": {"gt": 100, "lt": 500}, "category": {"eq": "electronics"}}
        )

        assert result == 3

    @pytest.mark.asyncio
    async def test_count_executes_query_in_connection_context(self, mock_pool) -> None:
        """Test that count() properly uses connection and cursor contexts."""
        pool, cursor = mock_pool
        cursor.fetchone.return_value = (7,)

        db = FraiseQLRepository(pool)
        await db.count("v_orders")

        # Verify connection was acquired
        pool.connection.assert_called_once()

        # Verify cursor was created
        connection = await pool.connection.return_value.__aenter__()
        connection.cursor.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_with_view_name_only(self, mock_pool) -> None:
        """Test count() with only view_name parameter (simplest case)."""
        pool, cursor = mock_pool
        cursor.fetchone.return_value = (200,)

        db = FraiseQLRepository(pool)
        result = await db.count("v_all_records")

        assert result == 200
        assert isinstance(result, int)
