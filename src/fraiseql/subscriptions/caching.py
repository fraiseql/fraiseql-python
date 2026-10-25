"""Caching for subscription results."""

import asyncio
import hashlib
import logging
import pickle
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Callable

from graphql import GraphQLResolveInfo

from fraiseql.utils.annotations import wraps

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached subscription result."""

    value: Any
    timestamp: float
    ttl: float

    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        return time.time() - self.timestamp > self.ttl


class SubscriptionCache:
    """Caches subscription results to reduce load."""

    def __init__(self) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start cache cleanup task."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Stop cache cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)

    def _make_key(self, func_name: str, args: dict[str, Any]) -> str:
        """Generate cache key from function and arguments."""
        key_data = {"func": func_name, "args": args}
        key_bytes = pickle.dumps(key_data, protocol=pickle.HIGHEST_PROTOCOL)
        return hashlib.sha256(key_bytes).hexdigest()

    async def get_or_generate(
        self,
        key: str,
        generator: AsyncGenerator,
        ttl: float,
    ) -> AsyncGenerator[Any]:
        """Get cached values or generate new ones."""
        # Check cache
        if key in self._cache:
            entry = self._cache[key]
            if not entry.is_expired():
                # Return cached value
                yield entry.value
                return

        # Ensure only one generator per key
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()

        async with self._locks[key]:
            # Double-check cache
            if key in self._cache and not self._cache[key].is_expired():
                yield self._cache[key].value
                return

            # Generate new value
            async for value in generator:
                # Cache the value
                self._cache[key] = CacheEntry(value=value, timestamp=time.time(), ttl=ttl)
                yield value

    async def _cleanup_loop(self) -> None:
        """Periodically clean expired entries."""
        while True:
            try:
                await asyncio.sleep(60)  # Every minute

                expired = []
                for key, entry in self._cache.items():
                    if entry.is_expired():
                        expired.append(key)

                for key in expired:
                    del self._cache[key]
                    if key in self._locks:
                        del self._locks[key]

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Cache cleanup error")


def cache(ttl: float = 5.0) -> Callable:
    """Decorator to cache subscription results.

    Usage:
        @subscription
        @cache(ttl=10)  # Cache for 10 seconds
        async def expensive_stats(info):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        func._cache_ttl = ttl

        @wraps(func)
        async def wrapper(info: GraphQLResolveInfo, **kwargs: Any) -> Any:
            # Get cache from context
            sub_cache = None
            if hasattr(info, "context") and info.context:
                sub_cache = info.context.get("subscription_cache")

            if not sub_cache:
                # No cache, execute directly
                async for value in func(info, **kwargs):
                    yield value
                return

            # Generate cache key
            cache_key = sub_cache._make_key(func.__name__, kwargs)

            # Use cached values or generate
            generator = func(info, **kwargs)
            async for value in sub_cache.get_or_generate(cache_key, generator, ttl):
                yield value

        return wrapper

    return decorator
