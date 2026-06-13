from unittest.mock import AsyncMock, MagicMock

import pytest

from fraiseql.db import FraiseQLRepository


class TestExists:
    """Test suite for exists() method."""

    def test_exists_method_exists(self) -> None:
        """Test that exists() method exists on FraiseQLRepository."""
        db = FraiseQLRepository(pool=MagicMock())
        assert hasattr(db, "exists")
        assert callable(db.exists)

    @pytest.mark.asyncio
    async def test_exists_returns_bool(self) -> None:
        """Test that exists() returns a boolean."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        # Mock database connection
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(True,))
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.exists("v_users")
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_exists_true_when_records_exist(self) -> None:
        """Test exists() returns True when records exist."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(True,))
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.exists("v_users")
        assert result is True

    @pytest.mark.asyncio
    async def test_exists_false_when_no_records(self) -> None:
        """Test exists() returns False when no records exist."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(False,))
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.exists("v_users")
        assert result is False

    @pytest.mark.asyncio
    async def test_exists_with_where_clause(self) -> None:
        """Test exists() with WHERE filter."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(True,))
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.exists("v_users", where={"email": {"eq": "test@example.com"}})

        # Verify WHERE clause was included in SQL
        assert mock_cursor.execute.called
        sql_query = str(mock_cursor.execute.call_args[0][0])
        assert "WHERE" in sql_query
        assert result is True

    @pytest.mark.asyncio
    async def test_exists_with_tenant_id(self) -> None:
        """Test exists() with tenant_id filter."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(True,))
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        import uuid

        tenant_id = uuid.uuid4()
        result = await db.exists("v_users", mandatory_filters={"tenant_id": tenant_id})

        # Verify tenant_id was included in SQL
        assert mock_cursor.execute.called
        sql_query = str(mock_cursor.execute.call_args[0][0])
        assert "tenant_id" in sql_query
        assert result is True

    @pytest.mark.asyncio
    async def test_exists_calls_execute(self) -> None:
        """Test exists() calls execute with a query."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(True,))
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        await db.exists("v_users")

        # Verify execute was called with a query
        assert mock_cursor.execute.called

    @pytest.mark.asyncio
    async def test_exists_with_multiple_filters(self) -> None:
        """Test exists() with multiple WHERE filters."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(False,))
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.exists(
            "v_users", where={"email": {"eq": "test@example.com"}, "status": {"eq": "active"}}
        )

        assert mock_cursor.execute.called
        sql_query = str(mock_cursor.execute.call_args[0][0])
        assert "WHERE" in sql_query
        assert result is False


class TestSum:
    """Test suite for sum() method."""

    def test_sum_method_exists(self) -> None:
        """Test that sum() method exists on FraiseQLRepository."""
        db = FraiseQLRepository(pool=MagicMock())
        assert hasattr(db, "sum")
        assert callable(db.sum)

    @pytest.mark.asyncio
    async def test_sum_returns_float(self) -> None:
        """Test that sum() returns a float."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(125.50,))
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.sum("v_orders", "amount")
        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_sum_with_values(self) -> None:
        """Test sum() returns correct sum."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(250.75,))
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.sum("v_orders", "amount")
        assert result == 250.75

    @pytest.mark.asyncio
    async def test_sum_returns_zero_when_no_records(self) -> None:
        """Test sum() returns 0.0 when no records."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(None,))
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.sum("v_orders", "amount")
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_sum_with_where_clause(self) -> None:
        """Test sum() with WHERE filter."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(500.0,))
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.sum("v_orders", "amount", where={"status": {"eq": "completed"}})

        assert mock_cursor.execute.called
        sql_query = str(mock_cursor.execute.call_args[0][0])
        assert "WHERE" in sql_query
        assert result == 500.0

    @pytest.mark.asyncio
    async def test_sum_with_tenant_id(self) -> None:
        """Test sum() with tenant_id filter."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(750.0,))
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        import uuid

        tenant_id = uuid.uuid4()
        result = await db.sum("v_orders", "amount", mandatory_filters={"tenant_id": tenant_id})

        assert mock_cursor.execute.called
        sql_query = str(mock_cursor.execute.call_args[0][0])
        assert "tenant_id" in sql_query
        assert result == 750.0

    @pytest.mark.asyncio
    async def test_sum_calls_execute(self) -> None:
        """Test sum() calls execute with a query."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(100.0,))
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        await db.sum("v_orders", "amount")

        # Verify execute was called with a query
        assert mock_cursor.execute.called

    @pytest.mark.asyncio
    async def test_sum_requires_field_parameter(self) -> None:
        """Test sum() requires field parameter."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        # Should raise TypeError if field is missing
        with pytest.raises(TypeError):
            await db.sum("v_orders")  # Missing field parameter


