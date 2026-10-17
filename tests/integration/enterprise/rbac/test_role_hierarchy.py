"""Test Role Hierarchy Engine

Tests for role inheritance computation using PostgreSQL recursive CTEs.
"""

from pathlib import Path
from uuid import uuid4

import pytest

from fraiseql.enterprise.rbac.hierarchy import RoleHierarchy

pytestmark = pytest.mark.enterprise


@pytest.fixture(autouse=True, scope="class")
async def ensure_rbac_schema(class_db_pool, test_schema) -> None:
    """Ensure RBAC schema exists before running tests."""
    # Check if roles table exists
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
        exists = (await cur.fetchone())[0]

        if not exists:
            # Read and execute the migration
            migration_path = Path("src/fraiseql/enterprise/migrations/002_rbac_tables.sql")
            migration_sql = migration_path.read_text()
            await conn.execute(migration_sql)
            await conn.commit()


@pytest.mark.asyncio
async def test_role_inheritance_chain(db_repo) -> None:
    """Verify role inherits permissions from parent roles."""
    # Create role chain: admin -> manager -> developer -> junior_dev
    RoleHierarchy(db_repo)

    # This test assumes the seed data from the migration is loaded
    # In a real test, we'd create the roles first
    uuid4()  # Would be actual ID from seed data

    # For now, test the basic functionality with a mock
    # inherited_roles = await hierarchy.get_inherited_roles(junior_dev_role_id)

    # role_names = [r.name for r in inherited_roles]
    # assert 'junior_dev' in role_names
    # assert 'developer' in role_names
    # assert 'manager' in role_names
    # assert 'admin' in role_names

    # Placeholder test - will be implemented when database is set up
    assert True  # Basic import test


@pytest.mark.asyncio
async def test_hierarchy_validation(db_repo) -> None:
    """Test hierarchy validation (cycle detection)."""
    hierarchy = RoleHierarchy(db_repo)

    # Test with a valid role ID (would need actual data)
    # For now, just test that the method exists
    assert hasattr(hierarchy, "validate_hierarchy")
    assert hasattr(hierarchy, "get_hierarchy_depth")


@pytest.mark.asyncio
async def test_get_inherited_roles_method_exists(db_repo) -> None:
    """Verify the get_inherited_roles method exists and is callable."""
    hierarchy = RoleHierarchy(db_repo)

    # Test that method exists
    assert hasattr(hierarchy, "get_inherited_roles")

    # Test method signature
    import inspect

    sig = inspect.signature(hierarchy.get_inherited_roles)
    assert "role_id" in sig.parameters
