"""PostgreSQL cache backend for FraiseQL.

This module provides a PostgreSQL-based cache backend implementation
using UNLOGGED tables for high-performance caching without WAL overhead.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


class PostgresCacheError(Exception):
    """Raised when PostgreSQL cache operation fails."""


class PostgresCache:
    """PostgreSQL-based cache backend using UNLOGGED tables.

    Uses UNLOGGED tables for maximum performance - data is not written to WAL,
    making cache operations as fast as in-memory solutions while providing
    persistence and shared access across multiple instances.

    Note: UNLOGGED tables are cleared on crash/restart, which is acceptable
    for cache data that can be regenerated.
    """

    def __init__(
        self,
        connection_pool: AsyncConnectionPool,
        table_name: str = "fraiseql_cache",
        auto_initialize: bool = True,
    ) -> None:
        """Initialize PostgreSQL cache.

        Args:
            connection_pool: psycopg connection pool
            table_name: Name of the cache table (default: fraiseql_cache), which
                may be schema-qualified (``"app.fraiseql_cache"``)
            auto_initialize: Whether the first operation creates the table if
                missing. With False, create it yourself or call ``initialize()``.
        """
        self.pool = connection_pool
        self.table_name = table_name
        self.auto_initialize = auto_initialize
        self._initialized = False

        # pg_fraiseql_cache extension detection
        self.has_domain_versioning: bool = False
        self.extension_version: str | None = None

    async def initialize(self) -> None:
        """Create the cache table (if missing) and detect pg_fraiseql_cache.

        With ``auto_initialize=True`` (the default) the first operation does this;
        with ``auto_initialize=False`` the first operation only detects the
        extension, and the table must exist or be created by calling this.
        """
        await self._setup(create_table=True)

    async def _ensure_initialized(self) -> None:
        """Run the first-use setup once: the table (if auto_initialize) and detection."""
        if self._initialized:
            return
        await self._setup(create_table=self.auto_initialize)

    async def _setup(self, *, create_table: bool) -> None:
        async with self.pool.connection() as conn, conn.cursor() as cur:
            if create_table:
                await self._create_table(cur)
            await self._detect_extension(cur)
            await conn.commit()

        self._initialized = True
        logger.info("PostgreSQL cache table '%s' initialized", self.table_name)

    async def _create_table(self, cur: Any) -> None:
        # Create UNLOGGED table for cache
        # UNLOGGED = no WAL = faster writes, but data lost on crash (acceptable for cache)
        await cur.execute(
            f"""
            CREATE UNLOGGED TABLE IF NOT EXISTS {self.table_name} (
                cache_key TEXT PRIMARY KEY,
                cache_value JSONB NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL
            )
        """
        )

        # Index on expiry for efficient cleanup. An index takes the table's
        # schema, so its name can't be schema-qualified.
        index_name = f"{self.table_name.rsplit('.', 1)[-1]}_expires_idx"
        await cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {index_name}
            ON {self.table_name} (expires_at)
        """
        )

    async def _detect_extension(self, cur: Any) -> None:
        """Set has_domain_versioning / extension_version from pg_extension."""
        # Detect pg_fraiseql_cache extension
        try:
            await cur.execute(
                """
                SELECT extversion
                FROM pg_extension
                WHERE extname = 'pg_fraiseql_cache'
            """
            )
            result = await cur.fetchone()

            if result:
                self.has_domain_versioning = True
                self.extension_version = result[0]
                logger.info("✓ Detected pg_fraiseql_cache v%s", self.extension_version)
            else:
                self.has_domain_versioning = False
                self.extension_version = None
                logger.info("pg_fraiseql_cache not installed, using TTL-only caching")
        except psycopg.Error as e:
            # If extension detection fails (e.g., permissions issue), fall back gracefully
            self.has_domain_versioning = False
            self.extension_version = None
            logger.warning(
                "Failed to detect pg_fraiseql_cache extension: %s. "
                "Falling back to TTL-only caching.",
                e,
            )

    async def get(self, key: str) -> Any | None:
        """Get value from cache, unwrapping metadata if present.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found or expired.
            If value has metadata structure, returns only the result.

        Raises:
            PostgresCacheError: If database operation fails
        """
        try:
            await self._ensure_initialized()

            async with self.pool.connection() as conn, conn.cursor() as cur:
                # Get value and check expiry in one query
                await cur.execute(
                    f"""
                    SELECT cache_value
                    FROM {self.table_name}
                    WHERE cache_key = %s
                      AND expires_at > NOW()
                    """,
                    (key,),
                )

                result = await cur.fetchone()
                if result is None:
                    return None

                cache_value = result[0]  # JSONB is automatically deserialized

                # Unwrap metadata if present
                if (
                    isinstance(cache_value, dict)
                    and "result" in cache_value
                    and "versions" in cache_value
                ):
                    return cache_value["result"]

                # Return value as-is (backward compatibility)
                return cache_value

        except psycopg.Error as e:
            logger.error("Failed to get cache key '%s': %s", key, e)
            raise PostgresCacheError(f"Failed to get cache key: {e}") from e

    async def get_with_metadata(self, key: str) -> tuple[Any | None, dict[str, int] | None]:
        """Get value from cache with version metadata.

        Args:
            key: Cache key

        Returns:
            Tuple of (result, versions) where:
            - result: The cached value (unwrapped)
            - versions: Domain version dict, or None if not available

        Raises:
            PostgresCacheError: If database operation fails
        """
        try:
            await self._ensure_initialized()

            async with self.pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    f"""
                    SELECT cache_value
                    FROM {self.table_name}
                    WHERE cache_key = %s
                      AND expires_at > NOW()
                    """,
                    (key,),
                )

                result = await cur.fetchone()
                if result is None:
                    return None, None

                cache_value = result[0]

                # Check if value has metadata structure
                if (
                    isinstance(cache_value, dict)
                    and "result" in cache_value
                    and "versions" in cache_value
                ):
                    return cache_value["result"], cache_value["versions"]

                # Old format without metadata
                return cache_value, None

        except psycopg.Error as e:
            logger.error("Failed to get cache key '%s': %s", key, e)
            raise PostgresCacheError(f"Failed to get cache key: {e}") from e

    async def get_domain_versions(self, tenant_id: Any, domains: list[str]) -> dict[str, int]:
        """Get current domain versions from pg_fraiseql_cache extension.

        Args:
            tenant_id: Tenant ID for version lookup
            domains: List of domain names to get versions for

        Returns:
            Dictionary mapping domain names to version numbers.
            If extension is not available, returns empty dict.

        Raises:
            PostgresCacheError: If database operation fails
        """
        # Early return for empty domains list
        if not domains:
            return {}

        try:
            await self._ensure_initialized()

            # If extension not available, return empty dict
            if not self.has_domain_versioning:
                return {}

            async with self.pool.connection() as conn, conn.cursor() as cur:
                # Query fraiseql_cache.domain_version table
                await cur.execute(
                    """
                    SELECT domain, version
                    FROM fraiseql_cache.domain_version
                    WHERE tenant_id = %s AND domain = ANY(%s)
                    """,
                    (tenant_id, domains),
                )

                rows = await cur.fetchall()

                # Build version dict
                versions = {row[0]: row[1] for row in rows}

                logger.debug(
                    "Retrieved %d domain versions for tenant %s",
                    len(versions),
                    tenant_id,
                )

                return versions

        except psycopg.Error as e:
            logger.error("Failed to get domain versions: %s", e)
            raise PostgresCacheError(f"Failed to get domain versions: {e}") from e

    async def set(
        self, key: str, value: Any, ttl: int, versions: dict[str, int] | None = None
    ) -> None:
        """Set value in cache with TTL and optional version metadata.

        Args:
            key: Cache key
            value: Value to cache (must be JSON-serializable)
            ttl: Time-to-live in seconds
            versions: Optional domain version metadata (for pg_fraiseql_cache integration)

        Raises:
            ValueError: If value cannot be serialized
            PostgresCacheError: If database operation fails

        Note:
            When pg_fraiseql_cache extension is enabled AND versions are provided,
            the value is wrapped with metadata structure:
            {
                "result": value,
                "versions": {domain: version, ...},
                "cached_at": timestamp
            }
        """
        try:
            await self._ensure_initialized()

            # Wrap value with metadata if extension is enabled and versions provided
            if self.has_domain_versioning and versions:
                cache_value = {
                    "result": value,
                    "versions": versions,
                    "cached_at": datetime.now(UTC).isoformat(),
                }
            else:
                # Store value directly (backward compatibility)
                cache_value = value

            # Validate that value is JSON-serializable
            try:
                json.dumps(cache_value)
            except (TypeError, ValueError) as e:
                raise ValueError(f"Failed to serialize value: {e}") from e

            expires_at = datetime.now(UTC) + timedelta(seconds=ttl)

            async with self.pool.connection() as conn, conn.cursor() as cur:
                # UPSERT using ON CONFLICT
                await cur.execute(
                    f"""
                    INSERT INTO {self.table_name} (cache_key, cache_value, expires_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (cache_key)
                    DO UPDATE SET
                        cache_value = EXCLUDED.cache_value,
                        expires_at = EXCLUDED.expires_at
                    """,
                    (key, json.dumps(cache_value), expires_at),
                )
                await conn.commit()

        except psycopg.Error as e:
            logger.error("Failed to set cache key '%s': %s", key, e)
            raise PostgresCacheError(f"Failed to set cache key: {e}") from e

    async def delete(self, key: str) -> bool:
        """Delete a key from cache.

        Args:
            key: Cache key

        Returns:
            True if key was deleted, False if key didn't exist

        Raises:
            PostgresCacheError: If database operation fails
        """
        try:
            await self._ensure_initialized()

            async with self.pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    f"DELETE FROM {self.table_name} WHERE cache_key = %s",
                    (key,),
                )
                await conn.commit()
                return cur.rowcount > 0

        except psycopg.Error as e:
            logger.error("Failed to delete cache key '%s': %s", key, e)
            raise PostgresCacheError(f"Failed to delete cache key: {e}") from e

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern.

        Args:
            pattern: SQL LIKE pattern (e.g., "user:%")

        Returns:
            Number of keys deleted

        Raises:
            PostgresCacheError: If database operation fails
        """
        try:
            await self._ensure_initialized()

            async with self.pool.connection() as conn, conn.cursor() as cur:
                # Convert Redis-style pattern to SQL LIKE pattern
                # Redis uses * for wildcard, SQL uses %
                sql_pattern = pattern.replace("*", "%")

                await cur.execute(
                    f"DELETE FROM {self.table_name} WHERE cache_key LIKE %s",
                    (sql_pattern,),
                )
                await conn.commit()
                return cur.rowcount

        except psycopg.Error as e:
            logger.error("Failed to delete pattern '%s': %s", pattern, e)
            raise PostgresCacheError(f"Failed to delete pattern: {e}") from e

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache and is not expired.

        Args:
            key: Cache key

        Returns:
            True if key exists and is not expired, False otherwise

        Raises:
            PostgresCacheError: If database operation fails
        """
        try:
            await self._ensure_initialized()

            async with self.pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    f"""
                    SELECT 1
                    FROM {self.table_name}
                    WHERE cache_key = %s
                      AND expires_at > NOW()
                    """,
                    (key,),
                )

                return await cur.fetchone() is not None

        except psycopg.Error as e:
            logger.error("Failed to check cache key '%s': %s", key, e)
            raise PostgresCacheError(f"Failed to check cache key: {e}") from e

    async def ping(self) -> bool:
        """Check if PostgreSQL connection is alive.

        The first ping also runs the first-use setup (see ``initialize``), so a
        ping at startup detects pg_fraiseql_cache.

        Returns:
            True if connection is alive

        Raises:
            PostgresCacheError: If connection check fails
        """
        try:
            await self._ensure_initialized()

            async with self.pool.connection() as conn, conn.cursor() as cur:
                await cur.execute("SELECT 1")
                result = await cur.fetchone()
                return result is not None

        except psycopg.Error as e:
            logger.error("Failed to ping PostgreSQL: %s", e)
            raise PostgresCacheError(f"Failed to ping PostgreSQL: {e}") from e

    async def cleanup_expired(self) -> int:
        """Remove expired cache entries.

        This should be called periodically (e.g., via a background task)
        to prevent the cache table from growing indefinitely.

        Returns:
            Number of expired entries removed

        Raises:
            PostgresCacheError: If cleanup operation fails
        """
        try:
            await self._ensure_initialized()

            async with self.pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    f"DELETE FROM {self.table_name} WHERE expires_at <= NOW()",
                )
                await conn.commit()
                cleaned = cur.rowcount

                if cleaned > 0:
                    logger.info("Cleaned %s expired cache entries", cleaned)

                return cleaned

        except psycopg.Error as e:
            logger.error("Failed to cleanup expired entries: %s", e)
            raise PostgresCacheError(f"Failed to cleanup expired entries: {e}") from e

    async def clear_all(self) -> int:
        """Clear all cache entries.

        Warning: This removes ALL cached data.

        Returns:
            Number of entries removed

        Raises:
            PostgresCacheError: If clear operation fails
        """
        try:
            await self._ensure_initialized()

            async with self.pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(f"DELETE FROM {self.table_name}")
                await conn.commit()
                return cur.rowcount

        except psycopg.Error as e:
            logger.error("Failed to clear cache: %s", e)
            raise PostgresCacheError(f"Failed to clear cache: {e}") from e

    async def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats (total_entries, expired_entries, table_size_bytes)

        Raises:
            PostgresCacheError: If stats query fails
        """
        try:
            await self._ensure_initialized()

            async with self.pool.connection() as conn, conn.cursor() as cur:
                # Get total entries
                await cur.execute(
                    f"SELECT COUNT(*) FROM {self.table_name}",
                )
                result = await cur.fetchone()
                total = result[0] if result else 0

                # Get expired entries (not yet cleaned)
                await cur.execute(
                    f"SELECT COUNT(*) FROM {self.table_name} WHERE expires_at <= NOW()",
                )
                result = await cur.fetchone()
                expired = result[0] if result else 0

                # Get table size
                await cur.execute(
                    """
                    SELECT pg_total_relation_size(%s)
                    """,
                    (self.table_name,),
                )
                result = await cur.fetchone()
                size_bytes = result[0] if result else 0

                return {
                    "total_entries": total,
                    "expired_entries": expired,
                    "active_entries": total - expired,
                    "table_size_bytes": size_bytes,
                }

        except psycopg.Error as e:
            logger.error("Failed to get cache stats: %s", e)
            raise PostgresCacheError(f"Failed to get cache stats: {e}") from e

    async def register_cascade_rule(
        self, source_domain: str, target_domain: str, rule_type: str = "invalidate"
    ) -> bool:
        """Register CASCADE rule for automatic cache invalidation.

        When source_domain data changes, target_domain caches are invalidated.

        Args:
            source_domain: Domain name that triggers invalidation
            target_domain: Domain name to invalidate
            rule_type: Either 'invalidate' or 'notify' (default: 'invalidate')

        Returns:
            True if the rule was registered, False if it was skipped because
            pg_fraiseql_cache isn't installed

        Raises:
            PostgresCacheError: If database operation fails

        Example:
            # When user data changes, invalidate post caches
            await cache.register_cascade_rule("user", "post")
        """
        try:
            await self._ensure_initialized()

            # CASCADE rules require pg_fraiseql_cache extension
            if not self.has_domain_versioning:
                logger.warning(
                    "CASCADE rules require pg_fraiseql_cache extension. "
                    "Skipping registration of %s -> %s",
                    source_domain,
                    target_domain,
                )
                return False

            async with self.pool.connection() as conn, conn.cursor() as cur:
                # Insert CASCADE rule (using ON CONFLICT for idempotency)
                await cur.execute(
                    """
                    INSERT INTO fraiseql_cache.cascade_rules
                        (source_domain, target_domain, rule_type)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_domain, target_domain)
                    DO UPDATE SET rule_type = EXCLUDED.rule_type
                    """,
                    (source_domain, target_domain, rule_type),
                )
                await conn.commit()

                logger.info(
                    "Registered CASCADE rule: %s -> %s (%s)",
                    source_domain,
                    target_domain,
                    rule_type,
                )
                return True

        except psycopg.Error as e:
            logger.error(
                "Failed to register CASCADE rule %s -> %s: %s",
                source_domain,
                target_domain,
                e,
            )
            raise PostgresCacheError(f"Failed to register CASCADE rule: {e}") from e

    async def clear_cascade_rules(self, source_domain: str | None = None) -> int:
        """Clear CASCADE rules.

        Args:
            source_domain: If provided, only clear rules for this source domain.
                         If None, clear all CASCADE rules.

        Returns:
            Number of rules deleted

        Raises:
            PostgresCacheError: If extension not available or database operation fails
        """
        try:
            await self._ensure_initialized()

            # CASCADE rules require pg_fraiseql_cache extension
            if not self.has_domain_versioning:
                logger.warning(
                    "CASCADE rules require pg_fraiseql_cache extension. Nothing to clear."
                )
                return 0

            async with self.pool.connection() as conn, conn.cursor() as cur:
                if source_domain:
                    # Clear rules for specific source domain
                    await cur.execute(
                        "DELETE FROM fraiseql_cache.cascade_rules WHERE source_domain = %s",
                        (source_domain,),
                    )
                else:
                    # Clear all rules
                    await cur.execute("DELETE FROM fraiseql_cache.cascade_rules")

                await conn.commit()
                deleted = cur.rowcount

                if deleted > 0:
                    logger.info("Cleared %d CASCADE rules", deleted)

                return deleted

        except psycopg.Error as e:
            logger.error("Failed to clear CASCADE rules: %s", e)
            raise PostgresCacheError(f"Failed to clear CASCADE rules: {e}") from e

    async def setup_table_trigger(
        self,
        table_name: str,
        domain_name: str | None = None,
        tenant_column: str = "tenant_id",
    ) -> None:
        """Setup automatic cache invalidation trigger for a table.

        Calls fraiseql_cache.setup_table_invalidation() to create triggers
        that automatically increment domain versions when table data changes.

        Args:
            table_name: Name of the table to watch (e.g., "users", "public.users")
            domain_name: Custom domain name (defaults to derived from table name)
            tenant_column: Name of tenant ID column (default: "tenant_id")

        Raises:
            PostgresCacheError: If extension not available or database operation fails

        Example:
            # Setup trigger for users table
            await cache.setup_table_trigger("users")

            # Setup with custom domain name
            await cache.setup_table_trigger("tb_users", domain_name="user")
        """
        try:
            await self._ensure_initialized()

            # Trigger setup requires pg_fraiseql_cache extension
            if not self.has_domain_versioning:
                logger.warning(
                    "Trigger setup requires pg_fraiseql_cache extension. "
                    "Skipping setup for table %s",
                    table_name,
                )
                return

            async with self.pool.connection() as conn, conn.cursor() as cur:
                # Call extension's setup function
                if domain_name:
                    await cur.execute(
                        "SELECT fraiseql_cache.setup_table_invalidation(%s, %s, %s)",
                        (table_name, domain_name, tenant_column),
                    )
                else:
                    await cur.execute(
                        "SELECT fraiseql_cache.setup_table_invalidation(%s, NULL, %s)",
                        (table_name, tenant_column),
                    )

                await conn.commit()

                logger.info(
                    "Setup cache invalidation trigger for table '%s' (domain: %s)",
                    table_name,
                    domain_name or "auto-derived",
                )

        except psycopg.Error as e:
            logger.error("Failed to setup trigger for table '%s': %s", table_name, e)
            raise PostgresCacheError(f"Failed to setup trigger for table {table_name}: {e}") from e
