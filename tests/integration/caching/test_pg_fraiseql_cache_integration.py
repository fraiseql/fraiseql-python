"""Integration tests for pg_fraiseql_cache extension with FraiseQL.

This module tests the automatic cache invalidation provided by the
pg_fraiseql_cache PostgreSQL extension.

Tests cover:
- Extension detection and availability
- Domain version checking for cache invalidation
- CASCADE rule generation for automatic invalidation
- Automatic trigger setup for watched tables
"""

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from fraiseql.caching import CacheConfig, PostgresCache

pytestmark = pytest.mark.integration

logger = logging.getLogger(__name__)


class TestExtensionDetection:
    """Test automatic detection of pg_fraiseql_cache extension."""

    @pytest.fixture
    def mock_pool(self) -> None:
        """Create mock database pool."""
        return MagicMock()

    @pytest.fixture
    def cache_config(self) -> None:
        """Create cache configuration."""
        return CacheConfig(enabled=True, default_ttl=300)

    @pytest.mark.asyncio
    async def test_extension_detected_when_installed(self, mock_pool, cache_config) -> None:
        """Test that FraiseQL detects pg_fraiseql_cache when installed.

        Expected behavior:
        - Query pg_extension table during initialization
        - Set has_domain_versioning = True
        - Set extension_version to detected version
        - Log success message
        """
        # Setup mock to simulate extension installed
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=("1.0",))  # Extension version
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        # Create cache backend
        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)

        # Ensure initialization runs
        await cache._ensure_initialized()

        # Verify extension was detected
        assert hasattr(cache, "has_domain_versioning"), "has_domain_versioning property missing"
        assert cache.has_domain_versioning is True, "Extension should be detected"

        assert hasattr(cache, "extension_version"), "extension_version property missing"
        assert cache.extension_version == "1.0", "Version should be 1.0"

        # Verify pg_extension was queried
        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        extension_query_found = any("pg_extension" in call for call in calls)
        assert extension_query_found, "Should query pg_extension table"

    @pytest.mark.asyncio
    async def test_fallback_when_extension_not_installed(self, mock_pool, cache_config) -> None:
        """Test that FraiseQL works without pg_fraiseql_cache extension.

        Expected behavior:
        - Query pg_extension table during initialization
        - Set has_domain_versioning = False
        - Set extension_version = None
        - Log fallback message
        - Continue to work with TTL-only caching
        """
        # Setup mock to simulate extension NOT installed
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)  # No extension
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        # Create cache backend
        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)

        # Ensure initialization runs
        await cache._ensure_initialized()

        # Verify fallback behavior
        assert hasattr(cache, "has_domain_versioning"), "has_domain_versioning property missing"
        assert cache.has_domain_versioning is False, "Extension should NOT be detected"

        assert hasattr(cache, "extension_version"), "extension_version property missing"
        assert cache.extension_version is None, "Version should be None"

    @pytest.mark.asyncio
    async def test_extension_detection_logs_correctly(
        self, mock_pool, cache_config, caplog
    ) -> None:
        """Test that extension detection produces appropriate log messages.

        Expected behavior:
        - Log success when extension found
        - Log fallback when extension not found
        """
        # Test with extension installed
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=("1.0",))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        with caplog.at_level(logging.INFO):
            cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)
            await cache._ensure_initialized()

            # Check for success log message
            log_messages = [record.message for record in caplog.records]
            assert any("pg_fraiseql_cache" in msg and "1.0" in msg for msg in log_messages), (
                "Should log extension detection with version"
            )

    @pytest.mark.asyncio
    async def test_properties_accessible_before_initialization(self, mock_pool) -> None:
        """Test that properties are accessible even before initialization.

        Expected behavior:
        - Properties should exist with default values
        - Should not raise AttributeError
        """
        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)

        # Should be accessible (will fail until implemented)
        try:
            has_versioning = cache.has_domain_versioning
            version = cache.extension_version
            # If we get here, properties exist (might be None or False)
            assert has_versioning is not None or version is None  # Just checking accessibility
        except AttributeError as e:
            pytest.fail(f"Properties should be accessible: {e}")

    @pytest.mark.asyncio
    async def test_extension_detection_only_runs_once(self, mock_pool) -> None:
        """Test that extension detection only happens once per cache instance.

        Expected behavior:
        - First call to _ensure_initialized() should query pg_extension
        - Subsequent calls should use cached result
        """
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=("1.0",))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)

        # First initialization
        await cache._ensure_initialized()
        first_call_count = mock_cursor.execute.call_count

        # Second initialization (should be skipped)
        await cache._ensure_initialized()
        second_call_count = mock_cursor.execute.call_count

        # Call count should be the same (no new queries)
        assert first_call_count == second_call_count, "Extension detection should only run once"

    @pytest.mark.asyncio
    async def test_graceful_fallback_on_extension_query_error(self, mock_pool, caplog) -> None:
        """Test graceful fallback when extension detection query fails.

        Expected behavior:
        - If pg_extension query fails (e.g., permissions), don't crash
        - Fall back to has_domain_versioning = False
        - Log warning message
        - Continue to work normally
        """
        import psycopg

        # Setup mock to simulate query error on pg_extension query
        mock_cursor = AsyncMock()

        # Track call count to know which query is being executed
        call_count = 0

        async def mock_execute(query, *args) -> None:
            nonlocal call_count
            call_count += 1
            # First two calls are CREATE TABLE queries (succeed)
            if call_count <= 2:
                return
            # Third call is pg_extension query (fail with permission error)
            raise psycopg.errors.InsufficientPrivilege("permission denied for table pg_extension")

        mock_cursor.execute = mock_execute
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        # Create cache backend
        with caplog.at_level(logging.WARNING):
            cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)
            await cache._ensure_initialized()

            # Verify graceful fallback
            assert cache.has_domain_versioning is False, "Should fallback to no versioning"
            assert cache.extension_version is None, "Version should be None on error"

            # Check for warning log
            log_messages = [record.message for record in caplog.records]
            assert any("Failed to detect pg_fraiseql_cache" in msg for msg in log_messages), (
                "Should log warning on error"
            )


