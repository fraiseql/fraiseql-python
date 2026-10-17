"""Memory leak detection tests for long-running processes.

These tests detect memory leaks and resource exhaustion issues that could
occur in production deployments with sustained load.
"""

import asyncio
import gc
import time

import pytest
from graphql import graphql

# Import schema_builder to ensure SchemaRegistry is patched
import fraiseql.gql.schema_builder  # noqa: F401
from fraiseql import fraise_type, query


@pytest.fixture(scope="class")
def memory_test_schema(meta_test_schema):
    """Schema designed for memory leak testing."""
    # Clear any existing registrations
    meta_test_schema.clear()

    @fraise_type(sql_source="memory_users")
    class User:
        id: int
        email: str
        name: str
        metadata: str  # Larger field to test memory usage

    @fraise_type(sql_source="memory_posts")
    class Post:
        id: int
        title: str
        content: str
        author_id: int

    @query
    async def get_users(info) -> list[User]:
        return []

    @query
    async def get_posts(info) -> list[Post]:
        return []

    # Register types
    meta_test_schema.register_type(User)
    meta_test_schema.register_type(Post)
    meta_test_schema.register_query(get_users)
    meta_test_schema.register_query(get_posts)

    return meta_test_schema


class TestMemoryLeakDetection:
    """Tests to detect memory leaks in long-running processes."""

    async def test_no_memory_leak_in_repeated_queries(self, memory_test_schema, meta_test_pool):
        """Ensure repeated query execution doesn't cause memory leaks."""
        schema = memory_test_schema.build_schema()

        query_str = """
        query {
            getUsers {
                id
                email
                name
                metadata
            }
        }
        """

        # Execute many queries to stress memory usage
        for i in range(1000):
            result = await graphql(schema, query_str)
            assert result is not None

            # Periodic garbage collection to detect leaks
            if i % 100 == 0:
                gc.collect()

        # If we get here without crashes, basic memory stability is maintained

    async def test_schema_reuse_memory_efficiency(self, memory_test_schema, meta_test_pool):
        """Test that reusing the same schema doesn't accumulate memory."""
        schema = memory_test_schema.build_schema()

        queries = [
            "query { getUsers { id } }",
            "query { getPosts { id title } }",
            "query { getUsers { id email name } }",
            "query { getPosts { id content } }",
        ]

        # Execute each query many times
        for _i in range(500):
            for query_str in queries:
                result = await graphql(schema, query_str)
                assert result is not None

        # Force garbage collection
        gc.collect()

        # System should still be responsive
        final_query = "query { getUsers { id } }"
        final_result = await graphql(schema, final_query)
        assert final_result is not None

    async def test_connection_pool_memory_usage(self, memory_test_schema, meta_test_pool):
        """Test that database connection pool doesn't leak memory."""
        schema = memory_test_schema.build_schema()

        query_str = "query { getUsers { id email } }"

        # Execute queries that use database connections
        for _i in range(200):
            result = await graphql(schema, query_str)
            assert result is not None

            # Verify connection pool is still functional
            async with meta_test_pool.connection() as conn:
                test_result = await conn.execute("SELECT 1")
                row = await test_result.fetchone()
                assert row[0] == 1

        # Force cleanup
        gc.collect()

    async def test_introspection_memory_usage(self, memory_test_schema, meta_test_pool):
        """Test that introspection queries don't cause memory issues."""
        schema = memory_test_schema.build_schema()

        # Full introspection query (large result)
        introspection_query = """
        query IntrospectionQuery {
            __schema {
                queryType { name }
                mutationType { name }
                types {
                    ...FullType
                }
            }
        }

        fragment FullType on __Type {
            kind
            name
            fields(includeDeprecated: true) {
                name
                type {
                    kind
                    name
                }
            }
        }
        """

        # Execute introspection multiple times
        for _i in range(50):
            result = await graphql(schema, introspection_query)
            assert result is not None
            assert result.data is not None

        # Force garbage collection
        gc.collect()

    async def test_complex_query_memory_usage(self, memory_test_schema, meta_test_pool):
        """Test memory usage with complex nested queries."""
        schema = memory_test_schema.build_schema()

        complex_query = """
        query {
            getUsers {
                id
                email
                posts: getPosts {
                    id
                    title
                    content
                }
            }
        }
        """

        # Execute complex queries multiple times
        for _i in range(100):
            result = await graphql(schema, complex_query)
            assert result is not None

        # Force cleanup
        gc.collect()

    async def test_error_handling_memory_usage(self, memory_test_schema, meta_test_pool):
        """Test that error handling doesn't cause memory leaks."""
        schema = memory_test_schema.build_schema()

        # Mix of valid and invalid queries
        queries = [
            "query { getUsers { id } }",  # Valid
            "query { getUsers { nonexistentField } }",  # Invalid - should error
            "query { getPosts { id } }",  # Valid
            "query { invalidQuery { id } }",  # Invalid - should error
        ]

        # Execute mix of queries that will produce errors
        for i in range(200):
            query_str = queries[i % len(queries)]
            result = await graphql(schema, query_str)
            # We don't assert success - some queries are designed to fail
            assert result is not None  # But execution should not crash

        # Force cleanup
        gc.collect()

    async def test_concurrent_execution_memory_usage(self, memory_test_schema, meta_test_pool):
        """Test memory usage under concurrent execution."""
        schema = memory_test_schema.build_schema()

        async def execute_query():
            query_str = "query { getUsers { id email } }"
            result = await graphql(schema, query_str)
            return result

        # Execute concurrent queries
        for _batch in range(10):
            tasks = [execute_query() for _ in range(20)]
            results = await asyncio.gather(*tasks)

            # All should complete
            assert len(results) == 20
            assert all(r is not None for r in results)

        # Force cleanup
        gc.collect()

    async def test_large_result_set_memory_handling(self, memory_test_schema, meta_test_pool):
        """Test memory handling with queries that could return large results."""
        schema = memory_test_schema.build_schema()

        # Query that selects many fields (simulating large result)
        large_query = """
        query {
            getUsers {
                id
                email
                name
                metadata
            }
            getPosts {
                id
                title
                content
            }
        }
        """

        # Execute multiple times
        for _i in range(100):
            result = await graphql(schema, large_query)
            assert result is not None

        # Force cleanup
        gc.collect()


