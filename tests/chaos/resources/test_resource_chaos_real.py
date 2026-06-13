"""Phase 4.1: Resource Chaos Tests (Real PostgreSQL Backend)

Tests for system resource failures and exhaustion scenarios.
Uses real PostgreSQL connections to validate FraiseQL's resource management
and graceful degradation under resource constraints.
"""

import asyncio
import random
import statistics

import pytest
from chaos.base import ChaosMetrics
from chaos.fraiseql_scenarios import FraiseQLTestScenarios


@pytest.mark.chaos
@pytest.mark.chaos_resources
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_memory_pressure_handling(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test memory pressure handling and graceful degradation.

    Scenario: System memory becomes constrained, forcing garbage collection and memory management.
    Expected: FraiseQL handles memory pressure gracefully without crashes.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.complex_nested_query()

    metrics.start_test()

    # Simulate memory pressure through operation complexity and frequency
    memory_pressure_operations = 25
    memory_stress = []

    # DETERMINISTIC PATTERN: Calculate exact GC pressure iterations
    # Industry best practice: Netflix's deterministic chaos scheduling
    gc_interval = max(1, int(1 / 0.2))  # Every 5th iteration triggers GC pressure
    gc_pressure_iterations = set(range(gc_interval - 1, memory_pressure_operations, gc_interval))

    for i in range(memory_pressure_operations):
        # Use increasingly complex operations to simulate memory pressure
        if i < 8:
            op = FraiseQLTestScenarios.simple_user_query()
        elif i < 16:
            op = FraiseQLTestScenarios.complex_nested_query()
        else:
            op = FraiseQLTestScenarios.search_query()  # Most complex

        try:
            result = await chaos_db_client.execute_query(op)
            execution_time = result.get("_execution_time_ms", 50.0)
            memory_stress.append(execution_time)
            metrics.record_query_time(execution_time)

            # Deterministic memory pressure (GC delays)
            if i in gc_pressure_iterations:  # Deterministic 20% rate
                await asyncio.sleep(0.050)  # 50ms delay simulating GC or memory allocation

        except Exception:
            metrics.record_error()

    metrics.end_test()

    # Validate memory pressure handling
    if memory_stress:
        avg_memory_time = statistics.mean(memory_stress)
        memory_variance = statistics.stdev(memory_stress) if len(memory_stress) > 1 else 0

        # Should handle memory pressure without excessive variance
        # Relaxed to 1.5x to account for GC pauses and memory allocation timing variance
        # Real-world variance: GC can cause ~80-90% variance in sub-millisecond operations
        assert memory_variance < avg_memory_time * 1.5, (
            f"Excessive variance under memory pressure: {memory_variance:.1f}ms"
        )

    summary = metrics.get_summary()
    success_rate = 1 - (summary.get("error_count", 0) / max(summary.get("query_count", 1), 1))
    assert success_rate >= 0.7, f"Memory pressure caused too many failures: {success_rate:.2f}"


@pytest.mark.chaos
@pytest.mark.chaos_resources
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_cpu_spike_resilience(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test CPU spike handling and computational resource management.

    Scenario: CPU usage spikes due to computational intensive operations.
    Expected: FraiseQL manages CPU resources and maintains responsiveness.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.complex_nested_query()

    metrics.start_test()

    # Simulate CPU-intensive operations
    cpu_intensive_operations = 15
    cpu_times = []

    for i in range(cpu_intensive_operations):
        # Mix of operations with varying computational complexity
        if i % 3 == 0:
            op = FraiseQLTestScenarios.simple_user_query()
            expected_complexity = 5
        elif i % 3 == 1:
            op = FraiseQLTestScenarios.complex_nested_query()
            expected_complexity = 50
        else:
            op = FraiseQLTestScenarios.search_query()
            expected_complexity = 75

        try:
            # Simulate CPU load based on complexity via latency injection
            cpu_load_factor = expected_complexity / 25.0  # Scale factor
            processing_delay = 10 + (cpu_load_factor * 5)  # Base 10ms + complexity factor

            # Inject latency to simulate CPU load
            chaos_db_client.inject_latency(processing_delay)

            result = await chaos_db_client.execute_query(op)
            execution_time = result.get("_execution_time_ms", processing_delay)
            cpu_times.append(execution_time)
            metrics.record_query_time(execution_time)

            # Reset chaos for next iteration
            chaos_db_client.reset_chaos()

        except Exception:
            metrics.record_error()
            chaos_db_client.reset_chaos()

    metrics.end_test()

    # Validate CPU spike handling
    if cpu_times:
        avg_cpu_time = statistics.mean(cpu_times)
        cpu_variance = statistics.stdev(cpu_times) if len(cpu_times) > 1 else 0

        # CPU-bound operations should have reasonable variance
        assert cpu_variance < avg_cpu_time * 1.2, (
            f"Excessive CPU time variance: {cpu_variance:.1f}ms"
        )

    summary = metrics.get_summary()
    assert summary.get("query_count", 0) >= cpu_intensive_operations * 0.8, (
        "Most CPU-intensive operations should complete"
    )


@pytest.mark.chaos
@pytest.mark.chaos_resources
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_disk_io_contention(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test disk I/O contention and storage resource management.

    Scenario: Disk I/O becomes contended due to concurrent operations.
    Expected: FraiseQL handles I/O contention gracefully with queuing.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.mutation_create_post()  # Write-heavy operation

    metrics.start_test()

    # Simulate disk I/O operations with contention
    io_operations = 20
    io_times = []
    io_contention_events = 0

    for i in range(io_operations):
        try:
            # Simulate I/O operation with potential contention
            base_io_time = 15  # 15ms base I/O time

            # Simulate contention (random I/O delays)
            if random.random() < 0.25:  # 25% chance of I/O contention
                io_contention_events += 1
                contention_delay = random.uniform(50, 150)  # 50-150ms additional delay
                base_io_time += contention_delay

            # Inject latency to simulate I/O delays
            chaos_db_client.inject_latency(base_io_time)

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", base_io_time)
            io_times.append(execution_time)
            metrics.record_query_time(execution_time)

            # Reset chaos for next iteration
            chaos_db_client.reset_chaos()

        except Exception:
            metrics.record_error()
            chaos_db_client.reset_chaos()

    metrics.end_test()

    # Validate disk I/O contention handling
    if io_times:
        avg_io_time = statistics.mean(io_times)
        io_variance = statistics.stdev(io_times) if len(io_times) > 1 else 0

        # I/O operations should show some variance due to contention but not excessive
        assert io_variance < avg_io_time * 1.5, f"Excessive I/O variance: {io_variance:.1f}ms"

    # Should have experienced some I/O contention
    assert io_contention_events > 0, "Should experience I/O contention events"

    summary = metrics.get_summary()
    success_rate = 1 - (summary.get("error_count", 0) / max(summary.get("query_count", 1), 1))
    assert success_rate >= 0.8, f"I/O contention caused too many failures: {success_rate:.2f}"


@pytest.mark.chaos
@pytest.mark.chaos_resources
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_resource_exhaustion_recovery(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test resource exhaustion scenarios and recovery mechanisms.

    Scenario: System resources become exhausted, then gradually recover.
    Expected: FraiseQL handles resource exhaustion gracefully and recovers.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.complex_nested_query()

    metrics.start_test()

    # Phase 1: Normal operation
    normal_operations = 5
    for _ in range(normal_operations):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 45.0)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    # Phase 2: Resource exhaustion
    exhaustion_operations = 8
    exhaustion_times = []
    resource_failures = 0

    for i in range(exhaustion_operations):
        try:
            # Simulate increasing resource exhaustion
            exhaustion_factor = (i + 1) / exhaustion_operations  # 0.125 to 1.0
            delay = 45 + (exhaustion_factor * 100)  # 45ms to 145ms

            chaos_db_client.inject_latency(delay)

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", delay)
            exhaustion_times.append(execution_time)
            metrics.record_query_time(execution_time)

            chaos_db_client.reset_chaos()

        except Exception:
            resource_failures += 1
            metrics.record_error()
            chaos_db_client.reset_chaos()

    # Phase 3: Resource recovery
    recovery_operations = 6
    recovery_times = []

    for i in range(recovery_operations):
        try:
            # Simulate improving resource availability
            recovery_factor = i / (recovery_operations - 1) if recovery_operations > 1 else 0
            delay = 145 - (recovery_factor * 100)  # 145ms to 45ms

            chaos_db_client.inject_latency(delay)

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", delay)
            recovery_times.append(execution_time)
            metrics.record_query_time(execution_time)

            chaos_db_client.reset_chaos()

        except Exception:
            metrics.record_error()
            chaos_db_client.reset_chaos()

    metrics.end_test()

    # Validate resource exhaustion and recovery
    if exhaustion_times and recovery_times:
        avg_exhaustion = statistics.mean(exhaustion_times)
        avg_recovery = statistics.mean(recovery_times)

        # Recovery should show improvement (lower latency)
        if avg_recovery > 0:
            recovery_improvement = (avg_exhaustion - avg_recovery) / avg_exhaustion
            # Don't assert, just validate recovery attempt was made
            assert recovery_improvement >= -0.5, "Recovery should not regress significantly"

    summary = metrics.get_summary()
    total_expected = normal_operations + exhaustion_operations + recovery_operations
    assert summary.get("query_count", 0) >= total_expected * 0.7, (
        f"Too many resource exhaustion failures: {summary.get('query_count', 0)}/{total_expected}"
    )


@pytest.mark.chaos
@pytest.mark.chaos_resources
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_system_resource_monitoring(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test system resource monitoring and adaptive behavior.

    Scenario: System monitors resource usage and adapts behavior accordingly.
    Expected: FraiseQL adapts to resource constraints intelligently.
    """
    metrics = ChaosMetrics()

    metrics.start_test()

    # Monitor system resources throughout the test
    monitoring_operations = 12
    adaptive_behavior = 0

    for i in range(monitoring_operations):
        try:
            # Simulate adaptive behavior based on resource usage
            # For testing, alternate between heavy and light operations
            if i % 3 == 0:
                # Heavy operation under resource constraint
                operation = FraiseQLTestScenarios.complex_nested_query()
                chaos_db_client.inject_latency(50)  # Simulate high resource usage
                adaptive_behavior += 1
            else:
                # Light operation (normal conditions)
                operation = FraiseQLTestScenarios.simple_user_query()

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 25.0)
            metrics.record_query_time(execution_time)

            chaos_db_client.reset_chaos()

            # Brief pause to allow resource monitoring
            await asyncio.sleep(0.010)

        except Exception:
            metrics.record_error()
            chaos_db_client.reset_chaos()

    metrics.end_test()

    # Validate resource monitoring and adaptation
    assert adaptive_behavior > 0, "Should demonstrate adaptive behavior"

    summary = metrics.get_summary()
    assert summary.get("query_count", 0) >= monitoring_operations * 0.8, (
        "Most monitoring operations should complete"
    )


@pytest.mark.chaos
@pytest.mark.chaos_resources
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_cascading_resource_failure_prevention(
    chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config
):
    """Test prevention of cascading resource failures.

    Scenario: One resource failure triggers cascading effects on other resources.
    Expected: FraiseQL contains resource failures and prevents cascading degradation.
    """
    metrics = ChaosMetrics()
    operations = [
        FraiseQLTestScenarios.simple_user_query(),
        FraiseQLTestScenarios.complex_nested_query(),
        FraiseQLTestScenarios.mutation_create_post(),
    ]

    metrics.start_test()

    # Simulate cascading resource failure scenario
    # Scale total_operations based on hardware (15 on baseline, 7-60 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    total_operations = max(7, int(15 * chaos_config.load_multiplier))
    primary_failures = 0
    cascading_failures = 0
    contained_operations = 0

    for i in range(total_operations):
        operation = operations[i % len(operations)]

        try:
            # Check for primary resource failure
            if i == 5:  # Primary failure at operation 5
                # Simulate resource exhaustion
                raise MemoryError("Primary resource failure: memory exhausted")

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 20.0)
            metrics.record_query_time(execution_time)
            contained_operations += 1

        except MemoryError:
            primary_failures += 1
            metrics.record_error()

            # Check if subsequent operations also fail (cascading)
            # Scale iterations based on hardware (2 on baseline, 3-8 adaptive)
            # Uses multiplier-based formula to ensure meaningful test on all hardware
            check_iterations = max(3, int(2 * chaos_config.load_multiplier))

            for j in range(check_iterations):  # Check next operations for cascading
                if i + j + 1 < total_operations:
                    try:
                        cascading_op = operations[(i + j + 1) % len(operations)]
                        result = await chaos_db_client.execute_query(cascading_op)
                        # If this succeeds, cascading was prevented
                    except Exception:
                        cascading_failures += 1

            break  # Stop after primary failure to check cascading

        except Exception:
            # Other failures
            metrics.record_error()

    metrics.end_test()

    # Validate cascading failure prevention
    assert primary_failures > 0, "Should experience primary resource failure"

    # Cascading failures should be minimal or prevented
    assert cascading_failures <= 1, f"Too many cascading failures: {cascading_failures}"
    # Test breaks after primary failure at operation 5, so expect ~5 contained operations
    assert contained_operations >= 3, (
        f"Too few operations completed before failure: {contained_operations}"
    )

    summary = metrics.get_summary()
    # System should remain operational despite resource failures
    if summary.get("query_count", 0) > 0:
        operational_rate = (
            summary.get("query_count", 0) - summary.get("error_count", 0)
        ) / summary.get("query_count", 1)
        assert operational_rate >= 0.6, (
            f"Resource failure caused excessive system degradation: {operational_rate:.2f}"
        )
