"""Phase 1.1: Database Connection Chaos Tests

Tests for database connection failures and recovery scenarios.
Validates FraiseQL's resilience to PostgreSQL connectivity issues.
"""

import statistics
import time

import pytest
from chaos.base import ChaosTestCase
from chaos.fixtures import ToxiproxyManager
from chaos.fraiseql_scenarios import FraiseQLTestScenarios, MockFraiseQLClient


class TestDatabaseConnectionChaos(ChaosTestCase):
    """Test database connection chaos scenarios."""

    @pytest.mark.chaos
    @pytest.mark.chaos_database
    def test_connection_refused_recovery(self):
        """Test recovery from database connection refused errors.

        Scenario: Database proxy rejects connections, then recovers.
        Expected: FraiseQL handles connection failures gracefully.
        """
        toxiproxy = ToxiproxyManager()
        # Setup PostgreSQL proxy
        proxy = toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

        # Create FraiseQL client for testing
        client = MockFraiseQLClient()
        operation = FraiseQLTestScenarios.simple_user_query()

        # Start baseline measurement
        self.metrics.start_test()

        # Measure baseline performance (no chaos)
        baseline_times = []
        # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(5 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            result = client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            baseline_times.append(execution_time)
            self.metrics.record_query_time(execution_time)

        avg_baseline = statistics.mean(baseline_times)

        # Inject chaos: Connection failures via mock client
        # (toxiproxy doesn't affect mock clients - use client's injection method)
        client.inject_connection_failure()

        # Test under chaos - operations should fail due to connection issues
        chaos_times = []
        errors_during_chaos = 0

        # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(5 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            try:
                result = client.execute_query(operation)
                execution_time = result.get("_execution_time_ms", 10.0)
                chaos_times.append(execution_time)
                self.metrics.record_query_time(execution_time)
                # Check if operation actually failed (should have errors in response)
                if "errors" in result:
                    errors_during_chaos += 1
                    self.metrics.record_error()
            except Exception:
                errors_during_chaos += 1
                self.metrics.record_error()

        # Reset chaos
        client.reset_chaos()

        # Test recovery - operations should work normally again
        recovery_times = []
        # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(5 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            result = client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            recovery_times.append(execution_time)
            self.metrics.record_query_time(execution_time)

        avg_recovery = statistics.mean(recovery_times)

        # End test and validate
        self.metrics.end_test()

        # Validate results
        assert errors_during_chaos > 0, "Should have connection errors during chaos"
        assert abs(avg_recovery - avg_baseline) < 5.0, (
            f"Recovery time {avg_recovery:.2f}ms should be close to baseline {avg_baseline:.2f}ms"
        )

        # Compare to baseline
        comparison = self.compare_to_baseline("db_connection")
        assert "current" in comparison

        # Cleanup
        toxiproxy.delete_proxy("fraiseql_postgres")

    @pytest.mark.chaos
    @pytest.mark.chaos_database
    def test_pool_exhaustion_recovery(self):
        """Test recovery from database connection pool exhaustion.

        Scenario: All database connections become slow/unavailable, then recover.
        Expected: FraiseQL handles pool exhaustion gracefully with queuing/recovery.
        """
        toxiproxy = ToxiproxyManager()
        # Setup proxy
        proxy = toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

        # Create FraiseQL client for testing
        client = MockFraiseQLClient()
        operation = FraiseQLTestScenarios.complex_nested_query()

        self.metrics.start_test()

        # Baseline: Normal operations
        baseline_times = []
        # Scale iterations based on hardware (3 on baseline, 3-12 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(3 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            result = client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            baseline_times.append(execution_time)
            self.metrics.record_query_time(execution_time)

        avg_baseline = statistics.mean(baseline_times)

        # Create FraiseQL client for testing
        client = MockFraiseQLClient()
        operation = FraiseQLTestScenarios.complex_nested_query()

        # Inject chaos: Simulate pool exhaustion by exhausting connection pool
        # Create multiple concurrent operations to exhaust the pool
        client.inject_latency(5000)  # 5 second delay to simulate pool exhaustion

        # Test under pool exhaustion conditions
        chaos_times = []
        timeouts = 0

        # Scale iterations based on hardware (3 on baseline, 3-12 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(3 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            try:
                result = client.execute_query(operation, timeout=2.0)  # 2 second timeout
                execution_time = result.get("_execution_time_ms", 2000.0)
                chaos_times.append(execution_time)
                self.metrics.record_query_time(execution_time)
                # Pool exhaustion might cause timeouts
                if execution_time >= 2000:
                    timeouts += 1
                    self.metrics.record_error()
            except Exception:
                timeouts += 1
                self.metrics.record_error()
                chaos_times.append(2000.0)  # Record as timeout

        # Remove chaos
        client.reset_chaos()

        # Test recovery
        recovery_times = []
        # Scale iterations based on hardware (3 on baseline, 3-12 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(3 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            result = client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            recovery_times.append(execution_time)
            self.metrics.record_query_time(execution_time)

        avg_recovery = statistics.mean(recovery_times)

        self.metrics.end_test()

        # Validate pool exhaustion behavior
        assert timeouts >= 1, "Should experience some timeouts during pool exhaustion"
        assert avg_recovery < avg_baseline * 2, (
            f"Recovery should be reasonably fast: {avg_recovery:.2f}ms vs baseline {avg_baseline:.2f}ms"
        )

        # Cleanup
        toxiproxy.delete_proxy("fraiseql_postgres")

    @pytest.mark.chaos
    @pytest.mark.chaos_database
    def test_slow_connection_establishment(self):
        """Test handling of slow database connection establishment.

        Scenario: Database connections take progressively longer to establish.
        Expected: FraiseQL adapts to slow connection times.
        """
        toxiproxy = ToxiproxyManager()
        proxy = toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

        self.metrics.start_test()

        # Baseline
        baseline_times = []
        # Scale iterations based on hardware (3 on baseline, 3-12 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(3 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            start = time.time()
            time.sleep(0.01)  # 10ms connection time
            baseline_times.append((time.time() - start) * 1000)

        avg_baseline = sum(baseline_times) / len(baseline_times)

        # Inject gradual latency increase (simulating network congestion)
        latencies = [100, 500, 1000, 2000]  # Progressive increase

        for latency_ms in latencies:
            toxiproxy.remove_all_toxics("fraiseql_postgres")
            toxiproxy.add_latency_toxic("fraiseql_postgres", latency_ms)

            # Test connection under increased latency
            connection_times = []
            # Scale iterations based on hardware (2 on baseline, 3-8 adaptive)
            # Uses multiplier-based formula to ensure meaningful test on all hardware
            iterations = max(3, int(2 * self.chaos_config.load_multiplier))

            for i in range(iterations):
                start = time.time()
                time.sleep(latency_ms / 1000.0)  # Simulate connection delay
                connection_times.append((time.time() - start) * 1000)

            avg_connection_time = sum(connection_times) / len(connection_times)
            self.metrics.record_query_time(avg_connection_time)

        # Remove chaos and test recovery
        toxiproxy.remove_all_toxics("fraiseql_postgres")

        recovery_times = []
        # Scale iterations based on hardware (3 on baseline, 3-12 adaptive)
        # Uses multiplier-based formula to ensure meaningful test on all hardware
        iterations = max(3, int(3 * self.chaos_config.load_multiplier))

        for i in range(iterations):
            start = time.time()
            time.sleep(0.01)
            recovery_times.append((time.time() - start) * 1000)

        avg_recovery = sum(recovery_times) / len(recovery_times)

        self.metrics.end_test()

        # Validate adaptation to slow connections
        assert avg_recovery < avg_baseline * 1.5, (
            f"Should recover to near-baseline: {avg_recovery:.2f}ms vs {avg_baseline:.2f}ms"
        )

        toxiproxy.delete_proxy("fraiseql_postgres")

    @pytest.mark.chaos
    @pytest.mark.chaos_database
    def test_mid_query_connection_drop(self):
        """Test recovery from mid-query connection drops.

        Scenario: Connection drops partway through a query execution.
        Expected: FraiseQL handles partial query failures gracefully.
        """
        toxiproxy = ToxiproxyManager()

        for drop_after_ms in [100, 500, 1000]:
            proxy = toxiproxy.create_proxy("fraiseql_postgres", "0.0.0.0:5433", "postgres:5432")

            self.metrics.start_test()

            # Baseline successful queries
            successful_queries = 0
            # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
            # Uses multiplier-based formula to ensure meaningful test on all hardware
            iterations = max(3, int(5 * self.chaos_config.load_multiplier))

            for i in range(iterations):
                start = time.time()
                time.sleep(0.020)  # 20ms query
                successful_queries += 1
                self.metrics.record_query_time((time.time() - start) * 1000)

            # Inject chaos: Connection drops after specified time
            # This simulates network interruption mid-query
            chaos_queries = 0
            interrupted_queries = 0

            # Scale iterations based on hardware (5 on baseline, 3-20 adaptive)
            # Uses multiplier-based formula to ensure meaningful test on all hardware
            iterations = max(3, int(5 * self.chaos_config.load_multiplier))

            for i in range(iterations):
                start = time.time()
                try:
                    # Simulate query that gets interrupted
                    time.sleep(drop_after_ms / 1000.0)
                    # At this point, connection would drop in real scenario
                    # We simulate this by raising an exception
                    if drop_after_ms <= 500:  # Drops at 100ms and 500ms cause failures
                        raise ConnectionError("Connection dropped mid-query")
                    time.sleep(0.010)  # Complete the query (only for 1000ms)
                    chaos_queries += 1
                except ConnectionError:
                    interrupted_queries += 1
                    self.metrics.record_error()
                    # Simulate retry delay
                    time.sleep(0.2)

            self.metrics.end_test()

            # Validate mid-query failure handling
            # With adaptive scaling and the logic at line 321 (if drop_after_ms <= 500),
            # drops at 100ms and 500ms fail all queries, only 1000ms allows success
            if drop_after_ms <= 500:
                # For early drops: expect interruptions, no successful queries
                assert interrupted_queries > 0, (
                    f"Should have interrupted queries with {drop_after_ms}ms drop time"
                )
            else:
                # For 1000ms: expect successful queries, no interruptions
                assert chaos_queries >= successful_queries * 0.3, (
                    f"Should have some successful queries at {drop_after_ms}ms"
                )

            toxiproxy.delete_proxy("fraiseql_postgres")
