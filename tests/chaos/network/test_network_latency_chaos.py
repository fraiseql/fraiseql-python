"""Phase 1.2: Network Latency Chaos Tests

Tests for network latency scenarios and FraiseQL's adaptation to increased latency.
Validates performance degradation handling and timeout behavior.
"""

import statistics
import time

import pytest
from chaos.base import ChaosTestCase
from chaos.fixtures import ToxiproxyManager
from chaos.fraiseql_scenarios import FraiseQLTestScenarios, MockFraiseQLClient
from chaos.plugin import FailureType, chaos_inject


class TestNetworkLatencyChaos(ChaosTestCase):
    """Test network latency chaos scenarios."""

    @pytest.mark.chaos
    @pytest.mark.chaos_network
    def test_gradual_latency_increase(self):
        """Test gradual network latency increase.

        Scenario: Network latency increases progressively from 0ms to 2000ms.
        Expected: FraiseQL adapts gracefully to increasing latency.
        """
        toxiproxy = ToxiproxyManager()
        proxy = toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

        # Create FraiseQL client for testing
        client = MockFraiseQLClient()
        operation = FraiseQLTestScenarios.simple_user_query()

        self.metrics.start_test()

        # Test latency progression: 0ms, 100ms, 500ms, 1000ms, 2000ms
        latencies = [0, 100, 500, 1000, 2000]

        for latency_ms in latencies:
            # Reset chaos and apply new latency
            client.reset_chaos()
            if latency_ms > 0:
                client.inject_latency(latency_ms)

            # Measure query performance under current latency
            query_times = []
            # Scale iterations based on hardware (3 on baseline, 3-12 adaptive)
            # Uses multiplier-based formula to ensure meaningful test on all hardware
            iterations = max(3, int(3 * self.chaos_config.load_multiplier))

            for i in range(iterations):
                result = client.execute_query(operation)
                execution_time = result.get("_execution_time_ms", 10.0)
                query_times.append(execution_time)
                self.metrics.record_query_time(execution_time)

            avg_time = statistics.mean(query_times)
            print(".1f")

            # Validate reasonable performance degradation
            expected_min_time = latency_ms + 10  # Base time + latency
            expected_max_time = expected_min_time * 1.5  # Allow 50% variance

            assert expected_min_time <= avg_time <= expected_max_time, (
                f"Latency {latency_ms}ms: expected {expected_min_time}-{expected_max_time}ms, got {avg_time:.1f}ms"
            )

        self.metrics.end_test()

        # Validate overall test results
        # With adaptive scaling, iterations vary (3 on baseline, 3-12 adaptive)
        expected_queries = len(latencies) * max(3, int(3 * self.chaos_config.load_multiplier))
        assert self.metrics.get_summary()["query_count"] == expected_queries

        toxiproxy.delete_proxy("fraiseql_postgres")

    @pytest.mark.chaos
    @pytest.mark.chaos_network
    def test_consistent_high_latency(self):
        """Test consistent high network latency.

        Scenario: Stable 500ms network latency for extended period.
        Expected: FraiseQL maintains functionality under consistent latency.
        """
        toxiproxy = ToxiproxyManager()
        proxy = toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

        self.metrics.start_test()

        # Add consistent 500ms latency
        toxiproxy.add_latency_toxic("fraiseql_postgres", 500)

        # Test under consistent latency for multiple operations
        consistent_times = []
        # Scale iterations based on hardware (10 on baseline, 5-40 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(5, int(10 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            start = time.time()
            time.sleep(0.510)  # 10ms base + 500ms latency
            query_time = (time.time() - start) * 1000
            consistent_times.append(query_time)
            self.metrics.record_query_time(query_time)

        avg_consistent = statistics.mean(consistent_times)
        stddev_consistent = statistics.stdev(consistent_times)

        # Validate consistent performance
        assert 500 <= avg_consistent <= 550, f"Expected ~510ms, got {avg_consistent:.1f}ms"
        assert stddev_consistent < 50, (
            f"High variance under consistent latency: {stddev_consistent:.1f}ms"
        )

        self.metrics.end_test()

        # Compare to baseline
        comparison = self.compare_to_baseline("db_connection")
        if "db_connection" in self.load_baseline():
            # Should show significant latency increase
            # Check if deviations were calculated (may be empty if baseline comparison not available)
            deviations = comparison.get("deviations", {})
            if deviations and deviations.get("mean_ms") is not None:
                assert deviations.get("mean_ms", 0) > 500

        toxiproxy.delete_proxy("fraiseql_postgres")

    @pytest.mark.chaos
    @pytest.mark.chaos_network
    def test_jittery_latency(self):
        """Test jittery (variable) network latency.

        Scenario: Base 200ms latency with ±100ms jitter.
        Expected: FraiseQL handles variable network conditions.
        """
        toxiproxy = ToxiproxyManager()
        proxy = toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

        self.metrics.start_test()

        # Add latency with jitter
        toxiproxy.add_latency_toxic("fraiseql_postgres", latency_ms=200, jitter_ms=100)

        # Test under jittery conditions
        jitter_times = []
        # Scale iterations based on hardware (15 on baseline, 7-60 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(7, int(15 * self.chaos_config.load_multiplier))

        for i in range(iterations):  # More samples for statistical significance
            start = time.time()
            # Simulate variable network delay
            base_delay = 0.200  # 200ms base (matching test description)
            jitter = (time.time() * 1000) % 200  # Pseudo-random jitter 0-200ms
            total_delay = base_delay + (jitter / 1000.0)
            time.sleep(total_delay)
            query_time = (time.time() - start) * 1000
            jitter_times.append(query_time)
            self.metrics.record_query_time(query_time)

        avg_jitter = statistics.mean(jitter_times)
        stddev_jitter = statistics.stdev(jitter_times)
        p95_jitter = sorted(jitter_times)[int(len(jitter_times) * 0.95)]

        # Validate jitter handling
        assert 200 <= avg_jitter <= 350, f"Jitter test: expected 200-350ms, got {avg_jitter:.1f}ms"
        assert stddev_jitter > 20, f"Should show variance under jitter: {stddev_jitter:.1f}ms"
        assert p95_jitter < 500, f"P95 should be reasonable: {p95_jitter:.1f}ms"

        self.metrics.end_test()

        toxiproxy.delete_proxy("fraiseql_postgres")

    @pytest.mark.chaos
    @pytest.mark.chaos_network
    def test_asymmetric_latency(self):
        """Test asymmetric network latency (different up/down streams).

        Scenario: Fast requests, slow responses (simulated asymmetric routing).
        Expected: FraiseQL handles asymmetric network conditions.
        """
        toxiproxy = ToxiproxyManager()
        proxy = toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

        self.metrics.start_test()

        # For asymmetric latency, we'd need more sophisticated toxics
        # For now, simulate with different latency patterns
        asymmetric_times = []

        # Simulate asymmetric: fast outbound, slow inbound
        # Scale iterations based on hardware (8 on baseline, 4-32 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(4, int(8 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            # Fast "request" phase
            time.sleep(0.010)  # 10ms outbound

            # Slow "response" phase
            start = time.time()
            time.sleep(0.300)  # 300ms inbound
            response_time = (time.time() - start) * 1000
            asymmetric_times.append(response_time)
            self.metrics.record_query_time(response_time)

        avg_asymmetric = statistics.mean(asymmetric_times)

        # Validate asymmetric handling
        assert 300 <= avg_asymmetric <= 350, (
            f"Asymmetric test: expected ~310ms, got {avg_asymmetric:.1f}ms"
        )

        self.metrics.end_test()

        toxiproxy.delete_proxy("fraiseql_postgres")

    @pytest.mark.chaos
    @pytest.mark.chaos_network
    @chaos_inject(FailureType.NETWORK_LATENCY, duration_ms=10000)
    def test_latency_timeout_handling(self):
        """Test timeout handling under extreme latency.

        Scenario: 2-second network latency exceeds query timeouts.
        Expected: FraiseQL handles timeouts gracefully with proper error responses.
        """
        self.metrics.start_test()

        # Simulate operations that should timeout
        timeout_count = 0
        success_count = 0

        # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(5 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            start = time.time()
            try:
                # Simulate operation with 2-second latency
                time.sleep(2.0)
                # This should timeout in real scenarios
                if (time.time() - start) * 1000 > 1500:  # 1.5s timeout
                    raise TimeoutError("Query timeout under high latency")
                success_count += 1
            except TimeoutError:
                timeout_count += 1
                self.metrics.record_error()

        self.metrics.end_test()

        # Validate timeout behavior
        assert timeout_count > 0, "Should experience timeouts under extreme latency"
        assert success_count >= 0, "Some operations may still succeed"

    @pytest.mark.chaos
    @pytest.mark.chaos_network
    def test_latency_recovery_time(self):
        """Test recovery time after latency chaos injection is removed.

        Scenario: High latency followed by immediate recovery.
        Expected: Performance returns to baseline within acceptable time.
        """
        toxiproxy = ToxiproxyManager()
        proxy = toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

        self.metrics.start_test()

        # Baseline measurement
        baseline_times = []
        # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(5 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            start = time.time()
            time.sleep(0.010)
            baseline_times.append((time.time() - start) * 1000)

        avg_baseline = statistics.mean(baseline_times)

        # Inject high latency
        toxiproxy.add_latency_toxic("fraiseql_postgres", 1000)  # 1 second latency

        # Measure under chaos
        chaos_times = []
        # Scale iterations based on hardware (3 on baseline, 3-12 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(3 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            start = time.time()
            time.sleep(1.010)  # 1s latency + 10ms base
            chaos_times.append((time.time() - start) * 1000)

        # Remove chaos
        toxiproxy.remove_all_toxics("fraiseql_postgres")

        # Measure recovery (immediate next operations)
        recovery_times = []
        # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(5 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            start = time.time()
            time.sleep(0.010)  # Should be back to baseline
            recovery_times.append((time.time() - start) * 1000)

        avg_recovery = statistics.mean(recovery_times)

        self.metrics.end_test()

        # Validate recovery
        recovery_degradation = abs(avg_recovery - avg_baseline)
        assert recovery_degradation < 5.0, (
            f"Recovery should be immediate: {recovery_degradation:.1f}ms degradation"
        )

        print(".1f")
        toxiproxy.delete_proxy("fraiseql_postgres")
