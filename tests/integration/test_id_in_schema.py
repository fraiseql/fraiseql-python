"""Integration tests for ID type in schema."""

import pytest
from graphql import graphql

import fraiseql
from fraiseql.types import ID


@pytest.fixture
async def schema_with_id(class_db_pool):
    """Create schema with ID type."""

    @fraiseql.type
    class User:
        id: ID
        name: str
        email: str

    # Simple query function instead of class
    async def users(info) -> list[User]:
        """Fetch all users."""
        return []

    schema = fraiseql.build_fraiseql_schema(query_types=[users])

    # Create table
    async with class_db_pool.connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tb_user (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE
            )
        """)
        await conn.execute("TRUNCATE tb_user")

        # Insert test data
        await conn.execute("""
            INSERT INTO tb_user (name, email) VALUES
            ('Alice', 'alice@example.com'),
            ('Bob', 'bob@example.com')
        """)

    yield schema

    # Cleanup
    async with class_db_pool.connection() as conn:
        await conn.execute("DROP TABLE IF EXISTS tb_user")


async def test_id_in_graphql_query(schema_with_id):
    """Test ID type in GraphQL query."""
    query = """
        query {
            users {
                id
                name
                email
            }
        }
    """

    result = await graphql(schema_with_id, query)

    assert result.errors is None
    assert len(result.data["users"]) == 0  # Query returns empty list

    # The test mainly verifies that ID type is recognized in schema


async def test_id_type_in_schema_introspection(schema_with_id):
    """Test that ID appears correctly in schema introspection."""
    introspection_query = """
        query {
            __type(name: "User") {
                fields {
                    name
                    type {
                        name
                        kind
                        ofType {
                            name
                            kind
                        }
                    }
                }
            }
        }
    """

    result = await graphql(schema_with_id, introspection_query)

    assert result.errors is None

    # Find id field
    fields = result.data["__type"]["fields"]
    id_field = next(f for f in fields if f["name"] == "id")

    # Check that type is ID (not UUID) - field is now non-null wrapped
    if id_field["type"]["kind"] == "NON_NULL":
        assert id_field["type"]["ofType"]["name"] == "ID"
    else:
        assert id_field["type"]["name"] == "ID"
