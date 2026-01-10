"""Tests for query conversion caching functionality."""

import pytest

from fraiseql.core.query_conversion_cache import (
    QueryConversionCache,
    cache_query_conversion,
    clear_query_cache,
    get_cache,
    get_cache_stats,
    get_cached_query_conversion,
)


class TestQueryConversionCache:
    """Test QueryConversionCache class."""

    def test_cache_creation(self) -> None:
        """Verify cache can be created with default and custom sizes."""
        cache_default = QueryConversionCache()
        assert cache_default.max_size == 1000

        cache_small = QueryConversionCache(max_size=10)
        assert cache_small.max_size == 10

    def test_cache_put_and_get(self) -> None:
        """Verify basic put and get operations."""
        cache = QueryConversionCache()
        cache.clear()

        query = "query { user { id } }"
        data = {"operation_type": "query", "parsed": True}

        # Cache miss before adding
        assert cache.get(query) is None

        # Add to cache
        cache.put(query, data)

        # Cache hit after adding
        cached = cache.get(query)
        assert cached is not None
        assert cached == data

    def test_cache_lru_eviction(self) -> None:
        """Verify LRU eviction when cache is full."""
        cache = QueryConversionCache(max_size=3)
        cache.clear()

        # Add three items
        for i in range(3):
            query = f"query {{ user{i} {{ id }} }}"
            cache.put(query, {"index": i})

        # Cache should be full
        assert len(cache._cache) == 3

        # Add fourth item (should evict oldest)
        query4 = "query { user4 { id } }"
        cache.put(query4, {"index": 4})

        # Should still have 3 items
        assert len(cache._cache) == 3

        # First item should be evicted
        assert cache.get("query { user0 { id } }") is None

        # Other items should be present
        assert cache.get("query { user1 { id } }") is not None
        assert cache.get("query { user2 { id } }") is not None
        assert cache.get(query4) is not None

    def test_cache_update_moves_to_end(self) -> None:
        """Verify updating existing entry moves it to end (most recent)."""
        cache = QueryConversionCache(max_size=3)
        cache.clear()

        # Add three items
        queries = [f"query {{ user{i} {{ id }} }}" for i in range(3)]
        for i, query in enumerate(queries):
            cache.put(query, {"index": i})

        # Update first item (should move to end)
        cache.put(queries[0], {"index": 0, "updated": True})

        # Add new item (should evict second item, not first)
        cache.put("query { user3 { id } }", {"index": 3})

        # First and third items should exist (second was evicted)
        assert cache.get(queries[0]) is not None
        assert cache.get(queries[1]) is None
        assert cache.get(queries[2]) is not None

    def test_cache_stats(self) -> None:
        """Verify cache statistics tracking."""
        cache = QueryConversionCache()
        cache.clear()

        query = "query { user { id } }"
        cache.put(query, {"data": True})

        # Get hit
        cache.get(query)
        cache.get(query)

        # Get miss
        cache.get("different query")

        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["total"] == 3
        assert stats["size"] == 1

    def test_cache_stats_hit_rate(self) -> None:
        """Verify cache hit rate calculation."""
        cache = QueryConversionCache()
        cache.clear()

        query = "query { user { id } }"
        cache.put(query, {"data": True})

        # 8 hits, 2 misses = 80% hit rate
        for _ in range(8):
            cache.get(query)

        for _ in range(2):
            cache.get("different query")

        stats = cache.stats()
        assert stats["hits"] == 8
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 80.0

    def test_cache_clear(self) -> None:
        """Verify cache clearing."""
        cache = QueryConversionCache()
        cache.clear()

        # Add items
        for i in range(5):
            cache.put(f"query {{ user{i} {{ id }} }}", {"index": i})

        assert len(cache._cache) == 5

        # Clear cache
        cache.clear()

        assert len(cache._cache) == 0
        assert cache.stats()["hits"] == 0
        assert cache.stats()["misses"] == 0

    def test_cache_key_generation(self) -> None:
        """Verify cache keys are consistent and unique."""
        cache = QueryConversionCache()

        query1 = "query { user { id } }"
        query2 = "query { user { name } }"
        query1_duplicate = "query { user { id } }"

        key1 = cache._get_cache_key(query1)
        key2 = cache._get_cache_key(query2)
        key1_dup = cache._get_cache_key(query1_duplicate)

        # Same query should generate same key
        assert key1 == key1_dup

        # Different queries should generate different keys
        assert key1 != key2

        # Keys should be strings
        assert isinstance(key1, str)
        assert len(key1) > 0


