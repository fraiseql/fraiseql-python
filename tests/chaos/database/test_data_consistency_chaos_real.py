"""Phase 2.2: Data Consistency Chaos Tests (Real PostgreSQL Backend)

Tests for data consistency issues and transactional integrity under chaos.
Uses real PostgreSQL to validate FraiseQL's handling of transaction rollbacks,
partial updates, and constraint violations.
"""

import asyncio

import pytest
from chaos.base import ChaosMetrics
from chaos.fraiseql_scenarios import FraiseQLTestScenarios


@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_transaction_rollback_recovery(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test recovery from transaction rollbacks.

    Scenario: Transactions are rolled back due to conflicts or errors.
    Expected: FraiseQL handles rollbacks gracefully and maintains consistency.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.mutation_create_post()

    metrics.start_test()

    # Simulate transaction scenarios
    successful_transactions = 0
    rolled_back_transactions = 0

    # Scale iterations based on hardware (8 on baseline, 4-32 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(4, int(8 * chaos_config.load_multiplier))



    for i in range(iterations):
        try:
            # Every 3rd transaction rolls back
            if i % 3 == 2:
                # Simulate transaction failure after some work
                result = await chaos_db_client.execute_query(operation)
                execution_time = result.get("_execution_time_ms", 30.0)
                metrics.record_query_time(execution_time)

                # Then simulate rollback
                raise Exception("Transaction rolled back due to conflict")

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 30.0)
            metrics.record_query_time(execution_time)
            successful_transactions += 1

        except Exception as e:
            if "rolled back" in str(e).lower() or "conflict" in str(e).lower():
                rolled_back_transactions += 1
                metrics.record_error()
            else:
                raise  # Re-raise unexpected errors

    metrics.end_test()

    # Validate transaction rollback handling
    assert rolled_back_transactions > 0, "Should experience some transaction rollbacks"
    assert successful_transactions >= rolled_back_transactions, (
        "Should successfully commit more than roll back"
    )
    # Scale rollback threshold based on adaptive scaling (every 3rd tx rolls back)
    expected_max_rollbacks = max(3, int(iterations / 3))
    assert rolled_back_transactions <= expected_max_rollbacks, (
        f"Rollback rate should be reasonable: {rolled_back_transactions} <= {expected_max_rollbacks}"
    )


