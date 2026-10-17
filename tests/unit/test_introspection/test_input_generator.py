"""Unit tests for InputGenerator."""

import pytest

from fraiseql.introspection.input_generator import InputGenerator
from fraiseql.introspection.metadata_parser import MutationAnnotation
from fraiseql.introspection.postgres_introspector import FunctionMetadata, ParameterInfo
from fraiseql.introspection.type_mapper import TypeMapper


@pytest.fixture
def mock_introspector() -> None:
    """Mock PostgresIntrospector for testing."""

    class MockIntrospector:
        async def discover_composite_type(self, type_name, schema) -> None:
            # Mock implementation - will be overridden in specific tests
            return None

    return MockIntrospector()


class TestInputGenerator:
    """Test InputGenerator functionality."""

    @pytest.fixture
    def type_mapper(self) -> TypeMapper:
        """Create a TypeMapper instance."""
        return TypeMapper()

    @pytest.fixture
    def input_generator(self, type_mapper: TypeMapper) -> InputGenerator:
        """Create an InputGenerator instance."""
        return InputGenerator(type_mapper)

    @pytest.mark.asyncio
    async def test_generate_input_type_basic(
        self, input_generator: InputGenerator, mock_introspector
    ):
        """Test generating input type from function parameters."""
        # Given: Function with basic parameters
        function_metadata = FunctionMetadata(
            schema_name="public",
            function_name="fn_create_user",
            parameters=[
                ParameterInfo(name="p_name", pg_type="text", mode="IN", default_value=None),
                ParameterInfo(name="p_email", pg_type="text", mode="IN", default_value=None),
            ],
            return_type="jsonb",
            comment=None,
            language="plpgsql",
        )

        annotation = MutationAnnotation(
            name="createUser",
            success_type="User",
            error_type="ValidationError",
            description="Create a user",
        )

        # When: Generate input type
        input_cls = await input_generator.generate_input_type(
            function_metadata, annotation, mock_introspector
        )

        # Then: Input class has correct annotations
        assert hasattr(input_cls, "__annotations__")
        annotations = input_cls.__annotations__
        assert "name" in annotations
        assert "email" in annotations
        assert annotations["name"] is str
        assert annotations["email"] is str

        # Class name should be generated correctly
        assert input_cls.__name__ == "CreateUserInput"

    @pytest.mark.asyncio
    async def test_generate_input_type_with_optional(
        self, input_generator: InputGenerator, mock_introspector
    ):
        """Test generating input type with optional parameters."""
        # Given: Function with default parameter
        function_metadata = FunctionMetadata(
            schema_name="public",
            function_name="fn_update_user",
            parameters=[
                ParameterInfo(name="p_id", pg_type="uuid", mode="IN", default_value=None),
                ParameterInfo(
                    name="p_name", pg_type="text", mode="IN", default_value="'Anonymous'"
                ),
            ],
            return_type="jsonb",
            comment=None,
            language="plpgsql",
        )

        annotation = MutationAnnotation(
            name="createUser", success_type="User", error_type="ValidationError"
        )

        # When: Generate input type
        input_cls = await input_generator.generate_input_type(
            function_metadata, annotation, mock_introspector
        )

        # Then: Optional parameter has Optional type
        annotations = input_cls.__annotations__
        assert "id" in annotations
        assert "name" in annotations

        # Check that name is Optional[str] due to default value
        from typing import Optional

        assert annotations["name"] == Optional[str]

    @pytest.mark.asyncio
    async def test_generate_input_type_filters_input_pk(
        self, input_generator: InputGenerator, mock_introspector
    ):
        """Test that input_pk parameters are filtered out."""
        # Given: Function with input_pk parameter
        function_metadata = FunctionMetadata(
            schema_name="public",
            function_name="fn_create_post",
            parameters=[
                ParameterInfo(name="input_pk_user", pg_type="uuid", mode="IN", default_value=None),
                ParameterInfo(name="p_title", pg_type="text", mode="IN", default_value=None),
                ParameterInfo(name="p_content", pg_type="text", mode="IN", default_value=None),
            ],
            return_type="jsonb",
            comment=None,
            language="plpgsql",
        )

        annotation = MutationAnnotation(
            name="createPost", success_type="Post", error_type="ValidationError"
        )

        # When: Generate input type
        input_cls = await input_generator.generate_input_type(
            function_metadata, annotation, mock_introspector
        )

        # Then: input_pk parameter is excluded
        annotations = input_cls.__annotations__
        assert "user" not in annotations  # input_pk_user becomes user, but should be filtered
        assert "title" in annotations
        assert "content" in annotations

    @pytest.mark.asyncio
    async def test_generate_input_type_various_types(
        self, input_generator: InputGenerator, mock_introspector
    ):
        """Test generating input type with various PostgreSQL types."""
        # Given: Function with various parameter types
        function_metadata = FunctionMetadata(
            schema_name="public",
            function_name="fn_create_product",
            parameters=[
                ParameterInfo(name="p_name", pg_type="text", mode="IN", default_value=None),
                ParameterInfo(name="p_price", pg_type="numeric", mode="IN", default_value=None),
                ParameterInfo(name="p_in_stock", pg_type="boolean", mode="IN", default_value=None),
                ParameterInfo(name="p_tags", pg_type="text[]", mode="IN", default_value=None),
            ],
            return_type="jsonb",
            comment=None,
            language="plpgsql",
        )

        annotation = MutationAnnotation(
            name="createProduct", success_type="Product", error_type="ValidationError"
        )

        # When: Generate input type
        input_cls = await input_generator.generate_input_type(
            function_metadata, annotation, mock_introspector
        )

        # Then: Types are mapped correctly
        annotations = input_cls.__annotations__
        assert annotations["name"] is str
        assert annotations["price"].__name__ == "Decimal"  # numeric -> Decimal
        assert annotations["in_stock"] is bool
        assert str(annotations["tags"]) == "typing.List[str]"  # text[] -> List[str]

    @pytest.mark.asyncio
    async def test_function_to_input_name_conversion(
        self, input_generator: InputGenerator, mock_introspector
    ):
        """Test function name to input class name conversion."""
        # Test various function name patterns
        test_cases = [
            ("fn_create_user", "CreateUserInput"),
            ("fn_update_post", "UpdatePostInput"),
            ("fn_delete_item", "DeleteItemInput"),
            ("tv_create_machine", "CreateMachineInput"),  # With tv_ prefix
        ]

        for function_name, expected_class_name in test_cases:
            function_metadata = FunctionMetadata(
                schema_name="public",
                function_name=function_name,
                parameters=[],
                return_type="jsonb",
                comment=None,
                language="plpgsql",
            )

            annotation = MutationAnnotation(name="test", success_type="Test", error_type="Error")

            input_cls = await input_generator.generate_input_type(
                function_metadata, annotation, mock_introspector
            )
            assert input_cls.__name__ == expected_class_name

    @pytest.mark.asyncio
    async def test_generate_input_from_composite_type(
        self, input_generator: InputGenerator, mock_introspector
    ):
        """Test input generation from composite type (SpecQL pattern)."""
        from fraiseql.introspection.postgres_introspector import (
            CompositeAttribute,
            CompositeTypeMetadata,
        )

        # Mock the introspector to return composite type metadata
        async def mock_discover_composite_type(type_name, schema) -> None:
            if type_name == "type_create_contact_input" and schema == "app":
                return CompositeTypeMetadata(
                    schema_name="app",
                    type_name="type_create_contact_input",
                    attributes=[
                        CompositeAttribute(
                            name="email",
                            pg_type="text",
                            ordinal_position=1,
                            comment="@fraiseql:field name=email,type=String!,required=true",
                        ),
                        CompositeAttribute(
                            name="company_id",
                            pg_type="uuid",
                            ordinal_position=2,
                            comment="@fraiseql:field name=companyId,type=UUID,required=false",
                        ),
                        CompositeAttribute(
                            name="status",
                            pg_type="text",
                            ordinal_position=3,
                            comment="@fraiseql:field name=status,type=String!,required=true",
                        ),
                    ],
                    comment="@fraiseql:input name=CreateContactInput",
                )
            return None

        mock_introspector.discover_composite_type = mock_discover_composite_type

        # Given: Function with JSONB parameter (as SpecQL creates it)
        function_metadata = FunctionMetadata(
            schema_name="app",
            function_name="create_contact",
            parameters=[
                ParameterInfo("input_tenant_id", "uuid", "IN", None),
                ParameterInfo("input_user_id", "uuid", "IN", None),
                ParameterInfo("input_payload", "jsonb", "IN", None),
            ],
            return_type="app.mutation_result",
            comment=None,
            language="plpgsql",
        )

        # Given: Annotation
        annotation = MutationAnnotation(
            name="createContact", success_type="Contact", error_type="ContactError"
        )

        # When: Generate input type (READS composite type from database)
        input_cls = await input_generator.generate_input_type(
            function_metadata, annotation, mock_introspector
        )

        # Then: Class name is correct
        assert input_cls.__name__ == "CreateContactInput"

        # Then: Has fields from composite type (that SpecQL created)
        assert "email" in input_cls.__annotations__
        assert "companyId" in input_cls.__annotations__  # camelCase from SpecQL metadata
        assert "status" in input_cls.__annotations__

        # Then: Types are correct
        assert input_cls.__annotations__["email"] is str

    @pytest.mark.asyncio
    async def test_generate_input_from_parameters_legacy(
        self, input_generator: InputGenerator, mock_introspector
    ):
        """Test input generation from parameters (legacy pattern).

        Verifies backward compatibility with non-SpecQL functions.
        """
        # Given: Function with simple parameters (no JSONB)
        function_metadata = FunctionMetadata(
            schema_name="public",
            function_name="fn_create_user",
            parameters=[
                ParameterInfo("p_name", "text", "IN", None),
                ParameterInfo("p_email", "text", "IN", None),
            ],
            return_type="uuid",
            comment=None,
            language="plpgsql",
        )

        # Given: Annotation
        annotation = MutationAnnotation(
            name="createUser", success_type="User", error_type="UserError"
        )

        # When: Generate input type
        input_cls = await input_generator.generate_input_type(
            function_metadata, annotation, mock_introspector
        )

        # Then: Falls back to parameter-based generation
        assert input_cls.__name__ == "CreateUserInput"
        assert "name" in input_cls.__annotations__
        assert "email" in input_cls.__annotations__

    @pytest.mark.asyncio
    async def test_generate_input_excludes_auth_params(
        self, input_generator: InputGenerator, mock_introspector
    ):
        """Test that auth_ parameters are excluded from GraphQL input schema."""
        # Given: Function with auth params (should be excluded)
        function_metadata = FunctionMetadata(
            schema_name="crm",
            function_name="qualify_lead",
            parameters=[
                ParameterInfo("p_contact_id", "uuid", "IN", None),
                ParameterInfo("auth_tenant_id", "text", "IN", None),  # Should be excluded
                ParameterInfo("auth_user_id", "uuid", "IN", None),  # Should be excluded
            ],
            return_type="jsonb",
            comment=None,
            language="plpgsql",
        )

        # Given: Context params (for exclusion)
        context_params = {"tenant_id": "auth_tenant_id", "user_id": "auth_user_id"}

        # Given: Annotation
        annotation = MutationAnnotation(
            name="qualifyLead",
            description=None,
            success_type="Contact",
            error_type="ContactError",
        )

        # When: Generate input type
        input_cls = await input_generator.generate_input_type(
            function_metadata,
            annotation,
            mock_introspector,
            context_params,  # Pass context params for exclusion
        )

        # Then: Only business parameter included (NO auth params)
        assert input_cls.__name__ == "QualifyLeadInput"
        assert "contact_id" in input_cls.__annotations__
        assert "auth_tenant_id" not in input_cls.__annotations__  # ✅ Excluded!
        assert "auth_user_id" not in input_cls.__annotations__  # ✅ Excluded!
        assert "tenant_id" not in input_cls.__annotations__  # ✅ Excluded!
        assert "user_id" not in input_cls.__annotations__  # ✅ Excluded!

    @pytest.mark.asyncio
    async def test_composite_attribute_comments_stored(
        self, input_generator: InputGenerator, mock_introspector
    ):
        """Test that composite type attribute comments are captured in input fields."""
        from fraiseql.introspection.postgres_introspector import (
            CompositeAttribute,
            CompositeTypeMetadata,
        )

        # Mock the introspector to return composite type metadata with comments
        async def mock_discover_composite_type(type_name, schema) -> None:
            if type_name == "type_create_user_input" and schema == "app":
                return CompositeTypeMetadata(
                    schema_name="app",
                    type_name="type_create_user_input",
                    attributes=[
                        CompositeAttribute(
                            name="email",
                            pg_type="text",
                            ordinal_position=1,
                            comment="Primary email address for authentication",  # PostgreSQL comment
                        ),
                        CompositeAttribute(
                            name="name",
                            pg_type="text",
                            ordinal_position=2,
                            comment="Full name of the user",
                        ),
                    ],
                    comment="Input parameters for user creation",
                )
            return None

        mock_introspector.discover_composite_type = mock_discover_composite_type

        # Act
        input_cls = await input_generator._generate_from_composite_type(
            "type_create_user_input", "app", mock_introspector
        )

        # Assert
        assert hasattr(input_cls, "__gql_fields__")
        assert "email" in input_cls.__gql_fields__
        assert (
            input_cls.__gql_fields__["email"].description
            == "Primary email address for authentication"
        )
        assert input_cls.__gql_fields__["name"].description == "Full name of the user"

    @pytest.mark.asyncio
    async def test_composite_type_comment_used_as_input_description(
        self, input_generator: InputGenerator, mock_introspector
    ):
        """Test that PostgreSQL composite type comments become GraphQL input type descriptions."""
        from fraiseql.introspection.postgres_introspector import (
            CompositeAttribute,
            CompositeTypeMetadata,
        )

        # Mock the introspector to return composite type metadata with comment
        async def mock_discover_composite_type(type_name, schema) -> None:
            if type_name == "type_create_user_input" and schema == "app":
                return CompositeTypeMetadata(
                    schema_name="app",
                    type_name="type_create_user_input",
                    attributes=[
                        CompositeAttribute(
                            name="email",
                            pg_type="text",
                            ordinal_position=1,
                            comment="Primary email address for authentication",
                        ),
                        CompositeAttribute(
                            name="name",
                            pg_type="text",
                            ordinal_position=2,
                            comment="Full name of the user",
                        ),
                    ],
                    comment="Input parameters for user creation",  # Composite type comment
                )
            return None

        mock_introspector.discover_composite_type = mock_discover_composite_type

        # Act
        input_cls = await input_generator._generate_from_composite_type(
            "type_create_user_input", "app", mock_introspector
        )

        # Assert
        assert input_cls.__doc__ == "Input parameters for user creation"
