"""Permission Resolver with PostgreSQL Caching

Resolves effective permissions for users with hierarchical role inheritance.
Uses 2-layer caching (request-level + PostgreSQL) with automatic invalidation.

**IMPORTANT**: This module handles permission RESOLUTION (computing which permissions
a user has), not permission ENFORCEMENT (blocking unauthorized actions). For enforcement,
see the directives module and middleware components.

**Testing Status (v1.9.7)**:
- ✅ Permission resolution: Fully tested (52 tests)
- ✅ Role hierarchy: Tested and working
- ✅ Caching: Tested and working
- ⚠️ Enforcement verification: Tests pending (Issue #225)
  - Positive tests exist (authorized users can do things)
  - Negative tests needed (unauthorized users are blocked)

Key Features:
- Computes effective permissions from role hierarchy
- PostgreSQL-native caching with domain versioning
- Automatic cache invalidation on RBAC changes
- Multi-tenant permission isolation
- Performance: <0.5ms cached, <100ms uncached
"""

import logging
from typing import Optional
from uuid import UUID

from fraiseql.db import DatabaseQuery, FraiseQLRepository

from .cache import PermissionCache
from .hierarchy import RoleHierarchy
from .models import Permission, Role

logger = logging.getLogger(__name__)


class PermissionResolver:
    """Resolves effective permissions for users with PostgreSQL caching.

    Architecture:
    - Computes permissions from role hierarchy using PostgreSQL CTEs
    - 2-layer cache: request-level (instant) + PostgreSQL (0.1-0.3ms)
    - Automatic invalidation via domain versioning
    - Multi-tenant support with tenant-scoped permissions
    """

    def __init__(self, repo: FraiseQLRepository, cache: Optional[PermissionCache] = None) -> None:
        """Initialize permission resolver.

        Args:
            repo: FraiseQL database repository
            cache: Permission cache (optional, creates new if not provided)
        """
        self.repo = repo
        self.hierarchy = RoleHierarchy(repo)
        self.cache = cache or PermissionCache(repo.get_pool())

    async def get_user_permissions(
        self, user_id: UUID, tenant_id: Optional[UUID] = None, use_cache: bool = True
    ) -> list[Permission]:
        """Get all effective permissions for a user.

        Flow:
        1. Check cache (request-level + PostgreSQL)
        2. If miss or stale, compute from database
        3. Cache result with domain versions
        4. Return permissions

        Args:
            user_id: User ID
            tenant_id: Optional tenant scope
            use_cache: Whether to use cache (default: True)

        Returns:
            List of effective permissions
        """
        # Try cache first
        if use_cache:
            cached = await self.cache.get(user_id, tenant_id)
            if cached is not None:
                logger.debug("Returning cached permissions for user %s", user_id)
                return cached

        # Cache miss or disabled - compute permissions
        logger.debug("Computing permissions for user %s", user_id)
        permissions = await self._compute_permissions(user_id, tenant_id)

        # Cache result
        if use_cache:
            await self.cache.set(user_id, tenant_id, permissions)

        return permissions

    async def _compute_permissions(
        self, user_id: UUID, tenant_id: Optional[UUID]
    ) -> list[Permission]:
        """Compute effective permissions from database.

        This is the expensive operation that we cache.

        Args:
            user_id: User ID
            tenant_id: Optional tenant scope

        Returns:
            List of effective permissions
        """
        # Get user's direct roles
        user_roles = await self._get_user_roles(user_id, tenant_id)

        # Get all inherited roles
        all_role_ids: set[UUID] = set()
        for role in user_roles:
            inherited = await self.hierarchy.get_inherited_roles(role.id)
            all_role_ids.update(r.id for r in inherited)

        if not all_role_ids:
            return []

        # Get permissions for all roles
        permissions_data = await self.repo.run(
            DatabaseQuery(
                statement="""
                SELECT DISTINCT p.*
                FROM permissions p
                INNER JOIN role_permissions rp ON p.id = rp.permission_id
                WHERE rp.role_id = ANY(%(role_ids)s::uuid[])
                AND rp.granted = TRUE
                ORDER BY p.resource, p.action
            """,
                params={"role_ids": list(all_role_ids)},
                fetch_result=True,
            )
        )

        permissions = [Permission(**row) for row in permissions_data]
        logger.debug("Computed %d permissions for user %s", len(permissions), user_id)
        return permissions

    async def _get_user_roles(self, user_id: UUID, tenant_id: Optional[UUID]) -> list[Role]:
        """Get roles directly assigned to user."""
        results = await self.repo.run(
            DatabaseQuery(
                statement="""
                SELECT r.*
                FROM roles r
                INNER JOIN user_roles ur ON r.id = ur.role_id
                WHERE ur.user_id = %(user_id)s
                AND (ur.tenant_id = %(tenant_id)s OR (ur.tenant_id IS NULL AND %(tenant_id)s IS NULL))
                AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
            """,
                params={
                    "user_id": str(user_id),
                    "tenant_id": str(tenant_id) if tenant_id else None,
                },
                fetch_result=True,
            )
        )

        return [Role(**row) for row in results]

    async def has_permission(
        self, user_id: UUID, resource: str, action: str, tenant_id: Optional[UUID] = None
    ) -> bool:
        """Check if user has specific permission.

        Args:
            user_id: User ID
            resource: Resource name (e.g., 'user', 'product')
            action: Action name (e.g., 'create', 'read')
            tenant_id: Optional tenant scope

        Returns:
            True if user has permission, False otherwise
        """
        permissions = await self.get_user_permissions(user_id, tenant_id)

        return any(p.resource == resource and p.action == action for p in permissions)

    async def check_permission(
        self,
        user_id: UUID,
        resource: str,
        action: str,
        tenant_id: Optional[UUID] = None,
        raise_on_deny: bool = True,
    ) -> bool:
        """Check permission and optionally raise error.

        Args:
            user_id: User ID
            resource: Resource name
            action: Action name
            tenant_id: Optional tenant scope
            raise_on_deny: If True, raise PermissionError when denied

        Returns:
            True if permitted

        Raises:
            PermissionError: If raise_on_deny=True and permission denied
        """
        has_perm = await self.has_permission(user_id, resource, action, tenant_id)

        if not has_perm and raise_on_deny:
            raise PermissionError(f"Permission denied: requires {resource}.{action}")

        return has_perm

    async def get_user_roles(self, user_id: UUID, tenant_id: Optional[UUID] = None) -> list[Role]:
        """Get roles assigned to user (public method)."""
        return await self._get_user_roles(user_id, tenant_id)

    async def get_role_permissions(
        self, role_id: UUID, include_inherited: bool = True
    ) -> list[Permission]:
        """Get permissions for a specific role.

        Args:
            role_id: Role ID
            include_inherited: Whether to include inherited permissions

        Returns:
            List of permissions for the role
        """
        if include_inherited:
            # Get all roles in hierarchy
            roles = await self.hierarchy.get_inherited_roles(role_id)
            role_ids = [r.id for r in roles]
        else:
            role_ids = [role_id]

        # Get permissions
        permissions_data = await self.repo.run(
            DatabaseQuery(
                statement="""
                SELECT DISTINCT p.*
                FROM permissions p
                INNER JOIN role_permissions rp ON p.id = rp.permission_id
                WHERE rp.role_id = ANY(%s::uuid[])
                AND rp.granted = TRUE
                ORDER BY p.resource, p.action
            """,
                params={"role_ids": role_ids},
                fetch_result=True,
            )
        )

        return [Permission(**row) for row in permissions_data]

    async def invalidate_user_cache(self, user_id: UUID, tenant_id: Optional[UUID] = None) -> None:
        """Manually invalidate permission cache for user.

        Note: With domain versioning, manual invalidation is rarely needed
        as cache is automatically invalidated when RBAC tables change.

        Args:
            user_id: User ID
            tenant_id: Tenant ID (None for global)
        """
        await self.cache.invalidate_user(user_id, tenant_id)
        logger.info("Invalidated permission cache for user %s", user_id)
