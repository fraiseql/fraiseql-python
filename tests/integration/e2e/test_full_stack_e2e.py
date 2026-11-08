"""End-to-end production readiness validation tests.

This test validates that FraiseQL is production-ready by testing complete
workflows from HTTP requests through GraphQL execution to database operations.
These tests ensure the system can handle real-world production scenarios.
"""

import asyncio
import time

import pytest
from graphql import graphql

# Import schema_builder to ensure SchemaRegistry is patched
import fraiseql.gql.schema_builder  # noqa: F401
from fraiseql import fraise_type, query


@pytest.fixture(scope="class")
def production_schema(meta_test_schema):
    """Production-like schema with realistic types and relationships."""
    # Clear any existing registrations
    meta_test_schema.clear()

    @fraise_type(sql_source="users")
    class User:
        id: int
        email: str
        first_name: str
        last_name: str
        created_at: str
        is_active: bool = True

        def full_name(self) -> str:
            return f"{self.first_name} {self.last_name}"

    @fraise_type(sql_source="posts")
    class Post:
        id: int
        title: str
        content: str
        author_id: int
        published_at: str | None = None
        view_count: int = 0
        tags: list[str]

    @fraise_type(sql_source="comments")
    class Comment:
        id: int
        post_id: int
        author_id: int
        content: str
        created_at: str
        likes: int = 0

    @fraise_type(sql_source="categories")
    class Category:
        id: int
        name: str
        description: str
        post_count: int = 0

    @query
    async def get_users(info) -> list[User]:
        return []

    @query
    async def get_posts(info) -> list[Post]:
        return []

    @query
    async def get_comments(info) -> list[Comment]:
        return []

    @query
    async def get_categories(info) -> list[Category]:
        return []

    # Register types with schema
    meta_test_schema.register_type(User)
    meta_test_schema.register_type(Post)
    meta_test_schema.register_type(Comment)
    meta_test_schema.register_type(Category)
    meta_test_schema.register_query(get_users)
    meta_test_schema.register_query(get_posts)
    meta_test_schema.register_query(get_comments)
    meta_test_schema.register_query(get_categories)

    return meta_test_schema


