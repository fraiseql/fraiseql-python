"""user_has_permission() of 004_rbac_row_level_security.sql follows the role hierarchy.

It must agree with PermissionResolver, which counts the permissions of each assigned
role and of that role's ancestors (a role inherits from its parent).
"""

from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from fraiseql.enterprise.rbac.resolver import PermissionResolver

pytestmark = [pytest.mark.integration, pytest.mark.database, pytest.mark.enterprise]

MIGRATIONS = Path(__file__).parents[4] / "src" / "fraiseql" / "enterprise" / "migrations"

SUPER_ADMIN = UUID("00000000-0000-0000-0000-000000000001")
ADMIN = UUID("00000000-0000-0000-0000-000000000002")
MANAGER = UUID("00000000-0000-0000-0000-000000000003")
VIEWER = UUID("00000000-0000-0000-0000-000000000005")


@pytest.fixture
async def rls_pool(rbac_pool):
    """002_rbac_tables.sql (from rbac_pool) plus 004, with permissions on two roles.

    The schema lives as long as the test class, so this runs again on the same tables.
    """
    async with rbac_pool.connection() as conn:
        await conn.execute((MIGRATIONS / "004_rbac_row_level_security.sql").read_text())
        for role_id, resource, action in [
            (VIEWER, "user", "read"),
            (SUPER_ADMIN, "settings", "update"),
        ]:
            await conn.execute(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT %s, id FROM permissions WHERE resource = %s AND action = %s "
                "ON CONFLICT DO NOTHING",
                (role_id, resource, action),
            )
    return rbac_pool


async def _assign(pool, role_id: UUID, expires_at: str | None = None) -> UUID:
    user_id = uuid4()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO user_roles (user_id, role_id, expires_at) VALUES (%s, %s, %s)",
            (user_id, role_id, expires_at),
        )
    return user_id


async def _sql_has(pool, user_id: UUID, resource: str, action: str) -> bool:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT user_has_permission(%s, %s, %s)", (user_id, resource, action)
        )
        return (await cur.fetchone())[0]


async def _resolver_has(repo, user_id: UUID, resource: str, action: str) -> bool:
    resolver = PermissionResolver(repo, cache=object())  # cache unused: use_cache=False
    permissions = await resolver.get_user_permissions(user_id, use_cache=False)
    return any(p.resource == resource and p.action == action for p in permissions)


CASES = [
    # (assigned role, permission, expected)
    (MANAGER, ("user", "read"), True),  # granted to viewer, an ancestor of manager
    (SUPER_ADMIN, ("user", "read"), True),  # four levels up
    (VIEWER, ("user", "read"), True),  # granted to the role itself
    (VIEWER, ("settings", "update"), False),  # granted to a descendant only
    (ADMIN, ("settings", "update"), False),
    (SUPER_ADMIN, ("settings", "update"), True),
]


class TestUserHasPermissionFollowsTheHierarchy:
    @pytest.mark.parametrize(("role_id", "permission", "expected"), CASES)
    async def test_agrees_with_the_permission_resolver(
        self, rls_pool, rbac_repo, role_id, permission, expected
    ) -> None:
        user_id = await _assign(rls_pool, role_id)

        assert await _resolver_has(rbac_repo, user_id, *permission) is expected
        assert await _sql_has(rls_pool, user_id, *permission) is expected

    async def test_an_expired_assignment_grants_nothing_inherited(
        self, rls_pool, rbac_repo
    ) -> None:
        user_id = await _assign(rls_pool, MANAGER, expires_at="2000-01-01T00:00:00Z")

        assert await _resolver_has(rbac_repo, user_id, "user", "read") is False
        assert await _sql_has(rls_pool, user_id, "user", "read") is False

    async def test_a_cycle_gives_every_role_of_the_cycle(self, rls_pool, rbac_repo) -> None:
        """get_inherited_roles() stops a cycle at depth 10 and keeps each role once."""
        async with rls_pool.connection() as conn:
            await conn.execute(
                "UPDATE roles SET parent_role_id = %s WHERE id = %s", (SUPER_ADMIN, VIEWER)
            )
        try:
            user_id = await _assign(rls_pool, MANAGER)

            assert await _resolver_has(rbac_repo, user_id, "settings", "update") is True
            assert await _sql_has(rls_pool, user_id, "settings", "update") is True
        finally:
            async with rls_pool.connection() as conn:
                await conn.execute(
                    "UPDATE roles SET parent_role_id = NULL WHERE id = %s", (VIEWER,)
                )

    async def test_a_hierarchy_of_ten_levels_is_an_error_as_in_the_resolver(
        self, rls_pool, rbac_repo
    ) -> None:
        # Ten more roles above viewer's descendants: role_10 -> ... -> role_1 -> viewer
        parent = VIEWER
        async with rls_pool.connection() as conn:
            for level in range(1, 11):
                cur = await conn.execute(
                    "INSERT INTO roles (name, parent_role_id) VALUES (%s, %s) RETURNING id",
                    (f"deep_{uuid4().hex[:8]}_{level}", parent),
                )
                parent = (await cur.fetchone())[0]
        user_id = await _assign(rls_pool, parent)

        with pytest.raises(ValueError, match="Cycle detected"):
            await _resolver_has(rbac_repo, user_id, "user", "read")
        with pytest.raises(psycopg.errors.RaiseException, match="Cycle detected"):
            await _sql_has(rls_pool, user_id, "user", "read")


class TestUserHasRoleChecksAssignedRoles:
    """Like @requires_role and PermissionResolver.get_user_roles(): no inheritance."""

    async def test_an_inherited_role_is_not_a_role_of_the_user(self, rls_pool, rbac_repo) -> None:
        user_id = await _assign(rls_pool, SUPER_ADMIN)
        resolver = PermissionResolver(rbac_repo, cache=object())

        assert {r.name for r in await resolver.get_user_roles(user_id)} == {"super_admin"}
        async with rls_pool.connection() as conn:
            cur = await conn.execute(
                "SELECT user_has_role(%s, 'super_admin'), user_has_role(%s, 'admin')",
                (user_id, user_id),
            )
            assert await cur.fetchone() == (True, False)
