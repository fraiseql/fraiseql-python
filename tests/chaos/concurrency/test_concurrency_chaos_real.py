"""Phase 4.2: Concurrency Chaos Tests (Real PostgreSQL Backend)

Tests for concurrent execution scenarios and thread safety.
Uses real PostgreSQL connections to validate FraiseQL's concurrent operation
handling and deadlock prevention.
"""

import asyncio
import random
import statistics

import pytest
from chaos.base import ChaosMetrics
from chaos.fraiseql_scenarios import FraiseQLTestScenarios


@pytest.mark.chaos
@pytest.mark.chaos_concurrency
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_concurrent_query_execution(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test concurrent query execution and thread safety.

    Scenario: Multiple concurrent requests execute simultaneously.
    Expected: FraiseQL handles concurrent requests gracefully without interference.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Simulate concurrent requests
    num_concurrent_requests = 8
    execution_times = []

    async def execute_concurrent_query(request_id: int):
        """Execute a query in a concurrent context."""
        try:
            # Add some randomness to simulate different execution times
            if random.random() < 0.1:  # 10% chance of latency injection
                chaos_db_client.inject_latency(random.uniform(10, 30))

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            metrics.record_query_time(execution_time)

            chaos_db_client.reset_chaos()
            return ("success", request_id, execution_time)

        except Exception as e:
            metrics.record_error()
            chaos_db_client.reset_chaos()
            return ("error", request_id, str(e))

    # Execute requests concurrently
    tasks = [execute_concurrent_query(i) for i in range(num_concurrent_requests)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    # Collect results
    successes = 0
    errors = 0
    for result in results:
        if isinstance(result, tuple) and result[0] == "success":
            successes += 1
            execution_times.append(result[2])
        else:
            errors += 1

    # Validate concurrent query execution
    assert successes >= num_concurrent_requests * 0.75, (
        f"Too many concurrent query failures: {successes}/{num_concurrent_requests}"
    )

    if execution_times:
        avg_time = statistics.mean(execution_times)
        max_time = max(execution_times)

        # Concurrent execution should not cause excessive delays
        assert max_time <= avg_time * 3, (
            f"Excessive concurrency variance: max {max_time:.1f}ms vs avg {avg_time:.1f}ms"
        )


@pytest.mark.chaos
@pytest.mark.chaos_concurrency
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_race_condition_prevention(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test race condition prevention in concurrent operations.

    Scenario: Multiple concurrent requests might cause race conditions.
    Expected: FraiseQL prevents race conditions and maintains data consistency.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Simulate concurrent operations that could cause race conditions
    num_concurrent = 5
    execution_times = []
    race_conditions_detected = 0

    async def execute_race_prone_operation(thread_id: int):
        """Execute operation that could trigger race conditions."""
        try:
            # Small delays to increase race condition chances
            await asyncio.sleep(random.uniform(0.001, 0.005))

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 15.0)
            metrics.record_query_time(execution_time)

            return ("success", thread_id, execution_time)

        except Exception as e:
            metrics.record_error()
            # Check if error indicates race condition
            if "race" in str(e).lower() or "conflict" in str(e).lower():
                return ("race_condition", thread_id, str(e))
            return ("error", thread_id, str(e))

    # Execute concurrent operations
    tasks = [execute_race_prone_operation(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    # Collect results
    successes = 0
    errors = 0
    for result in results:
        if isinstance(result, tuple):
            if result[0] == "success":
                successes += 1
                execution_times.append(result[2])
            elif result[0] == "race_condition":
                race_conditions_detected += 1
                errors += 1
            else:
                errors += 1

    # Validate race condition prevention
    success_rate = successes / num_concurrent
    assert success_rate >= 0.8, f"Race conditions caused too many failures: {success_rate:.2f}"

    # Race conditions should be minimal
    if race_conditions_detected > 0:
        assert race_conditions_detected <= 1, f"Too many race conditions: {race_conditions_detected}"


@pytest.mark.chaos
@pytest.mark.chaos_concurrency
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_deadlock_prevention_under_load(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test deadlock prevention under concurrent load.

    Scenario: Complex concurrent operations that could create deadlocks.
    Expected: FraiseQL prevents deadlocks through proper resource ordering.
    """
    metrics = ChaosMetrics()
    operations = [
        FraiseQLTestScenarios.simple_user_query(),
        FraiseQLTestScenarios.complex_nested_query(),
        FraiseQLTestScenarios.mutation_create_post(),
        FraiseQLTestScenarios.search_query(),
    ]

    metrics.start_test()

    # Simulate different operation types under concurrent load
    num_concurrent = 4
    operations_per_concurrent = 3
    execution_times = []
    deadlock_events = 0

    async def execute_complex_operation(thread_id: int, operation_index: int):
        """Execute a complex operation that might contribute to deadlocks."""
        try:
            operation = operations[operation_index % len(operations)]

            # Simulate some processing time (potential deadlock window)
            await asyncio.sleep(random.uniform(0.001, 0.005))

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 30.0)
            metrics.record_query_time(execution_time)

            return ("success", thread_id, execution_time)

        except Exception as e:
            metrics.record_error()
            if "deadlock" in str(e).lower():
                return ("deadlock", thread_id, str(e))
            return ("error", thread_id, str(e))

    # Execute concurrent operations
    tasks = []
    for thread_id in range(num_concurrent):
        for op_index in range(operations_per_concurrent):
            tasks.append(execute_complex_operation(thread_id, op_index))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    # Collect results
    successes = 0
    errors = 0
    for result in results:
        if isinstance(result, tuple):
            if result[0] == "success":
                successes += 1
                execution_times.append(result[2])
            elif result[0] == "deadlock":
                deadlock_events += 1
                errors += 1
            else:
                errors += 1

    total_ops = num_concurrent * operations_per_concurrent
    success_rate = successes / total_ops
    assert success_rate >= 0.75, (
        f"Deadlock prevention failures: {success_rate:.2f} success rate"
    )

    # Deadlocks should be minimal
    if deadlock_events > 0:
        deadlock_rate = deadlock_events / total_ops
        assert deadlock_rate < 0.2, f"Too many deadlocks: {deadlock_rate:.2f}"


@pytest.mark.chaos
@pytest.mark.chaos_concurrency
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_concurrent_connection_pooling(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test concurrent access to connection pools.

    Scenario: Multiple concurrent requests compete for database connections.
    Expected: FraiseQL manages connection pooling correctly under concurrency.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Simulate connection pool with high concurrency
    num_concurrent_requests = 8
    execution_times = []
    pool_exhaustion_events = 0

    async def execute_with_connection_pool(request_id: int):
        """Execute operation using connection pool."""
        try:
            # Add randomness to execution
            if random.random() < 0.15:  # 15% chance of high latency
                chaos_db_client.inject_latency(random.uniform(50, 100))

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 15.0)
            metrics.record_query_time(execution_time)

            chaos_db_client.reset_chaos()
            return ("success", request_id, execution_time)

        except ConnectionError:
            pool_exhaustion_events += 1
            metrics.record_error()
            chaos_db_client.reset_chaos()
            return ("pool_exhausted", request_id, "Connection pool exhausted")

        except Exception as e:
            metrics.record_error()
            chaos_db_client.reset_chaos()
            return ("error", request_id, str(e))

    # Execute concurrent operations competing for connections
    tasks = [execute_with_connection_pool(i) for i in range(num_concurrent_requests)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    # Collect results
    successes = 0
    errors = 0
    for result in results:
        if isinstance(result, tuple) and result[0] == "success":
            successes += 1
            execution_times.append(result[2])
        else:
            errors += 1

    # Validate connection pooling under concurrency
    success_rate = successes / num_concurrent_requests
    assert success_rate >= 0.7, f"Connection pooling failures: {success_rate:.2f}"

    if execution_times:
        avg_wait = statistics.mean(execution_times)
        max_wait = max(execution_times)
        assert max_wait < 200, f"Excessive connection wait times: max {max_wait:.1f}ms"


@pytest.mark.chaos
@pytest.mark.chaos_concurrency
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_concurrent_mutation_isolation(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test mutation operation isolation under concurrent execution.

    Scenario: Multiple mutation operations execute concurrently.
    Expected: FraiseQL maintains operation isolation and consistency.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.mutation_create_post()

    metrics.start_test()

    # Simulate concurrent mutation operations
    num_concurrent = 6
    execution_times = []
    isolation_violations = 0

    async def execute_isolated_mutation(thread_id: int):
        """Execute a mutation operation with isolation requirements."""
        try:
            # Small processing delay (isolation test window)
            await asyncio.sleep(random.uniform(0.001, 0.005))

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 25.0)
            metrics.record_query_time(execution_time)

            return ("success", thread_id, execution_time)

        except Exception as e:
            metrics.record_error()
            # Check for isolation violation
            if "isolation" in str(e).lower() or "conflict" in str(e).lower():
                return ("isolation_violation", thread_id, str(e))
            return ("error", thread_id, str(e))

    # Execute concurrent mutations
    tasks = [execute_isolated_mutation(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    # Collect results
    successes = 0
    errors = 0
    for result in results:
        if isinstance(result, tuple):
            if result[0] == "success":
                successes += 1
                execution_times.append(result[2])
            elif result[0] == "isolation_violation":
                isolation_violations += 1
                errors += 1
            else:
                errors += 1

    # Validate mutation isolation
    success_rate = successes / num_concurrent
    assert success_rate >= 0.9, f"Mutation operation failures: {success_rate:.2f}"

    # Isolation violations should be minimal
    if isolation_violations > 0:
        violation_rate = isolation_violations / num_concurrent
        assert violation_rate < 0.2, f"Too many isolation violations: {violation_rate:.2f}"


@pytest.mark.chaos
@pytest.mark.chaos_concurrency
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_load_shedding_under_extreme_concurrency(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test load shedding behavior under extreme concurrent load.

    Scenario: Many concurrent requests exceed system capacity.
    Expected: FraiseQL gracefully degrades and sheds load appropriately.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Simulate extreme concurrent load
    extreme_concurrency = 20
    execution_times = []
    load_shed_events = 0

    async def execute_under_extreme_load(request_id: int):
        """Execute query under extreme concurrent load."""
        try:
            # Inject varying latency to simulate resource contention
            if request_id % 3 == 0:
                chaos_db_client.inject_latency(random.uniform(50, 150))

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            metrics.record_query_time(execution_time)

            chaos_db_client.reset_chaos()
            return ("success", request_id, execution_time)

        except TimeoutError:
            load_shed_events += 1
            metrics.record_error()
            chaos_db_client.reset_chaos()
            return ("load_shed", request_id, "Request timeout")

        except Exception as e:
            metrics.record_error()
            chaos_db_client.reset_chaos()
            return ("error", request_id, str(e))

    # Execute extreme concurrent load
    tasks = [execute_under_extreme_load(i) for i in range(extreme_concurrency)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    # Collect results
    successes = 0
    errors = 0
    for result in results:
        if isinstance(result, tuple) and result[0] == "success":
            successes += 1
            execution_times.append(result[2])
        else:
            errors += 1

    # System should handle some portion of requests even under extreme load
    success_rate = successes / extreme_concurrency
    assert success_rate >= 0.5, (
        f"System failed under extreme concurrency: {success_rate:.2f} success rate"
    )

    # Load shedding should be graceful (some requests handled, some shed)
    if load_shed_events > 0:
        shed_rate = load_shed_events / extreme_concurrency
        assert shed_rate < 0.6, f"Excessive load shedding: {shed_rate:.2f}"
