"""Pytest configuration for Grafana dashboard tests."""

import pytest

# Known exceptions for certain test rules
# These are documented legitimate cases where strict rules don't apply

KNOWN_EXCEPTIONS = {
    # Queries that intentionally don't filter by environment
    # (e.g., "Errors by Environment" shows all environments)
    "no_environment_filter": [
        ("error_monitoring", "Errors by Environment"),
    ],
    # Queries with time columns but don't need time filtering
    # (e.g., latest value queries with complex CTEs)
    "no_time_filter": [
        ("database_pool", "Pool Utilization Rate"),
    ],
    # Queries with aggregates that intentionally don't use GROUP BY
    # (e.g., simple aggregate-only queries with FILTER clauses or single-row results)
    "no_group_by": [
        ("error_monitoring", "Error Resolution Status"),
        ("cache_hit_rate", "Overall Cache Hit Rate"),
    ],
}


@pytest.fixture
def known_exceptions() -> None:
    """Return known exceptions for test rules."""
    return KNOWN_EXCEPTIONS


def is_known_exception(dashboard, panel, exception_type) -> None:
    """Check if a query is a known exception to a test rule."""
    exceptions = KNOWN_EXCEPTIONS.get(exception_type, [])
    return (dashboard, panel) in exceptions
