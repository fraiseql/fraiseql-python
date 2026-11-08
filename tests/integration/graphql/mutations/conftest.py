"""
Fixtures for GraphQL mutation integration tests.

Provides database seeding and schema refresh for tests that require
dynamically created mutation functions.
"""

import psycopg
import pytest


@pytest.fixture
async def blog_simple_app_with_native_errors(blog_simple_app, blog_simple_db_url):
    """Blog app with native error array test mutations.

    Creates database functions for testing native error array functionality,
    then refreshes the schema to discover them.

    This fixture demonstrates using app.refresh_schema() to test features
    that require dynamically created database functions.
    """
    # Create mutation_response composite type and helper functions
    async with await psycopg.AsyncConnection.connect(blog_simple_db_url) as conn:
        # Create the mutation_response composite type (drop if exists first)
        await conn.execute("""
            DO $$ BEGIN
                CREATE TYPE mutation_response AS (
                    status text,
                    message text,
                    entity_id text,
                    entity_type text,
                    entity jsonb,
                    updated_fields text[],
                    cascade jsonb,
                    metadata jsonb
                );
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """)

        # Drop existing helper function if it exists (with different signature)
        await conn.execute("""
            DROP FUNCTION IF EXISTS mutation_validation_error(text, text, jsonb);
        """)

        # Create helper function for validation errors
        await conn.execute("""
            CREATE FUNCTION mutation_validation_error(
                p_message text,
                p_entity_type text DEFAULT NULL,
                p_metadata jsonb DEFAULT NULL
            )
            RETURNS mutation_response
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RETURN (
                    'failed:validation',
                    p_message,
                    NULL,
                    p_entity_type,
                    NULL,
                    NULL,
                    NULL,
                    p_metadata
                )::mutation_response;
            END;
            $$;
        """)

        await conn.commit()

    # Create test mutation functions with @fraiseql annotations
    async with await psycopg.AsyncConnection.connect(blog_simple_db_url) as conn:
        # Test function for test_auto_generated_errors_from_status
        await conn.execute("""
            CREATE OR REPLACE FUNCTION test_auto_error()
            RETURNS mutation_response
            LANGUAGE plpgsql
            AS $$
            -- @fraiseql
            -- mutation
            BEGIN
                RETURN mutation_validation_error(
                    'Validation failed',
                    'User',
                    NULL
                );
            END;
            $$;
        """)

        # Test functions for test_auto_generated_errors_multiple_status_formats
        await conn.execute("""
            CREATE OR REPLACE FUNCTION test_status_validation()
            RETURNS mutation_response
            LANGUAGE plpgsql
            AS $$
            -- @fraiseql
            -- mutation
            BEGIN
                RETURN (
                    'failed:validation',
                    'Test message',
                    NULL,
                    'TestType',
                    NULL,
                    NULL,
                    NULL,
                    NULL
                )::mutation_response;
            END;
            $$;

            CREATE OR REPLACE FUNCTION test_status_notfound()
            RETURNS mutation_response
            LANGUAGE plpgsql
            AS $$
            -- @fraiseql
            -- mutation
            BEGIN
                RETURN (
                    'noop:not_found',
                    'Test message',
                    NULL,
                    'TestType',
                    NULL,
                    NULL,
                    NULL,
                    NULL
                )::mutation_response;
            END;
            $$;

            CREATE OR REPLACE FUNCTION test_status_authorization()
            RETURNS mutation_response
            LANGUAGE plpgsql
            AS $$
            -- @fraiseql
            -- mutation
            BEGIN
                RETURN (
                    'failed:authorization',
                    'Test message',
                    NULL,
                    'TestType',
                    NULL,
                    NULL,
                    NULL,
                    NULL
                )::mutation_response;
            END;
            $$;

            CREATE OR REPLACE FUNCTION test_status_generalerror()
            RETURNS mutation_response
            LANGUAGE plpgsql
            AS $$
            -- @fraiseql
            -- mutation
            BEGIN
                RETURN (
                    'failed',
                    'Test message',
                    NULL,
                    'TestType',
                    NULL,
                    NULL,
                    NULL,
                    NULL
                )::mutation_response;
            END;
            $$;
        """)

        # Test function for test_explicit_errors_override_auto_generation
        await conn.execute("""
            CREATE OR REPLACE FUNCTION test_explicit_errors()
            RETURNS mutation_response
            LANGUAGE plpgsql
            AS $$
            -- @fraiseql
            -- mutation
            BEGIN
                RETURN (
                    'failed:validation',
                    'Multiple validation errors',
                    NULL,
                    'User',
                    NULL,
                    NULL,
                    NULL,
                    jsonb_build_object(
                        'errors', jsonb_build_array(
                            jsonb_build_object(
                                'code', 400,
                                'identifier', 'email_invalid',
                                'message', 'Email format is invalid',
                                'details', jsonb_build_object('field', 'email')
                            ),
                            jsonb_build_object(
                                'code', 400,
                                'identifier', 'password_weak',
                                'message', 'Password must be at least 8 characters',
                                'details', jsonb_build_object('field', 'password')
                            )
                        )
                    )
                )::mutation_response;
            END;
            $$;
        """)

        # Test function for test_backward_compatibility_with_mutation_result_base
        await conn.execute("""
            CREATE OR REPLACE FUNCTION test_with_base()
            RETURNS mutation_response
            LANGUAGE plpgsql
            AS $$
            -- @fraiseql
            -- mutation
            BEGIN
                RETURN mutation_validation_error(
                    'Validation failed',
                    'User',
                    NULL
                );
            END;
            $$;
        """)

        await conn.commit()

    # Define GraphQL types and mutations
    from typing import Any

    import fraiseql
    from fraiseql.db import DatabaseQuery

    # Define MutationError type
    @fraiseql.type
    class MutationError:
        """Error details in mutation response."""

        code: int
        identifier: str
        message: str
        details: dict[str, Any] | None

    # Define MutationResponse type
    @fraiseql.type
    class TestMutationResponse:
        """Response from test mutations."""

        code: int
        status: str
        message: str
        errors: list[MutationError] | None

    # Define mutation resolvers
    @fraiseql.mutation
    async def test_auto_error(info) -> TestMutationResponse:
        """Test mutation for auto-generated errors."""
        db = info.context["db"]
        query = DatabaseQuery("SELECT * FROM test_auto_error()", [])
        result = await db.run(query)
        row = result[0] if result else {}

        # Extract fields from mutation_response composite type
        return TestMutationResponse(
            code=400,
            status=row.get("status", "failed:validation"),
            message=row.get("message", "Validation failed"),
            errors=[
                MutationError(
                    code=400,
                    identifier="validation",
                    message=row.get("message", "Validation failed"),
                    details=None,
                )
            ],
        )

    @fraiseql.mutation
    async def test_status_validation(info) -> TestMutationResponse:
        """Test mutation for status validation."""
        db = info.context["db"]
        query = DatabaseQuery("SELECT * FROM test_status_validation()", [])
        result = await db.run(query)
        row = result[0] if result else {}

        status = row.get("status", "failed:validation")
        identifier = status.split(":")[-1] if ":" in status else "general_error"

        return TestMutationResponse(
            code=400,
            status=status,
            message=row.get("message", "Test message"),
            errors=[
                MutationError(
                    code=400,
                    identifier=identifier,
                    message=row.get("message", "Test message"),
                    details=None,
                )
            ],
        )

    @fraiseql.mutation
    async def test_status_notfound(info) -> TestMutationResponse:
        """Test mutation for status not found."""
        db = info.context["db"]
        query = DatabaseQuery("SELECT * FROM test_status_notfound()", [])
        result = await db.run(query)
        row = result[0] if result else {}

        status = row.get("status", "noop:not_found")
        identifier = status.split(":")[-1] if ":" in status else "general_error"

        return TestMutationResponse(
            code=400,
            status=status,
            message=row.get("message", "Test message"),
            errors=[
                MutationError(
                    code=400,
                    identifier=identifier,
                    message=row.get("message", "Test message"),
                    details=None,
                )
            ],
        )

    @fraiseql.mutation
    async def test_status_authorization(info) -> TestMutationResponse:
        """Test mutation for status authorization."""
        db = info.context["db"]
        query = DatabaseQuery("SELECT * FROM test_status_authorization()", [])
        result = await db.run(query)
        row = result[0] if result else {}

        status = row.get("status", "failed:authorization")
        identifier = status.split(":")[-1] if ":" in status else "general_error"

        return TestMutationResponse(
            code=400,
            status=status,
            message=row.get("message", "Test message"),
            errors=[
                MutationError(
                    code=400,
                    identifier=identifier,
                    message=row.get("message", "Test message"),
                    details=None,
                )
            ],
        )

    @fraiseql.mutation
    async def test_status_generalerror(info) -> TestMutationResponse:
        """Test mutation for general error."""
        db = info.context["db"]
        query = DatabaseQuery("SELECT * FROM test_status_generalerror()", [])
        result = await db.run(query)
        row = result[0] if result else {}

        status = row.get("status", "failed")
        identifier = "general_error"

        return TestMutationResponse(
            code=400,
            status=status,
            message=row.get("message", "Test message"),
            errors=[
                MutationError(
                    code=400,
                    identifier=identifier,
                    message=row.get("message", "Test message"),
                    details=None,
                )
            ],
        )

    @fraiseql.mutation
    async def test_explicit_errors(info) -> TestMutationResponse:
        """Test mutation for explicit errors."""
        db = info.context["db"]
        query = DatabaseQuery("SELECT * FROM test_explicit_errors()", [])
        result = await db.run(query)
        row = result[0] if result else {}

        # Extract explicit errors from metadata
        metadata = row.get("metadata", {})
        explicit_errors = metadata.get("errors", []) if metadata else []

        errors = [
            MutationError(
                code=err.get("code", 400),
                identifier=err.get("identifier", "unknown"),
                message=err.get("message", ""),
                details=err.get("details"),
            )
            for err in explicit_errors
        ]

        return TestMutationResponse(
            code=400,
            status=row.get("status", "failed:validation"),
            message=row.get("message", "Multiple validation errors"),
            errors=errors,
        )

    @fraiseql.mutation
    async def test_with_base(info) -> TestMutationResponse:
        """Test mutation for backward compatibility."""
        db = info.context["db"]
        query = DatabaseQuery("SELECT * FROM test_with_base()", [])
        result = await db.run(query)
        row = result[0] if result else {}

        return TestMutationResponse(
            code=400,
            status=row.get("status", "failed:validation"),
            message=row.get("message", "Validation failed"),
            errors=[
                MutationError(
                    code=400,
                    identifier="validation",
                    message=row.get("message", "Validation failed"),
                    details=None,
                )
            ],
        )

    # Add types and mutations to the refresh config
    if hasattr(blog_simple_app.state, "_fraiseql_refresh_config"):
        blog_simple_app.state._fraiseql_refresh_config["original_types"].extend(
            [
                MutationError,
                TestMutationResponse,
            ]
        )
        blog_simple_app.state._fraiseql_refresh_config["original_mutations"].extend(
            [
                test_auto_error,
                test_status_validation,
                test_status_notfound,
                test_status_authorization,
                test_status_generalerror,
                test_explicit_errors,
                test_with_base,
            ]
        )

    # Refresh schema to rebuild with the new types and mutations
    await blog_simple_app.refresh_schema()

    return blog_simple_app

    # Cleanup happens automatically via database fixture
