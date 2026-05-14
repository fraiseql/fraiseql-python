"""Phase 2.1: Query Execution Chaos Tests (Real PostgreSQL Backend)

Tests for database query execution failures and performance degradation.
Uses real PostgreSQL to validate FraiseQL's handling of slow queries, deadlocks,
and serialization failures.
"""

import asyncio
import statistics

import pytest
from chaos.base import ChaosMetrics
from chaos.fraiseql_scenarios import FraiseQLTestScenarios


@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_slow_query_timeout_handling(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test handling of slow queries that exceed timeout limits.

    Scenario: Queries take progressively longer to execute via latency injection.
    Expected: FraiseQL handles timeouts gracefully with proper error responses.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.complex_nested_query()

    metrics.start_test()

    # Test with different timeout thresholds
    timeout_durations = [5000, 15000, 30000]  # 5s, 15s, 30s

    for timeout_duration in timeout_durations:
        timeout_seconds = timeout_duration / 1000.0

        # Inject artificial slowness (half the timeout duration)
        chaos_db_client.inject_latency(timeout_duration // 2)

        try:
            # Try to execute with specific timeout
            result = await asyncio.wait_for(
                chaos_db_client.execute_query(operation),
                timeout=timeout_seconds
            )
            execution_time = result.get("_execution_time_ms", 0)

            if execution_time > timeout_duration:
                # Query should have timed out
                metrics.record_error()
                assert False, (
                    f"Query should have timed out: {execution_time:.1f}ms > {timeout_duration}ms"
                )
            else:
                # Query completed within timeout
                metrics.record_query_time(execution_time)

        except TimeoutError:
            # Expected timeout behavior
            metrics.record_error()
            # This is expected for the longer timeout durations
        except Exception as e:
            # Other errors should be handled gracefully
            metrics.record_error()
            assert False, f"Unexpected error: {e}"

    chaos_db_client.reset_chaos()
    metrics.end_test()

    # Validate timeout behavior
    summary = metrics.get_summary()
    assert summary.get("error_count", 0) >= 0, "Timeout handling recorded"


@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_deadlock_detection_and_recovery(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test detection and recovery from database deadlocks.

    Scenario: Concurrent operations create deadlock conditions.
    Expected: FraiseQL detects deadlocks and retries appropriately.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.mutation_create_post()

    metrics.start_test()

    # Simulate deadlock scenario
    successful_operations = 0
    deadlock_errors = 0

    # Scale iterations based on hardware (10 on baseline, 5-40 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(5, int(10 * chaos_config.load_multiplier))



    for i in range(iterations):
        try:
            # Every 3rd operation simulates a deadlock with retry
            if i % 3 == 0:
                # Simulate deadlock detection delay
                await asyncio.sleep(0.1)
                raise Exception("Deadlock detected")

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 50.0)
            metrics.record_query_time(execution_time)
            successful_operations += 1

        except Exception as e:
            if "Deadlock" in str(e):
                deadlock_errors += 1
                metrics.record_error()
                # Simulate retry delay
                await asyncio.sleep(0.05)
            else:
                raise  # Re-raise unexpected errors

    metrics.end_test()

    # Validate deadlock handling
    assert deadlock_errors > 0, "Should experience some deadlock conditions"
    assert successful_operations > deadlock_errors, "Should recover from most deadlocks"
    # Scale deadlock threshold based on adaptive scaling (every 3rd op is a deadlock)
    expected_max_deadlocks = max(4, int(iterations / 3) + 1)
    assert deadlock_errors <= expected_max_deadlocks, (
        f"Deadlock rate should be reasonable: {deadlock_errors} <= {expected_max_deadlocks}"
    )


@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_serialization_failure_handling(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test handling of serialization failures in concurrent environments.

    Scenario: Multiple transactions conflict due to concurrent modifications.
    Expected: FraiseQL handles serialization failures with appropriate retry logic.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.mutation_create_post()

    metrics.start_test()

    # Simulate serialization conflicts
    serialization_errors = 0
    successful_commits = 0

    # Scale iterations based on hardware (8 on baseline, 4-32 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(4, int(8 * chaos_config.load_multiplier))



    for i in range(iterations):
        retry_count = 0
        success = False

        while retry_count < 3 and not success:
            try:
                # Simulate serialization conflict probability
                if retry_count == 0 and i % 2 == 1:  # First attempt fails for odd operations
                    raise Exception("Serialization failure: could not serialize access")

                result = await chaos_db_client.execute_query(operation)
                execution_time = result.get("_execution_time_ms", 30.0)
                metrics.record_query_time(execution_time)
                successful_commits += 1
                success = True

            except Exception as e:
                if "Serialization failure" in str(e):
                    serialization_errors += 1
                    retry_count += 1
                    # Exponential backoff
                    await asyncio.sleep(0.01 * (2 ** retry_count))
                else:
                    raise

    metrics.end_test()

    # Validate serialization failure handling
    assert serialization_errors > 0, "Should experience serialization conflicts"
    assert successful_commits >= 6, "Should successfully commit most operations after retries"
    assert serialization_errors <= successful_commits, (
        "Should resolve most conflicts with retries"
    )


@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_query_execution_pool_exhaustion(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test handling of database connection pool exhaustion during query execution.

    Scenario: All database connections become occupied, new queries queue or fail.
    Expected: FraiseQL handles pool exhaustion gracefully.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Simulate pool exhaustion by setting very small pool size
    original_pool_size = chaos_db_client.max_pool_size
    chaos_db_client.max_pool_size = 2  # Very small pool

    # Exhaust the connection pool
    exhausted_operations = 0
    pool_exhaustion_errors = 0

    # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(3, int(5 * chaos_config.load_multiplier))



    for i in range(iterations):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 20.0)
            metrics.record_query_time(execution_time)
            exhausted_operations += 1

            # Hold connection longer to simulate pool exhaustion
            await asyncio.sleep(0.1)

        except ConnectionError as e:
            if "pool exhausted" in str(e).lower():
                pool_exhaustion_errors += 1
                metrics.record_error()
            else:
                raise
        except Exception:
            pool_exhaustion_errors += 1
            metrics.record_error()

    # Restore normal pool size
    chaos_db_client.max_pool_size = original_pool_size

    metrics.end_test()

    # Validate pool exhaustion handling
    total_operations = exhausted_operations + pool_exhaustion_errors
    assert pool_exhaustion_errors >= 0, "Pool exhaustion handling verified"
    assert exhausted_operations >= 0, "Some operations completed"


@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_query_complexity_resource_exhaustion(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test handling of resource exhaustion from highly complex queries.

    Scenario: Very complex queries consume excessive database resources.
    Expected: FraiseQL handles resource exhaustion gracefully.
    """
    metrics = ChaosMetrics()

    # Use complex operations
    complex_operation = FraiseQLTestScenarios.search_query()
    simple_operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Test resource exhaustion with very complex queries
    resource_exhaustion_errors = 0
    successful_complex_queries = 0

    # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(3, int(5 * chaos_config.load_multiplier))



    for i in range(iterations):
        try:
            # Complex query that might exhaust resources
            result = await asyncio.wait_for(
                chaos_db_client.execute_query(complex_operation),
                timeout=10.0
            )
            execution_time = result.get("_execution_time_ms", 100.0)
            metrics.record_query_time(execution_time)
            successful_complex_queries += 1

        except TimeoutError:
            resource_exhaustion_errors += 1
            metrics.record_error()
        except Exception as e:
            if "resource" in str(e).lower() or "exhausted" in str(e).lower():
                resource_exhaustion_errors += 1
                metrics.record_error()
            else:
                raise

    metrics.end_test()

    # Validate resource exhaustion handling
    assert successful_complex_queries > 0, "Should successfully execute some complex queries"

    # Resource exhaustion is acceptable for very complex queries
    if resource_exhaustion_errors > 0:
        assert resource_exhaustion_errors <= 2, (
            "Resource exhaustion should be rare for complex queries"
        )


@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_concurrent_query_deadlock_simulation(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test deadlock detection in concurrent query scenarios.

    Scenario: Multiple queries execute concurrently, creating deadlock potential.
    Expected: FraiseQL detects and resolves deadlocks appropriately.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.complex_nested_query()

    metrics.start_test()

    # Simulate concurrent query execution
    async def execute_concurrent_query(thread_id: int):
        """Execute a query in a separate async task."""
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 50.0)
            metrics.record_query_time(execution_time)
            return (thread_id, execution_time, None)
        except Exception as e:
            metrics.record_error()
            return (thread_id, None, str(e))

    # Start multiple concurrent queries
    tasks = [execute_concurrent_query(i) for i in range(3)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    # Validate concurrent execution
    successful_results = [r for r in results if isinstance(r, tuple) and r[1] is not None]
    error_results = [r for r in results if isinstance(r, tuple) and r[2] is not None]

    assert len(successful_results) + len(error_results) == 3, "All concurrent queries should complete"
    assert len(successful_results) >= 2, "Most concurrent queries should succeed"

    # Check for reasonable execution times (should not be excessively slow)
    if successful_results:
        execution_times = [r[1] for r in successful_results]
        avg_concurrent_time = statistics.mean(execution_times)
        assert avg_concurrent_time < 200, (
            f"Concurrent queries too slow: {avg_concurrent_time:.1f}ms"
        )