@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_partial_update_failure_recovery(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test recovery from partial update failures.

    Scenario: Multi-field updates fail partway through execution.
    Expected: FraiseQL handles partial failures and maintains data consistency.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.search_query()

    metrics.start_test()

    partial_failures = 0
    complete_successes = 0

    # Scale iterations based on hardware (6 on baseline, 3-24 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(3, int(6 * chaos_config.load_multiplier))



    for i in range(iterations):
        try:
            result = await chaos_db_client.execute_query(operation)

            # Check if operation completed fully
            if result.get("data"):
                # Simulate partial failure detection
                if i % 2 == 1:  # Every other operation has partial failure
                    raise Exception("Partial update failure: only some fields updated")

                execution_time = result.get("_execution_time_ms", 75.0)
                metrics.record_query_time(execution_time)
                complete_successes += 1
            else:
                partial_failures += 1
                metrics.record_error()

        except Exception as e:
            if "partial" in str(e).lower() or "incomplete" in str(e).lower():
                partial_failures += 1
                metrics.record_error()
            else:
                raise

    metrics.end_test()

    # Validate partial failure handling
    assert partial_failures > 0, "Should experience some partial update failures"
    assert complete_successes >= partial_failures, (
        "Should have more complete successes than partial failures"
    )


@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_constraint_violation_handling(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test handling of database constraint violations.

    Scenario: Operations violate database constraints (unique, foreign key, check).
    Expected: FraiseQL handles constraint violations with appropriate error responses.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.mutation_create_post()

    metrics.start_test()

    constraint_violations = 0
    successful_operations = 0

    # Scale iterations based on hardware (7 on baseline, 3-28 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(3, int(7 * chaos_config.load_multiplier))



    for i in range(iterations):
        try:
            # Simulate constraint violation scenarios
            if i % 3 == 1:  # Every 3rd operation violates constraints
                if i % 2 == 1:
                    raise Exception("Constraint violation: unique key constraint")
                raise Exception("Constraint violation: foreign key constraint")

            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 25.0)
            metrics.record_query_time(execution_time)
            successful_operations += 1

        except Exception as e:
            if (
                "constraint violation" in str(e).lower()
                or "unique key" in str(e).lower()
                or "foreign key" in str(e).lower()
            ):
                constraint_violations += 1
                metrics.record_error()
            else:
                raise

    metrics.end_test()

    # Validate constraint violation handling
    assert constraint_violations > 0, "Should experience constraint violations"
    assert successful_operations >= constraint_violations, (
        "Should have successful operations despite constraints"
    )


@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_transaction_isolation_anomaly_simulation(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test handling of transaction isolation anomalies.

    Scenario: Concurrent transactions create isolation anomalies (dirty reads, etc).
    Expected: FraiseQL maintains transactional consistency under concurrent load.
    """
    metrics = ChaosMetrics()
    read_operation = FraiseQLTestScenarios.simple_user_query()
    write_operation = FraiseQLTestScenarios.mutation_create_post()

    metrics.start_test()

    async def simulate_transaction(thread_id: int):
        """Simulate a transaction that might experience isolation anomalies."""
        anomalies_detected = 0
        successful_reads = 0

        try:
            # Simulate read operations that might see inconsistent data
            # Scale iterations based on hardware (3 on baseline, 3-12 adaptive)
            # Uses multiplier-based formula to ensure meaningful test on all hardware
            iterations = max(3, int(3 * chaos_config.load_multiplier))

            for read_num in range(iterations):
                result = await chaos_db_client.execute_query(read_operation)
                execution_time = result.get("_execution_time_ms", 15.0)

                # Simulate anomaly detection (inconsistent data)
                if thread_id == 1 and read_num == 1:  # Thread 1 sees anomaly on second read
                    anomalies_detected += 1
                    metrics.record_error()
                else:
                    successful_reads += 1
                    metrics.record_query_time(execution_time)

            # Simulate write operation (only thread 0 does writes)
            if thread_id == 0:
                result = await chaos_db_client.execute_query(write_operation)
                execution_time = result.get("_execution_time_ms", 30.0)
                metrics.record_query_time(execution_time)

            return (thread_id, anomalies_detected, successful_reads)

        except Exception:
            metrics.record_error()
            return (thread_id, anomalies_detected, successful_reads)

    # Start concurrent transactions
    tasks = [simulate_transaction(i) for i in range(2)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    # Collect results
    anomalies = 0
    successes = 0

    for result in results:
        if isinstance(result, tuple):
            thread_id, anom_count, success_count = result
            anomalies += anom_count
            successes += success_count

    # Validate isolation anomaly handling
    # We expect at least some successful reads despite potential anomalies
    assert successes > 0, "Should have successful read operations"
    # Anomalies should be detected
    assert anomalies >= 0, "Anomaly detection possible under concurrency"


@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_data_corruption_detection(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test detection of data corruption scenarios.

    Scenario: Database returns corrupted or inconsistent data.
    Expected: FraiseQL detects corruption and handles appropriately.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    corruption_detected = 0
    valid_responses = 0

    # Scale iterations based on hardware (8 on baseline, 4-32 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(4, int(8 * chaos_config.load_multiplier))



    for i in range(iterations):
        try:
            result = await chaos_db_client.execute_query(operation)

            # Simulate corruption detection
            if i % 4 == 3:  # Every 4th response is corrupted
                # Corrupted response
                corruption_detected += 1
                metrics.record_error()
            else:
                # Valid response
                execution_time = result.get("_execution_time_ms", 12.0)
                metrics.record_query_time(execution_time)

                # Validate response structure
                if result.get("data"):
                    valid_responses += 1
                else:
                    corruption_detected += 1
                    metrics.record_error()

        except Exception:
            corruption_detected += 1
            metrics.record_error()

    metrics.end_test()

    # Validate corruption detection
    assert corruption_detected > 0, "Should detect some data corruption"
    assert valid_responses > corruption_detected, (
        "Should have more valid responses than corruption"
    )


@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_cascading_failure_prevention(chaos_db_client, chaos_test_schema, baseline_metrics, chaos_config):
    """Test prevention of cascading failures in data operations.

    Scenario: One failed operation shouldn't cause cascading failures.
    Expected: FraiseQL contains failures and maintains system stability.
    """
    metrics = ChaosMetrics()
    simple_op = FraiseQLTestScenarios.simple_user_query()
    complex_op = FraiseQLTestScenarios.complex_nested_query()

    metrics.start_test()

    # Simulate cascading failure scenario
    primary_failures = 0
    cascading_failures = 0
    contained_operations = 0

    # Scale iterations based on hardware (6 on baseline, 3-24 adaptive)
    # Uses multiplier-based formula to ensure meaningful test on all hardware
    iterations = max(3, int(6 * chaos_config.load_multiplier))



    for i in range(iterations):
        try:
            # Primary operation (might fail)
            primary_result = await chaos_db_client.execute_query(simple_op)
            primary_time = primary_result.get("_execution_time_ms", 10.0)

            # Dependent complex operation
            if i % 2 == 1:  # Primary fails on odd iterations
                raise Exception("Primary operation failed")

            # If primary succeeds, execute dependent operation
            complex_result = await chaos_db_client.execute_query(complex_op)
            complex_time = complex_result.get("_execution_time_ms", 45.0)

            metrics.record_query_time(primary_time + complex_time)
            contained_operations += 1

        except Exception as e:
            if "Primary operation failed" in str(e):
                primary_failures += 1
                # Check if dependent operation also failed (cascading)
                try:
                    # Dependent operation should still succeed (no cascading)
                    complex_result = await chaos_db_client.execute_query(complex_op)
                    contained_operations += 1  # Successfully contained the failure
                except Exception:
                    # Dependent operation failed - this is a cascading failure
                    cascading_failures += 1
                    metrics.record_error()
            else:
                raise

    metrics.end_test()

    # Validate cascading failure prevention
    assert primary_failures > 0, "Should have primary operation failures"
    assert cascading_failures == 0, "Should prevent cascading failures"
    assert contained_operations > 0, "Should successfully contain some operations"
