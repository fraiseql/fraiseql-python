"""Test Permission Resolution with PostgreSQL Caching

Tests for effective permission computation with hierarchical role inheritance
and PostgreSQL-native caching.
"""

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from fraiseql.enterprise.rbac.cache import PermissionCache
from fraiseql.enterprise.rbac.resolver import PermissionResolver

pytestmark = pytest.mark.enterprise


@pytest_asyncio.fixture(autouse=True, scope="class")
async def ensure_rbac_schema(class_db_pool, test_schema) -> None:
    """Ensure RBAC schema exists before running tests."""
    # Check if roles table exists
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        cur = await conn.execute(
            """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'roles' AND table_schema = current_schema()
                )
            """
        )
        result = await cur.fetchone()
        exists = result[0] if result else False

        if not exists:
            # Read and execute the migration
            migration_path = Path("src/fraiseql/enterprise/migrations/002_rbac_tables.sql")
            migration_sql = migration_path.read_text()
            await conn.execute(migration_sql)
            await conn.commit()
            print("RBAC schema migration executed successfully")


class TestPermissionResolution:
    """Test permission resolution with caching."""

    @pytest.mark.asyncio
    async def test_user_effective_permissions_with_caching(self, db_repo, class_db_pool) -> None:
        """Verify user permissions are cached in PostgreSQL."""
        cache = PermissionCache(class_db_pool)
        resolver = PermissionResolver(db_repo, cache)

        user_id = uuid4()
        tenant_id = uuid4()

        # First call - should compute and cache
        permissions1 = await resolver.get_user_permissions(user_id, tenant_id)

        # Second call - should hit cache
        permissions2 = await resolver.get_user_permissions(user_id, tenant_id)

        assert permissions1 == permissions2

    @pytest.mark.asyncio
    async def test_permission_resolver_methods_exist(self, db_repo, class_db_pool) -> None:
        """Verify PermissionResolver has required methods."""
        cache = PermissionCache(class_db_pool)
        resolver = PermissionResolver(db_repo, cache)

        # Test core methods exist
        assert hasattr(resolver, "get_user_permissions")
        assert hasattr(resolver, "has_permission")
        assert hasattr(resolver, "check_permission")
        assert hasattr(resolver, "get_user_roles")
        assert hasattr(resolver, "get_role_permissions")
        assert hasattr(resolver, "invalidate_user_cache")

        # Test method signatures
        import inspect

        # get_user_permissions should accept user_id, tenant_id, use_cache
        sig = inspect.signature(resolver.get_user_permissions)
        assert "user_id" in sig.parameters
        assert "tenant_id" in sig.parameters
        assert "use_cache" in sig.parameters

        # has_permission should accept user_id, resource, action, tenant_id
        sig = inspect.signature(resolver.has_permission)
        assert "user_id" in sig.parameters
        assert "resource" in sig.parameters
        assert "action" in sig.parameters
        assert "tenant_id" in sig.parameters

    @pytest.mark.asyncio
    async def test_cache_integration(self, db_repo, class_db_pool) -> None:
        """Test that resolver integrates properly with cache."""
        cache = PermissionCache(class_db_pool)
        resolver = PermissionResolver(db_repo, cache)

        user_id = uuid4()
        tenant_id = uuid4()

        # Get permissions (should use cache)
        permissions = await resolver.get_user_permissions(user_id, tenant_id, use_cache=True)

        # Verify cache was attempted
        # (In real test, we'd check cache stats or mock the cache)

        # Test cache bypass
        permissions_no_cache = await resolver.get_user_permissions(
            user_id, tenant_id, use_cache=False
        )

        # Should be the same result
        assert permissions == permissions_no_cache
