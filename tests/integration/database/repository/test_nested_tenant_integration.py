"""Test the nested object tenant_id fix with a real database.

This test creates the necessary database schema and demonstrates that
the fix allows nested objects with sql_source to work without requiring
tenant_id when the data is embedded.
"""

import asyncio
from typing import Optional
from uuid import UUID

import psycopg
import pytest
from graphql import GraphQLResolveInfo

from fraiseql import query
from fraiseql import type as fraiseql_type

pytestmark = pytest.mark.database


async def setup_test_database() -> None:
    """Create a test database with the necessary schema."""
    # Get database connection details from environment
    import os

    # Use environment variables that match GitHub Actions setup
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")
    db_user = os.environ.get("DB_USER", "fraiseql")
    db_password = os.environ.get("DB_PASSWORD", "fraiseql")

    # Connect to PostgreSQL to create test database
    conn = await psycopg.AsyncConnection.connect(
        f"host={db_host} port={db_port} user={db_user} password={db_password} dbname=postgres",
        autocommit=True,
    )

    try:
        # Drop and recreate test database
        await conn.execute("DROP DATABASE IF EXISTS fraiseql_nested_test")
        await conn.execute("CREATE DATABASE fraiseql_nested_test")
    finally:
        await conn.close()

    # Connect to the new test database
    conn = await psycopg.AsyncConnection.connect(
        f"host={db_host} port={db_port} user={db_user} password={db_password} dbname=fraiseql_nested_test"
    )

    try:
        # Create schemas
        await conn.execute("CREATE SCHEMA IF NOT EXISTS tenant")
        await conn.execute("CREATE SCHEMA IF NOT EXISTS public")

        # Create the organizations table
        await conn.execute(
            """
            CREATE TABLE tenant.tb_organization (
                pk_organization UUID PRIMARY KEY,
                name TEXT NOT NULL,
                identifier TEXT UNIQUE NOT NULL,
                data JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """
        )

        # Create the contacts table
        await conn.execute(
            """
            CREATE TABLE tenant.tb_contact (
                pk_contact UUID PRIMARY KEY,
                fk_customer_org UUID NOT NULL REFERENCES tenant.tb_organization(pk_organization),
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                email_address TEXT UNIQUE NOT NULL,
                data JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """
        )

        # Create materialized view for organizations
        await conn.execute(
            """
            CREATE MATERIALIZED VIEW public.mv_organization AS
            SELECT
                pk_organization AS id,
                pk_organization AS tenant_id,  -- org is its own tenant
                jsonb_build_object(
                    'id', pk_organization,
                    'name', name,
                    'identifier', identifier,
                    'status', COALESCE(data->>'status', 'active')
                ) AS data
            FROM tenant.tb_organization
        """
        )

        # Create view for users with EMBEDDED organization data
        await conn.execute(
            """
            CREATE VIEW public.v_user AS
            SELECT
                c.pk_contact AS id,
                c.fk_customer_org AS tenant_id,
                jsonb_build_object(
                    'id', c.pk_contact,
                    'first_name', c.first_name,
                    'last_name', c.last_name,
                    'email_address', c.email_address,
                    'organization', jsonb_build_object(  -- EMBEDDED organization
                        'id', o.pk_organization,
                        'name', o.name,
                        'identifier', o.identifier,
                        'status', COALESCE(o.data->>'status', 'active')
                    )
                ) AS data
            FROM tenant.tb_contact c
            JOIN tenant.tb_organization o ON c.fk_customer_org = o.pk_organization
        """
        )

        # Insert test data
        await conn.execute(
            """
            INSERT INTO tenant.tb_organization (pk_organization, name, identifier, data)
            VALUES (
                '6f726700-0000-0000-0000-000000000000'::uuid,
                'Test Organization',
                'TEST-ORG',
                '{"status": "active", "type": "enterprise"}'::jsonb
            )
        """
        )

        await conn.execute(
            """
            INSERT INTO tenant.tb_contact (
                pk_contact,
                fk_customer_org,
                first_name,
                last_name,
                email_address,
                data
            )
            VALUES (
                '75736572-0000-0000-0000-000000000000'::uuid,
                '6f726700-0000-0000-0000-000000000000'::uuid,
                'Alice',
                'Cooper',
                'alice@example.com',
                '{"role": "admin", "department": "Engineering"}'::jsonb
            )
        """
        )

        # Refresh materialized view
        await conn.execute("REFRESH MATERIALIZED VIEW public.mv_organization")

        await conn.commit()
        return conn
    except Exception:
        await conn.rollback()
        await conn.close()
        raise


