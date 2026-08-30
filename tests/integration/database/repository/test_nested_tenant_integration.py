"""A nested object with its own ``sql_source`` resolves from embedded JSONB.

``User.organization`` is declared with ``sql_source="mv_organization"`` but its
data is embedded in ``v_user``'s ``data`` column. Resolving it must not demand a
``tenant_id`` from the GraphQL context, because nothing needs to be looked up.

The tests run against the shared test container through ``class_db_pool`` and
``test_schema``. They previously built their own connection from ``DB_HOST`` and
friends and created a whole ``fraiseql_nested_test`` database, then skipped
themselves whenever ``GITHUB_ACTIONS`` was set -- so CI never ran them and
``test_nested_organization_without_tenant_id`` sat red for three and a half
months without anything reporting it (#516).
"""

from typing import Any, Optional
from uuid import UUID

import pytest
import pytest_asyncio
from graphql import GraphQLResolveInfo
from psycopg.sql import SQL, Identifier

from fraiseql import query
from fraiseql import type as fraiseql_type

pytestmark = pytest.mark.database

ORG_ID = UUID("6f726700-0000-0000-0000-000000000000")
USER_ID = UUID("75736572-0000-0000-0000-000000000000")


@fraiseql_type(sql_source="mv_organization")
class Organization:
    """Organization type with sql_source pointing to materialized view."""

    id: UUID
    name: str
    identifier: str
    status: str = "active"

    @classmethod
    def from_dict(cls, data: dict) -> "Organization":
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
    def from_dict(cls, data: dict) -> "User":
        """Create User from dictionary."""
        org_data = data.get("organization")
        org = Organization.from_dict(org_data) if org_data else None

        return cls(
            id=data.get("id"),
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            email_address=data.get("email_address"),
            organization=org,
        )


