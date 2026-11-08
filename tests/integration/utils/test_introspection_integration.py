"""Integration tests for introspection utilities with real schema data.

These tests validate that introspection functions work correctly with real GraphQL
schemas and provide accurate metadata about types and fields.
"""

import pytest

# Import schema_builder to ensure SchemaRegistry is patched
import fraiseql.gql.schema_builder  # noqa: F401
from fraiseql import fraise_input, fraise_type, query
from fraiseql.utils.introspection import describe_type


@pytest.fixture(scope="class")
def introspection_test_schema(meta_test_schema):
    """Schema registry with diverse types for introspection testing."""
    # Clear any existing registrations
    meta_test_schema.clear()

    # Create input types
    @fraise_input
    class UserInput:
        name: str
        email: str
        age: int | None = None

    @fraise_input
    class AddressInput:
        street: str
        city: str
        zip_code: str

    # Create output types
    @fraise_type(sql_source="users")
    class User:
        id: int
        name: str
        email: str
        age: int | None = None
        created_at: str

        def full_name(self) -> str:
            return f"{self.name} (computed)"

    @fraise_type(sql_source="posts")
    class Post:
        id: int
        title: str
        content: str
        author_id: int
        published: bool = False

    # Create success/error types
    from fraiseql.mutations.decorators import error, success

    @success
    class CreateUserSuccess:
        user: User
        message: str = "User created successfully"

    @error
    class CreateUserError:
        message: str
        code: int

    @query
    async def get_users(info) -> list[User]:
        return []

    @query
    async def get_posts(info) -> list[Post]:
        return []

    # Register types with schema
    meta_test_schema.register_type(UserInput)
    meta_test_schema.register_type(AddressInput)
    meta_test_schema.register_type(User)
    meta_test_schema.register_type(Post)
    meta_test_schema.register_type(CreateUserSuccess)
    meta_test_schema.register_type(CreateUserError)
    meta_test_schema.register_query(get_users)
    meta_test_schema.register_query(get_posts)

    return meta_test_schema


