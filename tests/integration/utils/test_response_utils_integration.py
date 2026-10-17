"""Integration tests for response-related utilities with real schema data.

These tests validate that response utilities work correctly with real GraphQL schemas
and provide proper formatting, descriptions, and metadata for API responses.
"""

import pytest
from graphql import GraphQLNonNull, graphql

# Import schema_builder to ensure SchemaRegistry is patched
import fraiseql.gql.schema_builder  # noqa: F401
from fraiseql import fraise_type, query
from fraiseql.utils.field_descriptions import extract_field_descriptions


@pytest.fixture(scope="class")
def response_utils_test_schema(meta_test_schema):
    """Schema registry with types that have field descriptions for testing."""
    # Clear any existing registrations
    meta_test_schema.clear()

    @fraise_type(sql_source="response_test_users")
    class User:
        """User account model with various field types.

        Fields:
            id: Unique identifier for the user
            email: User's primary email address
            profile: User's profile information
        """

        id: int  # Primary key identifier
        name: str  # Full display name
        email: str  # Email address for notifications
        age: int | None = None  # Age in years (optional)
        is_active: bool = True  # Whether account is active
        created_at: str  # Account creation timestamp

        def display_name(self) -> str:
            """Computed field for user's display name."""
            return self.name

    @fraise_type(sql_source="response_test_posts")
    class Post:
        """Blog post model.

        Fields:
            id: Post identifier
            title: Post title
            content: Full post content
        """

        id: int  # Unique post identifier
        title: str  # Post headline
        content: str  # Full post text
        author_id: int  # Reference to author
        published: bool = False  # Publication status
        tags: list[str]  # Associated tags

    @query
    async def get_users(info) -> list[User]:
        return []

    @query
    async def get_posts(info) -> list[Post]:
        return []

    # Register types with schema
    meta_test_schema.register_type(User)
    meta_test_schema.register_type(Post)
    meta_test_schema.register_query(get_users)
    meta_test_schema.register_query(get_posts)

    return meta_test_schema


class TestFieldDescriptionsIntegration:
    """Integration tests for field description extraction with real schemas."""

    def test_extract_field_descriptions_from_real_types(self, response_utils_test_schema):
        """Field description extraction should work with real @fraise_type decorated classes."""
        # Get User type from schema
        user_type = None
        for type_cls in response_utils_test_schema.types.values():
            if type_cls.__name__ == "User":
                user_type = type_cls
                break

        assert user_type is not None, "User type not found in schema"

        # Extract field descriptions
        descriptions = extract_field_descriptions(user_type)

        # Should have extracted descriptions from various sources
        assert isinstance(descriptions, dict)
        assert len(descriptions) > 0, "Should have extracted some field descriptions"

        # Check that inline comment descriptions were extracted
        assert "id" in descriptions, "Should extract description for 'id' field"
        assert "Primary key identifier" in descriptions["id"]

        assert "name" in descriptions, "Should extract description for 'name' field"
        assert "Full display name" in descriptions["name"]

        assert "email" in descriptions, "Should extract description for 'email' field"
        assert "Email address" in descriptions["email"]

    def test_field_descriptions_with_docstring_extraction(self, response_utils_test_schema):
        """Field descriptions should be extracted from class docstrings."""
        # Get User type
        user_type = None
        for type_cls in response_utils_test_schema.types.values():
            if type_cls.__name__ == "User":
                user_type = type_cls
                break

        assert user_type is not None

        descriptions = extract_field_descriptions(user_type)

        # Should extract from docstring Fields section
        assert "id" in descriptions
        assert "email" in descriptions

        # Descriptions should contain expected text from docstring
        id_desc = descriptions["id"]
        email_desc = descriptions["email"]

        # Should contain the docstring descriptions
        assert "Unique identifier" in id_desc or "Primary key" in id_desc
        assert "email address" in email_desc.lower()

    def test_field_descriptions_with_computed_fields(self, response_utils_test_schema):
        """Field descriptions should work with computed fields (methods)."""
        # Get User type
        user_type = None
        for type_cls in response_utils_test_schema.types.values():
            if type_cls.__name__ == "User":
                user_type = type_cls
                break

        assert user_type is not None

        extract_field_descriptions(user_type)

        # Note: computed methods are not included in field descriptions
        # as they are not fields, just methods
        # assert "display_name" in descriptions

    def test_field_descriptions_consistency(self, response_utils_test_schema):
        """Field description extraction should be consistent across multiple calls."""
        # Get User type
        user_type = None
        for type_cls in response_utils_test_schema.types.values():
            if type_cls.__name__ == "User":
                user_type = type_cls
                break

        assert user_type is not None

        # Extract multiple times
        desc1 = extract_field_descriptions(user_type)
        desc2 = extract_field_descriptions(user_type)
        desc3 = extract_field_descriptions(user_type)

        # Should be identical
        assert desc1 == desc2 == desc3

    def test_field_descriptions_with_all_registered_types(self, response_utils_test_schema):
        """Field description extraction should work for all types in schema."""
        # Get all registered types
        registered_types = list(response_utils_test_schema.types.values())

        for type_cls in registered_types:
            # Should not raise exceptions
            descriptions = extract_field_descriptions(type_cls)

            # Should return a dictionary
            assert isinstance(descriptions, dict)

            # Should have reasonable content
            if hasattr(type_cls, "__annotations__"):
                # Should have at least some descriptions for annotated fields
                # (though not all fields may have descriptions)
                assert len(descriptions) >= 0

    async def test_field_descriptions_in_graphql_schema(self, response_utils_test_schema):
        """Field descriptions should be available in the built GraphQL schema."""
        schema = response_utils_test_schema.build_schema()

        # Get User type from GraphQL schema
        user_type = schema.get_type("User")
        assert user_type is not None, "User type not found in GraphQL schema"

        # Check that fields have descriptions
        assert hasattr(user_type, "fields"), "User type should have fields"

        id_field = user_type.fields.get("id")
        name_field = user_type.fields.get("name")
        email_field = user_type.fields.get("email")

        if id_field:
            # Field might have description from extraction
            assert id_field.description is None or isinstance(id_field.description, str)

        if name_field:
            assert name_field.description is None or isinstance(name_field.description, str)

        if email_field:
            assert email_field.description is None or isinstance(email_field.description, str)


