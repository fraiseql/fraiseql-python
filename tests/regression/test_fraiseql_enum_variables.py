"""Test enum variables with FraiseQL schema generation.

This test uses FraiseQL's actual decorator-based API to reproduce the bug
where nested fields are empty when enum arguments are passed as variables.
"""

import asyncio
from enum import Enum

import pytest
from graphql import graphql

import fraiseql

pytestmark = pytest.mark.regression


@fraiseql.enum
class Status(Enum):
    """Task status."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PENDING = "PENDING"


@fraiseql.type
class User:
    """User type."""

    id: str
    name: str
    email: str
    status: Status


async def user_by_status(info, status: Status) -> User:
    """Get user by status."""
    # Simulate database lookup
    if status == Status.ACTIVE:
        return User(id="1", name="Alice", email="alice@example.com", status=Status.ACTIVE)
    elif status == Status.INACTIVE:
        return User(id="2", name="Bob", email="bob@example.com", status=Status.INACTIVE)
    else:
        return User(id="3", name="Charlie", email="charlie@example.com", status=Status.PENDING)


class TestFraiseQLEnumVariables:
    """Test enum variables with FraiseQL schema."""

    @pytest.mark.asyncio
    async def test_enum_inline_literal(self, clear_registry) -> None:
        """Test enum as inline literal (should work)."""
        schema = fraiseql.build_fraiseql_schema(query_types=[user_by_status])

        query = """
        {
            userByStatus(status: ACTIVE) {
                id
                name
                email
                status
            }
        }
        """

        result = await graphql(schema, query)

        assert result.errors is None or len(result.errors) == 0, f"Errors: {result.errors}"
        assert result.data is not None
        user = result.data["userByStatus"]
        assert user["id"] == "1"
        assert user["name"] == "Alice"
        assert user["email"] == "alice@example.com"
        assert user["status"] == "ACTIVE"

    @pytest.mark.asyncio
    async def test_enum_variable(self, clear_registry) -> None:
        """Test enum as variable (currently fails with empty nested fields).

        This is the bug: nested fields are empty when enum is a variable.
        """
        schema = fraiseql.build_fraiseql_schema(query_types=[user_by_status])

        query = """
        query GetUserByStatus($status: Status!) {
            userByStatus(status: $status) {
                id
                name
                email
                status
            }
        }
        """

        variables = {"status": "ACTIVE"}

        result = await graphql(schema, query, variable_values=variables)

        assert result.errors is None or len(result.errors) == 0, f"Errors: {result.errors}"
        assert result.data is not None
        user = result.data["userByStatus"]

        # These assertions verify the bug:
        # When enum is a variable, nested fields should still be populated
        assert user["id"] == "1", f"Expected id='1', got {user.get('id')}"
        assert user["name"] == "Alice", (
            f"Expected name='Alice', got {user.get('name')} - "
            "BUG: nested field empty when enum is variable!"
        )
        assert user["email"] == "alice@example.com", f"Expected email, got {user.get('email')}"
        assert user["status"] == "ACTIVE"

    @pytest.mark.asyncio
    async def test_enum_variable_multiple_fields(self, clear_registry) -> None:
        """Test enum variable with multiple enum arguments."""
        # This is a more complex scenario

        @fraiseql.enum
        class Role(Enum):
            """User role."""

            ADMIN = "ADMIN"
            USER = "USER"

        @fraiseql.type
        class UserWithRole:
            """User with role."""

            id: str
            name: str
            status: Status
            role: Role

        async def find_user(info, status: Status, role: Role) -> UserWithRole:
            """Find user by status and role."""
            return UserWithRole(
                id="1",
                name="Alice",
                status=status,
                role=role,
            )

        schema = fraiseql.build_fraiseql_schema(query_types=[find_user])

        query = """
        query FindUser($status: Status!, $role: Role!) {
            findUser(status: $status, role: $role) {
                id
                name
                status
                role
            }
        }
        """

        variables = {"status": "ACTIVE", "role": "ADMIN"}

        result = await graphql(schema, query, variable_values=variables)

        assert result.errors is None or len(result.errors) == 0, f"Errors: {result.errors}"
        assert result.data is not None
        user = result.data["findUser"]

        # Verify all fields are populated
        assert user["id"] == "1"
        assert user["name"] == "Alice"
        assert user["status"] == "ACTIVE"
        assert user["role"] == "ADMIN"
