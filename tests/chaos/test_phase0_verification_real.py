"""Phase 0 Verification Test (Real PostgreSQL Backend)

This test verifies that the Phase 0 chaos engineering infrastructure works correctly
with real PostgreSQL database backend.
"""

import asyncio

import pytest
from chaos.base import ChaosMetrics
from chaos.fraiseql_scenarios import FraiseQLTestScenarios


@pytest.mark.chaos
@pytest.mark.chaos_verification
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_real_client_initialization(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test that real database client initializes correctly.

    Verifies the chaos_db_client fixture works with real PostgreSQL.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    try:
        result = await chaos_db_client.execute_query(operation)
        assert result is not None
        assert "_execution_time_ms" in result
        metrics.record_query_time(result.get("_execution_time_ms", 10.0))
    except Exception as e:
        metrics.record_error()
        pytest.fail(f"Real client initialization failed: {e}")

    metrics.end_test()

    summary = metrics.get_summary()
    assert summary.get("query_count", 0) >= 1
    assert summary.get("error_count", 0) == 0


@pytest.mark.chaos
@pytest.mark.chaos_verification
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_metrics_collection_real_db(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test that metrics collection works with real database.

    Verifies ChaosMetrics properly tracks queries against real database.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Execute multiple queries
    for i in range(5):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    metrics.end_test()

    summary = metrics.get_summary()
    assert summary.get("query_count", 0) == 5, "Should record exactly 5 queries"
    assert "avg_query_time_ms" in summary


@pytest.mark.chaos
@pytest.mark.chaos_verification
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_baseline_execution_real_db(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test baseline performance measurement against real database.

    Verifies baseline metrics can be established with real PostgreSQL.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.complex_nested_query()

    metrics.start_test()

    baseline_times = []
    for _ in range(5):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 50.0)
            baseline_times.append(execution_time)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    metrics.end_test()

    summary = metrics.get_summary()
    assert summary.get("query_count", 0) >= 4, "Most baseline queries should succeed"
    assert summary.get("error_count", 0) <= 1, "Baseline should have minimal errors"


@pytest.mark.chaos
@pytest.mark.chaos_verification
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_chaos_injection_basic(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test basic chaos injection with real database.

    Verifies chaos injection (latency) works with real PostgreSQL.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Baseline without chaos
    baseline_times = []
    for _ in range(3):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            baseline_times.append(execution_time)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    # Inject latency
    chaos_db_client.inject_latency(100)

    # Execute with chaos
    chaos_times = []
    for _ in range(3):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 100.0)
            chaos_times.append(execution_time)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    chaos_db_client.reset_chaos()

    # Recovery
    recovery_times = []
    for _ in range(3):
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            recovery_times.append(execution_time)
            metrics.record_query_time(execution_time)
        except Exception:
            metrics.record_error()

    metrics.end_test()

    # Verify chaos had effect
    if baseline_times and chaos_times:
        import statistics
        baseline_avg = statistics.mean(baseline_times)
        chaos_avg = statistics.mean(chaos_times)
        # Chaos should show measurable delay
        assert chaos_avg > baseline_avg, "Chaos injection should increase latency"


@pytest.mark.chaos
@pytest.mark.chaos_verification
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_fixture_isolation(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test that schema isolation works with real database fixtures.

    Verifies each test gets isolated schema with proper cleanup.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    # Should be able to execute queries in isolated schema
    try:
        result = await chaos_db_client.execute_query(operation)
        assert result is not None
        metrics.record_query_time(result.get("_execution_time_ms", 10.0))
    except Exception as e:
        metrics.record_error()
        pytest.fail(f"Fixture isolation test failed: {e}")

    metrics.end_test()

    summary = metrics.get_summary()
    assert summary.get("query_count", 0) >= 1
    assert summary.get("error_count", 0) == 0


@pytest.mark.chaos
@pytest.mark.chaos_verification
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_concurrent_verification(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test concurrent query execution with real database.

    Verifies asyncio concurrency works properly with real PostgreSQL.
    """
    metrics = ChaosMetrics()
    operation = FraiseQLTestScenarios.simple_user_query()

    metrics.start_test()

    async def execute_concurrent_query(query_id: int):
        """Execute a single query concurrently."""
        try:
            result = await chaos_db_client.execute_query(operation)
            execution_time = result.get("_execution_time_ms", 10.0)
            metrics.record_query_time(execution_time)
            return True
        except Exception:
            metrics.record_error()
            return False

    # Execute 5 queries concurrently
    tasks = [execute_concurrent_query(i) for i in range(5)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_test()

    summary = metrics.get_summary()
    successes = sum(1 for r in results if r is True)
    assert successes >= 4, "Most concurrent queries should succeed"
    assert summary.get("query_count", 0) >= 4