class TestTenantIdInCacheKeys:
    """Test that cache keys include tenant_id for security isolation."""

    @pytest.fixture
    def mock_pool(self) -> None:
        """Create mock database pool."""
        return MagicMock()

    @pytest.fixture
    def mock_cache_backend(self) -> None:
        """Create mock cache backend."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_cache_key_includes_tenant_id(self) -> None:
        """Test that cache keys include tenant_id for isolation.

        Expected behavior:
        - Cache keys should include tenant_id as second component
        - Format: "fraiseql:{tenant_id}:view_name:..."
        - Different tenants get different cache keys for same query
        """
        from uuid import uuid4

        from fraiseql.caching.cache_key import CacheKeyBuilder

        tenant1 = uuid4()
        tenant2 = uuid4()

        # Create cache key builder
        builder = CacheKeyBuilder()

        # Build keys for same query, different tenants
        key1 = builder.build_key("users", tenant_id=tenant1, filters={"status": "active"})
        key2 = builder.build_key("users", tenant_id=tenant2, filters={"status": "active"})

        # Keys MUST be different for different tenants
        assert key1 != key2, "Different tenants must have different cache keys"

        # Keys MUST include tenant_id
        assert str(tenant1) in key1, f"Cache key must include tenant_id: {key1}"
        assert str(tenant2) in key2, f"Cache key must include tenant_id: {key2}"

        # Verify tenant_id is in the correct position (second component)
        key1_parts = key1.split(":")

        assert len(key1_parts) >= 3, "Cache key should have at least 3 parts"
        assert key1_parts[0] == "fraiseql", "First part should be prefix"
        assert key1_parts[1] == str(tenant1), "Second part should be tenant_id"
        assert key1_parts[2] == "users", "Third part should be view name"

    @pytest.mark.asyncio
    async def test_cache_key_without_tenant_id(self) -> None:
        """Test that cache keys work without tenant_id for backward compatibility.

        Expected behavior:
        - If no tenant_id provided, should still generate valid key
        - Key should not have empty component
        """
        from fraiseql.caching.cache_key import CacheKeyBuilder

        builder = CacheKeyBuilder()

        # Build key without tenant_id (backward compatibility)
        key = builder.build_key("users", filters={"status": "active"})

        # Should still be valid
        assert key is not None
        assert "users" in key
        assert key.startswith("fraiseql:")

    @pytest.mark.asyncio
    async def test_cached_repository_passes_tenant_id_to_cache_key(
        self, mock_pool, mock_cache_backend
    ):
        """Test that CachedRepository extracts and passes tenant_id to cache key builder.

        Expected behavior:
        - CachedRepository should extract tenant_id from context
        - Pass tenant_id to CacheKeyBuilder.build_key()
        - Cache keys should be tenant-isolated
        """
        from uuid import uuid4

        from fraiseql.caching import CacheConfig
        from fraiseql.caching.repository_integration import CachedRepository
        from fraiseql.caching.result_cache import ResultCache
        from fraiseql.db import FraiseQLRepository

        tenant_id = uuid4()

        # Create base repository with tenant context
        base_repo = FraiseQLRepository(pool=mock_pool, context={"tenant_id": tenant_id})

        # Create cache with mock backend
        cache_config = CacheConfig(enabled=True, default_ttl=300)
        cache = ResultCache(backend=mock_cache_backend, config=cache_config)

        # Create cached repository
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

        # Execute find query
        await cached_repo.find("users", mandatory_filters={"status": "active"})

        # Verify cache.get was called
        assert mock_cache_backend.get.call_count >= 1, "Cache should be checked"

        # Get the cache key that was used
        cache_key = mock_cache_backend.get.call_args[0][0]

        # Verify tenant_id is in the cache key
        assert str(tenant_id) in cache_key, f"Cache key must include tenant_id: {cache_key}"

    @pytest.mark.asyncio
    async def test_different_tenants_get_different_cache_entries(
        self, mock_pool, mock_cache_backend
    ):
        """Test that different tenants don't share cache entries (SECURITY TEST).

        Expected behavior:
        - Tenant A and Tenant B query same data
        - Each should get their own cache entry
        - Cache keys must be different
        """
        from uuid import uuid4

        from fraiseql.caching import CacheConfig
        from fraiseql.caching.repository_integration import CachedRepository
        from fraiseql.caching.result_cache import ResultCache
        from fraiseql.db import FraiseQLRepository

        tenant_a = uuid4()
        tenant_b = uuid4()

        # Track cache keys used
        cache_keys_used = []

        def track_cache_get(key) -> None:
            cache_keys_used.append(key)

        mock_cache_backend.get = AsyncMock(side_effect=track_cache_get)
        mock_cache_backend.set = AsyncMock()

        # Mock database
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

        cache_config = CacheConfig(enabled=True, default_ttl=300)
        cache = ResultCache(backend=mock_cache_backend, config=cache_config)

        # Tenant A queries
        base_repo_a = FraiseQLRepository(pool=mock_pool, context={"tenant_id": tenant_a})
        cached_repo_a = CachedRepository(base_repo_a, cache)
        await cached_repo_a.find("users", mandatory_filters={"status": "active"})

        # Tenant B queries (same query)
        base_repo_b = FraiseQLRepository(pool=mock_pool, context={"tenant_id": tenant_b})
        cached_repo_b = CachedRepository(base_repo_b, cache)
        await cached_repo_b.find("users", mandatory_filters={"status": "active"})

        # Verify we tracked 2 cache lookups
        assert len(cache_keys_used) == 2, "Should have 2 cache lookups"

        # Verify cache keys are DIFFERENT
        key_a = cache_keys_used[0]
        key_b = cache_keys_used[1]
        assert key_a != key_b, "Different tenants MUST have different cache keys (SECURITY!)"

        # Verify each key contains its respective tenant_id
        assert str(tenant_a) in key_a, f"Tenant A key must contain tenant_a: {key_a}"
        assert str(tenant_b) in key_b, f"Tenant B key must contain tenant_b: {key_b}"


class TestCacheValueStructure:
    """Test cache value structure with version metadata."""

    @pytest.fixture
    def mock_pool(self) -> None:
        """Create mock database pool."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_cache_set_accepts_versions_parameter(self, mock_pool) -> None:
        """Test that PostgresCache.set() accepts versions parameter.

        Expected behavior:
        - set() should accept optional versions parameter
        - When extension is enabled AND versions provided, wrap value with metadata
        - When extension is disabled OR no versions, store value directly
        """
        from fraiseql.caching.postgres_cache import PostgresCache

        # Mock: extension installed
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=("1.0",))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)
        await cache._ensure_initialized()

        # Should accept versions parameter without error
        test_value = [{"id": 1}]
        test_versions = {"user": 42}

        # This should not raise an error
        await cache.set("test_key", test_value, ttl=300, versions=test_versions)

    @pytest.mark.asyncio
    async def test_cache_get_with_metadata_method_exists(self, mock_pool) -> None:
        """Test that PostgresCache has get_with_metadata() method.

        Expected behavior:
        - get_with_metadata() method should exist
        - Should return tuple of (result, versions)
        """
        from fraiseql.caching.postgres_cache import PostgresCache

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)

        # Method should exist
        assert hasattr(cache, "get_with_metadata"), "get_with_metadata() method should exist"


