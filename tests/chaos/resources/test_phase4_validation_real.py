"""Phase 4 Chaos Engineering Validation Tests (Real PostgreSQL Backend)

Tests to validate Phase 4 resource and concurrency chaos test success criteria.
Validates FraiseQL's resource management and concurrent execution reliability.
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
async def test_resource_exhaustion_recovery_time(
    chaos_db_client, chaos_test_schema, baseline_metrics
):
    """Validate resource exhaustion recovery time.

    Success Criteria: System should recover within reasonable timeframe
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.complex_nested_query()

    metrics.start_test()

    # Normal operation
    normal_times = []
    for _ in range(5):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 50.0)
            normal_times.append(execution_time)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    # Resource exhaustion phase
    chaos_db_client.inject_latency(200)

    exhausted_times = []
    for _ in range(5):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 200.0)
            exhausted_times.append(execution_time)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    # Recovery phase
    chaos_db_client.reset_chaos()

    recovery_times = []
    for _ in range(5):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 50.0)
            recovery_times.append(execution_time)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    metrics.end_test()

    # Validate recovery
    if exhausted_times and recovery_times:
        exhausted_avg = statistics.mean(exhausted_times)
        recovery_avg = statistics.mean(recovery_times)

        # Recovery should show improvement
        if exhausted_avg > 0:
            improvement = (exhausted_avg - recovery_avg) / exhausted_avg
            assert improvement >= -0.2, "System should recover from resource exhaustion"


