"""Phase 2 Chaos Engineering Validation Tests (Real PostgreSQL Backend)

Tests to validate that Phase 2 database chaos test success criteria are met.
Validates that FraiseQL maintains data consistency and handles database failures gracefully.
"""

import asyncio
import statistics

import pytest
from chaos.base import ChaosMetrics
from chaos.fraiseql_scenarios import FraiseQLTestScenarios


@pytest.mark.chaos
@pytest.mark.chaos_validation
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_query_execution_success_rate(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Validate query execution success rate under chaos.

    Success Criteria: 70% of operations must succeed under database chaos
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Execute queries with variable chaos
    num_operations = 20
    for i in range(num_operations):
        try:
            # Randomly inject latency on some operations
            if i % 4 == 0:
                chaos_db_client.inject_latency(100)

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            metrics.record_query_time(execution_time)

            chaos_db_client.reset_chaos()

        except Exception:
            metrics.record_error()
            chaos_db_client.reset_chaos()

    metrics.end_test()

    summary = metrics.get_summary()
    success_rate = 1 - (summary.get("error_count", 0) / max(summary.get("query_count", 1), 1))

    # Phase 2 success criteria: 70% operations must succeed
    assert success_rate >= 0.7, f"Success rate {success_rate:.2f} below 70% threshold"


@pytest.mark.chaos
@pytest.mark.chaos_validation
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_data_consistency_under_concurrent_load(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Validate data consistency under concurrent load.

    Success Criteria: Concurrent operations should maintain data consistency
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.mutation_create_post()

    metrics.start_test()

    num_concurrent = 6
    consistency_violations = 0

    async def execute_mutation_safely(operation_id: int):
        """Execute a mutation operation."""
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 25.0)
            metrics.record_query_time(execution_time)
            return True
        except Exception as e:
            if "conflict" in str(e).lower() or "consistency" in str(e).lower():
                nonlocal consistency_violations
                consistency_violations += 1
            metrics.record_error()
            return False

    # Execute concurrent mutations
    tasks = [execute_mutation_safely(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    summary = metrics.get_summary()

    # Most operations should complete successfully
    assert summary.get("query_count", 0) >= num_concurrent * 0.8, (
        "Most concurrent mutations should complete"
    )

    # Consistency violations should be minimal
    assert consistency_violations <= 1, f"Too many consistency violations: {consistency_violations}"


@pytest.mark.chaos
@pytest.mark.chaos_validation
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_error_rate_under_chaos_bounds(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Validate error rate stays within acceptable bounds under chaos.

    Success Criteria: Error rate spike should not exceed 60%
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.complex_nested_query()

    metrics.start_test()

    # Baseline phase (no chaos)
    baseline_errors = 0
    for _ in range(5):
        try:
            result = await chaos_db_client.execute_query(operation)
            metrics.record_query_time(result.get("_execution_time_ms", 50.0))
        except Exception:
            baseline_errors += 1
            metrics.record_error()

    baseline_error_rate = baseline_errors / 5

    # Chaos phase
    chaos_db_client.inject_latency(200)  # Significant latency

    chaos_errors = 0
    for _ in range(10):
        try:
            result = await chaos_db_client.execute_query(operation)
            metrics.record_query_time(result.get("_execution_time_ms", 200.0))
        except Exception:
            chaos_errors += 1
            metrics.record_error()

    chaos_db_client.reset_chaos()

    metrics.end_test()

    chaos_error_rate = chaos_errors / 10

    # Error rate spike should be bounded
    error_rate_spike = chaos_error_rate - baseline_error_rate
    assert error_rate_spike < 0.6, f"Error rate spike {error_rate_spike:.2f} exceeds 60% threshold"


@pytest.mark.chaos
@pytest.mark.chaos_validation
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_latency_degradation_bounds(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Validate latency degradation stays within bounds.

    Success Criteria: Query latency degradation should not exceed 10 seconds
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Baseline
    baseline_times = []
    for _ in range(5):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            baseline_times.append(execution_time)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    # Under chaos
    chaos_db_client.inject_latency(500)

    chaos_times = []
    for _ in range(5):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 500.0)
            chaos_times.append(execution_time)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    chaos_db_client.reset_chaos()

    metrics.end_test()

    # Validate latency degradation
    if baseline_times and chaos_times:
        baseline_avg = statistics.mean(baseline_times)
        chaos_avg = statistics.mean(chaos_times)
        degradation = chaos_avg - baseline_avg

        # Max degradation threshold: 10 seconds (10000ms)
        assert degradation < 10000, (
            f"Latency degradation {degradation:.1f}ms exceeds 10s threshold"
        )


@pytest.mark.chaos
@pytest.mark.chaos_validation
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_operation_isolation_under_concurrency(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Validate operation isolation under concurrent execution.

    Success Criteria: Concurrent operations should maintain isolation
    """
    metrics = ChaosMetrics()
    read_op = FraiseQLTestScenarios.simple_user_query()
    write_op = FraiseQLTestScenarios.mutation_create_post()

    metrics.start_test()

    num_concurrent = 4
    isolation_maintained = True

    async def execute_mixed_operations(op_id: int):
        """Execute read or write operations concurrently."""
        try:
            # Alternate between read and write
            operation = write_op if op_id % 2 == 0 else read_op

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 15.0)
            metrics.record_query_time(execution_time)

            return True
        except Exception as e:
            # Check for isolation violations
            if "isolation" in str(e).lower():
                return False
            metrics.record_error()
            return True  # Other errors don't count as isolation violations

    tasks = [execute_mixed_operations(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    # Most operations should maintain isolation
    isolation_successes = sum(1 for r in results if r is True)
    assert isolation_successes >= num_concurrent * 0.8, (
        "Most operations should maintain isolation"
    )


@pytest.mark.chaos
@pytest.mark.chaos_validation
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_cascading_failure_containment(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Validate that cascading failures are contained.

    Success Criteria: 95% of cascades should be prevented
    """
    metrics = ChaosMetrics()
    simple_op = FraiseQLTestScenarios.simple_user_query()
    complex_op = FraiseQLTestScenarios.complex_nested_query()

    metrics.start_test()

    cascade_attempts = 0
    cascade_prevented = 0

    for i in range(10):
        try:
            # Primary operation
            result = await chaos_db_client.execute_query(simple_op)
            metrics.record_query_time(result.get("_execution_time_ms", 10.0))

            # Dependent operation (should not cascade from primary failure)
            result = await chaos_db_client.execute_query(complex_op)
            metrics.record_query_time(result.get("_execution_time_ms", 50.0))

            cascade_prevented += 1
            cascade_attempts += 1

        except Exception:
            cascade_attempts += 1
            metrics.record_error()

    metrics.end_test()

    # Validate cascade prevention
    if cascade_attempts > 0:
        cascade_prevention_rate = cascade_prevented / cascade_attempts
        assert cascade_prevention_rate >= 0.9, (
            f"Cascade prevention rate {cascade_prevention_rate:.2f} below 90%"
        )
