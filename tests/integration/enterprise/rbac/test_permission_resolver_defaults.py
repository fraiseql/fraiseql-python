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


class TestPermissionsReadBackFromPostgreSQL:
    async def test_a_second_resolver_reads_the_cached_permissions(
        self, rbac_pool, rbac_repo
    ) -> None:
        user_id = await _viewer_with_user_read(rbac_pool)
        first = await PermissionResolver(rbac_repo).get_user_permissions(user_id)

        # Another resolver (another request, another process) has an empty
        # in-memory layer and reads the fraiseql_cache row.
        second = PermissionResolver(rbac_repo)
        cached = await second.cache.get(user_id, None)

        assert cached == first
        assert await second.get_user_permissions(user_id) == first

    async def test_a_cached_row_that_doesnt_validate_is_recomputed(
        self, rbac_pool, rbac_repo
    ) -> None:
        user_id = await _viewer_with_user_read(rbac_pool)
        resolver = PermissionResolver(rbac_repo)
        # A row in the shape 1.30 wrote: no created_at.
        await resolver.cache.pg_cache.set(
            key=resolver.cache._make_key(user_id, None),
            value=[{"id": str(uuid4()), "resource": "user", "action": "delete"}],
            ttl=300,
        )

        assert await resolver.cache.get(user_id, None) is None
        found = await resolver.get_user_permissions(user_id)
        assert {(p.resource, p.action) for p in found} == {("user", "read")}