class TestAvg:
    """Test suite for avg() method."""

    def test_avg_method_exists(self) -> None:
        """Test that avg() method exists."""
        db = FraiseQLRepository(pool=MagicMock())
        assert hasattr(db, "avg")
        assert callable(db.avg)

    @pytest.mark.asyncio
    async def test_avg_returns_float(self) -> None:
        """Test that avg() returns a float."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(125.50,))
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.avg("v_orders", "amount")
        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_avg_returns_zero_when_no_records(self) -> None:
        """Test avg() returns 0.0 when no records."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(None,))
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.avg("v_orders", "amount")
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_avg_calls_execute(self) -> None:
        """Test avg() calls execute with a query."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(100.0,))
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        await db.avg("v_orders", "amount")

        # Verify execute was called with a query
        assert mock_cursor.execute.called


class TestMin:
    """Test suite for min() method."""

    def test_min_method_exists(self) -> None:
        """Test that min() method exists."""
        db = FraiseQLRepository(pool=MagicMock())
        assert hasattr(db, "min")
        assert callable(db.min)

    @pytest.mark.asyncio
    async def test_min_returns_value(self) -> None:
        """Test that min() returns the minimum value."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(9.99,))
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.min("v_products", "price")
        assert result == 9.99

    @pytest.mark.asyncio
    async def test_min_returns_none_when_no_records(self) -> None:
        """Test min() returns None when no records."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(None,))
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.min("v_products", "price")
        assert result is None

    @pytest.mark.asyncio
    async def test_min_calls_execute(self) -> None:
        """Test min() calls execute with a query."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(9.99,))
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        await db.min("v_products", "price")

        # Verify execute was called with a query
        assert mock_cursor.execute.called


