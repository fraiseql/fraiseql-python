"""Test RBAC Enforcement - Critical Security Verification

This test verifies that unauthorized users are actually BLOCKED by RBAC,
not just that permissions are resolved correctly.

**What we're testing**:
- User WITHOUT permission is denied access
- User WITH permission is granted access
- PermissionError is raised for unauthorized access

**Why this matters**:
- v1.9.7 has 52 positive RBAC tests (authorized users can do things)
- v1.9.7 has 0 negative RBAC tests (unauthorized users are blocked)
- This test fills the critical security gap

**Pre-publication verification**:
If this test PASSES ✅: RBAC enforcement works, v1.9.7 is publishable
If this test FAILS ❌: RBAC is broken, do NOT publish v1.9.7
"""

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from fraiseql.db import DatabaseQuery, FraiseQLRepository
from fraiseql.enterprise.rbac.cache import PermissionCache
from fraiseql.enterprise.rbac.resolver import PermissionResolver

pytestmark = pytest.mark.enterprise


@pytest_asyncio.fixture(autouse=True, scope="class")
async def ensure_rbac_schema(class_db_pool, test_schema) -> None:
    """Ensure RBAC schema exists before running tests."""
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        cur = await conn.execute(
            """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'roles'
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


@pytest_asyncio.fixture
async def rbac_test_data(db_repo: FraiseQLRepository) -> dict:
    """Create test data: role, permission, users.

    Returns:
        Dict with:
        - role_id: Admin role
        - permission_id: 'post:create' permission
        - authorized_user_id: User WITH 'post:create' permission
        - unauthorized_user_id: User WITHOUT 'post:create' permission
    """
    # Use unique resource/action per test run to avoid conflicts
    test_id = str(uuid4())[:8]

    # Create permission
    permission_result = await db_repo.run(
        DatabaseQuery(
            statement="""
                INSERT INTO permissions (id, resource, action, description)
                VALUES (%(id)s, %(resource)s, %(action)s, %(description)s)
                RETURNING id
            """,
            params={
                "id": str(uuid4()),
                "resource": f"post_{test_id}",
                "action": "create",
                "description": "Create blog posts",
            },
            fetch_result=True,
        )
    )
    # Result is already a UUID, don't cast
    permission_id = permission_result[0]["id"]

    # Create admin role
    role_result = await db_repo.run(
        DatabaseQuery(
            statement="""
                INSERT INTO roles (id, name, description)
                VALUES (%(id)s, %(name)s, %(description)s)
                RETURNING id
            """,
            params={
                "id": str(uuid4()),
                "name": f"admin_{test_id}",
                "description": "Administrator role",
            },
            fetch_result=True,
        )
    )
    # Result is already a UUID, don't cast
    role_id = role_result[0]["id"]

    # Link permission to role
    await db_repo.run(
        DatabaseQuery(
            statement="""
                INSERT INTO role_permissions (role_id, permission_id, granted)
                VALUES (%(role_id)s, %(permission_id)s, TRUE)
            """,
            params={
                "role_id": str(role_id),
                "permission_id": str(permission_id),
            },
            fetch_result=False,
        )
    )

    # Create authorized user (has admin role)
    authorized_user_id = uuid4()
    await db_repo.run(
        DatabaseQuery(
            statement="""
                INSERT INTO user_roles (user_id, role_id)
                VALUES (%(user_id)s, %(role_id)s)
            """,
            params={
                "user_id": str(authorized_user_id),
                "role_id": str(role_id),
            },
            fetch_result=False,
        )
    )

    # Create unauthorized user (no roles)
    unauthorized_user_id = uuid4()

    return {
        "role_id": role_id,
        "permission_id": permission_id,
        "authorized_user_id": authorized_user_id,
        "unauthorized_user_id": unauthorized_user_id,
        "resource": f"post_{test_id}",
        "action": "create",
    }


class TestRBACEnforcement:
    """Critical security tests - verify RBAC actually blocks unauthorized users."""

    @pytest.mark.asyncio
    async def test_unauthorized_user_denied_permission(
        self, db_repo: FraiseQLRepository, class_db_pool, rbac_test_data: dict
    ) -> None:
        """🚨 CRITICAL: Verify unauthorized user is DENIED permission.

        This is the test that determines if v1.9.7 is safe to publish.
        Tests the check_permission() method with raise_on_deny=True.
        """
        # Create permission resolver
        cache = PermissionCache(class_db_pool)
        resolver = PermissionResolver(db_repo, cache)

        # CRITICAL TEST: User WITHOUT permission
        with pytest.raises(PermissionError) as exc_info:
            await resolver.check_permission(
                user_id=rbac_test_data["unauthorized_user_id"],
                resource=rbac_test_data["resource"],
                action=rbac_test_data["action"],
                raise_on_deny=True,
            )

        # Verify error message is correct
        assert "Permission denied" in str(exc_info.value)
        assert rbac_test_data["resource"] in str(exc_info.value)

        print("✅ PASS: Unauthorized user successfully denied (PermissionError raised)")

    @pytest.mark.asyncio
    async def test_unauthorized_user_has_permission_returns_false(
        self, db_repo: FraiseQLRepository, class_db_pool, rbac_test_data: dict
    ) -> None:
        """🚨 Verify has_permission() returns False for unauthorized user."""
        # Create permission resolver
        cache = PermissionCache(class_db_pool)
        resolver = PermissionResolver(db_repo, cache)

        # CRITICAL TEST: User WITHOUT permission
        has_perm = await resolver.has_permission(
            user_id=rbac_test_data["unauthorized_user_id"],
            resource=rbac_test_data["resource"],
            action=rbac_test_data["action"],
        )

        # Should return False
        assert has_perm is False, (
            "🚨 SECURITY FAILURE: has_permission() returned True for unauthorized user! "
            "RBAC enforcement is broken. DO NOT PUBLISH v1.9.7."
        )

        print("✅ PASS: has_permission() correctly returns False for unauthorized user")

    @pytest.mark.asyncio
    async def test_authorized_user_allowed_permission(
        self, db_repo: FraiseQLRepository, class_db_pool, rbac_test_data: dict
    ) -> None:
        """✅ Verify authorized user IS allowed (positive test for comparison)."""
        # Create permission resolver
        cache = PermissionCache(class_db_pool)
        resolver = PermissionResolver(db_repo, cache)

        # User WITH permission (via admin role)
        result = await resolver.check_permission(
            user_id=rbac_test_data["authorized_user_id"],
            resource=rbac_test_data["resource"],
            action=rbac_test_data["action"],
            raise_on_deny=True,
        )

        # Should succeed without raising exception
        assert result is True

        print("✅ PASS: Authorized user successfully allowed")

    @pytest.mark.asyncio
    async def test_authorized_user_has_permission_returns_true(
        self, db_repo: FraiseQLRepository, class_db_pool, rbac_test_data: dict
    ) -> None:
        """✅ Verify has_permission() returns True for authorized user."""
        # Create permission resolver
        cache = PermissionCache(class_db_pool)
        resolver = PermissionResolver(db_repo, cache)

        # User WITH permission
        has_perm = await resolver.has_permission(
            user_id=rbac_test_data["authorized_user_id"],
            resource=rbac_test_data["resource"],
            action=rbac_test_data["action"],
        )

        # Should return True
        assert has_perm is True

        print("✅ PASS: has_permission() correctly returns True for authorized user")

    @pytest.mark.asyncio
    async def test_check_permission_no_raise_returns_false(
        self, db_repo: FraiseQLRepository, class_db_pool, rbac_test_data: dict
    ) -> None:
        """🚨 Verify check_permission(raise_on_deny=False) returns False for unauthorized."""
        # Create permission resolver
        cache = PermissionCache(class_db_pool)
        resolver = PermissionResolver(db_repo, cache)

        # User WITHOUT permission, but don't raise exception
        result = await resolver.check_permission(
            user_id=rbac_test_data["unauthorized_user_id"],
            resource=rbac_test_data["resource"],
            action=rbac_test_data["action"],
            raise_on_deny=False,  # Don't raise, just return False
        )

        # Should return False
        assert result is False, (
            "🚨 SECURITY FAILURE: check_permission() returned True with raise_on_deny=False!"
        )

        print("✅ PASS: check_permission(raise_on_deny=False) correctly returns False")

    @pytest.mark.asyncio
    async def test_nonexistent_permission_denied(
        self, db_repo: FraiseQLRepository, class_db_pool, rbac_test_data: dict
    ) -> None:
        """🚨 Verify access denied for permission that doesn't exist."""
        # Create permission resolver
        cache = PermissionCache(class_db_pool)
        resolver = PermissionResolver(db_repo, cache)

        # Even authorized user shouldn't have non-existent permission
        with pytest.raises(PermissionError):
            await resolver.check_permission(
                user_id=rbac_test_data["authorized_user_id"],
                resource="nuclear_codes",  # This permission doesn't exist
                action="launch",
                raise_on_deny=True,
            )

        print("✅ PASS: Non-existent permission correctly denied")

    @pytest.mark.asyncio
    async def test_get_user_permissions_empty_for_unauthorized(
        self, db_repo: FraiseQLRepository, class_db_pool, rbac_test_data: dict
    ) -> None:
        """🚨 Verify unauthorized user gets empty permission list."""
        # Create permission resolver
        cache = PermissionCache(class_db_pool)
        resolver = PermissionResolver(db_repo, cache)

        # Get permissions for user with no roles
        permissions = await resolver.get_user_permissions(
            user_id=rbac_test_data["unauthorized_user_id"]
        )

        # Should be empty list
        assert permissions == [], (
            f"🚨 SECURITY FAILURE: Unauthorized user got permissions: {permissions}"
        )

        print("✅ PASS: Unauthorized user correctly has zero permissions")

    @pytest.mark.asyncio
    async def test_get_user_permissions_nonempty_for_authorized(
        self, db_repo: FraiseQLRepository, class_db_pool, rbac_test_data: dict
    ) -> None:
        """✅ Verify authorized user gets non-empty permission list."""
        # Create permission resolver
        cache = PermissionCache(class_db_pool)
        resolver = PermissionResolver(db_repo, cache)

        # Get permissions for user with admin role
        permissions = await resolver.get_user_permissions(
            user_id=rbac_test_data["authorized_user_id"]
        )

        # Should have at least the permission we created
        assert len(permissions) > 0, "Authorized user should have permissions"
        assert any(
            p.resource == rbac_test_data["resource"] and p.action == rbac_test_data["action"]
            for p in permissions
        ), f"Should have '{rbac_test_data['resource']}.{rbac_test_data['action']}' permission"

        print(f"✅ PASS: Authorized user has {len(permissions)} permission(s)")
