"""RBAC Permission Cache

PostgreSQL-native permission caching with 2-layer architecture:
- Layer 1: Request-level in-memory cache (fastest, same request only)
- Layer 2: PostgreSQL UNLOGGED table (0.1-0.3ms, shared across instances)

Supports automatic invalidation via domain versioning when pg_fraiseql_cache
extension is available.
"""

import logging
from datetime import timedelta
from typing import Optional
from uuid import UUID

from psycopg_pool import AsyncConnectionPool
from pydantic import ValidationError

from fraiseql.caching import PostgresCache

from .models import Permission

logger = logging.getLogger(__name__)


class PermissionCache:
    """2-layer permission cache (request-level + PostgreSQL).

    Architecture:
    - Layer 1: Request-level in-memory dict (instant)
    - Layer 2: PostgreSQL UNLOGGED table (0.1-0.3ms)
    - Automatic invalidation via domain versioning (requires pg_fraiseql_cache)
    """

    def __init__(self, db_pool: AsyncConnectionPool) -> None:
        """Initialize permission cache.

        Args:
            db_pool: PostgreSQL connection pool
        """
        self.pg_cache = PostgresCache(db_pool, table_name="fraiseql_cache")
        self._request_cache: dict[str, list[Permission]] = {}
        self._cache_ttl = timedelta(minutes=5)  # 5 minute TTL

        # RBAC domains for version checking
        self._rbac_domains = ["role", "permission", "role_permission", "user_role"]

    def _make_key(self, user_id: UUID, tenant_id: Optional[UUID]) -> str:
        """Generate cache key for user permissions.

        Format: rbac:permissions:{user_id}:{tenant_id}
        """
        tenant_str = str(tenant_id) if tenant_id else "global"
        return f"rbac:permissions:{user_id}:{tenant_str}"

    async def get(self, user_id: UUID, tenant_id: Optional[UUID]) -> Optional[list[Permission]]:
        """Get cached permissions with version checking.

        Flow:
        1. Check request-level cache (instant)
        2. Check PostgreSQL cache (0.1-0.3ms)
        3. If found, verify domain versions haven't changed
        4. If stale, return None (caller will recompute)

        Args:
            user_id: User ID
            tenant_id: Tenant ID (None for global)

        Returns:
            List of permissions or None if not cached/stale
        """
        key = self._make_key(user_id, tenant_id)

        # Try request-level cache first (fastest)
        if key in self._request_cache:
            logger.debug("Permission cache HIT (request-level): %s", key)
            return self._request_cache[key]

        # Try PostgreSQL cache with version checking
        result, cached_versions = await self.pg_cache.get_with_metadata(key)

        if result is None:
            logger.debug("Permission cache MISS: %s", key)
            return None

        # Verify domain versions if extension is available
        if self.pg_cache.has_domain_versioning and cached_versions:
            current_versions = await self.pg_cache.get_domain_versions(
                tenant_id or "global", self._rbac_domains
            )

            # Check if any domain version changed
            for domain in self._rbac_domains:
                cached_version = cached_versions.get(domain, 0)
                current_version = current_versions.get(domain, 0)

                if current_version != cached_version:
                    logger.debug(
                        "Permission cache STALE (domain %s changed: %d → %d): %s",
                        domain,
                        cached_version,
                        current_version,
                        key,
                    )
                    return None

        # Deserialize to Permission objects. A row that doesn't validate (written by an
        # older version, or altered) is a miss: the caller recomputes and overwrites it.
        try:
            permissions = [Permission.model_validate(p) for p in result]
        except (ValidationError, TypeError) as e:
            logger.warning("Ignoring invalid cached permissions for %s: %s", key, e)
            return None

        # Populate request cache
        self._request_cache[key] = permissions

        logger.debug("Permission cache HIT (PostgreSQL): %s", key)
        return permissions

    async def set(
        self, user_id: UUID, tenant_id: Optional[UUID], permissions: list[Permission]
    ) -> None:
        """Cache permissions with domain version metadata.

        Stores in both request-level and PostgreSQL cache.
        Attaches domain versions for automatic invalidation detection.

        Args:
            user_id: User ID
            tenant_id: Tenant ID (None for global)
            permissions: List of permissions to cache
        """
        key = self._make_key(user_id, tenant_id)

        # Serialize permissions (every field, so get() can validate them back)
        serialized = [p.model_dump(mode="json") for p in permissions]

        # Get current domain versions
        versions = None
        if self.pg_cache.has_domain_versioning:
            versions = await self.pg_cache.get_domain_versions(
                tenant_id or "global", self._rbac_domains
            )

        # Store in PostgreSQL cache with versions
        await self.pg_cache.set(
            key=key, value=serialized, ttl=int(self._cache_ttl.total_seconds()), versions=versions
        )

        # Store in request cache
        self._request_cache[key] = permissions

        logger.debug("Cached permissions for user %s (versions: %s)", user_id, versions)

    def clear_request_cache(self) -> None:
        """Clear request-level cache (called at end of request)."""
        self._request_cache.clear()

    async def invalidate_user(self, user_id: UUID, tenant_id: Optional[UUID] = None) -> None:
        """Manually invalidate cache for user.

        Note: With domain versioning, manual invalidation is rarely needed
        as cache is automatically invalidated when RBAC tables change.

        Args:
            user_id: User ID
            tenant_id: Tenant ID (None for global)
        """
        key = self._make_key(user_id, tenant_id)
        self._request_cache.pop(key, None)
        await self.pg_cache.delete(key)
        logger.debug("Invalidated permissions cache for user %s", user_id)

    async def invalidate_all(self) -> None:
        """Invalidate all cached permissions.

        Useful for testing or emergency cache clearing.
        """
        self._request_cache.clear()
        await self.pg_cache.delete_pattern("rbac:permissions:*")
        logger.info("Invalidated all permission caches")

    async def get_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with cache stats (hits, misses, size, etc.)
        """
        pg_stats = await self.pg_cache.get_stats()

        return {
            "request_cache_size": len(self._request_cache),
            "postgres_cache_total": pg_stats.get("total_entries", 0),
            "postgres_cache_active": pg_stats.get("active_entries", 0),
            "postgres_cache_size_bytes": pg_stats.get("table_size_bytes", 0),
            "has_domain_versioning": self.pg_cache.has_domain_versioning,
            "cache_ttl_seconds": int(self._cache_ttl.total_seconds()),
        }
