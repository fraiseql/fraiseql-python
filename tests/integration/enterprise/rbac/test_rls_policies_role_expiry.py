"""The example policies of 004_rbac_row_level_security.sql skip expired role assignments.

own_data_update_users, own_data_update_orders and product_management let an admin or
super_admin through; an assignment whose expires_at is past must not count, as in
user_has_role(). Each test applies the shipped file and runs the queries as a role
without superuser (a superuser bypasses row-level security), in a transaction that is
rolled back.
"""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg import sql

pytestmark = [pytest.mark.integration, pytest.mark.database, pytest.mark.enterprise]

MIGRATIONS = Path(__file__).parents[4] / "src" / "fraiseql" / "enterprise" / "migrations"

SUPER_ADMIN = UUID("00000000-0000-0000-0000-000000000001")
ADMIN = UUID("00000000-0000-0000-0000-000000000002")
MANAGER = UUID("00000000-0000-0000-0000-000000000003")

ACTOR_TENANT = uuid4()
OTHER_TENANT = uuid4()

PAST = "2000-01-01T00:00:00Z"
FUTURE = "2999-01-01T00:00:00Z"

# Rows of another tenant, so tenant_isolation_* doesn't let the actor through: only
# the admin check of the other policy can. The updates read no column, so PostgreSQL
# applies the UPDATE policies only, not the SELECT ones as well.
QUERIES = {
    "own_data_update_users": f"UPDATE users SET tenant_id = '{OTHER_TENANT}'",
    "own_data_update_orders": f"UPDATE orders SET tenant_id = '{OTHER_TENANT}'",
    "product_management": "SELECT id FROM products",
}


async def _rows_reached(conn, test_schema: str, role_id: UUID, expires_at: str | None, query: str):
    """Number of rows `query` reaches for a user of ACTOR_TENANT with that assignment."""
    actor = uuid4()
    await conn.execute("CREATE TABLE users (id UUID PRIMARY KEY, tenant_id UUID)")
    await conn.execute("CREATE TABLE orders (id UUID PRIMARY KEY, tenant_id UUID, user_id UUID)")
    await conn.execute("CREATE TABLE products (id UUID PRIMARY KEY, tenant_id UUID)")
    rls_sql = (MIGRATIONS / "004_rbac_row_level_security.sql").read_text()
    await conn.execute(rls_sql)
    await conn.execute(rls_sql)  # re-runnable over its own policies

    await conn.execute("INSERT INTO users VALUES (%s, %s)", (uuid4(), OTHER_TENANT))
    await conn.execute("INSERT INTO orders VALUES (%s, %s, %s)", (uuid4(), OTHER_TENANT, uuid4()))
    await conn.execute("INSERT INTO products VALUES (%s, %s)", (uuid4(), OTHER_TENANT))
    await conn.execute(
        "INSERT INTO user_roles (user_id, role_id, tenant_id, expires_at) VALUES (%s, %s, %s, %s)",
        (actor, role_id, ACTOR_TENANT, expires_at),
    )

    db_role = sql.Identifier(f"rls_expiry_{uuid4().hex[:12]}")
    await conn.execute(sql.SQL("CREATE ROLE {} NOSUPERUSER NOBYPASSRLS").format(db_role))
    await conn.execute(
        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(test_schema), db_role)
    )
    await conn.execute(
        sql.SQL("GRANT SELECT, UPDATE ON ALL TABLES IN SCHEMA {} TO {}").format(
            sql.Identifier(test_schema), db_role
        )
    )
    await conn.execute(sql.SQL("SET LOCAL ROLE {}").format(db_role))
    await conn.execute(
        "SELECT set_config('app.tenant_id', %s, TRUE), set_config('app.user_id', %s, TRUE),"
        " set_config('app.is_super_admin', 'false', TRUE)",
        (str(ACTOR_TENANT), str(actor)),
    )
    cur = await conn.execute(query)
    return cur.rowcount


@pytest.fixture
async def rls_conn(rbac_pool):
    async with rbac_pool.connection() as conn, conn.transaction(force_rollback=True):
        yield conn


class TestExamplePoliciesSkipExpiredAssignments:
    @pytest.mark.parametrize("policy", QUERIES)
    @pytest.mark.parametrize("role_id", [ADMIN, SUPER_ADMIN])
    async def test_an_expired_assignment_grants_nothing(
        self, rls_conn, test_schema, policy, role_id
    ) -> None:
        assert await _rows_reached(rls_conn, test_schema, role_id, PAST, QUERIES[policy]) == 0

    @pytest.mark.parametrize("policy", QUERIES)
    @pytest.mark.parametrize("role_id", [ADMIN, SUPER_ADMIN])
    @pytest.mark.parametrize("expires_at", [None, FUTURE])
    async def test_an_unexpired_assignment_still_grants(
        self, rls_conn, test_schema, policy, role_id, expires_at
    ) -> None:
        assert await _rows_reached(rls_conn, test_schema, role_id, expires_at, QUERIES[policy]) == 1

    @pytest.mark.parametrize("policy", QUERIES)
    async def test_another_role_grants_nothing(self, rls_conn, test_schema, policy) -> None:
        assert await _rows_reached(rls_conn, test_schema, MANAGER, None, QUERIES[policy]) == 0