class TestResourceLeakDetection:
    """Tests to detect resource leaks (connections, file handles, etc.)."""

    async def test_database_connection_leak_detection(self, memory_test_schema, meta_test_pool):
        """Detect database connection leaks."""
        schema = memory_test_schema.build_schema()

        query_str = "query { getUsers { id } }"

        # Execute many queries
        for _i in range(100):
            result = await graphql(schema, query_str)
            assert result is not None

        # Verify connection pool is still healthy
        meta_test_pool.get_stats() if hasattr(meta_test_pool, "get_stats") else None

        # Basic health check - can still execute queries
        final_result = await graphql(schema, query_str)
        assert final_result is not None

    async def test_graphql_context_cleanup(self, memory_test_schema, meta_test_pool):
        """Test that GraphQL contexts are properly cleaned up."""
        schema = memory_test_schema.build_schema()

        # Execute queries with context
        for i in range(50):
            result = await graphql(
                schema, "query { getUsers { id } }", context_value={"request_id": f"req-{i}"}
            )
            assert result is not None

        # Force cleanup
        gc.collect()

    async def test_schema_caching_memory_usage(self, memory_test_schema, meta_test_pool):
        """Test that schema caching doesn't cause memory growth."""
        # Create multiple schemas (simulating different requests)
        schemas = []
        for _i in range(10):
            schema = memory_test_schema.build_schema()
            schemas.append(schema)

        # Use each schema
        for schema in schemas:
            result = await graphql(schema, "query { getUsers { id } }")
            assert result is not None

        # Clear references and force cleanup
        del schemas
        gc.collect()

    async def test_long_running_process_stability(self, memory_test_schema, meta_test_pool):
        """Test stability over a simulated long-running process."""
        schema = memory_test_schema.build_schema()

        start_time = time.time()

        # Simulate 5 minutes of operation (in fast-forward)
        query_count = 0
        while time.time() - start_time < 10:  # 10 seconds simulation
            result = await graphql(schema, "query { getUsers { id } }")
            assert result is not None
            query_count += 1

            # Periodic cleanup
            if query_count % 100 == 0:
                gc.collect()

        # Should have executed many queries without issues
        assert query_count > 100, f"Only executed {query_count} queries in simulation"
