"""Query conversion caching for performance optimization.

Caches GraphQL query conversions to avoid repeated processing of identical
queries, improving performance for common operations.

Design:
- LRU cache for memory efficiency
- Thread-safe for concurrent access
- Configurable size limits
- Metrics tracking
"""

import hashlib
import threading
from typing import Any, Optional

from graphql import parse


class QueryConversionCache:
    """LRU cache for GraphQL query conversions.

    Stores parsed queries and their metadata to avoid re-parsing and
    re-processing identical queries.
    """

    def __init__(self, max_size: int = 1000) -> None:
        """Initialize the cache.

        Args:
            max_size: Maximum number of cached queries (default 1000)
        """
        self.max_size = max_size
        self._cache: dict[str, Any] = {}
        self._access_order: list[str] = []
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def _get_cache_key(self, query: str) -> str:
        """Generate cache key from query string.

        Uses SHA256 hash for consistent, collision-resistant keys.

        Args:
            query: GraphQL query string

        Returns:
            Hash-based cache key
        """
        return hashlib.sha256(query.encode()).hexdigest()

    def get(self, query: str) -> Optional[dict[str, Any]]:
        """Get cached query conversion if available.

        Args:
            query: GraphQL query string

        Returns:
            Cached conversion data or None if not found
        """
        key = self._get_cache_key(query)

        with self._lock:
            if key in self._cache:
                # Move to end (most recently used)
                self._access_order.remove(key)
                self._access_order.append(key)
                self._hits += 1
                return self._cache[key]

            self._misses += 1
            return None

    def put(self, query: str, conversion_data: dict[str, Any]) -> None:
        """Cache query conversion data.

        Args:
            query: GraphQL query string
            conversion_data: Conversion metadata to cache
        """
        key = self._get_cache_key(query)

        with self._lock:
            # If already exists, update and move to end
            if key in self._cache:
                self._access_order.remove(key)
            # If cache is full, remove oldest entry
            elif len(self._cache) >= self.max_size:
                oldest_key = self._access_order.pop(0)
                del self._cache[oldest_key]

            self._cache[key] = conversion_data
            self._access_order.append(key)

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Dictionary with hits, misses, and hit rate
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0

            return {
                "hits": self._hits,
                "misses": self._misses,
                "total": total,
                "hit_rate": hit_rate,
                "size": len(self._cache),
            }

    def reset_stats(self) -> None:
        """Reset cache statistics."""
        with self._lock:
            self._hits = 0
            self._misses = 0


# Global cache instance
_query_conversion_cache = QueryConversionCache()


def get_cache() -> QueryConversionCache:
    """Get the global query conversion cache.

    Returns:
        Global cache instance
    """
    return _query_conversion_cache


def cache_query_conversion(
    query_string: str,
    operation_type: str,  # "query", "mutation", "subscription"
    operation_name: Optional[str] = None,
) -> dict[str, Any]:
    """Parse and cache a GraphQL query.

    Args:
        query_string: GraphQL query string
        operation_type: Type of operation
        operation_name: Optional operation name

    Returns:
        Conversion metadata including parsed document
    """
    cache = get_cache()

    # Check cache first
    cached = cache.get(query_string)
    if cached is not None:
        return cached

    # Parse query
    try:
        document = parse(query_string)
    except Exception as e:
        raise ValueError(f"Failed to parse query: {e}")

    # Build conversion metadata
    conversion_data = {
        "document": document,
        "operation_type": operation_type,
        "operation_name": operation_name,
        "query_length": len(query_string),
    }

    # Cache the result
    cache.put(query_string, conversion_data)

    return conversion_data


def get_cached_query_conversion(query_string: str) -> Optional[dict[str, Any]]:
    """Get cached query conversion if available.

    Args:
        query_string: GraphQL query string

    Returns:
        Conversion metadata or None if not cached
    """
    return get_cache().get(query_string)


def clear_query_cache() -> None:
    """Clear the query conversion cache."""
    get_cache().clear()


def get_cache_stats() -> dict[str, int]:
    """Get cache statistics.

    Returns:
        Dictionary with cache performance metrics
    """
    return get_cache().stats()
