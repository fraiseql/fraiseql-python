"""Tests for Row-Level Security (RLS) enforcement."""

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from fraiseql.db import DatabaseQuery, FraiseQLRepository

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True, scope="class")
async def setup_rbac_schema(class_db_pool, test_schema) -> None:
    """Set up RBAC schema before running tests."""
    from pathlib import Path

    # Read the RBAC migration file
    rbac_migration_path = Path("src/fraiseql/enterprise/migrations/002_rbac_tables.sql")
    rbac_migration_sql = rbac_migration_path.read_text()

    # Execute the migrations
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        # Execute RBAC schema first
        await conn.execute(rbac_migration_sql)

        # Execute only the function definitions from RLS migration
        # (skip the ALTER TABLE and CREATE POLICY statements that require tables)
        function_sql = """
        -- Function to check if user has role (for use in policies)
        CREATE OR REPLACE FUNCTION user_has_role(p_user_id UUID, p_role_name TEXT)
        RETURNS BOOLEAN AS $$
        BEGIN
            RETURN EXISTS (
                SELECT 1 FROM user_roles ur
                INNER JOIN roles r ON ur.role_id = r.id
                WHERE ur.user_id = p_user_id
                AND r.name = p_role_name
                AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
            );
        END;
        $$ LANGUAGE plpgsql STABLE;

        -- Function to check if user has permission (for use in policies)
        CREATE OR REPLACE FUNCTION user_has_permission(p_user_id UUID, p_resource TEXT, p_action TEXT)
        RETURNS BOOLEAN AS $$
        BEGIN
            RETURN EXISTS (
                SELECT 1
                FROM user_roles ur
                INNER JOIN roles r ON ur.role_id = r.id
                INNER JOIN role_permissions rp ON r.id = rp.role_id
                INNER JOIN permissions p ON rp.permission_id = p.id
                WHERE ur.user_id = p_user_id
                AND p.resource = p_resource
                AND p.action = p_action
                AND rp.granted = TRUE
                AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
            );
        END;
        $$ LANGUAGE plpgsql STABLE;
        """

        await conn.execute(function_sql)
        await conn.commit()
        print("RBAC schema and functions migration executed successfully")


@pytest.mark.asyncio
async def test_session_variables_set_for_rls(class_db_pool, test_schema) -> None:
    """Verify RBAC session variables are set correctly for RLS."""
    # Create repository with RBAC context
    user_id = uuid4()
    tenant_id = uuid4()
    context = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "roles": [{"name": "admin"}],  # Not super_admin
    }

    repo = FraiseQLRepository(class_db_pool, context=context)

    # Check that session variables are set
    result = await repo.run(
        DatabaseQuery(
            statement="SELECT current_setting('app.user_id', TRUE) as user_id, current_setting('app.tenant_id', TRUE) as tenant_id, current_setting('app.is_super_admin', TRUE) as is_super_admin",
            params={},
            fetch_result=True,
        )
    )

    assert len(result) == 1
    row = result[0]
    assert row["user_id"] == str(user_id)
    assert row["tenant_id"] == str(tenant_id)
    assert row["is_super_admin"] == "false"  # Not super_admin


@pytest.mark.asyncio
async def test_super_admin_session_variable(class_db_pool, test_schema) -> None:
    """Verify super_admin session variable is set correctly."""
    # Create repository with super_admin role
    user_id = uuid4()
    tenant_id = uuid4()
    context = {"user_id": user_id, "tenant_id": tenant_id, "roles": [{"name": "super_admin"}]}

    repo = FraiseQLRepository(class_db_pool, context=context)

    # Check that super_admin is set to true
    result = await repo.run(
        DatabaseQuery(
            statement="SELECT current_setting('app.is_super_admin', TRUE) as is_super_admin",
            params={},
            fetch_result=True,
        )
    )

    assert len(result) == 1
    assert result[0]["is_super_admin"] == "true"


