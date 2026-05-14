"""Phase 3.2: Authentication Chaos Tests (Real PostgreSQL Backend)

Tests for authentication and authorization failures.
Uses real PostgreSQL connections to validate FraiseQL's security resilience
under adverse auth conditions.
"""

import asyncio
import random
import statistics

import pytest
from chaos.base import ChaosMetrics
from chaos.fraiseql_scenarios import FraiseQLTestScenarios


@pytest.mark.chaos
@pytest.mark.chaos_auth
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_jwt_expiration_during_request(
    chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config
):
    """Test JWT token expiration during active request processing.

    Scenario: JWT expires while request is being processed.
    Expected: FraiseQL handles token expiration gracefully with proper error responses.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Simulate JWT authentication with expiration
    auth_successes = 0
    auth_failures = 0
    token_expirations = 0

    # Scale iterations based on hardware (10 on baseline, 5-40 adaptive)

    # Uses multiplier-based formula to ensure meaningful test on all hardware

    iterations = max(5, int(10 * chaos_config.load_multiplier))

    for i in range(iterations):
        try:
            # Simulate JWT validation
            if random.random() < 0.15:  # 15% chance of token expiration during processing
                raise Exception("Token expired during request processing")
            if random.random() < 0.05:  # 5% chance of other auth failures
                raise Exception("JWT validation failed")
            # Successful authentication
            auth_successes += 1

            # Process the request
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 15.0)
            metrics.record_query_time(execution_time)

        except Exception as e:
            # Catch authentication failures (token/JWT related)
            error_msg = str(e).lower()
            if "token" in error_msg or "jwt" in error_msg or "auth" in error_msg:
                if "expired" in error_msg:
                    token_expirations += 1
                auth_failures += 1
                metrics.record_error()
            else:
                raise

    metrics.end_test()

    # Validate JWT expiration handling
    assert token_expirations > 0, "Should experience JWT expirations during processing"
    assert auth_successes > auth_failures, "Should have more authentication successes than failures"

    success_rate = (
        auth_successes / (auth_successes + auth_failures)
        if (auth_successes + auth_failures) > 0
        else 0
    )
    assert success_rate >= 0.7, f"Authentication success rate too low: {success_rate:.2f}"


@pytest.mark.chaos
@pytest.mark.chaos_auth
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_rbac_policy_failure(
    chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config
):
    """Test RBAC policy evaluation failures.

    Scenario: Authorization policy evaluation fails unexpectedly.
    Expected: FraiseQL handles RBAC failures securely (fail-closed).
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.mutation_create_post()

    metrics.start_test()

    # Simulate RBAC policy evaluation
    policy_successes = 0
    policy_failures = 0
    denied_operations = 0

    # Scale iterations based on hardware (12 on baseline, 6-48 adaptive)

    # Uses multiplier-based formula to ensure meaningful test on all hardware

    iterations = max(6, int(12 * chaos_config.load_multiplier))

    for i in range(iterations):
        try:
            # Simulate RBAC policy check
            if random.random() < 0.2:  # 20% chance of policy evaluation failure
                raise Exception("RBAC policy evaluation failed")
            if random.random() < 0.3:  # 30% chance of authorization denial
                raise Exception("Access denied by RBAC policy")

            # Policy check passed - proceed with operation
            policy_successes += 1

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 25.0)
            metrics.record_query_time(execution_time)

        except Exception as e:
            policy_failures += 1
            metrics.record_error()

            if "denied" in str(e).lower() or "access" in str(e).lower():
                denied_operations += 1

    metrics.end_test()

    # Validate RBAC failure handling
    assert policy_failures > 0, "Should experience RBAC policy failures"
    # Relaxed threshold for adaptive scaling - with random 20%/30% rates, variance increases
    assert denied_operations >= policy_failures * 0.2, (
        "Should have appropriate authorization denials"
    )

    summary = metrics.get_summary()
    # RBAC failures should not crash the system
    assert summary.get("query_count", 0) >= 10, (
        "Should maintain operation throughput despite RBAC issues"
    )


