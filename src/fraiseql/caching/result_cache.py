"""Result caching layer for FraiseQL queries.

This module provides the main caching functionality with support for
different backends, automatic key generation, and cache invalidation.
"""

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol, TypeVar

from fraiseql.utils.annotations import wraps

from .cache_key import CacheKeyBuilder

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CacheBackend(Protocol):
    """Protocol for cache backends."""

    async def get(self, key: str) -> Any | None:
        """Get value from cache."""
        ...

    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Set value in cache with TTL."""
        ...

    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        ...

    async def delete_pattern(self, pattern: str) -> int:
        """Delete keys matching pattern."""
        ...


@dataclass
class CacheConfig:
    """Configuration for result caching."""

    enabled: bool = True
    default_ttl: int = 300  # 5 minutes
    max_ttl: int = 3600  # 1 hour
    cache_errors: bool = False
    key_prefix: str = "fraiseql"


@dataclass
class CacheStats:
    """Cache performance statistics."""

    hits: int = 0
    misses: int = 0
    errors: int = 0

    @property
    def total(self) -> int:
        """Total cache operations."""
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        """Cache hit rate percentage."""
        if self.total == 0:
            return 0.0
        return (self.hits / self.total) * 100


class ResultCache:
    """Main result caching implementation."""

    def __init__(
        self,
        backend: CacheBackend,
        config: CacheConfig | None = None,
    ) -> None:
        """Initialize result cache.

        Args:
            backend: Cache backend to use
            config: Cache configuration
        """
        self.backend = backend
        self.config = config or CacheConfig()
        self.key_builder = CacheKeyBuilder(prefix=self.config.key_prefix)
        self.stats = CacheStats()

    async def get_or_set(
        self,
        key: str,
        func: Callable[[], Awaitable[T]],
        ttl: int | None = None,
    ) -> T:
        """Get from cache or execute function and cache result.

        Args:
            key: Cache key
            func: Function to execute if cache miss
            ttl: Time-to-live in seconds

        Returns:
            Cached or fresh result
        """
        if not self.config.enabled:
            return await func()

        # Try to get from cache
        try:
            cached = await self.backend.get(key)
            if cached is not None:
                self.stats.hits += 1
                logger.debug(f"Cache hit for key: {key}")
                return cached
        except Exception as e:
            self.stats.errors += 1
            logger.warning(f"Cache get error for key {key}: {e}")
            if not self.config.cache_errors:
                return await func()

        # Cache miss - execute function
        self.stats.misses += 1
        logger.debug(f"Cache miss for key: {key}")

        try:
            result = await func()
        except Exception:
            # Don't cache errors unless configured to
            raise

        # Store in cache
        try:
            ttl = min(ttl or self.config.default_ttl, self.config.max_ttl)
            await self.backend.set(key, result, ttl=ttl)
            logger.debug(f"Cached result for key: {key} with TTL: {ttl}")
        except Exception as e:
            self.stats.errors += 1
            logger.warning(f"Cache set error for key {key}: {e}")

        return result

    async def invalidate(self, key: str) -> None:
        """Invalidate a specific cache key.

        Args:
            key: Cache key to invalidate
        """
        try:
            deleted = await self.backend.delete(key)
            if deleted:
                logger.info(f"Invalidated cache key: {key}")
        except Exception as e:
            logger.error(f"Failed to invalidate key {key}: {e}")

    async def invalidate_pattern(self, pattern: str) -> None:
        """Invalidate all keys matching a pattern.

        Args:
            pattern: Pattern to match (e.g., "users:*")
        """
        try:
            count = await self.backend.delete_pattern(pattern)
            logger.info(f"Invalidated {count} cache keys matching: {pattern}")
        except Exception as e:
            logger.error(f"Failed to invalidate pattern {pattern}: {e}")

    def get_stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            Current cache statistics
        """
        return self.stats

    def reset_stats(self) -> None:
        """Reset cache statistics."""
        self.stats = CacheStats()

    async def warm_cache(
        self,
        queries: list[tuple[str, dict[str, Any]]],
        query_func: Callable,
    ) -> None:
        """Warm cache with specific queries.

        Args:
            queries: List of (query_name, filters) tuples
            query_func: Function to execute queries
        """
        for query_name, filters in queries:
            key = self.key_builder.build_key(query_name, filters=filters)
            try:
                result = await query_func(query_name, filters)
                await self.backend.set(key, result, ttl=self.config.default_ttl)
                logger.info(f"Warmed cache for {query_name} with filters {filters}")
            except Exception as e:
                logger.error(f"Failed to warm cache for {query_name}: {e}")


def cached_query(
    cache: ResultCache,
    ttl: int | None = None,
    key_func: Callable[..., str] | None = None,
) -> Callable:
    """Decorator for caching query results.

    Args:
        cache: ResultCache instance
        ttl: Time-to-live in seconds
        key_func: Custom key generation function

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Check for skip_cache parameter
            skip_cache = kwargs.pop("skip_cache", False)
            if skip_cache:
                return await func(*args, **kwargs)

            # Generate cache key
            if key_func:
                cache_key = key_func(**kwargs)
            else:
                # Auto-generate key from function name and args
                key_parts = [func.__name__]
                for arg in args:
                    key_parts.append(str(arg))
                for k, v in sorted(kwargs.items()):
                    key_parts.append(f"{k}:{v}")
                cache_key = ":".join(key_parts)

            # Use cache
            return await cache.get_or_set(
                key=cache_key,
                func=lambda: func(*args, **kwargs),
                ttl=ttl,
            )

        return wrapper

    return decorator
