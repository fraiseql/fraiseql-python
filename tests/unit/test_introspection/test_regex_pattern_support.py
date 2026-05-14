"""Tests for regex pattern support in PostgresIntrospector (Issue #149)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from fraiseql.introspection.postgres_introspector import PostgresIntrospector


class TestRegexPatternValidation:
    """Test regex pattern validation when use_regex=True."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)
        return pool

    @pytest.fixture
    def introspector(self, mock_pool):
        """Create PostgresIntrospector instance."""
        return PostgresIntrospector(mock_pool)

    @pytest.mark.asyncio
    async def test_discover_views_invalid_regex_raises_valueerror(self, introspector):
        """Invalid regex pattern should raise ValueError with descriptive message."""
        with pytest.raises(ValueError, match="Invalid regex pattern"):
            await introspector.discover_views(
                pattern="[invalid(regex",  # Unclosed bracket
                use_regex=True,
            )

    @pytest.mark.asyncio
    async def test_discover_functions_invalid_regex_raises_valueerror(self, introspector):
        """Invalid regex pattern should raise ValueError with descriptive message."""
        with pytest.raises(ValueError, match="Invalid regex pattern"):
            await introspector.discover_functions(
                pattern="*invalid",  # Invalid regex quantifier at start
                use_regex=True,
            )

    @pytest.mark.asyncio
    async def test_discover_views_valid_regex_no_error(self, introspector, mock_pool):
        """Valid regex pattern should not raise validation error."""
        # Setup mock to return empty results
        conn = mock_pool.connection.return_value.__aenter__.return_value
        views_result = MagicMock()
        views_result.fetchall = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value=views_result)

        # Should not raise - valid regex
        result = await introspector.discover_views(
            pattern=r"^v_(user|post)s?$",
            use_regex=True,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_discover_functions_valid_regex_no_error(self, introspector, mock_pool):
        """Valid regex pattern should not raise validation error."""
        # Setup mock to return empty results
        conn = mock_pool.connection.return_value.__aenter__.return_value
        func_result = MagicMock()
        func_result.fetchall = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value=func_result)

        # Should not raise - valid regex
        result = await introspector.discover_functions(
            pattern=r"^fn_(create|update|delete)_",
            use_regex=True,
        )
        assert result == []


class TestRegexPatternMatching:
    """Test that regex patterns use PostgreSQL ~ operator."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)
        return pool

    @pytest.fixture
    def introspector(self, mock_pool):
        """Create PostgresIntrospector instance."""
        return PostgresIntrospector(mock_pool)

    @pytest.mark.asyncio
    async def test_discover_views_regex_uses_tilde_operator(self, introspector, mock_pool):
        """When use_regex=True, query should use PostgreSQL ~ operator."""
        conn = mock_pool.connection.return_value.__aenter__.return_value
        views_result = MagicMock()
        views_result.fetchall = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value=views_result)

        await introspector.discover_views(pattern=r"^v_test", use_regex=True)

        # Verify the query uses ~ operator
        call_args = conn.execute.call_args_list[0]
        query = call_args[0][0]
        assert "~" in query, "Query should use PostgreSQL ~ regex operator"
        assert "LIKE" not in query, "Query should not use LIKE when use_regex=True"

    @pytest.mark.asyncio
    async def test_discover_views_default_uses_like_operator(self, introspector, mock_pool):
        """Default behavior (use_regex=False) should use LIKE operator."""
        conn = mock_pool.connection.return_value.__aenter__.return_value
        views_result = MagicMock()
        views_result.fetchall = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value=views_result)

        await introspector.discover_views(pattern="v_%")

        # Verify the query uses LIKE operator
        call_args = conn.execute.call_args_list[0]
        query = call_args[0][0]
        assert "LIKE" in query, "Query should use LIKE operator by default"

    @pytest.mark.asyncio
    async def test_discover_functions_regex_uses_tilde_operator(self, introspector, mock_pool):
        """When use_regex=True, query should use PostgreSQL ~ operator."""
        conn = mock_pool.connection.return_value.__aenter__.return_value
        func_result = MagicMock()
        func_result.fetchall = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value=func_result)

        await introspector.discover_functions(pattern=r"^fn_", use_regex=True)

        # Verify the query uses ~ operator
        call_args = conn.execute.call_args_list[0]
        query = call_args[0][0]
        assert "~" in query, "Query should use PostgreSQL ~ regex operator"
        assert "LIKE" not in query, "Query should not use LIKE when use_regex=True"

    @pytest.mark.asyncio
    async def test_discover_functions_default_uses_like_operator(self, introspector, mock_pool):
        """Default behavior (use_regex=False) should use LIKE operator."""
        conn = mock_pool.connection.return_value.__aenter__.return_value
        func_result = MagicMock()
        func_result.fetchall = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value=func_result)

        await introspector.discover_functions(pattern="fn_%")

        # Verify the query uses LIKE operator
        call_args = conn.execute.call_args_list[0]
        query = call_args[0][0]
        assert "LIKE" in query, "Query should use LIKE operator by default"


class TestBackwardCompatibility:
    """Test that default behavior remains unchanged (backward compatible)."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)
        return pool

    @pytest.fixture
    def introspector(self, mock_pool):
        """Create PostgresIntrospector instance."""
        return PostgresIntrospector(mock_pool)

    @pytest.mark.asyncio
    async def test_discover_views_default_pattern_unchanged(self, introspector, mock_pool):
        """Default pattern 'v_%' should work as before."""
        conn = mock_pool.connection.return_value.__aenter__.return_value
        views_result = MagicMock()
        views_result.fetchall = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value=views_result)

        # Call without use_regex parameter (should default to False)
        await introspector.discover_views()

        # Verify default pattern was used
        call_args = conn.execute.call_args_list[0]
        params = call_args[0][1]
        assert params[1] == "v_%", "Default pattern should be 'v_%'"

    @pytest.mark.asyncio
    async def test_discover_functions_default_pattern_unchanged(self, introspector, mock_pool):
        """Default pattern 'fn_%' should work as before."""
        conn = mock_pool.connection.return_value.__aenter__.return_value
        func_result = MagicMock()
        func_result.fetchall = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value=func_result)

        # Call without use_regex parameter (should default to False)
        await introspector.discover_functions()

        # Verify default pattern was used
        call_args = conn.execute.call_args_list[0]
        params = call_args[0][1]
        assert params[1] == "fn_%", "Default pattern should be 'fn_%'"

    @pytest.mark.asyncio
    async def test_discover_views_explicit_use_regex_false(self, introspector, mock_pool):
        """Explicit use_regex=False should behave same as default."""
        conn = mock_pool.connection.return_value.__aenter__.return_value
        views_result = MagicMock()
        views_result.fetchall = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value=views_result)

        await introspector.discover_views(pattern="v_%", use_regex=False)

        # Verify LIKE is used
        call_args = conn.execute.call_args_list[0]
        query = call_args[0][0]
        assert "LIKE" in query