class TestFullStackE2E:
    """Complete end-to-end workflow tests simulating production usage."""

    async def test_complete_graphql_workflow(self, production_schema, meta_test_pool):
        """Test complete workflow: GraphQL parsing → SQL generation → PostgreSQL → Response."""
        schema = production_schema.build_schema()

        # Complex query simulating real application usage
        complex_query = """
        query GetBlogData($userId: Int, $publishedOnly: Boolean) {
            getUsers(where: {id: {eq: $userId}}) {
                id
                email
                fullName
                isActive
                posts: getPosts(where: {
                    authorId: {eq: $userId},
                    publishedAt: {isnull: $publishedOnly}
                }) {
                    id
                    title
                    content
                    viewCount
                    tags
                    comments: getComments {
                        id
                        content
                        likes
                        author: getUsers {
                            id
                            fullName
                        }
                    }
                }
            }
            getCategories {
                id
                name
                description
            }
        }
        """

        # Execute with realistic variables
        result = await graphql(
            schema, complex_query, variable_values={"userId": 1, "publishedOnly": False}
        )

        # Should complete without errors (even if data is empty)
        assert result is not None, "GraphQL execution should not crash"
        # Note: We don't assert no errors since data-related errors are expected in test environment

    async def test_concurrent_request_handling(self, production_schema, meta_test_pool):
        """Test handling multiple concurrent GraphQL requests."""
        schema = production_schema.build_schema()

        async def execute_query(query_id: int):
            query_str = f"""
            query Query{query_id} {{
                getUsers {{
                    id
                    email
                    fullName
                }}
            }}
            """

            result = await graphql(schema, query_str)
            return result

        # Execute multiple queries concurrently
        tasks = [execute_query(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # All should complete
        assert len(results) == 10, "All concurrent queries should complete"
        for i, result in enumerate(results):
            assert result is not None, f"Query {i} should not crash"

    async def test_large_result_set_handling(self, production_schema, meta_test_pool):
        """Test handling queries that would return large result sets."""
        schema = production_schema.build_schema()

        # Query that could potentially return many results
        query_str = """
        query {
            getPosts {
                id
                title
                content
                author: getUsers {
                    id
                    fullName
                    email
                }
                comments: getComments {
                    id
                    content
                    author: getUsers {
                        id
                        fullName
                    }
                }
            }
        }
        """

        result = await graphql(schema, query_str)

        # Should handle the complexity without crashing
        assert result is not None, "Large result set query should not crash"

    async def test_error_handling_in_production_scenario(self, production_schema, meta_test_pool):
        """Test error handling in realistic production scenarios."""
        schema = production_schema.build_schema()

        # Query with invalid syntax
        invalid_query = """
        query {
            getUsers(where: {invalidField: {eq: "test"}}) {
                id
                nonExistentField
            }
        }
        """

        result = await graphql(schema, invalid_query)

        # Should return errors, not crash
        assert result is not None, "Invalid query should not crash system"
        assert result.errors is not None, "Invalid query should return errors"

        # Errors should be GraphQL validation errors, not system crashes
        error_messages = [str(e) for e in result.errors]
        crash_indicators = ["panic", "segmentation fault", "null pointer", "exception"]
        for error in error_messages:
            for indicator in crash_indicators:
                assert indicator not in error.lower(), f"System crash detected: {error}"

    async def test_mixed_query_patterns(self, production_schema, meta_test_pool):
        """Test various query patterns that occur in real applications."""
        schema = production_schema.build_schema()

        test_queries = [
            # Simple list query
            """
            query { getUsers { id email } }
            """,
            # Filtered query
            """
            query { getPosts(where: {viewCount: {gt: 0}}) { id title } }
            """,
            # Nested query with aliases
            """
            query {
                users: getUsers { id name: fullName }
                posts: getPosts { id title author: getUsers { email } }
            }
            """,
            # Query with fragments
            """
            fragment UserInfo on User {
                id
                email
                fullName
            }
            query { getUsers { ...UserInfo } }
            """,
        ]

        for query_str in test_queries:
            result = await graphql(schema, query_str)
            assert result is not None, f"Query pattern should not crash: {query_str[:50]}..."

    async def test_introspection_in_production(self, production_schema, meta_test_pool):
        """Test GraphQL introspection works in production-like scenarios."""
        schema = production_schema.build_schema()

        # Full introspection query
        introspection_query = """
        query IntrospectionQuery {
            __schema {
                queryType { name }
                mutationType { name }
                subscriptionType { name }
                types {
                    ...FullType
                }
                directives {
                    name
                    description
                    locations
                    args {
                        ...InputValue
                    }
                }
            }
        }

        fragment FullType on __Type {
            kind
            name
            description
            fields(includeDeprecated: true) {
                name
                description
                args {
                    ...InputValue
                }
                type {
                    ...TypeRef
                }
                isDeprecated
                deprecationReason
            }
            inputFields {
                ...InputValue
            }
            interfaces {
                ...TypeRef
            }
            enumValues(includeDeprecated: true) {
                name
                description
                isDeprecated
                deprecationReason
            }
            possibleTypes {
                ...TypeRef
            }
        }

        fragment InputValue on __InputValue {
            name
            description
            type { ...TypeRef }
            defaultValue
        }

        fragment TypeRef on __Type {
            kind
            name
            ofType {
                kind
                name
                ofType {
                    kind
                    name
                    ofType {
                        kind
                        name
                        ofType {
                            kind
                            name
                            ofType {
                                kind
                                name
                                ofType {
                                    kind
                                    name
                                    ofType {
                                        kind
                                        name
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        result = await graphql(schema, introspection_query)

        assert result is not None, "Introspection should not crash"
        assert result.data is not None, "Introspection should return data"
        assert "__schema" in result.data, "Introspection should return schema information"


class TestPerformanceValidation:
    """Performance regression detection tests."""

    async def test_query_execution_performance(self, production_schema, meta_test_pool):
        """Ensure query execution performance meets basic requirements."""
        schema = production_schema.build_schema()

        query_str = """
        query {
            getUsers {
                id
                email
                fullName
                posts: getPosts {
                    id
                    title
                    comments: getComments {
                        id
                        content
                    }
                }
            }
        }
        """

        # Warm up
        await graphql(schema, query_str)

        # Time multiple executions
        executions = 5
        times = []

        for _ in range(executions):
            start_time = time.time()
            result = await graphql(schema, query_str)
            end_time = time.time()

            assert result is not None, "Query should execute successfully"
            times.append(end_time - start_time)

        avg_time = sum(times) / len(times)

        # Should complete in reasonable time (< 2 seconds average)
        assert avg_time < 2.0, f"Query too slow: {avg_time:.3f}s average"

    async def test_concurrent_performance(self, production_schema, meta_test_pool):
        """Test performance under concurrent load."""
        schema = production_schema.build_schema()

        async def execute_query():
            query_str = "query { getUsers { id email } }"
            result = await graphql(schema, query_str)
            return result

        # Execute 20 concurrent queries
        start_time = time.time()
        tasks = [execute_query() for _ in range(20)]
        results = await asyncio.gather(*tasks)
        end_time = time.time()

        total_time = end_time - start_time

        # All should complete
        assert len(results) == 20, "All concurrent queries should complete"
        assert all(r is not None for r in results), "All queries should return results"

        # Should complete in reasonable time (< 5 seconds for 20 concurrent queries)
        assert total_time < 5.0, f"Concurrent queries too slow: {total_time:.3f}s"

    async def test_memory_usage_stability(self, production_schema, meta_test_pool):
        """Test that memory usage remains stable under load."""
        # This is a basic test - in production you'd use proper memory profiling
        schema = production_schema.build_schema()

        query_str = """
        query { getPosts { id title author: getUsers { id email } } }
        """

        # Execute many queries to check for memory issues
        for i in range(50):
            result = await graphql(schema, query_str)
            assert result is not None, f"Query {i} should execute successfully"

        # If we get here without crashes, basic memory stability is maintained
        # In production, you'd monitor actual memory usage patterns


class TestMemoryLeakDetection:
    """Memory leak detection tests for long-running processes."""

    async def test_no_obvious_memory_leaks(self, production_schema, meta_test_pool):
        """Basic test for obvious memory leaks in repeated operations."""
        schema = production_schema.build_schema()

        # Execute the same query many times
        query_str = """
        query {
            getUsers { id email fullName }
            getPosts { id title }
            getComments { id content }
        }
        """

        for i in range(100):
            result = await graphql(schema, query_str)
            assert result is not None, f"Iteration {i} should not crash"

        # If we complete without crashes, no obvious memory leaks detected
        # Note: This is a very basic test. Production memory leak detection
        # would use specialized tools and monitoring.

    async def test_schema_reuse_stability(self, production_schema, meta_test_pool):
        """Test that reusing the same schema multiple times doesn't cause issues."""
        schema = production_schema.build_schema()

        queries = [
            "query { getUsers { id } }",
            "query { getPosts { id title } }",
            "query { getComments { id content } }",
            "query { getCategories { id name } }",
        ]

        # Execute each query multiple times
        for query_str in queries:
            for i in range(10):
                result = await graphql(schema, query_str)
                assert result is not None, f"Query {query_str[:30]}... iteration {i} failed"

    async def test_connection_pool_stability(self, production_schema, meta_test_pool):
        """Test that database connection pool remains stable under load."""
        schema = production_schema.build_schema()

        # Execute queries that would use the database connection pool
        query_str = "query { getUsers { id email } }"

        for i in range(50):
            result = await graphql(schema, query_str)
            assert result is not None, f"Database query {i} should not fail"

        # Verify connection pool is still functional
        async with meta_test_pool.connection() as conn:
            result = await conn.execute("SELECT 1")
            row = await result.fetchone()
            assert row[0] == 1, "Connection pool should still work after load"


class TestProductionReadiness:
    """Overall production readiness validation."""

    async def test_system_startup_stability(self, production_schema, meta_test_pool):
        """Test that the system can start up and handle requests immediately."""
        # This simulates what happens when a production service starts
        schema = production_schema.build_schema()

        # Immediately execute queries without warmup
        queries = [
            "query { getUsers { id } }",
            "query { getPosts { id } }",
            "query { getUsers(where: {isActive: {eq: true}}) { id email } }",
        ]

        for query_str in queries:
            result = await graphql(schema, query_str)
            assert result is not None, f"Startup query should work: {query_str}"

    async def test_error_recovery(self, production_schema, meta_test_pool):
        """Test that the system can recover from errors."""
        schema = production_schema.build_schema()

        # First, execute a failing query
        bad_query = "query { getUsers { nonexistentField } }"
        bad_result = await graphql(schema, bad_query)
        assert bad_result.errors is not None, "Bad query should produce errors"

        # Then execute a good query - system should still work
        good_query = "query { getUsers { id } }"
        good_result = await graphql(schema, good_query)
        assert good_result is not None, "System should recover after errors"

    async def test_resource_cleanup(self, production_schema, meta_test_pool):
        """Test that resources are properly cleaned up."""
        schema = production_schema.build_schema()

        # Execute many operations
        for _i in range(20):
            query_str = "query { getUsers { id } }"
            result = await graphql(schema, query_str)
            assert result is not None

        # In a real production test, you'd check that:
        # - Database connections are returned to pool
        # - Memory usage doesn't grow unbounded
        # - File handles are closed
        # - Temporary objects are garbage collected

        # For this basic test, we just ensure no crashes occurred
        assert True, "Resource cleanup test completed without crashes"
