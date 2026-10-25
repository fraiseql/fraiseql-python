"""PermissionResolver built from a FraiseQLRepository alone, against PostgreSQL."""

from uuid import UUID, uuid4

import pytest

from fraiseql.enterprise.rbac.cache import PermissionCache
from fraiseql.enterprise.rbac.resolver import PermissionResolver

pytestmark = [pytest.mark.integration, pytest.mark.database, pytest.mark.enterprise]

VIEWER = UUID("00000000-0000-0000-0000-000000000005")


async def _viewer_with_user_read(pool) -> UUID:
    user_id = uuid4()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT %s, id FROM permissions WHERE resource = 'user' AND action = 'read'
            ON CONFLICT DO NOTHING
            """,
            (VIEWER,),
        )
        await conn.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)", (user_id, VIEWER)
        )
    return user_id


class TestPermissionResolverWithItsDefaultCache:
    async def test_resolver_from_a_repository_alone(self, rbac_pool, rbac_repo) -> None:
        user_id = await _viewer_with_user_read(rbac_pool)

        resolver = PermissionResolver(rbac_repo)

        assert isinstance(resolver.cache, PermissionCache)
        assert await resolver.has_permission(user_id, "user", "read")
        assert not await resolver.has_permission(user_id, "user", "delete")
