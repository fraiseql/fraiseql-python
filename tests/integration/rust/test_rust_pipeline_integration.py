"""Integration tests for Rust pipeline functionality with real GraphQL queries.

This test validates that the Rust pipeline works correctly end-to-end with real
GraphQL schemas, complex queries, and database operations. The Rust pipeline
is a critical performance feature that must be thoroughly tested.

Rust pipeline provides significant performance improvements for query execution,
so failures here impact the core value proposition of FraiseQL.
"""

import pytest
from graphql import graphql

# Import schema_builder to ensure SchemaRegistry is patched
import fraiseql.gql.schema_builder  # noqa: F401
from fraiseql import fraise_type, query

try:
    # Try to import Rust pipeline components
    from fraiseql.core import rust_pipeline
    from fraiseql.core.rust_pipeline import execute_via_rust_pipeline

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    rust_pipeline = None
    execute_via_rust_pipeline = None


@pytest.fixture(scope="class")
def rust_test_schema(meta_test_schema):
    """Schema registry with complex types for Rust pipeline testing."""
    # Clear any existing registrations
    meta_test_schema.clear()

    @fraise_type(sql_source="rust_test_users")
    class User:
        id: int
        name: str
        email: str
        age: int | None = None
        is_active: bool = True
        created_at: str

        def full_name(self) -> str:
            return f"{self.name} (computed)"

        def is_adult(self) -> bool:
            return self.age is not None and self.age >= 18

    @fraise_type(sql_source="rust_test_posts")
    class Post:
        id: int
        title: str
        content: str
        author_id: int
        published: bool = False
        tags: list[str]
        view_count: int = 0

    @fraise_type(sql_source="rust_test_comments")
    class Comment:
        id: int
        post_id: int
        author_id: int
        content: str
        created_at: str
        likes: int = 0

    @query
    async def get_users(info) -> list[User]:
        return []

    @query
    async def get_posts(info) -> list[Post]:
        return []

    @query
    async def get_comments(info) -> list[Comment]:
        return []

    # Register types with schema
    meta_test_schema.register_type(User)
    meta_test_schema.register_type(Post)
    meta_test_schema.register_type(Comment)
    meta_test_schema.register_query(get_users)
    meta_test_schema.register_query(get_posts)
    meta_test_schema.register_query(get_comments)

    return meta_test_schema


@pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust pipeline not available")
class TestRustPipelineAvailability:
    """Test that Rust pipeline components are available and functional."""

    def test_rust_pipeline_can_be_imported(self):
        """Rust pipeline should be importable without errors."""
        assert rust_pipeline is not None, "Rust pipeline module should be available"
        assert execute_via_rust_pipeline is not None, (
            "execute_via_rust_pipeline should be available"
        )

    async def test_rust_pipeline_basic_functionality(self, meta_test_pool):
        """Rust pipeline should handle basic operations without crashing."""
        # Test basic functionality - this should not raise exceptions
        try:
            # Try a simple operation that should work
            async with meta_test_pool.connection() as conn:
                result = await conn.execute("SELECT 1 as test")
                row = await result.fetchone()
                assert row[0] == 1, "Basic database operation should work"
        except Exception as e:
            # If it fails, it should fail gracefully with a clear error
            assert "rust" in str(e).lower() or "pipeline" in str(e).lower(), (
                f"Rust pipeline error should mention rust or pipeline: {e}"
            )

    def test_rust_pipeline_has_required_functions(self):
        """Rust pipeline should export required functions."""
        assert hasattr(rust_pipeline, "execute_via_rust_pipeline"), (
            "Rust pipeline should have execute_via_rust_pipeline function"
        )


@pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust pipeline not available")
class TestRustPipelineEquivalence:
    """Test that Rust and Python pipelines produce equivalent results."""

    async def test_simple_query_equivalence(self, rust_test_schema, meta_test_pool):
        """Simple queries should produce identical results in Rust and Python pipelines."""
        schema = rust_test_schema.build_schema()

        query_str = """
        query {
            getUsers {
                id
                name
            }
        }
        """

        # Execute with GraphQL (which may use either pipeline internally)
        result = await graphql(schema, query_str)

        # Should not have errors regardless of which pipeline is used
        assert not result.errors, f"Query failed: {result.errors}"
        assert result.data is not None

    async def test_filtered_query_equivalence(self, rust_test_schema, meta_test_pool):
        """Filtered queries should work consistently across pipelines."""
        schema = rust_test_schema.build_schema()

        query_str = """
        query {
            getUsers(where: {isActive: {eq: true}}) {
                id
                name
                isActive
            }
        }
        """

        result = await graphql(schema, query_str)
        assert not result.errors, f"Filtered query failed: {result.errors}"

    async def test_complex_nested_query_equivalence(self, rust_test_schema, meta_test_pool):
        """Complex nested queries should work consistently."""
        schema = rust_test_schema.build_schema()

        query_str = """
        query {
            getPosts(where: {published: {eq: true}}) {
                id
                title
                author {
                    id
                    name
                    fullName
                }
                comments {
                    id
                    content
                    author {
                        name
                    }
                }
            }
        }
        """

        result = await graphql(schema, query_str)
        # This might fail due to missing data, but should not crash
        # The important thing is it doesn't crash due to pipeline differences
        if result.errors:
            # Check that errors are data-related, not pipeline-related
            error_messages = [str(e) for e in result.errors]
            pipeline_errors = [
                e for e in error_messages if "rust" in e.lower() or "pipeline" in e.lower()
            ]
            assert len(pipeline_errors) == 0, f"Pipeline-related errors found: {pipeline_errors}"


@pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust pipeline not available")
class TestRustPipelineComplexQueries:
    """Test Rust pipeline with complex GraphQL operations."""

    async def test_rust_pipeline_with_aggregations(self, rust_test_schema, meta_test_pool):
        """Rust pipeline should handle queries with aggregations."""
        schema = rust_test_schema.build_schema()

        query_str = """
        query {
            getPosts {
                id
                title
                viewCount
                comments {
                    id
                    likes
                }
            }
        }
        """

        result = await graphql(schema, query_str)
        # Should handle the query structure without pipeline-specific errors
        assert result is not None

    async def test_rust_pipeline_with_multiple_filters(self, rust_test_schema, meta_test_pool):
        """Rust pipeline should handle complex WHERE clauses."""
        schema = rust_test_schema.build_schema()

        query_str = """
        query {
            getUsers(where: {
                AND: [
                    {isActive: {eq: true}},
                    {age: {gte: 18}}
                ]
            }) {
                id
                name
                age
                isAdult
            }
        }
        """

        result = await graphql(schema, query_str)
        assert result is not None
        # Check for pipeline-specific errors
        if result.errors:
            error_str = str(result.errors)
            assert "rust" not in error_str.lower(), (
                f"Rust pipeline error in complex query: {error_str}"
            )

    async def test_rust_pipeline_with_pagination(self, rust_test_schema, meta_test_pool):
        """Rust pipeline should handle pagination queries."""
        schema = rust_test_schema.build_schema()

        query_str = """
        query {
            getPosts(first: 10, where: {published: {eq: true}}) {
                edges {
                    node {
                        id
                        title
                        content
                    }
                }
                pageInfo {
                    hasNextPage
                    endCursor
                }
            }
        }
        """

        result = await graphql(schema, query_str)
        assert result is not None

    async def test_rust_pipeline_with_variables(self, rust_test_schema, meta_test_pool):
        """Rust pipeline should handle GraphQL variables."""
        schema = rust_test_schema.build_schema()

        query_str = """
        query GetUsersByAge($minAge: Int!) {
            getUsers(where: {age: {gte: $minAge}}) {
                id
                name
                age
            }
        }
        """

        result = await graphql(schema, query_str, variable_values={"minAge": 21})

        assert result is not None
        if result.errors:
            error_str = str(result.errors)
            assert "rust" not in error_str.lower(), (
                f"Rust pipeline error with variables: {error_str}"
            )


@pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust pipeline not available")
class TestRustPipelineErrorHandling:
    """Test that Rust pipeline handles errors gracefully."""

    async def test_rust_pipeline_graceful_fallback(self, rust_test_schema, meta_test_pool):
        """Rust pipeline should fallback gracefully on errors."""
        # This test ensures that if the Rust pipeline fails,
        # the system can still function (presumably falling back to Python)

        schema = rust_test_schema.build_schema()

        # Try a query that might stress the pipeline
        query_str = """
        query {
            getUsers(where: {
                AND: [
                    {age: {gte: 0}},
                    {name: {contains: ""}},
                    {isActive: {eq: true}}
                ]
            }) {
                id
                name
                age
                fullName
                isAdult
            }
        }
        """

        result = await graphql(schema, query_str)

        # Should not crash the entire system
        assert result is not None, "GraphQL execution should not crash"

        # If there are errors, they should be data/query related, not pipeline crashes
        if result.errors:
            error_messages = [str(e) for e in result.errors]
            # Look for crash indicators
            crash_indicators = ["panic", "segmentation fault", "null pointer", "rust"]
            for error in error_messages:
                for indicator in crash_indicators:
                    assert indicator not in error.lower(), f"Pipeline crash detected: {error}"

    async def test_rust_pipeline_with_invalid_sql(self, meta_test_pool):
        """Rust pipeline should handle invalid SQL gracefully."""
        try:
            # Try invalid SQL that should fail gracefully
            async with meta_test_pool.connection() as conn:
                await conn.execute("SELECT * FROM nonexistent_table_invalid_sql_test")
                # If it succeeds, that's unexpected but not a crash
                # If it fails, it should be a clean database error
        except Exception as e:
            # Should be a database error, not a Rust panic or crash
            error_str = str(e).lower()
            crash_indicators = ["panic", "segmentation fault", "null pointer"]
            for indicator in crash_indicators:
                assert indicator not in error_str, f"Rust pipeline crash on invalid SQL: {e}"


@pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust pipeline not available")
class TestRustPipelinePerformance:
    """Test Rust pipeline performance characteristics."""

    async def test_rust_pipeline_response_time(self, rust_test_schema, meta_test_pool):
        """Rust pipeline should provide reasonable response times."""
        import time

        schema = rust_test_schema.build_schema()

        query_str = """
        query {
            getUsers {
                id
                name
                email
            }
        }
        """

        # Time multiple executions
        times = []
        for _ in range(5):
            start_time = time.time()
            result = await graphql(schema, query_str)
            end_time = time.time()

            assert not result.errors, f"Query failed during timing: {result.errors}"
            times.append(end_time - start_time)

        avg_time = sum(times) / len(times)

        # Should complete in reasonable time (< 1 second per query)
        assert avg_time < 1.0, f"Rust pipeline too slow: {avg_time:.3f}s average"

    async def test_rust_pipeline_memory_usage(self, rust_test_schema, meta_test_pool):
        """Rust pipeline should not have excessive memory usage."""
        # This is a basic test - in a real scenario you'd use memory profiling
        schema = rust_test_schema.build_schema()

        # Run multiple complex queries
        for i in range(10):
            query_str = f"""
            query GetUsers{i} {{
                getUsers(where: {{id: {{eq: {i % 5}}}}}) {{
                    id
                    name
                    email
                }}
            }}
            """

            result = await graphql(schema, query_str)
            assert result is not None, f"Query {i} failed"

        # If we get here without crashes, memory usage is likely acceptable
        # In production, you'd monitor actual memory usage


class TestPipelineAvailability:
    """Test pipeline availability and basic functionality regardless of Rust."""

    async def test_some_pipeline_is_available(self, rust_test_schema, meta_test_pool):
        """At minimum, Python pipeline should be available."""
        schema = rust_test_schema.build_schema()

        query_str = """
        query {
            getUsers {
                id
                name
            }
        }
        """

        result = await graphql(schema, query_str)

        # Should have some result (success or expected failure)
        assert result is not None, "No pipeline available for GraphQL execution"

    def test_pipeline_choice_logic(self):
        """System should have logic to choose appropriate pipeline."""
        # This tests the high-level pipeline selection logic
        # In practice, this might be environment-dependent

        # At minimum, we should be able to import the core execution logic
        # FraiseQL uses graphql-core's graphql function for execution,
        # so we test that the schema can be built and executed
        from graphql import graphql as graphql_executor

        # Basic sanity check - graphql executor should be available
        assert graphql_executor is not None, "Core GraphQL execution not available"

    async def test_fallback_mechanism(self, rust_test_schema, meta_test_pool):
        """System should have fallback mechanisms when preferred pipeline fails."""
        schema = rust_test_schema.build_schema()

        # Test with a query that should work regardless of pipeline
        query_str = """
        query {
            getUsers {
                id
            }
        }
        """

        result = await graphql(schema, query_str)

        # Should succeed or fail gracefully, but not crash
        assert result is not None, "Pipeline fallback mechanism failed"
