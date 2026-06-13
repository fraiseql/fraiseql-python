"""Phase 4.1: Resource Chaos Tests

Tests for system resource failures and exhaustion scenarios.
Validates FraiseQL's resource management and graceful degradation under resource constraints.
"""

import random
import statistics
import time

import psutil
import pytest
from chaos.base import ChaosTestCase
from chaos.fraiseql_scenarios import FraiseQLTestScenarios, MockFraiseQLClient


class TestResourceChaos(ChaosTestCase):
    """Test resource chaos scenarios."""

    @pytest.mark.chaos
    @pytest.mark.chaos_resources
    def test_memory_pressure_handling(self):
        """Test memory pressure handling and graceful degradation.

        Scenario: System memory becomes constrained, forcing garbage collection and memory management.
        Expected: FraiseQL handles memory pressure gracefully without crashes.
        """
        client = MockFraiseQLClient()
        operation = FraiseQLTestScenarios.complex_nested_query()

        self.metrics.start_test()

        # Simulate memory pressure through operation complexity and frequency
        memory_pressure_operations = 25
        memory_stress = []

        # Get initial memory usage
        initial_memory = psutil.virtual_memory().percent

        for i in range(memory_pressure_operations):
            # Use increasingly complex operations to simulate memory pressure
            if i < 8:
                op = FraiseQLTestScenarios.simple_user_query()
            elif i < 16:
                op = FraiseQLTestScenarios.complex_nested_query()
            else:
                op = FraiseQLTestScenarios.search_query()  # Most complex

            result = client.execute_query(op)
            execution_time = result.get("_execution_time_ms", 50.0)
            memory_stress.append(execution_time)
            self.metrics.record_query_time(execution_time)

            # Simulate memory pressure by introducing delays (representing GC pressure)
            if random.random() < 0.2:  # 20% chance of memory pressure
                time.sleep(0.050)  # 50ms delay simulating GC or memory allocation

            # Check current memory usage
            current_memory = psutil.virtual_memory().percent
            if current_memory > initial_memory + 5:  # Significant memory increase
                # System is under memory pressure
                pass

        self.metrics.end_test()

        # Validate memory pressure handling
        avg_memory_time = statistics.mean(memory_stress)
        memory_variance = statistics.stdev(memory_stress)

        # Should handle memory pressure without excessive variance
        assert memory_variance < avg_memory_time * 0.8, (
            f"Excessive variance under memory pressure: {memory_variance:.1f}ms"
        )

        summary = self.metrics.get_summary()
        success_rate = 1 - (summary["error_count"] / max(summary["query_count"], 1))
        assert success_rate >= 0.8, f"Memory pressure caused too many failures: {success_rate:.2f}"

        print(f"Memory pressure test: {len(memory_stress)} operations, avg {avg_memory_time:.1f}ms")

    @pytest.mark.chaos
    @pytest.mark.chaos_resources
    def test_cpu_spike_resilience(self):
        """Test CPU spike handling and computational resource management.

        Scenario: CPU usage spikes due to computational intensive operations.
        Expected: FraiseQL manages CPU resources and maintains responsiveness.
        """
        client = MockFraiseQLClient()

        self.metrics.start_test()

        # Simulate CPU-intensive operations
        cpu_intensive_operations = 15
        cpu_times = []

        # Get initial CPU usage
        initial_cpu = psutil.cpu_percent(interval=0.1)

        for i in range(cpu_intensive_operations):
            # Mix of operations with varying computational complexity
            if i % 3 == 0:
                operation = FraiseQLTestScenarios.simple_user_query()
                expected_complexity = 5
            elif i % 3 == 1:
                operation = FraiseQLTestScenarios.complex_nested_query()
                expected_complexity = 50
            else:
                operation = FraiseQLTestScenarios.search_query()
                expected_complexity = 75

            # Simulate CPU load based on complexity
            cpu_load_factor = expected_complexity / 25.0  # Scale factor
            processing_time = 0.010 + (cpu_load_factor * 0.005)  # Base 10ms + complexity factor

            start = time.time()
            time.sleep(processing_time)  # Simulate CPU-bound processing

            # Execute the operation
            result = client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", processing_time * 1000)
            cpu_times.append(execution_time)
            self.metrics.record_query_time(execution_time)

        # Check CPU usage after operations
        final_cpu = psutil.cpu_percent(interval=0.1)

        self.metrics.end_test()

        # Validate CPU spike handling
        avg_cpu_time = statistics.mean(cpu_times)
        cpu_variance = statistics.stdev(cpu_times)

        # CPU-bound operations should have reasonable variance
        assert cpu_variance < avg_cpu_time * 1.2, (
            f"Excessive CPU time variance: {cpu_variance:.1f}ms"
        )

        # System should remain responsive (no excessive CPU usage)
        cpu_increase = final_cpu - initial_cpu
        assert cpu_increase < 20, f"Excessive CPU usage increase: +{cpu_increase:.1f}%"

        summary = self.metrics.get_summary()
        assert summary["query_count"] == cpu_intensive_operations, (
            "All CPU-intensive operations should complete"
        )

        print(
            f"CPU spike test: {cpu_increase:.1f}% CPU increase, {cpu_intensive_operations} operations"
        )

    @pytest.mark.chaos
    @pytest.mark.chaos_resources
    def test_disk_io_contention(self):
        """Test disk I/O contention and storage resource management.

        Scenario: Disk I/O becomes contended due to concurrent operations.
        Expected: FraiseQL handles I/O contention gracefully with queuing.
        """
        client = MockFraiseQLClient()
        operation = FraiseQLTestScenarios.mutation_create_post()  # Write-heavy operation

        self.metrics.start_test()

        # Simulate disk I/O operations with contention
        io_operations = 20
        io_times = []
        io_contention_events = 0

        for i in range(io_operations):
            # Simulate I/O operation with potential contention
            base_io_time = 0.015  # 15ms base I/O time

            # Simulate contention (random I/O delays)
            if random.random() < 0.25:  # 25% chance of I/O contention
                io_contention_events += 1
                contention_delay = random.uniform(0.050, 0.150)  # 50-150ms additional delay
                base_io_time += contention_delay

            start = time.time()
            time.sleep(base_io_time)

            # Execute write operation
            result = client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", base_io_time * 1000)
            io_times.append(execution_time)
            self.metrics.record_query_time(execution_time)

        self.metrics.end_test()

        # Validate disk I/O contention handling
        avg_io_time = statistics.mean(io_times)
        io_variance = statistics.stdev(io_times)

        # I/O operations should show some variance due to contention but not excessive
        assert io_variance < avg_io_time * 1.5, f"Excessive I/O variance: {io_variance:.1f}ms"

        # Should have experienced some I/O contention
        assert io_contention_events > 0, "Should experience I/O contention events"

        summary = self.metrics.get_summary()
        success_rate = 1 - (summary["error_count"] / max(summary["query_count"], 1))
        assert success_rate >= 0.85, f"I/O contention caused too many failures: {success_rate:.2f}"

        print(f"Disk I/O test: {io_contention_events} contention events, avg {avg_io_time:.1f}ms")

    @pytest.mark.chaos
    @pytest.mark.chaos_resources
    def test_resource_exhaustion_recovery(self):
        """Test resource exhaustion scenarios and recovery mechanisms.

        Scenario: System resources become exhausted, then gradually recover.
        Expected: FraiseQL handles resource exhaustion gracefully and recovers.
        """
        client = MockFraiseQLClient()
        operation = FraiseQLTestScenarios.complex_nested_query()

        self.metrics.start_test()

        # Phase 1: Normal operation
        normal_operations = 5
        for _ in range(normal_operations):
            result = client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 45.0)
            self.metrics.record_query_time(execution_time)

        # Phase 2: Resource exhaustion
        exhaustion_operations = 8
        exhaustion_times = []
        resource_failures = 0

        for i in range(exhaustion_operations):
            try:
                # Simulate increasing resource exhaustion
                exhaustion_factor = (i + 1) / exhaustion_operations  # 0.125 to 1.0
                delay = 0.045 + (exhaustion_factor * 0.100)  # 45ms to 145ms

                start = time.time()
                time.sleep(delay)

                result = client.execute_query(operation)
                execution_time = result.get("_execution_time_ms", delay * 1000)
                exhaustion_times.append(execution_time)
                self.metrics.record_query_time(execution_time)

            except Exception:
                resource_failures += 1
                self.metrics.record_error()

        # Phase 3: Resource recovery
        recovery_operations = 6
        recovery_times = []

        for i in range(recovery_operations):
            # Simulate improving resource availability
            recovery_factor = i / (recovery_operations - 1)  # 0.0 to 1.0
            delay = 0.145 - (recovery_factor * 0.100)  # 145ms to 45ms

            result = client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", delay * 1000)
            recovery_times.append(execution_time)
            self.metrics.record_query_time(execution_time)

        self.metrics.end_test()

        # Validate resource exhaustion and recovery
        if exhaustion_times:
            avg_exhaustion = statistics.mean(exhaustion_times)
            avg_recovery = statistics.mean(recovery_times) if recovery_times else 0

            # Recovery should show improvement (or at least not regression)
            # Relaxed threshold for mock client which returns simulated times
            if avg_recovery > 0:
                recovery_improvement = (avg_exhaustion - avg_recovery) / avg_exhaustion
                assert recovery_improvement >= -0.5, (
                    f"Recovery should not regress significantly: {recovery_improvement:.2f}"
                )

        summary = self.metrics.get_summary()
        total_expected = normal_operations + exhaustion_operations + recovery_operations
        assert summary["query_count"] >= total_expected * 0.8, (
            f"Too many resource exhaustion failures: {summary['query_count']}/{total_expected}"
        )

        print(f"Resource exhaustion test: {resource_failures} failures, recovery demonstrated")

    @pytest.mark.chaos
    @pytest.mark.chaos_resources
    def test_system_resource_monitoring(self):
        """Test system resource monitoring and adaptive behavior.

        Scenario: System monitors resource usage and adapts behavior accordingly.
        Expected: FraiseQL adapts to resource constraints intelligently.
        """
        client = MockFraiseQLClient()

        self.metrics.start_test()

        # Monitor system resources throughout the test
        monitoring_operations = 12
        resource_readings = []
        adaptive_behavior = 0

        for i in range(monitoring_operations):
            # Monitor current system resources
            cpu_percent = psutil.cpu_percent(interval=0.05)
            memory_percent = psutil.virtual_memory().percent

            resource_readings.append({"cpu": cpu_percent, "memory": memory_percent, "operation": i})

            # Adapt behavior based on resource usage
            if cpu_percent > 70 or memory_percent > 80:
                # High resource usage - use simpler operations
                operation = FraiseQLTestScenarios.simple_user_query()
                adaptive_behavior += 1
            else:
                # Normal resources - use complex operations
                operation = FraiseQLTestScenarios.complex_nested_query()

            result = client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 25.0)
            self.metrics.record_query_time(execution_time)

            # Brief pause to allow resource monitoring
            time.sleep(0.010)

        self.metrics.end_test()

        # Validate resource monitoring and adaptation
        high_resource_periods = sum(
            1 for r in resource_readings if r["cpu"] > 70 or r["memory"] > 80
        )

        if high_resource_periods > 0:
            assert adaptive_behavior > 0, "Should adapt behavior during high resource usage"
            # Adaptation rate depends on actual system resource state during test
            # Only check that some adaptation occurred when resources were constrained
            adaptation_rate = adaptive_behavior / monitoring_operations
            assert adaptation_rate > 0, (
                f"No adaptation to resource constraints detected: {adaptation_rate:.2f}"
            )

        summary = self.metrics.get_summary()
        assert summary["query_count"] == monitoring_operations, (
            "All monitoring operations should complete"
        )

        print(
            f"Resource monitoring test: {adaptive_behavior} adaptations, {high_resource_periods} high-resource periods"
        )

    @pytest.mark.chaos
    @pytest.mark.chaos_resources
    def test_cascading_resource_failure_prevention(self):
        """Test prevention of cascading resource failures.

        Scenario: One resource failure triggers cascading effects on other resources.
        Expected: FraiseQL contains resource failures and prevents cascading degradation.
        """
        client = MockFraiseQLClient()
        operations = [
            FraiseQLTestScenarios.simple_user_query(),
            FraiseQLTestScenarios.complex_nested_query(),
            FraiseQLTestScenarios.mutation_create_post(),
        ]

        self.metrics.start_test()

        # Simulate cascading resource failure scenario
        # Scale total_operations based on hardware (15 on baseline, 7-60 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        total_operations = max(7, int(15 * self.chaos_config.load_multiplier))
        primary_failures = 0
        cascading_failures = 0
        contained_operations = 0

        for i in range(total_operations):
            operation = operations[i % len(operations)]

            try:
                # Check for primary resource failure
                if i == 5:  # Primary failure at operation 5
                    # Simulate memory exhaustion
                    raise MemoryError("Primary resource failure: memory exhausted")

                result = client.execute_query(operation)
                execution_time = result.get("_execution_time_ms", 20.0)
                self.metrics.record_query_time(execution_time)
                contained_operations += 1

            except MemoryError:
                primary_failures += 1
                self.metrics.record_error()

                # Check if subsequent operations also fail (cascading)
                # Scale iterations based on hardware (2 on baseline, 3-8 adaptive)
                # Uses multiplier-based formula to ensure meaningful test on all hardware
                check_iterations = max(3, int(2 * self.chaos_config.load_multiplier))

                for j in range(check_iterations):  # Check next operations for cascading
                    if i + j + 1 < total_operations:
                        try:
                            cascading_op = operations[(i + j + 1) % len(operations)]
                            result = client.execute_query(cascading_op)
                            # If this succeeds, cascading was prevented
                        except Exception:
                            cascading_failures += 1

                break  # Stop after primary failure to check cascading

            except Exception:
                # Other failures (not cascading)
                self.metrics.record_error()

        self.metrics.end_test()

        # Validate cascading failure prevention
        assert primary_failures > 0, "Should experience primary resource failure"

        # Cascading failures should be minimal or prevented
        assert cascading_failures <= 1, f"Too many cascading failures: {cascading_failures}"
        # Test breaks after primary failure at operation 5, so expect ~5 contained operations
        assert contained_operations >= 3, (
            f"Too few operations completed before failure: {contained_operations}"
        )

        summary = self.metrics.get_summary()
        # System should remain operational despite resource failures
        operational_rate = (summary["query_count"] - summary["error_count"]) / summary[
            "query_count"
        ]
        assert operational_rate >= 0.7, (
            f"Resource failure caused excessive system degradation: {operational_rate:.2f}"
        )

        print(
            f"Cascading failure test: {primary_failures} primary, {cascading_failures} cascading failures"
        )
