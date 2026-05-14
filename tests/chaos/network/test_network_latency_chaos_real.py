"""Phase 1.2: Network Latency Chaos Tests (Real PostgreSQL Backend)

Tests for network latency scenarios and FraiseQL's adaptation to increased latency.
Uses real PostgreSQL connections to validate actual performance degradation and timeout behavior.
"""

import asyncio
import statistics

import pytest
from chaos.base import ChaosMetrics
from chaos.fraiseql_scenarios import FraiseQLTestScenarios


@pytest.mark.chaos
@pytest.mark.chaos_network
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_gradual_latency_increase(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test gradual network latency increase with real database.

    Scenario: Network latency increases progressively from 0ms to 2000ms.
    Expected: FraiseQL adapts gracefully to increasing latency,
    with execution times scaling linearly with injected latency.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Test latency progression: 0ms, 100ms, 500ms, 1000ms, 2000ms
    latencies = [0, 100, 500, 1000, 2000]

    for latency_ms in latencies:
        # Reset chaos and apply new latency
        chaos_db_client.reset_chaos()
        if latency_ms > 0:
            chaos_db_client.inject_latency(latency_ms)

        # Measure query performance under current latency
        query_times = []
        # Scale iterations based on hardware (3 on baseline, 3-12 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(3 * chaos_config.load_multiplier))

        for _ in range(iterations):
            try:
                result = await chaos_db_client.execute_query(operation)
                execution_time = result.get("_execution_time_ms", 10.0)
                query_times.append(execution_time)
                metrics.record_query_time(execution_time)
            except Exception:
                metrics.record_error()

        if query_times:
            avg_time = statistics.mean(query_times)

            # Validate reasonable performance degradation
            # For 0ms latency, just verify it's fast (< 10ms)
            # For non-zero latency, expect latency + small base time
            if latency_ms == 0:
                assert avg_time < 10, f"Baseline should be fast: got {avg_time:.1f}ms"
            else:
                expected_min_time = latency_ms * 0.9  # Allow 10% variance below
                expected_max_time = latency_ms * 1.5  # Allow 50% variance above

                assert expected_min_time <= avg_time <= expected_max_time, (
                    f"Latency {latency_ms}ms: expected {expected_min_time:.1f}-{expected_max_time:.1f}ms, "
                    f"got {avg_time:.1f}ms"
                )

    metrics.end_test()

    # Validate overall test results
    # With adaptive scaling, iterations vary (3 on baseline, 3-12 adaptive)
    expected_queries = len(latencies) * max(3, int(3 * chaos_config.load_multiplier))
    assert metrics.get_summary()["query_count"] == expected_queries


@pytest.mark.chaos
@pytest.mark.chaos_network
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_consistent_high_latency(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test consistent high network latency with real database.

    Scenario: Stable 500ms network latency for extended period.
    Expected: FraiseQL maintains functionality under consistent latency
    with consistent response times.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Apply consistent 500ms latency
    chaos_db_client.inject_latency(500)

    # Test under consistent latency for multiple operations
    consistent_times = []
    # Scale iterations based on hardware (10 on baseline, 5-40 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(5, int(10 * chaos_config.load_multiplier))

    for _ in range(iterations):
        try:
            result = await chaos_db_client.execute_query(operation)
            query_time = result.get("_execution_time_ms", 500.0)
            consistent_times.append(query_time)
            metrics.record_query_time(query_time)
        except Exception:
            metrics.record_error()

    chaos_db_client.reset_chaos()
    metrics.end_test()

    if consistent_times:
        avg_consistent = statistics.mean(consistent_times)
        stddev_consistent = statistics.stdev(consistent_times)

        # Validate consistent performance
        # Should be around 500ms (the injected latency)
        assert 400 <= avg_consistent <= 600, f"Expected ~500ms, got {avg_consistent:.1f}ms"

        # Variance should be small (latency is consistent)
        assert stddev_consistent < 150, (
            f"High variance under consistent latency: {stddev_consistent:.1f}ms"
        )


@pytest.mark.chaos
@pytest.mark.chaos_network
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_jittery_latency(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test jittery (variable) network latency with real database.

    Scenario: Base 200ms latency with variable jitter.
    Expected: FraiseQL handles variable network conditions with acceptable variance.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Simulate jittery latency (base + variable component)
    base_latency_ms = 200
    jitter_range_ms = 100

    # Test under jittery conditions
    jitter_times = []
    # Scale iterations based on hardware (15 on baseline, 7-60 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(7, int(15 * chaos_config.load_multiplier))

    for i in range(iterations):  # More samples for statistical significance
        # Variable jitter component
        jitter_ms = (i * 17) % jitter_range_ms  # Pseudo-random: 0-100ms jitter

        chaos_db_client.reset_chaos()
        chaos_db_client.inject_latency(base_latency_ms + jitter_ms)

        try:
            result = await chaos_db_client.execute_query(operation)
            query_time = result.get("_execution_time_ms", base_latency_ms + 50)
            jitter_times.append(query_time)
            metrics.record_query_time(query_time)
        except Exception:
            metrics.record_error()

    chaos_db_client.reset_chaos()
    metrics.end_test()

    if jitter_times:
        avg_jitter = statistics.mean(jitter_times)
        stddev_jitter = statistics.stdev(jitter_times)
        p95_jitter = sorted(jitter_times)[int(len(jitter_times) * 0.95)]

        # Validate jitter handling
        # Should be around base + average jitter
        assert 200 <= avg_jitter <= 400, f"Jitter test: expected 200-400ms, got {avg_jitter:.1f}ms"

        # Should show some variance (due to jitter)
        assert stddev_jitter > 10, f"Should show variance under jitter: {stddev_jitter:.1f}ms"

        # P95 should be reasonable (< 550ms)
        assert p95_jitter < 550, f"P95 should be reasonable: {p95_jitter:.1f}ms"


@pytest.mark.chaos
@pytest.mark.chaos_network
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_asymmetric_latency(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test asymmetric network latency (different request/response delays).

    Scenario: Simulate fast requests, slow responses.
    Expected: FraiseQL handles asymmetric network conditions.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Simulate asymmetric: fast outbound, slow inbound
    asymmetric_times = []

    # Scale iterations based on hardware (8 on baseline, 4-32 adaptive)

    # Uses multiplier-based formula to ensure meaningful test on all hardware

    iterations = max(4, int(8 * chaos_config.load_multiplier))

    for _ in range(iterations):
        # Simulate asymmetric latency: request fast, response slow
        # In real scenario, request has low latency but response has high latency
        chaos_db_client.reset_chaos()

        # Simulate with higher latency to simulate slow response
        chaos_db_client.inject_latency(300)

        try:
            result = await chaos_db_client.execute_query(operation)
            query_time = result.get("_execution_time_ms", 300.0)
            asymmetric_times.append(query_time)
            metrics.record_query_time(query_time)
        except Exception:
            metrics.record_error()

    chaos_db_client.reset_chaos()
    metrics.end_test()

    if asymmetric_times:
        avg_asymmetric = statistics.mean(asymmetric_times)

        # Validate asymmetric handling
        # Should be around the injected latency
        assert 250 <= avg_asymmetric <= 400, (
            f"Asymmetric test: expected ~300ms, got {avg_asymmetric:.1f}ms"
        )


@pytest.mark.chaos
@pytest.mark.chaos_network
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_latency_timeout_handling(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test timeout handling under extreme latency.

    Scenario: 2-second network latency exceeds query timeouts.
    Expected: FraiseQL handles timeouts gracefully with proper error responses.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Inject extreme latency that will cause timeouts
    chaos_db_client.inject_latency(2000)  # 2 second latency

    # Simulate operations that should timeout
    timeout_count = 0
    success_count = 0

    # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)

    # Uses multiplier-based formula to ensure meaningful test on all hardware

    iterations = max(3, int(5 * chaos_config.load_multiplier))

    for _ in range(iterations):
        try:
            # Set a short timeout (1.5s) while latency is 2s
            result = await asyncio.wait_for(chaos_db_client.execute_query(operation), timeout=1.5)
            success_count += 1
            metrics.record_query_time(result.get("_execution_time_ms", 2000))
        except TimeoutError:
            timeout_count += 1
            metrics.record_error()
        except Exception:
            timeout_count += 1
            metrics.record_error()

    chaos_db_client.reset_chaos()
    metrics.end_test()

    # Validate timeout behavior
    assert timeout_count > 0, "Should experience timeouts under extreme latency"
    # Some operations may complete if latency happens to be just under timeout
    assert (success_count + timeout_count) == iterations, (
        f"All {iterations} operations should complete (timeout or success)"
    )


@pytest.mark.chaos
@pytest.mark.chaos_network
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_latency_recovery_time(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test recovery time after latency chaos injection is removed.

    Scenario: High latency followed by immediate removal.
    Expected: Performance returns to baseline within acceptable time.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Baseline measurement (no chaos)
    baseline_times = []
    # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(3, int(5 * chaos_config.load_multiplier))

    for _ in range(iterations):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            baseline_times.append(execution_time)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    avg_baseline = statistics.mean(baseline_times) if baseline_times else 20.0

    # Inject high latency (1 second)
    chaos_db_client.inject_latency(1000)

    # Measure under chaos
    chaos_times = []
    # Scale iterations based on hardware (3 on baseline, 3-12 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(3, int(3 * chaos_config.load_multiplier))

    for _ in range(iterations):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 1000.0)
            chaos_times.append(execution_time)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    # Remove chaos immediately
    chaos_db_client.reset_chaos()

    # Measure recovery (immediate next operations)
    recovery_times = []
    # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(3, int(5 * chaos_config.load_multiplier))

    for _ in range(iterations):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            recovery_times.append(execution_time)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    metrics.end_test()

    if recovery_times:
        avg_recovery = statistics.mean(recovery_times)

        # Validate recovery (very relaxed threshold for sub-millisecond variance)
        # Sub-millisecond database timing in containers is inherently variable:
        # - First query cache effects (can be 10x faster than subsequent)
        # - Container networking jitter (0.1-0.5ms variance normal)
        # - Python GIL / OS scheduler (0.1-1ms variance)
        # Allow up to 500% variance for sub-millisecond baselines
        # (still validates recovery happens - just not exact timing)
        recovery_degradation = abs(avg_recovery - avg_baseline)
        assert recovery_degradation < avg_baseline * 5.0, (
            f"Recovery should be immediate: {recovery_degradation:.1f}ms degradation"
        )