# Define GraphQL types with sql_source
@fraiseql_type(sql_source="mv_organization")
class Organization:
    """Organization type with sql_source pointing to materialized view."""

    id: UUID
    name: str
    identifier: str
    status: str = "active"

    @classmethod
    def from_dict(cls, data: dict) -> None:
        """Create Organization from dictionary."""
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            identifier=data.get("identifier"),
            status=data.get("status", "active"),
        )


@fraiseql_type(sql_source="v_user")
class User:
    """User type with embedded organization in JSONB data."""

    id: UUID
    first_name: str
    last_name: str
    email_address: str
    organization: Optional[Organization] = None  # This is EMBEDDED in data column

    @classmethod
    def from_dict(cls, data: dict) -> None:
        """Create User from dictionary."""
        org_data = data.get("organization")
        org = None
        if org_data:
            org = Organization.from_dict(org_data)

        return cls(
            id=data.get("id"),
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            email_address=data.get("email_address"),
            organization=org,
        )


@pytest.mark.asyncio
async def test_nested_organization_without_tenant_id() -> None:
    """Test that querying user with nested organization works without tenant_id."""
    # Skip in CI environment where database setup may differ
    import os

    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.skip("Test requires complex database setup not available in CI")

    # Define database connection variables first
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")
    db_user = os.environ.get("DB_USER", "fraiseql")
    db_password = os.environ.get("DB_PASSWORD", "fraiseql")

    # Skip if no local database available
    try:
        # Try a quick connection test first
        test_conn = await psycopg.AsyncConnection.connect(
            f"host={db_host} port={db_port} user={db_user} password={db_password} dbname=postgres",
            autocommit=True,
            connect_timeout=1,
        )
        await test_conn.close()
    except Exception:
        pytest.skip("Test requires PostgreSQL database connection")

    # Setup database
    conn = await setup_test_database()

    try:
        # Create a FraiseQL repository wrapper
        from fraiseql.cqrs.repository import CQRSRepository

        class TestRepository(CQRSRepository):
            async def find_one(self, table: str, **kwargs) -> None:
                """Find one record from a table/view."""
                where_conditions = []
                params = []

                for key, value in kwargs.items():
                    where_conditions.append(f"{key} = %s")
                    params.append(value)

                where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

                query = f"SELECT data FROM {table} WHERE {where_clause} LIMIT 1"

                async with self.connection.cursor() as cursor:
                    await cursor.execute(query, params)
                    result = await cursor.fetchone()

                    if result:
                        return result[0]  # Return the JSONB data
                    return None

        db = TestRepository(conn)

        # Define query resolver
        @query
        async def user(info: GraphQLResolveInfo, user_id: Optional[UUID] = None) -> Optional[User]:
            """Query to get a user by ID."""
            db = info.context["db"]

            # Use a fixed test user ID if not provided
            if user_id is None:
                user_id = UUID("75736572-0000-0000-0000-000000000000")

            result = await db.find_one("v_user", mandatory_filters={"id": user_id})

            if result:
                return User.from_dict(result)
            return None

        # Build GraphQL schema
        from fraiseql.gql.builders.registry import SchemaRegistry
        from fraiseql.gql.builders.schema_composer import SchemaComposer

        registry = SchemaRegistry()
        registry.register_query(user)  # Just pass the function
        registry.register_type(User)
        registry.register_type(Organization)

        composer = SchemaComposer(registry)
        schema = composer.compose()

        # Execute GraphQL query
        from graphql import graphql

        query_str = """
        query GetUser {
          user {
            id
            firstName
            lastName
            emailAddress
            organization {
              id
              name
              identifier
              status
            }
          }
        }
        """

        # Context WITHOUT tenant_id - this is the key test
        context = {
            "db": db,
            # Note: NOT providing tenant_id
        }

        result = await graphql(schema, query_str, context_value=context)

        # Check results
        if result.errors:
            error_messages = [str(e) for e in result.errors]

            # The bug would cause "missing a required argument: 'tenant_id'" error
            has_tenant_error = any("tenant_id" in msg.lower() for msg in error_messages)

            if has_tenant_error:
                pytest.fail(
                    f"❌ Bug still present: Got tenant_id error when querying embedded organization.\n"
                    f"Errors: {error_messages}"
                )

        # Verify the data was returned correctly
        assert result.data is not None, "No data returned"
        assert result.data["user"] is not None, "User data is None"

        user_data = result.data["user"]
        assert user_data["firstName"] == "Alice"
        assert user_data["lastName"] == "Cooper"
        assert user_data["emailAddress"] == "alice@example.com"

        # Most importantly, the organization should be returned
        assert user_data["organization"] is not None, (
            "Organization data is None (embedded data not returned)"
        )

        org_data = user_data["organization"]
        assert org_data["name"] == "Test Organization"
        assert org_data["identifier"] == "TEST-ORG"
        assert org_data["status"] == "active"

    finally:
        # Cleanup
        await conn.close()

        # Drop test database
        cleanup_conn = await psycopg.AsyncConnection.connect(
            f"host={db_host} port={db_port} user={db_user} password={db_password} dbname=postgres",
            autocommit=True,
        )
        await cleanup_conn.execute("DROP DATABASE IF EXISTS fraiseql_nested_test")
        await cleanup_conn.close()