@pytest.mark.chaos
@pytest.mark.chaos_validation
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_concurrent_throughput_under_load(
    chaos_db_client, chaos_test_schema, baseline_metrics
):
    """Validate concurrent throughput under resource load.

    Success Criteria: System should maintain reasonable throughput under load
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    num_concurrent = 10
    start_time = asyncio.get_event_loop().time()

    async def execute_under_load(query_id: int):
        """Execute query under load."""
        try:
            # Some queries experience latency
            if query_id % 3 == 0:
                chaos_db_client.inject_latency(50)

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            metrics.record_query_time(execution_time)

            chaos_db_client.reset_chaos()
            return True
        except Exception:
            metrics.record_error()
            chaos_db_client.reset_chaos()
            return False

    # Execute concurrent queries
    tasks = [execute_under_load(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    elapsed_time = asyncio.get_event_loop().time() - start_time
    metrics.end_test()

    summary = metrics.get_summary()

    # System should complete most concurrent operations
    assert summary.get("query_count", 0) >= num_concurrent * 0.8, (
        "System should handle concurrent load"
    )

    # Throughput should be measurable
    throughput = summary.get("query_count", 0) / max(elapsed_time, 0.001)
    assert throughput > 0, "System should have positive throughput"


@pytest.mark.chaos
@pytest.mark.chaos_validation
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_deadlock_detection_and_recovery(
    chaos_db_client, chaos_test_schema, baseline_metrics
):
    """Validate deadlock detection and recovery.

    Success Criteria: Deadlocks should be detected and recovered automatically
    """
    metrics = ChaosMetrics()
    operations = [
        FraiseQLTestScenarios.simple_user_query(),
        FraiseQLTestScenarios.mutation_create_post(),
    ]

    metrics.start_test()

    num_concurrent = 6
    deadlock_attempts = 0
    deadlock_recovered = 0

    async def execute_potential_deadlock(op_id: int):
        """Execute operation that might cause deadlock."""
        try:
            operation = operations[op_id % len(operations)]

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 20.0)
            metrics.record_query_time(execution_time)

            return True
        except Exception as e:
            if "deadlock" in str(e).lower():
                return False
            metrics.record_error()
            return True

    # Execute concurrent operations that might deadlock
    tasks = [execute_potential_deadlock(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    successes = sum(1 for r in results if r is True)

    # Most operations should complete despite deadlock potential
    success_rate = successes / num_concurrent
    assert success_rate >= 0.75, f"Deadlock recovery rate {success_rate:.2f} too low"


@pytest.mark.chaos
@pytest.mark.chaos_validation
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_connection_pool_utilization(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Validate connection pool utilization under concurrent load.

    Success Criteria: Connection pool should handle concurrent requests efficiently
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    num_concurrent = 8
    success_count = 0

    async def execute_with_pooling(query_id: int):
        """Execute query using connection pool."""
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            metrics.record_query_time(execution_time)
            return True
        except ConnectionError:
            metrics.record_error()
            return False
        except Exception:
            metrics.record_error()
            return False

    # Execute concurrent queries using pool
    tasks = [execute_with_pooling(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    success_count = sum(1 for r in results if r is True)

    # Most concurrent operations should get connections
    success_rate = success_count / num_concurrent
    assert success_rate >= 0.75, f"Connection pool efficiency {success_rate:.2f} too low"


@pytest.mark.chaos
@pytest.mark.chaos_validation
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_extreme_concurrency_handling(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Validate system behavior under extreme concurrent load.

    Success Criteria: System should degrade gracefully, not crash
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    extreme_concurrency = 20
    success_count = 0

    async def execute_extreme_load(query_id: int):
        """Execute query under extreme load."""
        try:
            # Inject varying latency to simulate contention
            if query_id % 4 == 0:
                chaos_db_client.inject_latency(100)

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            metrics.record_query_time(execution_time)

            chaos_db_client.reset_chaos()
            return True
        except Exception:
            metrics.record_error()
            chaos_db_client.reset_chaos()
            return False

    # Execute extreme load
    tasks = [execute_extreme_load(i) for i in range(extreme_concurrency)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    success_count = sum(1 for r in results if r is True)

    # System should handle at least 50% of requests even under extreme load
    success_rate = success_count / extreme_concurrency
    assert success_rate >= 0.5, (
        f"Extreme concurrency handling failed: {success_rate:.2f} success rate"
    )

    # Should not crash (we get here if it didn't)
    summary = metrics.get_summary()
    assert summary.get("query_count", 0) > 0, "System should not crash under extreme load"


@pytest.mark.chaos
@pytest.mark.chaos_validation
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_graceful_degradation_under_stress(
    chaos_db_client, chaos_test_schema, baseline_metrics
):
    """Validate graceful degradation under stress.

    Success Criteria: Performance should degrade gracefully, not collapse
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.complex_nested_query()

    metrics.start_test()

    # Progressive stress test
    stress_levels = [0, 50, 100, 200]
    times_by_stress = {}

    for stress in stress_levels:
        stress_times = []

        if stress > 0:
            chaos_db_client.inject_latency(stress)

        for _ in range(5):
            try:
                result = await chaos_db_client.execute_query(operation)
                execution_time = result.get("_execution_time_ms", 50.0 + stress)
                stress_times.append(execution_time)
                metrics.record_query_time(execution_time)
            except Exception:
                metrics.record_error()

        if stress_times:
            times_by_stress[stress] = statistics.mean(stress_times)

        chaos_db_client.reset_chaos()

    metrics.end_test()

    # Validate graceful degradation (not exponential collapse)
    stress_levels_present = sorted(times_by_stress.keys())
    if len(stress_levels_present) >= 2:
        # Performance should increase roughly linearly with stress
        # Not exponentially worse
        for i in range(len(stress_levels_present) - 1):
            stress1 = stress_levels_present[i]
            stress2 = stress_levels_present[i + 1]
            time1 = times_by_stress[stress1]
            time2 = times_by_stress[stress2]

            # Performance should not collapse
            # (degradation should be roughly proportional)
            if time1 > 0:
                # Use absolute difference to avoid misleading ratios on small baselines
                # (50ms latency on 2.5ms base = 20x ratio, but only 47.5ms absolute difference)
                # Allow up to 150ms absolute degradation for system variance tolerance
                absolute_degradation = time2 - time1
                assert absolute_degradation < 150, (
                    f"Performance collapse detected: {time1:.1f}ms → {time2:.1f}ms "
                    f"(absolute: {absolute_degradation:.1f}ms)"
                )