class TestMax:
    """Test suite for max() method."""

    def test_max_method_exists(self) -> None:
        """Test that max() method exists."""
        db = FraiseQLRepository(pool=MagicMock())
        assert hasattr(db, "max")
        assert callable(db.max)

    @pytest.mark.asyncio
    async def test_max_returns_value(self) -> None:
        """Test that max() returns the maximum value."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(999.99,))
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.max("v_products", "price")
        assert result == 999.99

    @pytest.mark.asyncio
    async def test_max_returns_none_when_no_records(self) -> None:
        """Test max() returns None when no records."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(None,))
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.max("v_products", "price")
        assert result is None

    @pytest.mark.asyncio
    async def test_max_calls_execute(self) -> None:
        """Test max() calls execute with a query."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(999.99,))
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        await db.max("v_products", "price")

        # Verify execute was called with a query
        assert mock_cursor.execute.called


class TestDistinct:
    """Test suite for distinct() method."""

    def test_distinct_method_exists(self) -> None:
        """Test that distinct() method exists."""
        db = FraiseQLRepository(pool=MagicMock())
        assert hasattr(db, "distinct")
        assert callable(db.distinct)

    @pytest.mark.asyncio
    async def test_distinct_returns_list(self) -> None:
        """Test that distinct() returns a list."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("books",), ("electronics",), ("clothing",)])
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.distinct("v_products", "category")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_distinct_returns_unique_values(self) -> None:
        """Test distinct() returns unique values."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("books",), ("electronics",), ("clothing",)])
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.distinct("v_products", "category")
        assert result == ["books", "electronics", "clothing"]

    @pytest.mark.asyncio
    async def test_distinct_returns_empty_list_when_no_records(self) -> None:
        """Test distinct() returns empty list when no records."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.distinct("v_products", "category")
        assert result == []

    @pytest.mark.asyncio
    async def test_distinct_with_where_clause(self) -> None:
        """Test distinct() with WHERE filter."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("active",), ("pending",)])
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.distinct(
            "v_orders", "status", where={"created_at": {"gte": "2024-01-01"}}
        )

        assert mock_cursor.execute.called
        sql_query = str(mock_cursor.execute.call_args[0][0])
        assert "WHERE" in sql_query
        assert result == ["active", "pending"]

    @pytest.mark.asyncio
    async def test_distinct_calls_execute(self) -> None:
        """Test distinct() calls execute with a query."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("books",)])
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        await db.distinct("v_products", "category")

        # Verify execute was called with a query
        assert mock_cursor.execute.called

    @pytest.mark.asyncio
    async def test_distinct_with_tenant_id(self) -> None:
        """Test distinct() with tenant_id filter."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("US",), ("FR",)])
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        import uuid

        tenant_id = uuid.uuid4()
        result = await db.distinct("v_users", "country", mandatory_filters={"tenant_id": tenant_id})

        assert mock_cursor.execute.called
        sql_query = str(mock_cursor.execute.call_args[0][0])
        assert "tenant_id" in sql_query
        assert result == ["US", "FR"]


class TestPluck:
    """Test suite for pluck() method."""

    def test_pluck_method_exists(self) -> None:
        """Test that pluck() method exists."""
        db = FraiseQLRepository(pool=MagicMock())
        assert hasattr(db, "pluck")
        assert callable(db.pluck)

    @pytest.mark.asyncio
    async def test_pluck_returns_list(self) -> None:
        """Test that pluck() returns a list."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        import uuid

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(
            return_value=[
                (uuid.uuid4(),),
                (uuid.uuid4(),),
                (uuid.uuid4(),),
            ]
        )
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.pluck("v_users", "id")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_pluck_returns_field_values(self) -> None:
        """Test pluck() returns field values."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(
            return_value=[
                ("user1@example.com",),
                ("user2@example.com",),
                ("user3@example.com",),
            ]
        )
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.pluck("v_users", "email")
        assert result == ["user1@example.com", "user2@example.com", "user3@example.com"]

    @pytest.mark.asyncio
    async def test_pluck_returns_empty_list_when_no_records(self) -> None:
        """Test pluck() returns empty list when no records."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.pluck("v_users", "email")
        assert result == []

    @pytest.mark.asyncio
    async def test_pluck_with_where_clause(self) -> None:
        """Test pluck() with WHERE filter."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("active@example.com",)])
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.pluck("v_users", "email", where={"status": {"eq": "active"}})

        assert mock_cursor.execute.called
        sql_query = str(mock_cursor.execute.call_args[0][0])
        assert "WHERE" in sql_query
        assert result == ["active@example.com"]

    @pytest.mark.asyncio
    async def test_pluck_calls_execute(self) -> None:
        """Test pluck() calls execute with a query."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("test@example.com",)])
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        await db.pluck("v_users", "email")

        # Verify execute was called with a query
        assert mock_cursor.execute.called

    @pytest.mark.asyncio
    async def test_pluck_with_limit(self) -> None:
        """Test pluck() with limit parameter."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(
            return_value=[("email1@example.com",), ("email2@example.com",)]
        )
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.pluck("v_users", "email", limit=2)

        assert mock_cursor.execute.called
        sql_query = str(mock_cursor.execute.call_args[0][0])
        assert "LIMIT" in sql_query
        assert len(result) <= 2


class TestAggregate:
    """Test suite for aggregate() method."""

    def test_aggregate_method_exists(self) -> None:
        """Test that aggregate() method exists."""
        db = FraiseQLRepository(pool=MagicMock())
        assert hasattr(db, "aggregate")
        assert callable(db.aggregate)

    @pytest.mark.asyncio
    async def test_aggregate_returns_dict(self) -> None:
        """Test that aggregate() returns a dict."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(1000.0, 250.0, 4))
        mock_cursor.description = [
            ("total", None),
            ("avg", None),
            ("count", None),
        ]
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.aggregate(
            "v_orders",
            aggregations={"total": "SUM(amount)", "avg": "AVG(amount)", "count": "COUNT(*)"},
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_aggregate_multiple_aggregations(self) -> None:
        """Test aggregate() with multiple aggregations."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(1000.0, 250.0, 500.0, 10.0, 4))
        mock_cursor.description = [
            ("total_revenue", None),
            ("avg_order", None),
            ("max_order", None),
            ("min_order", None),
            ("order_count", None),
        ]
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.aggregate(
            "v_orders",
            aggregations={
                "total_revenue": "SUM(amount)",
                "avg_order": "AVG(amount)",
                "max_order": "MAX(amount)",
                "min_order": "MIN(amount)",
                "order_count": "COUNT(*)",
            },
        )

        assert result == {
            "total_revenue": 1000.0,
            "avg_order": 250.0,
            "max_order": 500.0,
            "min_order": 10.0,
            "order_count": 4,
        }

    @pytest.mark.asyncio
    async def test_aggregate_with_where_clause(self) -> None:
        """Test aggregate() with WHERE filter."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(750.0, 2))
        mock_cursor.description = [("total", None), ("count", None)]
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.aggregate(
            "v_orders",
            aggregations={"total": "SUM(amount)", "count": "COUNT(*)"},
            where={"status": {"eq": "completed"}},
        )

        assert mock_cursor.execute.called
        sql_query = str(mock_cursor.execute.call_args[0][0])
        assert "WHERE" in sql_query
        assert result == {"total": 750.0, "count": 2}

    @pytest.mark.asyncio
    async def test_aggregate_calls_execute(self) -> None:
        """Test aggregate() calls execute with a query."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(1000.0, 250.0))
        mock_cursor.description = [("total", None), ("avg", None)]
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        await db.aggregate("v_orders", aggregations={"total": "SUM(amount)", "avg": "AVG(amount)"})

        # Verify execute was called with a query
        assert mock_cursor.execute.called

    @pytest.mark.asyncio
    async def test_aggregate_returns_empty_dict_when_no_aggregations(self) -> None:
        """Test aggregate() returns empty dict when no aggregations provided."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        result = await db.aggregate("v_orders", aggregations={})
        assert result == {}


class TestBatchExists:
    """Test suite for batch_exists() method."""

    def test_batch_exists_method_exists(self) -> None:
        """Test that batch_exists() method exists."""
        db = FraiseQLRepository(pool=MagicMock())
        assert hasattr(db, "batch_exists")
        assert callable(db.batch_exists)

    @pytest.mark.asyncio
    async def test_batch_exists_returns_dict(self) -> None:
        """Test that batch_exists() returns a dict."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        import uuid

        id1, id2 = uuid.uuid4(), uuid.uuid4()

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[(id1,), (id2,)])
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.batch_exists("v_users", [id1, id2])
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_batch_exists_all_exist(self) -> None:
        """Test batch_exists() when all IDs exist."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        import uuid

        id1, id2, id3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[(id1,), (id2,), (id3,)])
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.batch_exists("v_users", [id1, id2, id3])

        assert result == {id1: True, id2: True, id3: True}

    @pytest.mark.asyncio
    async def test_batch_exists_some_missing(self) -> None:
        """Test batch_exists() when some IDs are missing."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        import uuid

        id1, id2, id3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        # Only id1 and id3 exist
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[(id1,), (id3,)])
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.batch_exists("v_users", [id1, id2, id3])

        assert result == {id1: True, id2: False, id3: True}

    @pytest.mark.asyncio
    async def test_batch_exists_none_exist(self) -> None:
        """Test batch_exists() when no IDs exist."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        import uuid

        id1, id2 = uuid.uuid4(), uuid.uuid4()

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.batch_exists("v_users", [id1, id2])

        assert result == {id1: False, id2: False}

    @pytest.mark.asyncio
    async def test_batch_exists_empty_list(self) -> None:
        """Test batch_exists() with empty ID list."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        result = await db.batch_exists("v_users", [])
        assert result == {}

    @pytest.mark.asyncio
    async def test_batch_exists_calls_execute(self) -> None:
        """Test batch_exists() calls execute with a query."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        import uuid

        id1, id2 = uuid.uuid4(), uuid.uuid4()

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[(id1,)])
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        await db.batch_exists("v_users", [id1, id2])

        # Verify execute was called with a query
        assert mock_cursor.execute.called

    @pytest.mark.asyncio
    async def test_batch_exists_custom_id_field(self) -> None:
        """Test batch_exists() with custom ID field."""
        pool = MagicMock()
        db = FraiseQLRepository(pool=pool)

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("user123",)])
        mock_cursor.execute = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        pool.connection = MagicMock(return_value=mock_conn)

        result = await db.batch_exists("v_users", ["user123", "user456"], field="username")

        assert mock_cursor.execute.called
        sql_query = str(mock_cursor.execute.call_args[0][0])
        assert "username" in sql_query
        assert result == {"user123": True, "user456": False}
