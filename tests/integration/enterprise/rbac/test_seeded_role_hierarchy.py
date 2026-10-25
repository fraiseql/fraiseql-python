"""The system roles 002_rbac_tables.sql seeds inherit from the less privileged ones."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from fraiseql.enterprise.rbac.hierarchy import RoleHierarchy
from fraiseql.enterprise.rbac.resolver import PermissionResolver

pytestmark = [pytest.mark.integration, pytest.mark.database, pytest.mark.enterprise]

MIGRATIONS = Path(__file__).parents[4] / "src" / "fraiseql" / "enterprise" / "migrations"

SUPER_ADMIN = UUID("00000000-0000-0000-0000-000000000001")
ADMIN = UUID("00000000-0000-0000-0000-000000000002")
MANAGER = UUID("00000000-0000-0000-0000-000000000003")
USER = UUID("00000000-0000-0000-0000-000000000004")
VIEWER = UUID("00000000-0000-0000-0000-000000000005")


async def _grant(pool, role_id: UUID, resource: str, action: str) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT %s, id FROM permissions WHERE resource = %s AND action = %s
            """,
            (role_id, resource, action),
        )


async def _assign(pool, role_id: UUID) -> UUID:
    user_id = uuid4()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)", (user_id, role_id)
        )
    return user_id


async def _parents(pool) -> dict[str, str | None]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT r.name, p.name FROM roles r LEFT JOIN roles p ON p.id = r.parent_role_id
            WHERE r.is_system
            """
        )
        return dict(await cur.fetchall())


EXPECTED_PARENTS = {
    "viewer": None,
    "user": "viewer",
    "manager": "user",
    "admin": "manager",
    "super_admin": "admin",
}


class TestSeededRoleHierarchy:
    async def test_each_role_inherits_from_the_one_below_it(self, rbac_pool) -> None:
        assert await _parents(rbac_pool) == EXPECTED_PARENTS

    async def test_viewer_cannot_do_an_admin_action(self, rbac_pool, rbac_repo) -> None:
        await _grant(rbac_pool, VIEWER, "user", "read")
        await _grant(rbac_pool, ADMIN, "user", "delete")
        await _grant(rbac_pool, SUPER_ADMIN, "settings", "update")
        viewer = await _assign(rbac_pool, VIEWER)
        admin = await _assign(rbac_pool, ADMIN)
        resolver = PermissionResolver(rbac_repo, cache=object())  # cache unused below

        async def perms(user_id: UUID) -> set[str]:
            found = await resolver.get_user_permissions(user_id, use_cache=False)
            return {f"{p.resource}.{p.action}" for p in found}

        assert await perms(viewer) == {"user.read"}
        # admin has its own permission and the viewer's, not the super_admin's
        assert await perms(admin) == {"user.read", "user.delete"}

    async def test_inherited_roles_of_viewer_and_super_admin(self, rbac_repo) -> None:
        hierarchy = RoleHierarchy(rbac_repo)

        assert {r.id for r in await hierarchy.get_inherited_roles(VIEWER)} == {VIEWER}
        assert {r.id for r in await hierarchy.get_inherited_roles(SUPER_ADMIN)} == {
            SUPER_ADMIN,
            ADMIN,
            MANAGER,
            USER,
            VIEWER,
        }


# The chain the migration used to seed, each role the parent of the one before it.
OLD_PARENTS = {
    "viewer": "user",
    "user": "manager",
    "manager": "admin",
    "admin": "super_admin",
    "super_admin": None,
}


class TestReapplyingTheMigrationOnTheOldSeed:
    async def test_the_old_chain_is_repaired(self, rbac_pool) -> None:
        async with rbac_pool.connection() as conn:
            await conn.execute(
                """
                UPDATE roles SET parent_role_id = CASE id
                    WHEN %(super_admin)s THEN NULL
                    WHEN %(admin)s THEN %(super_admin)s
                    WHEN %(manager)s THEN %(admin)s
                    WHEN %(user)s THEN %(manager)s
                    WHEN %(viewer)s THEN %(user)s
                END
                WHERE id IN (%(super_admin)s, %(admin)s, %(manager)s, %(user)s, %(viewer)s)
                """,
                {
                    "super_admin": SUPER_ADMIN,
                    "admin": ADMIN,
                    "manager": MANAGER,
                    "user": USER,
                    "viewer": VIEWER,
                },
            )
        assert await _parents(rbac_pool) == OLD_PARENTS

        async with rbac_pool.connection() as conn:
            await conn.execute((MIGRATIONS / "002_rbac_tables.sql").read_text())

        assert await _parents(rbac_pool) == EXPECTED_PARENTS


class TestReapplyingTheMigrationOnAChangedHierarchy:
    async def test_a_hierarchy_the_app_changed_is_kept(self, rbac_pool) -> None:
        """Only the exact old seed is rewritten: the app may have built on it."""
        changed = {**OLD_PARENTS, "user": None}
        async with rbac_pool.connection() as conn:
            await conn.execute(
                """
                UPDATE roles SET parent_role_id = CASE id
                    WHEN %(admin)s THEN %(super_admin)s
                    WHEN %(manager)s THEN %(admin)s
                    WHEN %(viewer)s THEN %(user)s
                END
                WHERE id IN (%(super_admin)s, %(admin)s, %(manager)s, %(user)s, %(viewer)s)
                """,
                {
                    "super_admin": SUPER_ADMIN,
                    "admin": ADMIN,
                    "manager": MANAGER,
                    "user": USER,
                    "viewer": VIEWER,
                },
            )
        assert await _parents(rbac_pool) == changed

        async with rbac_pool.connection() as conn:
            await conn.execute((MIGRATIONS / "002_rbac_tables.sql").read_text())

        assert await _parents(rbac_pool) == changed


class TestRolePermissions:
    async def test_get_role_permissions(self, rbac_pool, rbac_repo) -> None:
        await _grant(rbac_pool, VIEWER, "user", "read")
        await _grant(rbac_pool, ADMIN, "user", "delete")
        resolver = PermissionResolver(rbac_repo)

        async def perms(role_id: UUID, **kwargs) -> set[str]:
            found = await resolver.get_role_permissions(role_id, **kwargs)
            return {f"{p.resource}.{p.action}" for p in found}

        assert await perms(ADMIN) == {"user.read", "user.delete"}
        assert await perms(ADMIN, include_inherited=False) == {"user.delete"}
        assert await perms(VIEWER) == {"user.read"}
        assert await perms(SUPER_ADMIN, include_inherited=False) == set()