@pytest.mark.asyncio
async def test_comparison_with_and_without_embedded() -> None:
    """Compare behavior with embedded vs non-embedded organization data."""
    # Skip in CI environment where database setup may differ
    import os

    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.skip("Test requires complex database setup not available in CI")

    # Define database connection variables first
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")
    db_user = os.environ.get("DB_USER", "fraiseql")
    db_password = os.environ.get("DB_PASSWORD", "fraiseql")

    # Skip if no local database available
    try:
        # Try a quick connection test first
        test_conn = await psycopg.AsyncConnection.connect(
            f"host={db_host} port={db_port} user={db_user} password={db_password} dbname=postgres",
            autocommit=True,
            connect_timeout=1,
        )
        await test_conn.close()
    except Exception:
        pytest.skip("Test requires PostgreSQL database connection")

    # Setup database
    conn = await setup_test_database()

    try:
        # Also create a view WITHOUT embedded organization (for comparison)
        await conn.execute(
            """
            CREATE VIEW public.v_user_no_embed AS
            SELECT
                c.pk_contact AS id,
                c.fk_customer_org AS tenant_id,
                jsonb_build_object(
                    'id', c.pk_contact,
                    'first_name', c.first_name,
                    'last_name', c.last_name,
                    'email_address', c.email_address,
                    'organization_id', c.fk_customer_org  -- Just the FK, not embedded
                ) AS data
            FROM tenant.tb_contact c
        """
        )
        await conn.commit()

        from fraiseql.cqrs.repository import CQRSRepository

        class TestRepository(CQRSRepository):
            async def find_one(self, table: str, **kwargs) -> None:
                """Find one record from a table/view."""
                where_conditions = []
                params = []

                for key, value in kwargs.items():
                    where_conditions.append(f"{key} = %s")
                    params.append(value)

                where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

                query = f"SELECT data FROM {table} WHERE {where_clause} LIMIT 1"

                async with self.connection.cursor() as cursor:
                    await cursor.execute(query, params)
                    result = await cursor.fetchone()

                    if result:
                        return result[0]
                    return None

        db = TestRepository(conn)

        # Test 1: With embedded data (should work)
        result = await db.find_one("v_user", id=UUID("75736572-0000-0000-0000-000000000000"))
        assert result is not None
        assert "organization" in result
        assert result["organization"]["name"] == "Test Organization"

        # Test 2: Without embedded data (would need separate query)
        result = await db.find_one(
            "v_user_no_embed", id=UUID("75736572-0000-0000-0000-000000000000")
        )
        assert result is not None
        assert "organization" not in result  # No embedded org
        assert "organization_id" in result  # Just the FK

    finally:
        await conn.close()

        # Cleanup
        cleanup_conn = await psycopg.AsyncConnection.connect(
            "host=localhost port=5432 user=postgres dbname=postgres", autocommit=True
        )
        await cleanup_conn.execute("DROP DATABASE IF EXISTS fraiseql_nested_test")
        await cleanup_conn.close()


if __name__ == "__main__":
    # Run tests directly
    asyncio.run(test_nested_organization_without_tenant_id())
    asyncio.run(test_comparison_with_and_without_embedded())