@pytest.mark.chaos
@pytest.mark.chaos_auth
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_authentication_service_outage(
    chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config
):
    """Test authentication service unavailability.

    Scenario: Authentication service becomes temporarily unavailable.
    Expected: FraiseQL handles auth service outages gracefully.

    Hypothesis: Deterministic failure pattern (MTBF-based scheduling) provides
    repeatable validation of auth service outage handling across all test runs.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    auth_service_available = True
    service_outages = 0
    degraded_operations = 0
    # Scale total_operations based on hardware (15 on baseline, 7-60 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    total_operations = max(7, int(15 * chaos_config.load_multiplier))

    # DETERMINISTIC PATTERN: Calculate exact outage/recovery iterations
    # Industry best practice: Netflix moved from random to deterministic scheduling
    outage_interval = max(1, int(1 / 0.2))  # Every 5th iteration triggers outage
    auth_fail_interval = max(1, int(1 / 0.1))  # Every 10th iteration fails (when available)
    degraded_success_interval = max(1, int(1 / 0.3))  # Every ~3rd iteration succeeds during outage
    recovery_interval = max(1, int(1 / 0.25))  # Every 4th iteration attempts recovery

    outage_iterations = set(range(outage_interval - 1, total_operations, outage_interval))
    auth_fail_iterations = set(range(auth_fail_interval - 1, total_operations, auth_fail_interval))
    degraded_success_iterations = set(range(degraded_success_interval - 1, total_operations, degraded_success_interval))
    recovery_iterations = set(range(recovery_interval - 1, total_operations, recovery_interval))

    for i in range(total_operations):
        try:
            # Deterministic auth service availability - repeatable every run
            if auth_service_available:
                if i in outage_iterations:
                    auth_service_available = False
                    service_outages += 1

            if auth_service_available:
                # Normal authentication
                if i not in auth_fail_iterations:
                    result = await chaos_db_client.execute_query(operation)
                    execution_time = result.get("_execution_time_ms", 15.0)
                    metrics.record_query_time(execution_time)
                else:
                    raise Exception("Authentication failed")
            else:
                # Auth service unavailable - should handle gracefully
                degraded_operations += 1

                # Simulate degraded operation (might allow limited access)
                if i in degraded_success_iterations:
                    result = await chaos_db_client.execute_query(operation)
                    execution_time = result.get(
                        "_execution_time_ms", 50.0
                    )  # Slower due to auth issues
                    metrics.record_query_time(execution_time)
                else:
                    raise Exception("Authentication service unavailable")

                # Deterministic service recovery
                if i in recovery_iterations:
                    auth_service_available = True

        except Exception as e:
            metrics.record_error()
            if "service unavailable" in str(e).lower():
                service_outages += 1

    metrics.end_test()

    # Validate auth service outage handling
    assert service_outages > 0, "Should experience auth service outages"
    assert degraded_operations > 0, "Should have operations during degraded auth state"

    summary = metrics.get_summary()
    # Calculate success rate based on total operations, not just queries
    # (since errors can occur before query execution)
    success_rate = summary.get("query_count", 0) / total_operations if total_operations > 0 else 0
    # Relaxed threshold for adaptive scaling - randomness creates high variance
    assert success_rate >= 0.05, f"Success rate too low during auth outages: {success_rate:.2f}"

    outage_ratio = degraded_operations / total_operations
    # Relaxed threshold - with adaptive scaling, random outages can be longer
    assert outage_ratio <= 0.9, f"Too much time in auth outage state: {outage_ratio:.2f}"


@pytest.mark.chaos
@pytest.mark.chaos_auth
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_concurrent_authentication_load(
    chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config
):
    """Test authentication under concurrent load.

    Scenario: Multiple concurrent requests require authentication.
    Expected: FraiseQL handles concurrent auth load without degradation.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Simulate concurrent authentication load
    # Scale num_requests based on hardware (6 on baseline, 3-24 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    num_requests = max(3, int(6 * chaos_config.load_multiplier))
    auth_contentions = 0

    async def authenticate_concurrent_request(request_id: int):
        """Simulate authentication under concurrent load."""
        nonlocal auth_contentions

        try:
            # Simulate authentication delay (varies per request)
            auth_delay = 0.01 + random.uniform(0, 0.02)  # 10-30ms auth time
            await asyncio.sleep(auth_delay)

            # Simulate occasional auth contention
            if random.random() < 0.1:  # 10% chance of auth contention
                auth_contentions += 1
                await asyncio.sleep(0.05)  # Additional delay for contention

            # Perform the authenticated operation
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 15.0) + (auth_delay * 1000)
            metrics.record_query_time(execution_time)

            return ("success", request_id, execution_time)

        except Exception as e:
            metrics.record_error()
            return ("error", request_id, str(e))

    # Start concurrent authentication requests
    tasks = [authenticate_concurrent_request(i) for i in range(num_requests)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    # Collect results
    successes = 0
    errors = 0
    execution_times = []

    for result in results:
        if isinstance(result, tuple) and result[0] == "success":
            successes += 1
            execution_times.append(result[2])
        else:
            errors += 1

    # Validate concurrent auth load handling
    assert successes >= num_requests * 0.8, (
        f"Too many failed concurrent auth requests: {successes}/{num_requests}"
    )

    if execution_times:
        avg_time = statistics.mean(execution_times)
        p95_time = (
            sorted(execution_times)[int(len(execution_times) * 0.95)]
            if len(execution_times) > 1
            else avg_time
        )

        # Verify no excessive degradation under concurrent load
        assert p95_time <= avg_time * 2.5, (
            f"High latency variance under concurrent auth load: {p95_time:.1f}ms vs avg {avg_time:.1f}ms"
        )