class TestGlobalCacheIntegration:
    """Test global cache functions."""

    def test_get_cache_returns_singleton(self) -> None:
        """Verify get_cache returns the same instance."""
        cache1 = get_cache()
        cache2 = get_cache()

        assert cache1 is cache2

    def test_cache_query_conversion(self) -> None:
        """Test caching a query conversion."""
        clear_query_cache()

        query = "query { users { id name } }"

        # First call parses and caches
        result1 = cache_query_conversion(query, "query")

        assert result1["operation_type"] == "query"
        assert "document" in result1
        assert result1["query_length"] == len(query)

        # Stats should show cache miss
        stats = get_cache_stats()
        assert stats["misses"] > 0

    def test_get_cached_query_conversion(self) -> None:
        """Test retrieving cached query conversion."""
        clear_query_cache()

        query = "query { users { id } }"

        # Prime cache
        cache_query_conversion(query, "query")

        # Get from cache
        cached = get_cached_query_conversion(query)

        assert cached is not None
        assert cached["operation_type"] == "query"

    def test_invalid_query_raises_error(self) -> None:
        """Verify invalid queries raise appropriate errors."""
        clear_query_cache()

        invalid_query = "invalid { syntax"

        with pytest.raises(ValueError, match="Failed to parse query"):
            cache_query_conversion(invalid_query, "query")

    def test_different_operations_cached_separately(self) -> None:
        """Verify different queries are cached separately."""
        clear_query_cache()

        query_get = "query GetUser { user { id } }"
        query_update = "mutation UpdateUser { updateUser { id } }"

        result_query = cache_query_conversion(query_get, "query", "GetUser")
        result_mutation = cache_query_conversion(query_update, "mutation", "UpdateUser")

        assert result_query["operation_type"] == "query"
        assert result_query["operation_name"] == "GetUser"

        assert result_mutation["operation_type"] == "mutation"
        assert result_mutation["operation_name"] == "UpdateUser"

    def test_cache_reset_stats(self) -> None:
        """Verify stats can be reset."""
        cache = get_cache()
        cache.clear()

        # Create some activity
        for i in range(5):
            cache.put(f"query {i}", {"data": i})
            cache.get(f"query {i}")

        stats_before = cache.stats()
        assert stats_before["hits"] > 0

        # Reset stats
        cache.reset_stats()

        stats_after = cache.stats()
        assert stats_after["hits"] == 0
        assert stats_after["misses"] == 0
        assert stats_after["total"] == 0
        # Size should still be 5 (reset_stats doesn't clear cache)
        assert stats_after["size"] == 5


class TestCacheConcurrency:
    """Test thread safety of cache."""

    def test_concurrent_access_safe(self) -> None:
        """Verify cache is thread-safe for concurrent access."""
        import threading

        cache = QueryConversionCache(max_size=100)
        cache.clear()

        results = []

        def worker(thread_id: int) -> None:
            for i in range(10):
                query = f"query {{ user{thread_id}_{i} {{ id }} }}"
                data = {"thread": thread_id, "index": i}

                cache.put(query, data)
                cached = cache.get(query)

                if cached == data:
                    results.append(True)
                else:
                    results.append(False)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # All operations should succeed
        assert all(results), "Some concurrent operations failed"
        assert len(results) == 50  # 5 threads × 10 operations


class TestCachePerformance:
    """Test cache performance characteristics."""

    def test_cache_hit_performance(self) -> None:
        """Verify cache hits are fast."""
        import timeit

        cache = QueryConversionCache()
        cache.clear()

        query = "query { users { id name email } }"
        cache.put(query, {"data": "test"})

        def measure_hit() -> None:
            cache.get(query)

        # Measure hit performance
        elapsed = timeit.timeit(measure_hit, number=1000)
        per_hit = elapsed / 1000

        # Cache hits should be < 1 microsecond
        assert per_hit < 1e-5, f"Cache hit took {per_hit * 1e6:.2f}µs"

    def test_cache_miss_performance(self) -> None:
        """Verify cache misses are also fast."""
        import timeit

        cache = QueryConversionCache()
        cache.clear()

        cache.put("query { users { id } }", {"data": "test"})

        def measure_miss() -> None:
            cache.get("different query")

        # Measure miss performance
        elapsed = timeit.timeit(measure_miss, number=1000)
        per_miss = elapsed / 1000

        # Cache misses should be < 10 microseconds
        assert per_miss < 1e-4, f"Cache miss took {per_miss * 1e6:.2f}µs"


class TestCacheMemoryEfficiency:
    """Test cache memory efficiency."""

    def test_lru_prevents_unbounded_growth(self) -> None:
        """Verify LRU prevents unbounded memory growth."""
        cache = QueryConversionCache(max_size=100)
        cache.clear()

        # Add 1000 items to cache with max_size=100
        for i in range(1000):
            query = f"query {{ user{i} {{ id }} }}"
            cache.put(query, {"index": i, "data": "x" * 1000})

        # Cache should never exceed max_size
        assert len(cache._cache) <= 100

    def test_cache_size_tracking(self) -> None:
        """Verify cache size is tracked accurately."""
        cache = QueryConversionCache(max_size=50)
        cache.clear()

        for i in range(50):
            query = f"query {{ user{i} {{ id }} }}"
            cache.put(query, {"index": i})

        stats = cache.stats()
        assert stats["size"] == 50

        # Overflow should not increase size beyond max
        cache.put("query { overflow { id } }", {"overflow": True})

        stats = cache.stats()
        assert stats["size"] == 50