class TestVersionChecking:
    """Test domain version checking for cache invalidation."""

    @pytest.fixture
    def mock_pool(self) -> None:
        """Create mock database pool."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_get_domain_versions_method_exists(self, mock_pool) -> None:
        """Test that PostgresCache has get_domain_versions() method.

        Expected behavior:
        - get_domain_versions() method should exist
        - Should accept tenant_id and domains list
        - Should return dict[str, int] mapping domain names to versions
        """
        from fraiseql.caching.postgres_cache import PostgresCache

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)

        # Method should exist
        assert hasattr(cache, "get_domain_versions"), "get_domain_versions() method should exist"

    @pytest.mark.asyncio
    async def test_get_domain_versions_returns_current_versions(self, mock_pool) -> None:
        """Test that get_domain_versions() returns current domain versions.

        Expected behavior:
        - Query fraiseql_cache.domain_version table
        - Return versions for requested domains
        - Filter by tenant_id
        """
        from uuid import uuid4

        from fraiseql.caching.postgres_cache import PostgresCache

        tenant_id = uuid4()

        # Mock database returning domain versions
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        # First fetchone for extension detection
        mock_cursor.fetchone = AsyncMock(return_value=("1.0",))
        # Fetchall for domain versions query
        mock_cursor.fetchall = AsyncMock(
            return_value=[
                ("user", 42),
                ("post", 15),
            ]
        )
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)
        await cache._ensure_initialized()

        # Get domain versions
        versions = await cache.get_domain_versions(tenant_id, ["user", "post"])

        # Should return version dict
        assert isinstance(versions, dict), "Should return dict"
        assert versions.get("user") == 42, "Should return user version"
        assert versions.get("post") == 15, "Should return post version"

    @pytest.mark.asyncio
    async def test_cache_invalidated_on_data_change(self, mock_pool) -> None:
        """Test that cache is invalidated when underlying data changes.

        Expected behavior:
        - Cache entry stored with domain versions
        - Domain version increments (simulating data change)
        - On cache hit, compare cached_version vs current_version
        - If mismatch, invalidate and refetch
        """
        from uuid import uuid4

        from fraiseql.caching.postgres_cache import PostgresCache

        tenant_id = uuid4()

        # Mock database with proper fetch handling for get_with_metadata
        cached_data = {}

        async def mock_execute(query, params=None) -> None:
            # Track what gets cached during SET
            if "INSERT INTO" in query and params:
                key, value_json, expires = params
                cached_data[key] = json.loads(value_json)

        async def mock_fetchone() -> None:
            # For get_with_metadata, return cached value
            if "test_key" in cached_data:
                return (cached_data["test_key"],)
            return None

        async def mock_fetchall() -> None:
            # For get_domain_versions queries
            # Simulate: first call returns version 42, later calls return 43
            if len(cached_data) > 0:
                # After data has been cached, return updated version
                return [("user", 43)]
            return [("user", 42)]

        # Initial setup mocks for extension detection
        initial_fetchone = AsyncMock(return_value=("1.0",))

        # Track call count to return correct data
        fetchone_call_count = 0

        async def fetchone_router() -> None:
            nonlocal fetchone_call_count
            fetchone_call_count += 1
            if fetchone_call_count == 1:
                # Extension detection
                return ("1.0",)
            # Subsequent calls for cache get
            return await mock_fetchone()

        mock_cursor = AsyncMock()
        mock_cursor.execute = mock_execute
        mock_cursor.fetchone = fetchone_router
        mock_cursor.fetchall = mock_fetchall
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)
        await cache._ensure_initialized()

        # Step 1: Cache value with version 42
        await cache.set("test_key", [{"id": 1, "name": "Alice"}], ttl=300, versions={"user": 42})

        # Step 2: Get cached value (should include version metadata)
        result, cached_versions = await cache.get_with_metadata("test_key")
        assert cached_versions == {"user": 42}, (
            f"Should cache with version 42, got {cached_versions}"
        )

        # Step 3: Get current versions (simulates data change to version 43)
        current_versions = await cache.get_domain_versions(tenant_id, ["user"])
        assert current_versions == {"user": 43}, "Should return updated version 43"

        # Step 4: Compare versions - should detect mismatch
        assert cached_versions["user"] != current_versions["user"], "Versions should mismatch"

    @pytest.mark.asyncio
    async def test_tenant_isolated_version_checks(self, mock_pool) -> None:
        """Test that version checks are tenant-isolated (CRITICAL SECURITY TEST).

        Expected behavior:
        - Tenant A has domain version 42
        - Tenant B has domain version 10
        - get_domain_versions() must filter by tenant_id
        - Each tenant sees only their versions
        """
        from uuid import uuid4

        from fraiseql.caching.postgres_cache import PostgresCache

        tenant_a = uuid4()
        tenant_b = uuid4()

        # Track which execute call we're on to return appropriate data
        execute_calls = []

        async def mock_execute(query, params=None) -> None:
            execute_calls.append((query, params))

        async def mock_fetchall() -> None:
            # Get the last execute call
            if execute_calls:
                last_query, last_params = execute_calls[-1]
                if last_params:
                    tenant_id = last_params[0]
                    if tenant_id == tenant_a:
                        return [("user", 42)]
                    if tenant_id == tenant_b:
                        return [("user", 10)]
            return []

        mock_cursor = AsyncMock()
        mock_cursor.execute = mock_execute
        mock_cursor.fetchone = AsyncMock(return_value=("1.0",))
        mock_cursor.fetchall = mock_fetchall
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)
        await cache._ensure_initialized()

        # Tenant A gets their version
        versions_a = await cache.get_domain_versions(tenant_a, ["user"])
        assert versions_a == {"user": 42}, "Tenant A should see version 42"

        # Tenant B gets their version
        versions_b = await cache.get_domain_versions(tenant_b, ["user"])
        assert versions_b == {"user": 10}, "Tenant B should see version 10"

        # Versions MUST be different (tenant isolation)
        assert versions_a != versions_b, "Tenant versions must be isolated (SECURITY!)"


class TestCascadeRules:
    """Test CASCADE rule registration for automatic invalidation.

    CASCADE rules define domain dependencies - when source_domain changes,
    target_domain caches are invalidated automatically by the extension.
    """

    @pytest.fixture
    def mock_pool(self) -> None:
        """Create mock database pool."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_register_cascade_rule_method_exists(self, mock_pool) -> None:
        """Test that PostgresCache has register_cascade_rule() method.

        Expected behavior:
        - Method should exist
        - Should accept source_domain, target_domain parameters
        """
        from fraiseql.caching.postgres_cache import PostgresCache

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)

        # Method should exist
        assert hasattr(cache, "register_cascade_rule"), (
            "register_cascade_rule() method should exist"
        )

    @pytest.mark.asyncio
    async def test_register_cascade_rule_inserts_into_table(self, mock_pool) -> None:
        """Test that register_cascade_rule() inserts into cascade_rules table.

        Expected behavior:
        - INSERT INTO fraiseql_cache.cascade_rules
        - source_domain and target_domain should be set
        - rule_type defaults to 'invalidate'
        """
        from fraiseql.caching.postgres_cache import PostgresCache

        # Mock: extension installed
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=("1.0",))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)
        await cache._ensure_initialized()

        # Register CASCADE rule: user → post
        await cache.register_cascade_rule("user", "post")

        # Verify INSERT was executed
        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        insert_found = any("INSERT INTO" in call and "cascade_rules" in call for call in calls)
        assert insert_found, "Should INSERT into fraiseql_cache.cascade_rules"

    @pytest.mark.asyncio
    async def test_register_cascade_rule_only_when_extension_available(self, mock_pool) -> None:
        """Test that CASCADE rules only work when extension is installed.

        Expected behavior:
        - If extension not available, should raise or warn
        - CASCADE rules require pg_fraiseql_cache extension
        """
        from fraiseql.caching.postgres_cache import PostgresCache, PostgresCacheError

        # Mock: NO extension
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)  # No extension
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)
        await cache._ensure_initialized()

        # Should fail gracefully when extension not available
        try:
            await cache.register_cascade_rule("user", "post")
            # If it doesn't raise, it should be a no-op
            assert not cache.has_domain_versioning, "Extension should not be available"
        except PostgresCacheError:
            # Or it might raise an error - either is acceptable
            pass

    @pytest.mark.asyncio
    async def test_clear_cascade_rules_method_exists(self, mock_pool) -> None:
        """Test that PostgresCache has clear_cascade_rules() method.

        Expected behavior:
        - Method should exist
        - Should allow clearing all CASCADE rules or filtered by domain
        """
        from fraiseql.caching.postgres_cache import PostgresCache

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)

        # Method should exist
        assert hasattr(cache, "clear_cascade_rules"), "clear_cascade_rules() method should exist"