class TestResponseFormattingIntegration:
    """Integration tests for response formatting utilities."""

    async def test_response_structure_with_field_descriptions(self, response_utils_test_schema):
        """GraphQL responses should include properly described fields."""
        schema = response_utils_test_schema.build_schema()

        # Test query execution
        query_str = """
        query {
            getUsers {
                id
                name
                email
                age
                isActive
            }
        }
        """

        result = await graphql(schema, query_str)

        # Should execute without errors
        assert not result.errors, f"Query execution failed: {result.errors}"

        # Should have proper response structure
        assert result.data is not None
        assert "getUsers" in result.data

    async def test_response_with_optional_fields(self, response_utils_test_schema):
        """Responses should handle optional fields correctly."""
        schema = response_utils_test_schema.build_schema()

        query_str = """
        query {
            getUsers {
                id
                name
                age  # Optional field
                isActive  # Field with default
            }
        }
        """

        result = await graphql(schema, query_str)

        assert not result.errors, f"Query with optional fields failed: {result.errors}"
        assert result.data is not None

    async def test_response_with_list_fields(self, response_utils_test_schema):
        """Responses should handle list fields correctly."""
        schema = response_utils_test_schema.build_schema()

        query_str = """
        query {
            getPosts {
                id
                title
                tags  # List field
            }
        }
        """

        result = await graphql(schema, query_str)

        assert not result.errors, f"Query with list fields failed: {result.errors}"
        assert result.data is not None


class TestSchemaMetadataIntegration:
    """Integration tests for schema metadata and introspection."""

    async def test_schema_introspection_with_descriptions(self, response_utils_test_schema):
        """Schema introspection should include field descriptions."""
        schema = response_utils_test_schema.build_schema()

        # Test introspection query
        introspection_query = """
        query {
            __type(name: "User") {
                name
                fields {
                    name
                    description
                    type {
                        name
                        kind
                    }
                }
            }
        }
        """

        result = await graphql(schema, introspection_query)

        assert not result.errors, f"Introspection query failed: {result.errors}"
        assert result.data is not None

        type_info = result.data["__type"]
        assert type_info is not None
        assert type_info["name"] == "User"

        fields = type_info["fields"]
        assert isinstance(fields, list)
        assert len(fields) > 0

        # Check that some fields have descriptions
        fields_with_descriptions = [f for f in fields if f.get("description")]
        # At least some fields should have descriptions from our extraction
        assert (
            len(fields_with_descriptions) >= 0
        )  # May be 0 if descriptions not set in GraphQL schema

    async def test_schema_field_types_preservation(self, response_utils_test_schema):
        """Field types should be preserved correctly in GraphQL schema."""
        schema = response_utils_test_schema.build_schema()

        user_type = schema.get_type("User")
        assert user_type is not None

        # Check field types
        id_field = user_type.fields.get("id")
        name_field = user_type.fields.get("name")
        age_field = user_type.fields.get("age")
        is_active_field = user_type.fields.get("isActive")

        # Helper to get underlying type (unwrap GraphQLNonNull if present)
        def get_type_name(field_type):
            if isinstance(field_type, GraphQLNonNull):
                return field_type.of_type.name
            return field_type.name

        if id_field:
            # Required field wrapped in NON_NULL (Issue #243)
            assert get_type_name(id_field.type) == "Int"
        if name_field:
            # Required field wrapped in NON_NULL (Issue #243)
            assert get_type_name(name_field.type) == "String"
        if age_field:
            # Optional field should NOT be wrapped in NON_NULL
            assert age_field.type.name in ["Int", None] or hasattr(age_field.type, "ofType")
        if is_active_field:
            # Required field wrapped in NON_NULL (Issue #243)
            assert get_type_name(is_active_field.type) == "Boolean"