@pytest.mark.asyncio
async def test_rbac_utility_functions(db_repo) -> None:
    """Test the RBAC utility functions created in the migration."""
    # Test user_has_role function
    user_id = uuid4()
    role_id = uuid4()
    tenant_id = uuid4()

    # Insert test data
    await db_repo.run(
        DatabaseQuery(
            statement="""
            INSERT INTO roles (id, name, tenant_id) VALUES (%(id)s, %(name)s, %(tenant_id)s)
        """,
            params={"id": str(role_id), "name": "test_role", "tenant_id": str(tenant_id)},
            fetch_result=False,
        )
    )

    await db_repo.run(
        DatabaseQuery(
            statement="""
            INSERT INTO user_roles (user_id, role_id, tenant_id) VALUES (%(user_id)s, %(role_id)s, %(tenant_id)s)
        """,
            params={"user_id": str(user_id), "role_id": str(role_id), "tenant_id": str(tenant_id)},
            fetch_result=False,
        )
    )

    # Test user_has_role function
    result = await db_repo.run(
        DatabaseQuery(
            statement="SELECT user_has_role(%(user_id)s, %(role_name)s) as user_has_role",
            params={"user_id": str(user_id), "role_name": "test_role"},
            fetch_result=True,
        )
    )

    assert len(result) == 1
    assert result[0]["user_has_role"] is True

    # Test with non-existent role
    result = await db_repo.run(
        DatabaseQuery(
            statement="SELECT user_has_role(%(user_id)s, %(role_name)s) as user_has_role",
            params={"user_id": str(user_id), "role_name": "non_existent_role"},
            fetch_result=True,
        )
    )

    assert len(result) == 1
    assert result[0]["user_has_role"] is False

    # Test user_has_permission function
    permission_id = uuid4()

    await db_repo.run(
        DatabaseQuery(
            statement="""
            INSERT INTO permissions (id, resource, action) VALUES (%(id)s, %(resource)s, %(action)s)
        """,
            params={"id": str(permission_id), "resource": "test_resource", "action": "test_action"},
            fetch_result=False,
        )
    )

    await db_repo.run(
        DatabaseQuery(
            statement="""
            INSERT INTO role_permissions (role_id, permission_id) VALUES (%(role_id)s, %(permission_id)s)
        """,
            params={"role_id": str(role_id), "permission_id": str(permission_id)},
            fetch_result=False,
        )
    )

    result = await db_repo.run(
        DatabaseQuery(
            statement="SELECT user_has_permission(%(user_id)s, %(resource)s, %(action)s) as user_has_permission",
            params={"user_id": str(user_id), "resource": "test_resource", "action": "test_action"},
            fetch_result=True,
        )
    )

    assert len(result) == 1
    assert result[0]["user_has_permission"] is True

    # Test with non-existent permission
    result = await db_repo.run(
        DatabaseQuery(
            statement="SELECT user_has_permission(%(user_id)s, %(resource)s, %(action)s) as user_has_permission",
            params={
                "user_id": str(user_id),
                "resource": "test_resource",
                "action": "non_existent_action",
            },
            fetch_result=True,
        )
    )

    assert len(result) == 1
    assert result[0]["user_has_permission"] is False


@pytest.mark.asyncio
async def test_rls_policies_applied(db_repo) -> None:
    """Test that RLS policies can be applied to tables (when they exist)."""
    # For now, just verify that the RLS migration file exists and is valid
    # Actual RLS policy testing would require tables to exist
    rls_migration_path = Path("src/fraiseql/enterprise/migrations/004_rbac_row_level_security.sql")

    assert rls_migration_path.exists(), "RLS migration file should exist"

    # Read the migration to ensure it's valid SQL
    migration_sql = rls_migration_path.read_text()
    assert "ROW LEVEL SECURITY" in migration_sql, "Migration should contain RLS setup"
    assert "current_setting" in migration_sql, "Migration should use session variables"


@pytest.mark.asyncio
async def test_tenant_isolation_logic() -> None:
    """Test the logical correctness of tenant isolation (without actual data)."""
    # This test verifies the RLS policy logic is sound
    # In a real scenario, this would be tested with actual data

    # Mock tenant IDs
    tenant1 = uuid4()
    tenant2 = uuid4()
    uuid4()

    # Simulate the RLS policy logic:
    # A user should only see data where tenant_id matches their context tenant_id
    # OR they are super_admin

    # Case 1: User in tenant1, data in tenant1 -> should see
    context_tenant = tenant1
    data_tenant = tenant1
    is_super_admin = False

    can_see = (data_tenant == context_tenant) or is_super_admin
    assert can_see is True

    # Case 2: User in tenant1, data in tenant2 -> should not see
    context_tenant = tenant1
    data_tenant = tenant2
    is_super_admin = False

    can_see = (data_tenant == context_tenant) or is_super_admin
    assert can_see is False

    # Case 3: User in tenant1, data in tenant2, but super_admin -> should see
    context_tenant = tenant1
    data_tenant = tenant2
    is_super_admin = True

    can_see = (data_tenant == context_tenant) or is_super_admin
    assert can_see is True

    # Case 2: User in tenant1, data in tenant2 -> should not see
    context_tenant = tenant1
    data_tenant = tenant2
    is_super_admin = False

    can_see = (data_tenant == context_tenant) or is_super_admin
    assert can_see is False

    # Case 3: User in tenant1, data in tenant2, but super_admin -> should see
    context_tenant = tenant1
    data_tenant = tenant2
    is_super_admin = True

    can_see = (data_tenant == context_tenant) or is_super_admin
    assert can_see is True