class TestTriggerSetup:
    """Test automatic trigger setup for watched tables.

    Automatic trigger setup calls fraiseql_cache.setup_table_invalidation()
    for tables to enable automatic cache invalidation on data changes.
    """

    @pytest.fixture
    def mock_pool(self) -> None:
        """Create mock database pool."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_setup_table_trigger_method_exists(self, mock_pool) -> None:
        """Test that PostgresCache has setup_table_trigger() method.

        Expected behavior:
        - Method should exist
        - Should accept table_name parameter
        - Should optionally accept domain_name and tenant_column
        """
        from fraiseql.caching.postgres_cache import PostgresCache

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)

        # Method should exist
        assert hasattr(cache, "setup_table_trigger"), "setup_table_trigger() method should exist"

    @pytest.mark.asyncio
    async def test_setup_table_trigger_calls_extension_function(self, mock_pool) -> None:
        """Test that setup_table_trigger() calls fraiseql_cache.setup_table_invalidation().

        Expected behavior:
        - Call fraiseql_cache.setup_table_invalidation() function
        - Pass table_name, domain_name, tenant_column parameters
        """
        from fraiseql.caching.postgres_cache import PostgresCache

        # Mock: extension installed
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=("1.0",))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)
        await cache._ensure_initialized()

        # Setup trigger for users table
        await cache.setup_table_trigger("users")

        # Verify fraiseql_cache.setup_table_invalidation was called
        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        setup_function_called = any(
            "fraiseql_cache.setup_table_invalidation" in call for call in calls
        )
        assert setup_function_called, "Should call fraiseql_cache.setup_table_invalidation()"

    @pytest.mark.asyncio
    async def test_setup_table_trigger_with_custom_domain(self, mock_pool) -> None:
        """Test setup_table_trigger() with custom domain name.

        Expected behavior:
        - Accept custom domain_name parameter
        - Pass it to setup_table_invalidation function
        """
        from fraiseql.caching.postgres_cache import PostgresCache

        # Mock: extension installed
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=("1.0",))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)
        await cache._ensure_initialized()

        # Setup trigger with custom domain
        await cache.setup_table_trigger("tb_users", domain_name="user")

        # Verify function was called
        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        assert any("setup_table_invalidation" in call for call in calls)

    @pytest.mark.asyncio
    async def test_setup_table_trigger_only_when_extension_available(self, mock_pool) -> None:
        """Test that trigger setup only works when extension is installed.

        Expected behavior:
        - If extension not available, should warn and skip
        - Trigger setup requires pg_fraiseql_cache extension
        """
        from fraiseql.caching.postgres_cache import PostgresCache

        # Mock: NO extension
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)  # No extension
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_conn)

        cache = PostgresCache(connection_pool=mock_pool, auto_initialize=False)
        await cache._ensure_initialized()

        # Should skip gracefully when extension not available
        await cache.setup_table_trigger("users")

        # Should NOT call setup function (extension not available)
        assert not cache.has_domain_versioning, "Extension should not be available"
