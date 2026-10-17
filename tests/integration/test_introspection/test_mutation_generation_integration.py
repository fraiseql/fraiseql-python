"""Integration tests for mutation generation with real database.

These tests verify that the mutation generation pipeline works end-to-end
with real PostgreSQL functions and proper GraphQL execution.
"""

import pytest
import pytest_asyncio

from fraiseql.introspection.input_generator import InputGenerator
from fraiseql.introspection.metadata_parser import MetadataParser
from fraiseql.introspection.mutation_generator import MutationGenerator
from fraiseql.introspection.postgres_introspector import PostgresIntrospector
from fraiseql.introspection.type_mapper import TypeMapper

pytestmark = pytest.mark.integration


class TestMutationGenerationIntegration:
    """Integration tests for end-to-end mutation generation."""

    @pytest_asyncio.fixture
    async def type_mapper(self) -> TypeMapper:
        """Create TypeMapper instance."""
        return TypeMapper()

    @pytest_asyncio.fixture
    async def input_generator(self, type_mapper: TypeMapper) -> InputGenerator:
        """Create InputGenerator instance."""
        return InputGenerator(type_mapper)

    @pytest_asyncio.fixture
    async def mutation_generator(self, input_generator: InputGenerator) -> MutationGenerator:
        """Create MutationGenerator instance."""
        return MutationGenerator(input_generator)

    @pytest_asyncio.fixture
    async def metadata_parser(self) -> MetadataParser:
        """Create MetadataParser instance."""
        return MetadataParser()

    @pytest_asyncio.fixture
    async def introspector(self, class_db_pool, test_schema) -> PostgresIntrospector:
        """Create PostgresIntrospector with real database pool."""
        return PostgresIntrospector(class_db_pool)

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def test_mutation_function(self, class_db_pool, test_schema):
        """Create a test mutation function for introspection."""
        import uuid

        function_suffix = uuid.uuid4().hex[:8]
        function_name = f"fn_create_user_{function_suffix}"

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            # Create the function
            await conn.execute(f"""
                CREATE OR REPLACE FUNCTION {test_schema}.{function_name}(
                    p_name TEXT,
                    p_email TEXT DEFAULT 'user@example.com'
                )
                RETURNS JSONB
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    -- Simulate user creation
                    RETURN jsonb_build_object(
                        'success', true,
                        'user', jsonb_build_object(
                            'id', 1,
                            'name', p_name,
                            'email', p_email,
                            'created_at', NOW()
                        )
                    );
                END;
                $$;
            """)

            # Add comment with @fraiseql:mutation annotation
            await conn.execute(f"""
                COMMENT ON FUNCTION {test_schema}.{function_name}(TEXT, TEXT) IS '@fraiseql:mutation
                name: createUser
                success_type: User
                error_type: ValidationError
                description: Create a new user account'
            """)

            # Commit the transaction so the function is visible to other connections
            await conn.commit()

        yield function_name

        async with class_db_pool.connection() as conn:
            await conn.execute(f"DROP FUNCTION IF EXISTS {test_schema}.{function_name}(TEXT, TEXT)")
            await conn.commit()

    @pytest.mark.asyncio
    async def test_full_mutation_generation_pipeline(
        self,
        introspector: PostgresIntrospector,
        metadata_parser: MetadataParser,
        mutation_generator: MutationGenerator,
        test_mutation_function: str,
        test_schema,
    ):
        """Test complete mutation generation from database function."""
        # Given: Database with annotated function
        # When: Discover and generate mutation
        functions = await introspector.discover_functions(
            pattern=test_mutation_function, schemas=[test_schema]
        )

        # Then: Function is discovered
        assert len(functions) == 1
        function_metadata = functions[0]
        assert function_metadata.function_name == test_mutation_function
        assert len(function_metadata.parameters) == 2  # p_name, p_email

        # Parse annotation
        annotation = metadata_parser.parse_mutation_annotation(function_metadata.comment)
        assert annotation is not None
        assert annotation.success_type == "User"
        assert annotation.error_type == "ValidationError"

        # Generate input type
        context_params = mutation_generator._extract_context_params(function_metadata, annotation)  # type: ignore[arg-type]
        input_cls = await mutation_generator.input_generator.generate_input_type(
            function_metadata,
            annotation,
            introspector,
            context_params,  # type: ignore[arg-type]
        )
        assert (
            input_cls.__name__
            == f"CreateUser{test_mutation_function.rsplit('_', maxsplit=1)[-1].capitalize()}Input"
        )
        assert hasattr(input_cls, "__annotations__")
        annotations = input_cls.__annotations__
        assert "name" in annotations
        assert "email" in annotations

        # Mock type registry
        type_registry = {
            "User": type("User", (), {"__annotations__": {"id": int, "name": str, "email": str}}),
            "ValidationError": type("ValidationError", (), {"__annotations__": {"message": str}}),
        }

        # Generate mutation
        mutation = await mutation_generator.generate_mutation_for_function(
            function_metadata,
            annotation,
            type_registry,
            introspector,  # type: ignore
        )

        # Then: Mutation is generated successfully
        assert mutation is not None
        assert hasattr(mutation, "__name__")
        assert mutation.__name__.startswith("CreateUser")

    @pytest.mark.asyncio
    async def test_mutation_generation_with_missing_types_fails(
        self,
        introspector: PostgresIntrospector,
        metadata_parser: MetadataParser,
        mutation_generator: MutationGenerator,
        test_mutation_function: str,
        test_schema,
    ):
        """Test that mutation generation fails gracefully when types are missing."""
        # Given: Function with annotation but missing types in registry
        functions = await introspector.discover_functions(
            pattern=test_mutation_function, schemas=[test_schema]
        )
        function_metadata = functions[0]
        annotation = metadata_parser.parse_mutation_annotation(function_metadata.comment)

        # Empty type registry
        type_registry = {}

        # When: Generate mutation
        mutation = await mutation_generator.generate_mutation_for_function(
            function_metadata,
            annotation,
            type_registry,
            introspector,  # type: ignore[arg-type]
        )

        # When: Generate mutation (missing types test)
        mutation = await mutation_generator.generate_mutation_for_function(
            function_metadata,
            annotation,
            type_registry,
            introspector,  # type: ignore[arg-type]
        )

        # Then: Returns None due to missing types
        assert mutation is None

    @pytest.mark.asyncio
    async def test_input_type_generation_filters_parameters(
        self,
        introspector: PostgresIntrospector,
        metadata_parser: MetadataParser,
        mutation_generator: MutationGenerator,
        class_db_pool,
        test_schema,
    ):
        """Test that input_pk parameters are properly filtered."""
        import uuid

        function_suffix = uuid.uuid4().hex[:8]
        function_name = f"fn_create_post_{function_suffix}"

        # Create function with auth parameter
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            await conn.execute(f"""
                CREATE OR REPLACE FUNCTION {test_schema}.{function_name}(
                    auth_user_id UUID,
                    p_title TEXT,
                    p_content TEXT
                )
                RETURNS JSONB
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RETURN jsonb_build_object('success', true);
                END;
                $$;
            """)

            # Add comment
            await conn.execute(f"""
                COMMENT ON FUNCTION {test_schema}.{function_name}(UUID, TEXT, TEXT) IS '@fraiseql:mutation
                name: createPost
                success_type: Post
                error_type: ValidationError'
            """)

            # Commit the transaction so the function is visible to other connections
            await conn.commit()

        try:
            # When: Discover and generate input type
            functions = await introspector.discover_functions(
                pattern=function_name, schemas=[test_schema]
            )
            function_metadata = functions[0]
            annotation = metadata_parser.parse_mutation_annotation(function_metadata.comment)

            context_params = mutation_generator._extract_context_params(
                function_metadata, annotation
            )
            input_cls = await mutation_generator.input_generator.generate_input_type(
                function_metadata, annotation, introspector, context_params
            )

            # Then: input_pk parameter is excluded
            annotations = input_cls.__annotations__
            assert "user" not in annotations  # input_pk_user should be filtered
            assert "title" in annotations
            assert "content" in annotations

        finally:
            # Cleanup
            async with class_db_pool.connection() as conn:
                await conn.execute(
                    f"DROP FUNCTION IF EXISTS {test_schema}.{function_name}(UUID, TEXT, TEXT)"
                )
                await conn.commit()
