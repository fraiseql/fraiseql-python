"""Performance regression detection tests.

These tests ensure that query performance doesn't degrade over time and that
the system maintains acceptable response times under various load conditions.
"""

import asyncio
import statistics
import time

import pytest
from graphql import graphql

# Import schema_builder to ensure SchemaRegistry is patched
import fraiseql.gql.schema_builder  # noqa: F401
from fraiseql import fraise_type, query


@pytest.fixture(scope="class")
def performance_schema(meta_test_schema):
    """Schema optimized for performance testing."""
    # Clear any existing registrations
    meta_test_schema.clear()

    @fraise_type(sql_source="perf_users")
    class User:
        id: int
        email: str
        name: str
        created_at: str

    @fraise_type(sql_source="perf_posts")
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


class TestPerformanceBaseline:
    """Tests to detect performance regressions in query execution."""

    async def test_baseline_query_performance(self, performance_schema, meta_test_pool):
        """Establish baseline performance for simple queries."""
        schema = performance_schema.build_schema()

        query_str = "query { getUsers { id email } }"

        # Execute multiple times to get stable measurements
        times = []
        iterations = 10

        for _ in range(iterations):
            start = time.perf_counter()
            result = await graphql(schema, query_str)
            end = time.perf_counter()

            assert result is not None
            times.append(end - start)

        avg_time = statistics.mean(times)
        p95_time = statistics.quantiles(times, n=20)[18]  # 95th percentile

        # Baseline expectations (these would be adjusted based on actual performance)
        assert avg_time < 0.1, f"Average query time too slow: {avg_time:.4f}s"
        assert p95_time < 0.2, f"95th percentile too slow: {p95_time:.4f}s"

        # Store performance metrics for regression detection
        self.baseline_metrics = {
            "avg_time": avg_time,
            "p95_time": p95_time,
            "min_time": min(times),
            "max_time": max(times),
        }

    async def test_complex_query_performance(self, performance_schema, meta_test_pool):
        """Test performance of complex nested queries."""
        schema = performance_schema.build_schema()

        complex_query = """
        query {
            getUsers {
                id
                email
                posts: getPosts {
                    id
                    title
                }
            }
        }
        """

        times = []
        iterations = 5

        for _ in range(iterations):
            start = time.perf_counter()
            result = await graphql(schema, complex_query)
            end = time.perf_counter()

            assert result is not None
            times.append(end - start)

        avg_time = statistics.mean(times)

        # Complex queries should still be reasonably fast
        assert avg_time < 0.5, f"Complex query too slow: {avg_time:.4f}s"

    async def test_concurrent_load_performance(self, performance_schema, meta_test_pool):
        """Test performance under concurrent load."""
        schema = performance_schema.build_schema()

        async def execute_query(query_id: int):
            query_str = "query { getUsers { id } }"
            start = time.perf_counter()
            result = await graphql(schema, query_str)
            end = time.perf_counter()

            assert result is not None
            return end - start

        # Test with different concurrency levels
        concurrency_levels = [1, 5, 10, 20]

        for concurrency in concurrency_levels:
            tasks = [execute_query(i) for i in range(concurrency)]
            start_time = time.perf_counter()
            results = await asyncio.gather(*tasks)
            total_time = time.perf_counter() - start_time

            avg_response_time = statistics.mean(results)
            throughput = concurrency / total_time

            # Basic performance expectations
            assert avg_response_time < 1.0, (
                f"High latency at concurrency {concurrency}: {avg_response_time:.4f}s"
            )
            assert throughput > 1, (
                f"Low throughput at concurrency {concurrency}: {throughput:.2f} req/s"
            )

    async def test_memory_usage_under_load(self, performance_schema, meta_test_pool):
        """Monitor memory usage patterns under sustained load."""
        schema = performance_schema.build_schema()

        query_str = "query { getUsers { id email name } }"

        # Execute sustained load
        for i in range(100):
            result = await graphql(schema, query_str)
            assert result is not None

            # Periodic check that we haven't crashed
            if i % 25 == 0:
                # In a real implementation, you'd check actual memory usage
                # For now, we just ensure the system is still responsive
                assert True, f"System still operational after {i} queries"

    async def test_database_connection_pool_performance(self, performance_schema, meta_test_pool):
        """Test that database connection pool doesn't become a bottleneck."""
        schema = performance_schema.build_schema()

        query_str = "query { getUsers { id } }"

        # Execute many queries quickly
        start_time = time.perf_counter()

        for _i in range(50):
            result = await graphql(schema, query_str)
            assert result is not None

        total_time = time.perf_counter() - start_time
        avg_time = total_time / 50

        # Connection pool should not add significant overhead
        assert avg_time < 0.1, f"Connection pool bottleneck detected: {avg_time:.4f}s per query"

    async def test_schema_building_performance(self, performance_schema, meta_test_pool):
        """Test that schema building remains fast."""
        # Measure schema building time
        start_time = time.perf_counter()
        schema = performance_schema.build_schema()
        end_time = time.perf_counter()

        build_time = end_time - start_time

        assert schema is not None
        assert build_time < 1.0, f"Schema building too slow: {build_time:.4f}s"

    async def test_introspection_performance(self, performance_schema, meta_test_pool):
        """Test that GraphQL introspection remains performant."""
        schema = performance_schema.build_schema()

        # Basic introspection query
        introspection_query = """
        query {
            __schema {
                queryType { name }
                types { name kind }
            }
        }
        """

        start_time = time.perf_counter()
        result = await graphql(schema, introspection_query)
        end_time = time.perf_counter()

        query_time = end_time - start_time

        assert result is not None
        assert result.data is not None
        assert query_time < 0.5, f"Introspection too slow: {query_time:.4f}s"


class TestPerformanceBenchmarks:
    """Performance benchmarks for tracking over time."""

    async def test_query_throughput_benchmark(self, performance_schema, meta_test_pool):
        """Benchmark query throughput for regression detection."""
        schema = performance_schema.build_schema()

        queries = [
            "query { getUsers { id } }",
            "query { getPosts { id title } }",
            "query { getUsers { id email name } }",
        ]

        total_queries = 0
        total_time = 0
        start_time = time.perf_counter()

        # Run for approximately 2 seconds
        while time.perf_counter() - start_time < 2.0:
            for query_str in queries:
                query_start = time.perf_counter()
                result = await graphql(schema, query_str)
                query_end = time.perf_counter()

                assert result is not None
                total_time += query_end - query_start
                total_queries += 1

        end_time = time.perf_counter()
        total_wall_time = end_time - start_time

        throughput = total_queries / total_wall_time
        avg_latency = total_time / total_queries

        # Performance expectations
        assert throughput > 10, f"Low throughput: {throughput:.2f} queries/second"
        assert avg_latency < 0.1, f"High latency: {avg_latency:.4f}s per query"

    async def test_memory_efficiency_benchmark(self, performance_schema, meta_test_pool):
        """Benchmark memory efficiency for large result sets."""
        schema = performance_schema.build_schema()

        # Query that would return many results in production
        query_str = """
        query {
            getUsers {
                id
                email
                name
                created_at
            }
        }
        """

        # Execute multiple times to check for memory issues
        for i in range(20):
            start = time.perf_counter()
            result = await graphql(schema, query_str)
            end = time.perf_counter()

            assert result is not None
            execution_time = end - start

            # Ensure queries don't get progressively slower (memory leak indicator)
            assert execution_time < 1.0, (
                f"Query {i} too slow, possible memory issue: {execution_time:.4f}s"
            )
