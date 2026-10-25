"""RoleHierarchy.get_role_descendants() returns the roles that inherit from a role."""

from uuid import UUID

import pytest

from fraiseql.enterprise.rbac.hierarchy import RoleHierarchy

pytestmark = [pytest.mark.integration, pytest.mark.database, pytest.mark.enterprise]

SUPER_ADMIN = UUID("00000000-0000-0000-0000-000000000001")
ADMIN = UUID("00000000-0000-0000-0000-000000000002")
MANAGER = UUID("00000000-0000-0000-0000-000000000003")
USER = UUID("00000000-0000-0000-0000-000000000004")
VIEWER = UUID("00000000-0000-0000-0000-000000000005")


class TestRoleDescendants:
    async def test_every_seeded_role_descends_from_viewer(self, rbac_repo) -> None:
        descendants = await RoleHierarchy(rbac_repo).get_role_descendants(VIEWER)
        assert {r.id for r in descendants} == {USER, MANAGER, ADMIN, SUPER_ADMIN}

    async def test_descendants_of_manager(self, rbac_repo) -> None:
        descendants = await RoleHierarchy(rbac_repo).get_role_descendants(MANAGER)
        assert {r.id for r in descendants} == {ADMIN, SUPER_ADMIN}

    async def test_nothing_descends_from_super_admin(self, rbac_repo) -> None:
        assert await RoleHierarchy(rbac_repo).get_role_descendants(SUPER_ADMIN) == []

    async def test_ancestors_are_the_other_direction(self, rbac_repo) -> None:
        ancestors = await RoleHierarchy(rbac_repo).get_role_ancestors(MANAGER)
        assert {r.id for r in ancestors} == {USER, VIEWER}