class StubRepository:
    """Minimal ``find_one`` over a raw connection, for resolvers under test.

    One definition rather than a copy per test: the two copies this replaces
    drifted apart, and only the one that had been updated to pass
    ``mandatory_filters`` was broken by it (#516).
    """

    def __init__(self, connection) -> None:
        self.connection = connection

    async def find_one(self, table: str, **kwargs: Any) -> dict[str, Any] | None:
        """Return one row's ``data``, honouring the real ``mandatory_filters`` contract.

        ``FraiseQLRepository.find_one`` takes ``mandatory_filters`` as a mapping
        of column to value and AND-s it into the WHERE clause. Treating it as a
        column in its own right -- as this stub did until #516 -- builds
        ``WHERE mandatory_filters = %s`` and hands psycopg a dict, which raises
        ``cannot adapt type 'dict' using placeholder '%s'``. GraphQL then
        recorded that as a field error and resolved the field to ``None``.
        """
        filters: dict[str, Any] = {}
        for key, value in kwargs.items():
            if key == "mandatory_filters":
                filters.update(value or {})
            else:
                filters[key] = value

        statement = SQL("SELECT data FROM {}").format(Identifier(table))
        if filters:
            predicates = SQL(" AND ").join(
                SQL("{} = %s").format(Identifier(column)) for column in filters
            )
            statement = statement + SQL(" WHERE ") + predicates
        statement = statement + SQL(" LIMIT 1")

        async with self.connection.cursor() as cursor:
            await cursor.execute(statement, list(filters.values()))
            row = await cursor.fetchone()
            return row[0] if row else None


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def nested_tenant_schema(class_db_pool, test_schema) -> None:
    """Build the tables and views the resolvers query, inside the class schema."""
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")

        await conn.execute(
            """
            CREATE TABLE tb_organization (
                pk_organization UUID PRIMARY KEY,
                name TEXT NOT NULL,
                identifier TEXT UNIQUE NOT NULL,
                data JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE tb_contact (
                pk_contact UUID PRIMARY KEY,
                fk_customer_org UUID NOT NULL REFERENCES tb_organization(pk_organization),
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                email_address TEXT UNIQUE NOT NULL,
                data JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )

        await conn.execute(
            """
            INSERT INTO tb_organization (pk_organization, name, identifier, data)
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
            INSERT INTO tb_contact (
                pk_contact, fk_customer_org, first_name, last_name, email_address, data
            )
            VALUES (
                '75736572-0000-0000-0000-000000000000'::uuid,
                '6f726700-0000-0000-0000-000000000000'::uuid,
                'Alice', 'Cooper', 'alice@example.com',
                '{"role": "admin", "department": "Engineering"}'::jsonb
            )
            """
        )

        await conn.execute(
            """
            CREATE MATERIALIZED VIEW mv_organization AS
            SELECT
                pk_organization AS id,
                pk_organization AS tenant_id,  -- org is its own tenant
                jsonb_build_object(
                    'id', pk_organization,
                    'name', name,
                    'identifier', identifier,
                    'status', COALESCE(data->>'status', 'active')
                ) AS data
            FROM tb_organization
            """
        )

        # The organization is embedded in the user's own data column.
        await conn.execute(
            """
            CREATE VIEW v_user AS
            SELECT
                c.pk_contact AS id,
                c.fk_customer_org AS tenant_id,
                jsonb_build_object(
                    'id', c.pk_contact,
                    'first_name', c.first_name,
                    'last_name', c.last_name,
                    'email_address', c.email_address,
                    'organization', jsonb_build_object(
                        'id', o.pk_organization,
                        'name', o.name,
                        'identifier', o.identifier,
                        'status', COALESCE(o.data->>'status', 'active')
                    )
                ) AS data
            FROM tb_contact c
            JOIN tb_organization o ON c.fk_customer_org = o.pk_organization
            """
        )

        # The same user carrying only the foreign key, for the comparison test.
        await conn.execute(
            """
            CREATE VIEW v_user_no_embed AS
            SELECT
                c.pk_contact AS id,
                c.fk_customer_org AS tenant_id,
                jsonb_build_object(
                    'id', c.pk_contact,
                    'first_name', c.first_name,
                    'last_name', c.last_name,
                    'email_address', c.email_address,
                    'organization_id', c.fk_customer_org
                ) AS data
            FROM tb_contact c
            """
        )

        await conn.commit()


@pytest.mark.usefixtures("nested_tenant_schema")
class TestNestedOrganizationEmbedding:
    """Embedded nested data must resolve without a tenant_id in the context."""

    @staticmethod
    async def _repository(pool, schema) -> tuple[Any, Any]:
        """Open a connection on the class schema and wrap it for the resolver."""
        conn = await pool.getconn()
        await conn.execute(f"SET search_path TO {schema}, public")
        return conn, StubRepository(conn)

    async def test_nested_organization_without_tenant_id(
        self, class_db_pool, test_schema
    ) -> None:
        """A query with no tenant_id in context must still return the organization."""
        from graphql import graphql

        from fraiseql.gql.builders.registry import SchemaRegistry
        from fraiseql.gql.builders.schema_composer import SchemaComposer

        conn, db = await self._repository(class_db_pool, test_schema)
        try:

            @query
            async def user(
                info: GraphQLResolveInfo, user_id: Optional[UUID] = None
            ) -> Optional[User]:
                """Query to get a user by ID."""
                repo = info.context["db"]
                result = await repo.find_one(
                    "v_user", mandatory_filters={"id": user_id or USER_ID}
                )
                return User.from_dict(result) if result else None

            registry = SchemaRegistry()
            registry.register_query(user)
            registry.register_type(User)
            registry.register_type(Organization)
            schema = SchemaComposer(registry).compose()

            query_str = """
            query GetUser {
              user {
                id
                firstName
                lastName
                emailAddress
                organization { id name identifier status }
              }
            }
            """

            # Deliberately no tenant_id: that is the whole point of the test.
            result = await graphql(schema, query_str, context_value={"db": db})

            # Every error is reported, not just the tenant_id one. Checking only
            # for "tenant_id" let an unrelated psycopg adapter failure through in
            # silence, so the test reported "User data is None" -- the
            # consequence -- for three and a half months instead of the cause
            # (#516).
            assert not result.errors, f"GraphQL errors: {[str(e) for e in result.errors]}"

            assert result.data is not None, "No data returned"
            assert result.data["user"] is not None, "User data is None"

            user_data = result.data["user"]
            assert user_data["firstName"] == "Alice"
            assert user_data["lastName"] == "Cooper"
            assert user_data["emailAddress"] == "alice@example.com"

            assert user_data["organization"] is not None, (
                "Organization data is None (embedded data not returned)"
            )
            assert user_data["organization"]["name"] == "Test Organization"
            assert user_data["organization"]["identifier"] == "TEST-ORG"
            assert user_data["organization"]["status"] == "active"
        finally:
            await class_db_pool.putconn(conn)

    async def test_mandatory_filters_and_direct_columns_agree(
        self, class_db_pool, test_schema
    ) -> None:
        """``mandatory_filters={"id": x}`` must select the same row as ``id=x``.

        The regression in #516 was exactly this divergence: the stub understood
        one spelling and not the other, so the resolver silently returned
        nothing.
        """
        conn, db = await self._repository(class_db_pool, test_schema)
        try:
            direct = await db.find_one("v_user", id=USER_ID)
            mandatory = await db.find_one("v_user", mandatory_filters={"id": USER_ID})

            assert direct is not None
            assert direct == mandatory
        finally:
            await class_db_pool.putconn(conn)

    async def test_comparison_with_and_without_embedded(
        self, class_db_pool, test_schema
    ) -> None:
        """Only the embedding view carries the organization; the other has the FK."""
        conn, db = await self._repository(class_db_pool, test_schema)
        try:
            embedded = await db.find_one("v_user", id=USER_ID)
            assert embedded is not None
            assert "organization" in embedded
            assert embedded["organization"]["name"] == "Test Organization"

            flat = await db.find_one("v_user_no_embed", id=USER_ID)
            assert flat is not None
            assert "organization" not in flat, "No embedded org expected"
            assert "organization_id" in flat, "Expected just the FK"
            assert UUID(flat["organization_id"]) == ORG_ID
        finally:
            await class_db_pool.putconn(conn)
