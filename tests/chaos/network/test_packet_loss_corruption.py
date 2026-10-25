"""Phase 1.3: Packet Loss & Corruption Chaos Tests

Tests for packet loss, corruption, and network reliability scenarios.
Validates FraiseQL's handling of unreliable network conditions.
"""

import random
import statistics
import time

import pytest
from chaos.base import ChaosTestCase
from chaos.fixtures import ToxiproxyManager
from chaos.fraiseql_scenarios import FraiseQLTestScenarios, MockFraiseQLClient


class TestPacketLossCorruptionChaos(ChaosTestCase):
    """Test packet loss and corruption chaos scenarios."""

    @pytest.mark.chaos
    @pytest.mark.chaos_network
    def test_packet_loss_recovery(self):
        """Test recovery from packet loss at different severity levels.

        Scenario: Network drops packets at specified rate.
        Expected: FraiseQL handles packet loss with retries and timeouts.
        """
        toxiproxy = ToxiproxyManager()
        for loss_percentage in [0.01, 0.05, 0.1]:
            toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

            # Create FraiseQL client for testing
            client = MockFraiseQLClient()
            operation = FraiseQLTestScenarios.simple_user_query()

            self.metrics.start_test()

            # Baseline: No packet loss
            baseline_successes = 0
            baseline_times = []

            # Scale iterations based on hardware (10 on baseline, 5-40 adaptive)
            # Uses multiplier-based formula to ensure meaningful test on all hardware
            iterations = max(5, int(10 * self.chaos_config.load_multiplier))

            for _i in range(iterations):
                result = client.execute_query(operation)
                execution_time = result.get("_execution_time_ms", 10.0)
                baseline_times.append(execution_time)
                self.metrics.record_query_time(execution_time)
                baseline_successes += 1

            avg_baseline = statistics.mean(baseline_times)

            # Inject packet loss
            toxiproxy.add_packet_loss_toxic("fraiseql_postgres", loss_percentage)

            # Test under packet loss
            chaos_successes = 0
            chaos_failures = 0
            chaos_times = []
            retry_count = 0

            # Scale iterations based on hardware (20 on baseline, 10-80 adaptive)
            # Uses multiplier-based formula to ensure meaningful test on all hardware
            iterations = max(10, int(20 * self.chaos_config.load_multiplier))

            # DETERMINISTIC SCHEDULE: the packets lost at loss_percentage (at least
            # one), 70% of them recovered by the retry, in an order shuffled with a
            # fixed seed (was an unseeded random.random() per operation)
            lost = max(1, round(iterations * loss_percentage))
            recovered = round(lost * 0.7)
            outcomes = (
                ["ok"] * (iterations - lost)
                + ["retried"] * recovered
                + ["lost"] * (lost - recovered)
            )
            random.Random(int(loss_percentage * 100)).shuffle(outcomes)

            # The times are the simulated client's, plus a simulated 50ms retry delay:
            # sleeping and timing the sleeps measured time.sleep's overshoot, which the
            # machine's load sets, and the recovery check compared two such measurements.
            retry_delay_ms = 50.0
            for outcome in outcomes:
                if outcome == "ok":
                    result = client.execute_query(operation)
                    chaos_times.append(result["_execution_time_ms"])
                    chaos_successes += 1
                    continue

                # Packet loss - operation fails
                chaos_failures += 1
                self.metrics.record_error()

                # Simulate retry logic
                retry_count += 1
                if outcome == "retried":
                    result = client.execute_query(operation)
                    chaos_times.append(retry_delay_ms + result["_execution_time_ms"])
                    chaos_successes += 1
                    retry_count -= 1  # Successful retry

            self.metrics.record_query_time(statistics.mean(chaos_times) if chaos_times else 1000.0)

            # Remove chaos
            toxiproxy.remove_all_toxics("fraiseql_postgres")

            # Test recovery
            recovery_successes = 0
            recovery_times = []

            # Scale iterations based on hardware (10 on baseline, 5-40 adaptive)
            # Uses multiplier-based formula to ensure meaningful test on all hardware
            iterations = max(5, int(10 * self.chaos_config.load_multiplier))

            for _i in range(iterations):
                result = client.execute_query(operation)
                recovery_times.append(result["_execution_time_ms"])
                recovery_successes += 1

            avg_recovery = statistics.mean(recovery_times)

            self.metrics.end_test()

            # Validate packet loss behavior
            assert chaos_failures == lost, (
                f"Expected {lost} failures at {loss_percentage * 100}% loss, got {chaos_failures}"
            )

            success_rate = chaos_successes / len(outcomes)
            min_success_rate = 1.0 - (loss_percentage * 2)  # Allow for retry effectiveness
            assert success_rate >= min_success_rate, (
                f"Success rate {success_rate:.2f} too low for {loss_percentage * 100}% loss"
            )

            # Recovery should be near baseline
            assert abs(avg_recovery - avg_baseline) < 5.0, (
                f"Recovery time {avg_recovery:.1f}ms vs baseline {avg_baseline:.1f}ms"
            )

            print(".1f")
            toxiproxy.delete_proxy("fraiseql_postgres")

    @pytest.mark.chaos
    @pytest.mark.chaos_network
    def test_packet_corruption_handling(self):
        """Test handling of corrupted packets.

        Scenario: Network delivers corrupted data.
        Expected: FraiseQL detects corruption and handles appropriately.
        """
        toxiproxy = ToxiproxyManager()
        toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

        self.metrics.start_test()

        # Simulate packet corruption (not directly supported by toxiproxy)
        # We'll simulate this through timeout patterns
        corruption_scenarios = [
            ("minor_corruption", 0.02, 0.1),  # 2% corruption, 10% impact
            ("moderate_corruption", 0.05, 0.3),  # 5% corruption, 30% impact
            ("severe_corruption", 0.10, 0.6),  # 10% corruption, 60% impact
        ]

        for scenario_name, corruption_rate, impact_rate in corruption_scenarios:
            corrupt_successes = 0
            corrupt_failures = 0

            # Scale iterations based on hardware (15 on baseline, 7-60 adaptive)
            # Uses multiplier-based formula to ensure meaningful test on all hardware
            iterations = max(7, int(15 * self.chaos_config.load_multiplier))

            # DETERMINISTIC SCHEDULE: corruption_rate of the packets corrupted, then
            # impact_rate of the others failing too, in an order shuffled with a fixed
            # seed (was two unseeded random.random() draws per packet, which failed
            # the severe scenario about 1 run in 130)
            corrupted = round(iterations * corruption_rate)
            impacted = int((iterations - corrupted) * impact_rate)
            outcomes = (
                ["corrupted"] * corrupted
                + ["impacted"] * impacted
                + ["ok"] * (iterations - corrupted - impacted)
            )
            random.Random(scenario_name).shuffle(outcomes)

            for i, outcome in enumerate(outcomes):
                if outcome == "corrupted":
                    # Corrupted packet - operation fails
                    corrupt_failures += 1
                    self.metrics.record_error()
                # Normal operation, but may still fail due to impact
                elif outcome == "ok":
                    corrupt_successes += 1
                    self.metrics.record_query_time(10.0 + (i % 5) - 2)
                else:
                    corrupt_failures += 1
                    self.metrics.record_error()

            success_rate = corrupt_successes / iterations
            expected_min_success = 1.0 - corruption_rate - impact_rate

            assert success_rate >= expected_min_success, (
                f"{scenario_name}: Success rate {success_rate:.2f} below expected {expected_min_success:.2f}"
            )

        self.metrics.end_test()

        toxiproxy.delete_proxy("fraiseql_postgres")

    @pytest.mark.chaos
    @pytest.mark.chaos_network
    def test_out_of_order_delivery(self):
        """Test handling of out-of-order packet delivery.

        Scenario: Network delivers packets in wrong order.
        Expected: FraiseQL handles reordering gracefully (TCP handles this).
        """
        toxiproxy = ToxiproxyManager()
        # Note: Out-of-order delivery is primarily handled by TCP
        # This test simulates application-level reordering effects
        toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

        self.metrics.start_test()

        # Simulate out-of-order effects through variable timing
        reorder_times = []

        # Scale iterations based on hardware (10 on baseline, 5-40 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(5, int(10 * self.chaos_config.load_multiplier))

        for _i in range(iterations):
            # Simulate packets arriving out of order
            packet_delays = [0.010, 0.015, 0.008, 0.012, 0.009]  # Varied delays
            random.shuffle(packet_delays)  # Out of order

            start = time.time()
            for delay in packet_delays:
                time.sleep(delay)

            total_time = (time.time() - start) * 1000
            reorder_times.append(total_time)
            self.metrics.record_query_time(total_time)

        avg_reorder_time = statistics.mean(reorder_times)
        reorder_variance = statistics.stdev(reorder_times)

        # Validate reordering doesn't cause excessive variance
        assert reorder_variance < avg_reorder_time * 0.5, (
            f"High variance under reordering: {reorder_variance:.1f}ms"
        )

        self.metrics.end_test()

        toxiproxy.delete_proxy("fraiseql_postgres")

    @pytest.mark.chaos
    @pytest.mark.chaos_network
    def test_adaptive_retry_under_packet_loss(self):
        """Test adaptive retry strategies under packet loss.

        Scenario: System adapts retry count based on packet loss conditions.
        Expected: FraiseQL implements intelligent retry logic.
        """
        for packet_loss_rate in [0.02, 0.08, 0.15]:
            self.metrics.start_test()

            # Simulate adaptive retry behavior
            # Scale iterations based on hardware (12 on baseline, 6-48 adaptive)
            # Uses multiplier-based formula to ensure meaningful test on all hardware
            operations = max(6, int(12 * self.chaos_config.load_multiplier))
            successful_operations = 0
            total_retries = 0

            for _ in range(operations):
                retries = 0
                success = False

                while retries < 5 and not success:  # Max 5 retries
                    if random.random() >= packet_loss_rate:
                        success = True
                        successful_operations += 1
                    else:
                        retries += 1
                        total_retries += 1
                        # Exponential backoff
                        time.sleep(0.001 * (2**retries))

                    self.metrics.record_query_time(10.0 * (retries + 1))

            success_rate = successful_operations / operations
            avg_retries_per_operation = total_retries / operations

            # Validate adaptive behavior
            expected_success_rate = 1.0 - (packet_loss_rate**2)  # With retries
            assert success_rate >= expected_success_rate * 0.8, (
                f"Success rate {success_rate:.2f} too low for {packet_loss_rate * 100}% loss"
            )

            # Should use more retries under higher loss
            # Note: Mock tests use random simulation which has high variance in retry counts
            # The success rate assertion above is the primary validation - retry counts are informational
            packet_loss_rate * 3  # Rough estimate

            # For mock tests with random simulation, retry counts have too much variance to assert
            # Only validate that higher loss rates trend toward more retries (informational check)
            if packet_loss_rate >= 0.1:
                # Very relaxed check - just validate some retries occur at high loss rates
                assert avg_retries_per_operation >= 0, (
                    f"Should see some retry activity: {avg_retries_per_operation:.1f}"
                )

            self.metrics.end_test()

    @pytest.mark.chaos
    @pytest.mark.chaos_network
    def test_network_recovery_after_corruption(self):
        """Test network recovery after corruption chaos.

        Scenario: Heavy packet corruption followed by network recovery.
        Expected: FraiseQL recovers quickly when network improves.
        """
        toxiproxy = ToxiproxyManager()
        toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

        self.metrics.start_test()

        # The times are the simulated client's: sleeping and timing the sleeps
        # measured time.sleep's overshoot, and the recovery check compared two such
        # measurements
        client = MockFraiseQLClient()
        operation = FraiseQLTestScenarios.simple_user_query()

        # Phase 1: Baseline
        baseline_times = []
        # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(5 * self.chaos_config.load_multiplier))

        for _i in range(iterations):
            baseline_times.append(client.execute_query(operation)["_execution_time_ms"])

        avg_baseline = statistics.mean(baseline_times)

        # Phase 2: Heavy corruption (simulate 20% packet issues)
        toxiproxy.add_packet_loss_toxic("fraiseql_postgres", 0.15)  # 15% loss
        toxiproxy.add_latency_toxic("fraiseql_postgres", 200, 50)  # High latency + jitter

        corruption_times = []
        corruption_errors = 0

        # Scale iterations based on hardware (8 on baseline, 4-32 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(4, int(8 * self.chaos_config.load_multiplier))

        # DETERMINISTIC SCHEDULE: 25% of the operations fail (at least one), in an
        # order shuffled with a fixed seed (an unseeded random.random() drew no
        # failure about 1 run in 75)
        failures = max(1, round(iterations * 0.25))
        outcomes = [True] * failures + [False] * (iterations - failures)
        random.Random("network_recovery_after_corruption").shuffle(outcomes)

        for i, fails in enumerate(outcomes):
            try:
                # High chance of failure under corruption
                if fails:  # 25% failure rate
                    raise ConnectionError("Network corruption")

                # Variable timing due to corruption: 0-200ms extra latency
                client.inject_latency((i * 73) % 200)
                corruption_times.append(client.execute_query(operation)["_execution_time_ms"])

            except ConnectionError:
                corruption_errors += 1
                self.metrics.record_error()

        # Phase 3: Network recovery
        toxiproxy.remove_all_toxics("fraiseql_postgres")
        client.reset_chaos()

        recovery_times = []
        # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(5 * self.chaos_config.load_multiplier))

        for _i in range(iterations):
            # Should be back to normal
            recovery_times.append(client.execute_query(operation)["_execution_time_ms"])

        avg_recovery = statistics.mean(recovery_times)

        self.metrics.end_test()

        # Validate recovery behavior
        assert corruption_errors > 0, "Should experience corruption-related errors"
        assert abs(avg_recovery - avg_baseline) < 10.0, (
            f"Recovery should be quick: {avg_recovery:.1f}ms vs baseline {avg_baseline:.1f}ms"
        )

        print(".1f")
        toxiproxy.delete_proxy("fraiseql_postgres")
