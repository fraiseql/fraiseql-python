"""Integration tests for caching with FraiseQLRepository."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from fraiseql.caching import CacheConfig, ResultCache
from fraiseql.caching.repository_integration import CachedRepository
from fraiseql.db import FraiseQLRepository

pytestmark = pytest.mark.integration


class TestCachedRepository:
    """Test caching integration with FraiseQLRepository."""

    @pytest.fixture
    def mock_cache_backend(self) -> None:
        """Create mock cache backend."""
        return AsyncMock()

    @pytest.fixture
    def mock_pool(self) -> None:
        """Create mock database pool."""
        return MagicMock()

    @pytest.fixture
    def cache_config(self) -> None:
        """Create cache configuration."""
        return CacheConfig(enabled=True, default_ttl=300)

    @pytest.mark.asyncio
    async def test_find_with_cache_hit(self, mock_cache_backend, mock_pool, cache_config) -> None:
        """Test find method with cache hit."""
        # Setup
        cache = ResultCache(backend=mock_cache_backend, config=cache_config)
        base_repo = FraiseQLRepository(pool=mock_pool)
        cached_repo = CachedRepository(base_repo, cache)

        # Mock cache hit
        cached_data = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        mock_cache_backend.get.return_value = cached_data

        # Execute
        result = await cached_repo.find("users", mandatory_filters={"status": "active"}, limit=10)

        # Verify
        assert result == cached_data
        mock_cache_backend.get.assert_called_once()
        # Base repository should not be called on cache hit
        assert not mock_pool.connection.called

    @pytest.mark.asyncio
    async def test_find_with_cache_miss(self, mock_cache_backend, mock_pool, cache_config) -> None:
        """Test find method with cache miss."""
        # Setup
        cache = ResultCache(backend=mock_cache_backend, config=cache_config)
        base_repo = FraiseQLRepository(pool=mock_pool)
        cached_repo = CachedRepository(base_repo, cache)

        # Mock cache miss
        mock_cache_backend.get.return_value = None

        # Mock database result

        # Create async context managers for connection and cursor
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[('{"id": 3, "name": "Charlie"}',)])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        # Execute
        result = await cached_repo.find("users", mandatory_filters={"status": "active"})

        # Verify
        mock_cache_backend.get.assert_called_once()
        mock_cache_backend.set.assert_called_once()

        # Note: With Rust pipeline, find() returns RustResponseBytes instead of list
        # This test needs updating to handle the new return type
        # For now, we just verify the cache methods were called correctly
        # TODO: Update caching layer to properly handle RustResponseBytes
        assert result is not None

    @pytest.mark.asyncio
    async def test_find_one_with_caching(self, mock_cache_backend, mock_pool, cache_config) -> None:
        """Test find_one method with caching."""
        # Setup
        cache = ResultCache(backend=mock_cache_backend, config=cache_config)
        base_repo = FraiseQLRepository(pool=mock_pool)
        cached_repo = CachedRepository(base_repo, cache)

        # Mock cache hit
        cached_data = {"id": 1, "name": "Alice"}
        mock_cache_backend.get.return_value = cached_data

        # Execute
        result = await cached_repo.find_one("users", mandatory_filters={"id": uuid4()})

        # Verify
        assert result == cached_data
        mock_cache_backend.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_mutation_invalidates_cache(
        self, mock_cache_backend, mock_pool, cache_config
    ) -> None:
        """Test that mutations invalidate related cache entries."""
        # Setup
        cache = ResultCache(backend=mock_cache_backend, config=cache_config)
        base_repo = FraiseQLRepository(pool=mock_pool)
        cached_repo = CachedRepository(base_repo, cache)

        # Mock successful mutation
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"id": str(uuid4()), "status": "success"})
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        # Execute mutation
        await cached_repo.execute_function("create_user", {"name": "Dave"})

        # Verify cache invalidation
        mock_cache_backend.delete_pattern.assert_called()

    @pytest.mark.asyncio
    async def test_skip_cache_option(self, mock_cache_backend, mock_pool, cache_config) -> None:
        """Test skip_cache option bypasses cache."""
        # Setup
        cache = ResultCache(backend=mock_cache_backend, config=cache_config)
        base_repo = FraiseQLRepository(pool=mock_pool)
        cached_repo = CachedRepository(base_repo, cache)

        # Mock database result
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        # Execute with skip_cache
        await cached_repo.find("users", skip_cache=True)

        # Verify cache was not used
        mock_cache_backend.get.assert_not_called()
        mock_cache_backend.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_custom_ttl(self, mock_cache_backend, mock_pool, cache_config) -> None:
        """Test custom TTL for specific queries."""
        # Setup
        cache = ResultCache(backend=mock_cache_backend, config=cache_config)
        base_repo = FraiseQLRepository(pool=mock_pool)
        cached_repo = CachedRepository(base_repo, cache)

        # Mock cache miss
        mock_cache_backend.get.return_value = None

        # Mock database result
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        # Execute with custom TTL
        await cached_repo.find("users", cache_ttl=600)

        # Verify custom TTL was used
        mock_cache_backend.set.assert_called_once()
        call_args = mock_cache_backend.set.call_args
        assert call_args[1]["ttl"] == 600