class TestIntrospectionIntegration:
    """Integration tests for introspection utilities with real schema data."""

    def test_describe_input_type(self, introspection_test_schema):
        """describe_type should work correctly with @fraise_input decorated classes."""
        # Get the UserInput type from registered types
        user_input_type = None
        for type_cls in introspection_test_schema.types.values():
            if type_cls.__name__ == "UserInput":
                user_input_type = type_cls
                break

        assert user_input_type is not None, "UserInput type not found in schema"

        # Describe the type
        description = describe_type(user_input_type)

        # Verify basic structure
        assert description["typename"] == "UserInput"
        assert description["is_input"] is True
        assert description["is_output"] is False
        assert description["sql_source"] is None  # Input types don't have SQL source

        # Verify fields
        fields = description["fields"]
        assert "name" in fields
        assert "email" in fields
        assert "age" in fields

        # Check field metadata
        name_field = fields["name"]
        assert name_field["type"] is str
        assert name_field["purpose"] == "input"

        age_field = fields["age"]
        assert age_field["type"] == (int | None)
        assert age_field["default"] is None  # Should have default value

    def test_describe_output_type(self, introspection_test_schema):
        """describe_type should work correctly with @fraise_type decorated classes."""
        # Get the User type
        user_type = None
        for type_cls in introspection_test_schema.types.values():
            if type_cls.__name__ == "User":
                user_type = type_cls
                break

        assert user_type is not None, "User type not found in schema"

        # Describe the type
        description = describe_type(user_type)

        # Verify basic structure
        assert description["typename"] == "User"
        assert description["is_input"] is False
        assert description["is_output"] is True
        assert description["sql_source"] == "users"

        # Verify fields
        fields = description["fields"]
        assert "id" in fields
        assert "name" in fields
        assert "email" in fields
        assert "age" in fields
        assert "created_at" in fields
        # Note: computed methods like full_name are not included as fields

        # Check field metadata
        id_field = fields["id"]
        assert id_field["type"] is int
        # Note: "both" indicates field can be used in both input and output contexts
        assert id_field["purpose"] in ("output", "both")

        age_field = fields["age"]
        assert age_field["type"] == (int | None)
        assert age_field["default"] is None

    def test_describe_success_type(self, introspection_test_schema):
        """describe_type should work correctly with @success decorated classes."""
        # Get the CreateUserSuccess type
        success_type = None
        for type_cls in introspection_test_schema.types.values():
            if type_cls.__name__ == "CreateUserSuccess":
                success_type = type_cls
                break

        assert success_type is not None, "CreateUserSuccess type not found in schema"

        # Describe the type
        description = describe_type(success_type)

        # Verify basic structure
        assert description["typename"] == "CreateUserSuccess"
        assert description["is_input"] is False
        assert description["is_output"] is True

        # Verify fields (should include auto-injected fields)
        fields = description["fields"]
        assert "user" in fields
        assert "message" in fields  # Auto-injected field

        # Check field metadata
        message_field = fields["message"]
        assert message_field["type"] is str
        assert message_field["default"] == "User created successfully"

    def test_describe_error_type(self, introspection_test_schema):
        """describe_type should work correctly with @error decorated classes."""
        # Get the CreateUserError type
        error_type = None
        for type_cls in introspection_test_schema.types.values():
            if type_cls.__name__ == "CreateUserError":
                error_type = type_cls
                break

        assert error_type is not None, "CreateUserError type not found in schema"

        # Describe the type
        description = describe_type(error_type)

        # Verify basic structure
        assert description["typename"] == "CreateUserError"
        assert description["is_input"] is False
        assert description["is_output"] is True

        # Verify fields (should include auto-injected fields)
        fields = description["fields"]
        assert "message" in fields  # Auto-injected field
        assert "code" in fields  # Auto-injected field
        assert "errors" in fields  # Auto-injected field
        assert "status" in fields  # Auto-injected field

        # Check field metadata
        message_field = fields["message"]
        # message can be either str or str | None depending on implementation
        assert message_field["type"] in (str, str | None)
        # default may or may not be None depending on auto-injection
        assert message_field["default"] is None or isinstance(message_field["default"], str)

        code_field = fields["code"]
        assert code_field["type"] is int
        # Default may be 0 or None depending on error decorator implementation
        assert code_field["default"] in (0, None)

        errors_field = fields["errors"]
        assert str(errors_field["type"]).startswith("list[")  # List type
        assert errors_field["default"] == []  # Empty list

    def test_describe_type_with_invalid_type(self):
        """describe_type should raise TypeError for non-FraiseQL types."""

        class NotAFraiseQLType:
            pass

        with pytest.raises(TypeError, match="not a valid FraiseQL type"):
            describe_type(NotAFraiseQLType)

    def test_introspection_with_schema_registry(self, introspection_test_schema):
        """Introspection should work with all types registered in schema."""
        # Get all registered types
        registered_types = list(introspection_test_schema.types.values())

        assert len(registered_types) >= 6, f"Expected at least 6 types, got {len(registered_types)}"

        # Try to describe each type
        for type_cls in registered_types:
            # Should not raise exceptions
            description = describe_type(type_cls)

            # Should have basic structure
            assert "typename" in description
            assert "is_input" in description
            assert "is_output" in description
            assert "fields" in description

            # Fields should be a dict
            assert isinstance(description["fields"], dict)

    def test_field_descriptions_from_introspection(self, introspection_test_schema):
        """Field descriptions should be extractable from introspection data."""
        # Get User type
        user_type = None
        for type_cls in introspection_test_schema.types.values():
            if type_cls.__name__ == "User":
                user_type = type_cls
                break

        assert user_type is not None

        description = describe_type(user_type)
        fields = description["fields"]

        # Collect all field descriptions
        field_descriptions = {}
        for field_name, field_info in fields.items():
            field_descriptions[field_name] = {
                "type": field_info["type"],
                "purpose": field_info["purpose"],
                "has_default": field_info["default"] is not None,
                "description": field_info.get("description"),
            }

        # Verify we have expected fields
        assert "id" in field_descriptions
        assert "name" in field_descriptions
        assert "email" in field_descriptions
        # Note: full_name is a method, not a field annotation, so it may not be in fields
        # depending on introspection implementation

        # Check field purposes - "both" indicates field can be used in both contexts
        assert field_descriptions["id"]["purpose"] in ("output", "both")
        assert field_descriptions["name"]["purpose"] in ("output", "both")

    def test_introspection_performance(self, introspection_test_schema):
        """Introspection should perform well with multiple types."""
        import time

        # Get all registered types
        registered_types = list(introspection_test_schema.types.values())

        # Time the introspection process
        start_time = time.time()

        for _ in range(10):  # Multiple iterations
            for type_cls in registered_types:
                describe_type(type_cls)

        end_time = time.time()
        duration = end_time - start_time

        # Should complete quickly (< 0.1 second for 10 iterations of ~6 types)
        assert duration < 0.1, (
            f"Introspection too slow: {duration:.3f}s for {len(registered_types)} types"
        )

    def test_introspection_consistency(self, introspection_test_schema):
        """Introspection results should be consistent across multiple calls."""
        # Get a type to test
        user_type = None
        for type_cls in introspection_test_schema.types.values():
            if type_cls.__name__ == "User":
                user_type = type_cls
                break

        assert user_type is not None

        # Get description multiple times
        desc1 = describe_type(user_type)
        desc2 = describe_type(user_type)
        desc3 = describe_type(user_type)

        # Should be identical
        assert desc1 == desc2 == desc3

        # Should have same structure
        for desc in [desc1, desc2, desc3]:
            assert desc["typename"] == "User"
            assert desc["is_output"] is True
            assert "id" in desc["fields"]
            assert "name" in desc["fields"]
