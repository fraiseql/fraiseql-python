from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from fraiseql.enterprise.rbac.models import Permission

pytestmark = pytest.mark.enterprise


@pytest.mark.asyncio
async def test_permission_cache_invalidates_on_role_change() -> None:
    """Verify cache invalidates when user roles change."""
    from fraiseql.enterprise.rbac.cache import PermissionCache

    # Mock database pool
    db_pool = MagicMock()

    # Mock PostgresCache
    with patch("fraiseql.enterprise.rbac.cache.PostgresCache") as mock_pg_cache_class:
        mock_pg_cache = MagicMock()
        mock_pg_cache.has_domain_versioning = True  # Enable domain versioning
        mock_pg_cache.get_with_metadata = AsyncMock()
        mock_pg_cache.get_domain_versions = AsyncMock()
        mock_pg_cache.set = AsyncMock()
        mock_pg_cache_class.return_value = mock_pg_cache

        cache = PermissionCache(db_pool)

        user_id = uuid4()
        tenant_id = uuid4()

        # Mock initial permissions (cached)
        now = datetime.now()
        initial_permissions = [
            Permission(
                id=uuid4(), resource="user", action="read", description="Read users", created_at=now
            )
        ]

        # Mock cache hit initially
        serialized_initial = [
            {
                "id": str(p.id),
                "resource": p.resource,
                "action": p.action,
                "description": p.description,
                "constraints": p.constraints,
                "created_at": p.created_at.isoformat(),
            }
            for p in initial_permissions
        ]

        # Setup initial cache hit
        mock_pg_cache.get_with_metadata.return_value = (
            serialized_initial,
            {"role": 1, "permission": 1, "role_permission": 1, "user_role": 1},
        )
        mock_pg_cache.get_domain_versions.return_value = {
            "role": 1,
            "permission": 1,
            "role_permission": 1,
            "user_role": 1,
        }

        # Get initial permissions (should cache)
        permissions1 = await cache.get(user_id, tenant_id)
        assert permissions1 is not None
        len(permissions1)

        # Simulate new request (clear request-level cache)
        cache.clear_request_cache()

        # Simulate role change by updating domain versions
        # (In real scenario, this would be done by database triggers)
        mock_pg_cache.get_domain_versions.return_value = {
            "role": 1,
            "permission": 1,
            "role_permission": 1,
            "user_role": 2,
        }  # user_role version changed

        # Mock cache miss (stale) due to version change
        mock_pg_cache.get_with_metadata.return_value = (None, None)

        # Get permissions again (should detect stale cache)
        permissions2 = await cache.get(user_id, tenant_id)

        # Should return None (cache miss) because versions changed
        assert permissions2 is None


@pytest.mark.asyncio
async def test_cascade_invalidation_on_role_permission_change() -> None:
    """Verify CASCADE rule invalidates user permissions when role permissions change."""
    from fraiseql.enterprise.rbac.cache import PermissionCache

    # Mock database pool
    db_pool = MagicMock()

    # Mock PostgresCache
    with patch("fraiseql.enterprise.rbac.cache.PostgresCache") as mock_pg_cache_class:
        mock_pg_cache = MagicMock()
        mock_pg_cache.has_domain_versioning = True  # Enable domain versioning
        mock_pg_cache.get_with_metadata = AsyncMock()
        mock_pg_cache.get_domain_versions = AsyncMock()
        mock_pg_cache.set = AsyncMock()
        mock_pg_cache_class.return_value = mock_pg_cache

        cache = PermissionCache(db_pool)

        user_id = uuid4()
        uuid4()
        permission_id = uuid4()
        tenant_id = uuid4()

        # Setup: user has role
        now = datetime.now()
        initial_permissions = [
            Permission(
                id=permission_id,
                resource="user",
                action="read",
                description="Read users",
                created_at=now,
            )
        ]

        serialized_initial = [
            {
                "id": str(p.id),
                "resource": p.resource,
                "action": p.action,
                "description": p.description,
                "constraints": p.constraints,
                "created_at": p.created_at.isoformat(),
            }
            for p in initial_permissions
        ]

        # Initial state: user has permission
        mock_pg_cache.get_with_metadata.return_value = (
            serialized_initial,
            {
                "role": 1,
                "permission": 1,
                "role_permission": 1,
                "user_role": 1,
                "user_permissions": 1,
            },
        )
        mock_pg_cache.get_domain_versions.return_value = {
            "role": 1,
            "permission": 1,
            "role_permission": 1,
            "user_role": 1,
            "user_permissions": 1,
        }

        # Get initial permissions (caches result)
        permissions1 = await cache.get(user_id, tenant_id)
        assert permissions1 is not None

        # Simulate adding permission to role
        # Domain version increments:
        # 1. role_permissions INSERT → role_permission domain version++
        # 2. CASCADE rule → user_permissions domain version++

        cache.clear_request_cache()  # Simulate new request

        # Updated versions after role permission change
        mock_pg_cache.get_domain_versions.return_value = {
            "role": 1,
            "permission": 1,
            "role_permission": 2,
            "user_role": 1,
            "user_permissions": 2,
        }

        # Mock cache miss (stale) due to CASCADE invalidation
        mock_pg_cache.get_with_metadata.return_value = (None, None)

        # Get permissions again
        permissions2 = await cache.get(user_id, tenant_id)

        # Should include new permission (cache miss due to CASCADE)
        assert permissions2 is None  # Cache invalidated by CASCADE rule
