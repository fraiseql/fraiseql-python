"""Docstring extraction for GraphQL schema descriptions."""

import pytest
from graphql import GraphQLObjectType

import fraiseql
from fraiseql.core.graphql_type import convert_type_to_graphql_output

# These tests build schemas from the global SchemaRegistry, which other tests in the
# same process leave types in; start each one from an empty registry.
pytestmark = pytest.mark.usefixtures("clear_registry")


class TestTypeDescriptions:
    def test_fraise_type_uses_docstring_as_description(self) -> None:
        @fraiseql.type(sql_source="test_table")
        class TestUser:
            """A user in the system with authentication and profile data."""

            id: int
            name: str
            email: str

        gql_type = convert_type_to_graphql_output(TestUser)
        assert isinstance(gql_type, GraphQLObjectType)
        assert gql_type.description == "A user in the system with authentication and profile data."

    def test_fraise_type_without_docstring_has_no_description(self) -> None:
        @fraiseql.type(sql_source="test_table")
        class TestProduct:
            id: int
            name: str
            price: float

        gql_type = convert_type_to_graphql_output(TestProduct)
        assert isinstance(gql_type, GraphQLObjectType)
        assert gql_type.description is None

    def test_fraise_type_multiline_docstring_is_cleaned(self) -> None:
        @fraiseql.type(sql_source="test_table")
        class TestOrder:
            """An order in the e-commerce system.

            Contains line items, customer information,
            and payment details.
            """

            id: int
            customer_id: int
            total: float

        gql_type = convert_type_to_graphql_output(TestOrder)
        assert isinstance(gql_type, GraphQLObjectType)
        expected_description = "An order in the e-commerce system.\n\nContains line items, customer information,\nand payment details."
        assert gql_type.description == expected_description

    def test_fraise_type_description_in_built_schema(self) -> None:
        @fraiseql.type(sql_source="posts")
        class Post:
            """A blog post with content and metadata."""

            id: int
            title: str
            content: str

        from fraiseql.gql.schema_builder import build_fraiseql_schema

        @fraiseql.query
        @pytest.mark.asyncio
        async def test_query(info) -> str:
            return "test"

        schema = build_fraiseql_schema(
            query_types=[Post],
            mutation_resolvers=[],
        )

        post_type = schema.type_map.get("Post")
        assert post_type is not None
        assert isinstance(post_type, GraphQLObjectType)
        assert post_type.description == "A blog post with content and metadata."

    def test_fraise_type_description_preserved_with_existing_functionality(self) -> None:
        @fraiseql.type(sql_source="users")
        class DetailedUser:
            """A comprehensive user model with rich metadata."""

            id: int
            name: str = fraiseql.fraise_field(description="Full name of the user")
            email: str = fraiseql.fraise_field(description="Primary email address")

        gql_type = convert_type_to_graphql_output(DetailedUser)
        assert isinstance(gql_type, GraphQLObjectType)
        assert gql_type.description == "A comprehensive user model with rich metadata."

        name_field = gql_type.fields["name"]
        email_field = gql_type.fields["email"]
        assert name_field.description == "Full name of the user"
        assert email_field.description == "Primary email address"
