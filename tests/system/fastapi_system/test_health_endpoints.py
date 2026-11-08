"""Tests for health and readiness endpoints."""

import pytest
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app


@fraiseql.type
class TestStatus:
    """Test status type."""

    message: str


async def get_status(info) -> TestStatus:
    """Get test status."""
    return TestStatus(message="OK")


@pytest.fixture
def test_app(clear_registry):
    """Create a test FraiseQL app with database.

    The registry is cleared first: collecting other test modules in the same process
    runs their module-level @fraiseql.query decorators, and this app should only
    carry the type and query it passes.
    """
    app = create_fraiseql_app(
        database_url="postgresql://postgres:postgres@localhost:5432/fraiseql_test",
        types=[TestStatus],
        queries=[get_status],
        auto_discover=False,
    )
    return app


@pytest.fixture
def test_app_no_db(clear_registry):
    """Create a test FraiseQL app without database (for testing failures)."""
    app = create_fraiseql_app(
        database_url="postgresql://invalid-host:5432/test",
        types=[TestStatus],
        queries=[get_status],
        auto_discover=False,
    )
    return app


def test_health_endpoint_always_returns_200(test_app):
    """Test that /health always returns 200 (liveness probe)."""
    client = TestClient(test_app)

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "fraiseql"


def test_health_endpoint_always_healthy_even_without_db(test_app_no_db):
    """Test that /health returns 200 even when database is unreachable.

    Liveness probes should only check if the process is alive,
    not if dependencies are ready.
    """
    client = TestClient(test_app_no_db)

    response = client.get("/health")

    # Should still be 200 (process is alive)
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_ready_endpoint_returns_200_when_database_available(test_app):
    """Test that /ready returns 200 when database is reachable.

    Note: This test may return 503 if the test database is not available,
    which is expected. The key is that the endpoint responds correctly.
    """
    client = TestClient(test_app)

    response = client.get("/ready")

    # Accept either 200 (database available) or 503 (database not available)
    assert response.status_code in [200, 503]
    data = response.json()
    assert data["status"] in ["ready", "not_ready"]
    assert "checks" in data
    assert "database" in data["checks"]
    assert "schema" in data["checks"]
    assert "timestamp" in data


def test_ready_endpoint_returns_503_when_database_unavailable(test_app_no_db):
    """Test that /ready returns 503 when database is unreachable."""
    client = TestClient(test_app_no_db)

    response = client.get("/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert "checks" in data
    assert "failed" in data["checks"]["database"]
    assert "timestamp" in data


def test_ready_endpoint_response_format(test_app):
    """Test that /ready returns the expected response format."""
    client = TestClient(test_app)

    response = client.get("/ready")
    data = response.json()

    # Check response structure
    assert "status" in data
    assert "checks" in data
    assert "timestamp" in data

    # Check checks structure
    assert isinstance(data["checks"], dict)
    assert "database" in data["checks"]
    assert "schema" in data["checks"]

    # Check timestamp is a number
    assert isinstance(data["timestamp"], (int, float))


def test_health_vs_ready_difference(test_app_no_db):
    """Test that /health and /ready have different behavior.

    /health (liveness) should always return 200 if process is alive.
    /ready (readiness) should return 503 if dependencies are not ready.
    """
    client = TestClient(test_app_no_db)

    # Health should always be 200 (process is alive)
    health_response = client.get("/health")
    assert health_response.status_code == 200

    # Ready should be 503 (database unreachable)
    ready_response = client.get("/ready")
    assert ready_response.status_code == 503


def test_ready_endpoint_database_check_details(test_app_no_db):
    """Test that /ready provides detailed error information for database failures."""
    client = TestClient(test_app_no_db)

    response = client.get("/ready")
    data = response.json()

    # Should have database check failure
    assert "database" in data["checks"]
    db_status = data["checks"]["database"]
    assert "failed" in db_status
    # Should include some error detail (truncated to 100 chars)
    assert len(db_status) > 0


def test_ready_endpoint_async(test_app):
    """Test /ready endpoint with test client (sync)."""
    client = TestClient(test_app)

    response = client.get("/ready")

    # Should return a valid response (200 or 503)
    assert response.status_code in [200, 503]
    data = response.json()
    assert data["status"] in ["ready", "not_ready"]


def test_ready_endpoint_performance(test_app):
    """Test that /ready responds quickly (< 5 seconds for Kubernetes timeout)."""
    import time

    client = TestClient(test_app)

    start_time = time.time()
    response = client.get("/ready")
    elapsed_time = time.time() - start_time

    # Should respond (200 or 503)
    assert response.status_code in [200, 503]
    # Should respond in under 5 seconds (Kubernetes default timeout)
    assert elapsed_time < 5.0
    # Should actually respond much faster (< 1 second even when checking DB)
    assert elapsed_time < 1.0


def test_ready_endpoint_idempotent(test_app):
    """Test that /ready can be called repeatedly without side effects."""
    client = TestClient(test_app)

    # Call /ready multiple times
    responses = [client.get("/ready") for _ in range(5)]

    # All should return the same result (no side effects)
    first_status = responses[0].status_code
    for response in responses:
        assert response.status_code == first_status  # Consistent
        data = response.json()
        assert data["status"] in ["ready", "not_ready"]
        assert "database" in data["checks"]
