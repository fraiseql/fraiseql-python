"""Role Hierarchy Engine

Computes role inheritance and transitive permissions using PostgreSQL recursive CTEs.
Supports complex organizational structures with up to 10 levels of inheritance.

Key Features:
- Efficient recursive role inheritance computation
- Cycle detection (prevents infinite loops)
- Multi-tenant support
- Integration with PostgreSQL get_inherited_roles() function
"""

import logging
from uuid import UUID

from fraiseql.db import DatabaseQuery, FraiseQLRepository

from .models import Role

logger = logging.getLogger(__name__)


class RoleHierarchy:
    """Computes role hierarchy and inheritance.

    Uses PostgreSQL recursive CTE for efficient computation of role inheritance chains.
    Supports multiple inheritance paths and diamond problem resolution.
    """

    def __init__(self, repo: FraiseQLRepository) -> None:
        """Initialize role hierarchy engine.

        Args:
            repo: FraiseQL database repository
        """
        self.repo = repo

    async def get_inherited_roles(self, role_id: UUID) -> list[Role]:
        """Get all roles in inheritance chain (including self).

        Uses PostgreSQL recursive CTE for efficient computation.

        Args:
            role_id: Starting role ID

        Returns:
            List of roles from most specific to most general

        Raises:
            ValueError: If cycle detected in role hierarchy
        """
        results = await self.repo.run(
            DatabaseQuery(
                statement="SELECT * FROM get_inherited_roles(%(role_id)s)",
                params={"role_id": str(role_id)},
                fetch_result=True,
            )
        )

        if not results:
            return []

        # Check if we hit cycle detection limit
        if any(int(r["depth"]) >= 10 for r in results):
            raise ValueError(f"Cycle detected in role hierarchy for role {role_id}")

        # Get full role details
        role_ids = [r["role_id"] for r in results]
        roles_data = await self.repo.run(
            DatabaseQuery(
                statement="""
                SELECT * FROM roles
                WHERE id = ANY(%(ids)s::uuid[])
                ORDER BY name
            """,
                params={"ids": role_ids},
                fetch_result=True,
            )
        )

        roles = [Role(**row) for row in roles_data]
        logger.debug("Found %d inherited roles for role %s", len(roles), role_id)
        return roles

    async def get_role_ancestors(self, role_id: UUID) -> list[Role]:
        """Get all ancestor roles (excluding self).

        Args:
            role_id: Role ID to get ancestors for

        Returns:
            List of ancestor roles (parent, grandparent, etc.)
        """
        all_roles = await self.get_inherited_roles(role_id)
        # Exclude the role itself (depth 0)
        return [r for r in all_roles if r.id != role_id]

    async def get_role_descendants(self, role_id: UUID) -> list[Role]:
        """Get all descendant roles (roles that inherit from this role).

        This is more expensive as it requires scanning the entire roles table.

        Args:
            role_id: Role ID to get descendants for

        Returns:
            List of descendant roles
        """
        # Find all roles that have this role among their ancestors
        results = await self.repo.run(
            DatabaseQuery(
                statement="""
                SELECT r.* FROM roles r
                WHERE r.id <> %(parent_role_id)s::uuid  -- Exclude self
                AND EXISTS (
                    SELECT 1 FROM get_inherited_roles(r.id) ir
                    WHERE ir.role_id = %(parent_role_id)s::uuid
                )
                ORDER BY r.name
            """,
                params={"parent_role_id": str(role_id)},
                fetch_result=True,
            )
        )

        return [Role(**row) for row in results]

    async def validate_hierarchy(self, role_id: UUID) -> bool:
        """Validate that a role's hierarchy is valid (no cycles).

        Args:
            role_id: Role ID to validate

        Returns:
            True if hierarchy is valid, False if cycle detected
        """
        try:
            await self.get_inherited_roles(role_id)
            return True
        except ValueError:
            return False

    async def get_hierarchy_depth(self, role_id: UUID) -> int:
        """Get the maximum inheritance depth for a role.

        Args:
            role_id: Role ID

        Returns:
            Maximum depth (0 = no inheritance, 1 = one parent, etc.)
        """
        results = await self.repo.run(
            DatabaseQuery(
                statement="SELECT MAX(depth) as max_depth FROM get_inherited_roles(%(role_id)s)",
                params={"role_id": str(role_id)},
                fetch_result=True,
            )
        )

        if not results or results[0]["max_depth"] is None:
            return 0

        return int(results[0]["max_depth"])
