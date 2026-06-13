"""Regression test for enum variables causing empty nested fields (v1.9.18 bug).

Issue: Users on v1.9.18 experience empty nested fields when enum arguments are
passed as GraphQL variables (not inline literals).

Expected behavior:
- Query with inline enum literal: ✅ nested fields populated
- Query with enum variable: ✅ nested fields populated (CURRENTLY FAILS)

This test reproduces the bug and will be used to validate the fix.
"""

from enum import Enum
from typing import Any

import pytest
from graphql import (
    GraphQLArgument,
    GraphQLEnumType,
    GraphQLEnumValue,
    GraphQLField,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
)

import fraiseql

pytestmark = pytest.mark.regression


@fraiseql.enum
class Status(Enum):
    """Task status enum."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PENDING = "PENDING"


@fraiseql.type
class User:
    """User type with nested fields."""

    id: str
    name: str
    status: str


class TestEnumVariableBug:
    """Test that reproduces the enum variable nested field bug."""

    @staticmethod
    def build_test_schema() -> GraphQLSchema:
        """Build a simple GraphQL schema for testing enum variables."""
        # Define the Status enum in GraphQL
        status_enum = GraphQLEnumType(
            "Status",
            {
                "ACTIVE": GraphQLEnumValue("ACTIVE"),
                "INACTIVE": GraphQLEnumValue("INACTIVE"),
                "PENDING": GraphQLEnumValue("PENDING"),
            },
        )

        # Define the User object type with nested fields
        user_type = GraphQLObjectType(
            "User",
            {
                "id": GraphQLField(GraphQLNonNull(GraphQLString)),
                "name": GraphQLField(GraphQLNonNull(GraphQLString)),
                "status": GraphQLField(GraphQLNonNull(GraphQLString)),
            },
        )

        # Query type that filters users by status
        def resolve_user_by_status(
            root: Any, info: Any, status: str | Status
        ) -> dict[str, str]:
            # Convert enum to string if needed for comparison
            status_str = status.value if isinstance(status, Status) else status

            # Simulate finding a user
            if status_str == "ACTIVE":
                return {"id": "1", "name": "Alice", "status": "ACTIVE"}
            if status_str == "INACTIVE":
                return {"id": "2", "name": "Bob", "status": "INACTIVE"}
            return {"id": "3", "name": "Charlie", "status": "PENDING"}

        query_type = GraphQLObjectType(
            "Query",
            {
                "userByStatus": GraphQLField(
                    user_type,
                    args={
                        "status": GraphQLArgument(GraphQLNonNull(status_enum)),
                    },
                    resolve=resolve_user_by_status,
                ),
            },
        )

        return GraphQLSchema(query_type)

    def test_enum_inline_literal_with_nested_fields(self) -> None:
        """Test that inline enum literals work with nested fields.

        This is the control test - it should PASS.
        """
        schema = self.build_test_schema()

        # Query with inline enum literal (WORKS)
        query = """
        {
            userByStatus(status: ACTIVE) {
                id
                name
                status
            }
        }
        """

        result = graphql_sync(schema, query)

        # Verify no errors
        assert result.errors is None, f"Unexpected errors: {result.errors}"

        # Verify nested fields are populated
        assert result.data is not None
        user = result.data["userByStatus"]
        assert user is not None
        assert user["id"] == "1"
        assert user["name"] == "Alice"  # This should be populated
        assert user["status"] == "ACTIVE"

    def test_enum_variable_with_nested_fields(self) -> None:
        """Test that enum variables work with nested fields.

        This is the failing test - it currently returns empty nested fields.
        Related to GitHub issue #287.

        CURRENTLY FAILS: nested fields are empty when enum is a variable
        """
        schema = self.build_test_schema()

        # Query with enum variable (CURRENTLY FAILS)
        query = """
        query GetUserByStatus($status: Status!) {
            userByStatus(status: $status) {
                id
                name
                status
            }
        }
        """

        variables = {"status": "ACTIVE"}

        result = graphql_sync(schema, query, variable_values=variables)

        # Verify no errors
        assert result.errors is None, f"Unexpected errors: {result.errors}"

        # Verify nested fields are populated (THIS IS CURRENTLY FAILING)
        assert result.data is not None
        user = result.data["userByStatus"]
        assert user is not None, "User should not be None"
        assert user["id"] == "1", f"Expected id='1', got {user.get('id')}"
        assert (
            user["name"] == "Alice"
        ), f"Expected name='Alice', got {user.get('name')} - BUG: nested field is empty when enum is variable!"
        assert user["status"] == "ACTIVE"

    def test_enum_variable_inline_literal_comparison(self) -> None:
        """Compare results between inline literal and variable.

        This test should show the difference in behavior.
        """
        schema = self.build_test_schema()

        # Query with inline literal
        inline_query = """
        {
            userByStatus(status: ACTIVE) {
                id
                name
                status
            }
        }
        """

        # Query with variable
        variable_query = """
        query GetUserByStatus($status: Status!) {
            userByStatus(status: $status) {
                id
                name
                status
            }
        }
        """

        inline_result = graphql_sync(schema, inline_query)
        variable_result = graphql_sync(
            schema, variable_query, variable_values={"status": "ACTIVE"}
        )

        # Both should have the same data
        assert inline_result.errors is None
        assert variable_result.errors is None

        inline_user = inline_result.data["userByStatus"]
        variable_user = variable_result.data["userByStatus"]

        # Both should have the same nested field values
        assert (
            inline_user == variable_user
        ), f"Inline: {inline_user}, Variable: {variable_user} - Results differ!"
