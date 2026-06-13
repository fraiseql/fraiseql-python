"""Chaos Engineering Pytest Plugin

This plugin provides decorators and utilities for chaos engineering tests,
including failure injection, retry logic, and chaos scenario management.
"""

import functools
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional

import pytest

# Import for type annotations


class FailureType(Enum):
    """Types of failures that can be injected."""

    NETWORK_LATENCY = "network_latency"
    NETWORK_PACKET_LOSS = "network_packet_loss"
    NETWORK_DISCONNECT = "network_disconnect"
    DATABASE_SLOW_QUERY = "database_slow_query"
    DATABASE_CONNECTION_REFUSED = "database_connection_refused"
    CACHE_INVALIDATION = "cache_invalidation"
    CACHE_CORRUPTION = "cache_corruption"
    MEMORY_PRESSURE = "memory_pressure"
    CPU_SPIKE = "cpu_spike"
    THREAD_EXHAUSTION = "thread_exhaustion"


class ChaosInjector:
    """Chaos injection manager."""

    def __init__(self):
        self.active_failures: Dict[str, Dict[str, Any]] = {}

    def inject_failure(self, failure_type: FailureType, duration_ms: int, **kwargs) -> str:
        """Inject a failure scenario.

        Returns a failure ID that can be used to check status or cancel.
        """
        failure_id = f"{failure_type.value}_{int(time.time() * 1000)}"

        failure_config = {
            "type": failure_type,
            "start_time": time.time(),
            "duration_ms": duration_ms,
            "end_time": time.time() + (duration_ms / 1000),
            "active": True,
            "config": kwargs,
        }

        self.active_failures[failure_id] = failure_config

        # TODO: Implement actual failure injection based on type
        # For now, this is a placeholder that just waits

        return failure_id

    def is_failure_active(self, failure_id: str) -> bool:
        """Check if a failure is still active."""
        if failure_id not in self.active_failures:
            return False

        failure = self.active_failures[failure_id]
        if not failure["active"]:
            return False

        current_time = time.time()
        if current_time >= failure["end_time"]:
            failure["active"] = False
            return False

        return True

    def cancel_failure(self, failure_id: str):
        """Cancel an active failure."""
        if failure_id in self.active_failures:
            self.active_failures[failure_id]["active"] = False

    def get_active_failures(self) -> Dict[str, Dict[str, Any]]:
        """Get all currently active failures."""
        return {k: v for k, v in self.active_failures.items() if v["active"]}


# Global chaos injector instance
_chaos_injector = ChaosInjector()


def chaos_inject(failure_type: FailureType, duration_ms: int = 5000, **kwargs):
    """Decorator to inject chaos into a test function.

    Args:
        failure_type: Type of failure to inject
        duration_ms: How long to inject the failure (default: 5 seconds)
        **kwargs: Additional configuration for the failure type

    Example:
        @chaos_inject(FailureType.NETWORK_LATENCY, duration_ms=2000, latency_ms=500)
        def test_with_latency(self):
            # Test runs with 500ms network latency for 2 seconds
            pass
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs_inner):
            # Inject chaos before running the test
            failure_id = _chaos_injector.inject_failure(failure_type, duration_ms, **kwargs)

            try:
                # Run the test
                result = func(*args, **kwargs_inner)
                return result
            finally:
                # Clean up chaos injection
                _chaos_injector.cancel_failure(failure_id)

        # Mark the function as a chaos test
        wrapper._chaos_test = True
        wrapper._failure_type = failure_type
        wrapper._chaos_duration = duration_ms

        return wrapper

    return decorator


def retry_chaos_test(
    max_retries: int = 3, retry_on: tuple = (Exception,), record_all: bool = False
):
    """Decorator to retry chaos tests that may be inherently flaky.

    Args:
        max_retries: Maximum number of retry attempts
        retry_on: Exception types to retry on
        record_all: Whether to record all attempts or just final result

    Example:
        @retry_chaos_test(max_retries=5, retry_on=(ConnectionError, TimeoutError))
        def test_flaky_chaos_scenario(self):
            # Test that might fail due to chaos injection
            pass
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    if record_all:
                        # Record successful attempt
                        _record_chaos_attempt(func.__name__, attempt, success=True)
                    return result

                except retry_on as e:
                    last_exception = e
                    if record_all:
                        _record_chaos_attempt(func.__name__, attempt, success=False, error=str(e))

                    if attempt < max_retries:
                        # Wait before retry (exponential backoff)
                        time.sleep(0.1 * (2**attempt))
                        continue

            # All retries exhausted
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


def _record_chaos_attempt(test_name: str, attempt: int, success: bool, error: Optional[str] = None):
    """Record a chaos test attempt for analysis."""
    # TODO: Implement attempt recording
    # This could write to a database or file for later analysis


# Pytest plugin hooks


def pytest_configure(config):
    """Configure pytest with chaos engineering support."""
    # Add chaos test markers
    config.addinivalue_line(
        "markers", "chaos_inject: mark test to inject specific failure scenarios"
    )
    config.addinivalue_line("markers", "chaos_retry: mark test to retry on chaos-induced failures")


def pytest_collection_modifyitems(config, items):
    """Modify test collection to handle chaos tests."""
    for item in items:
        # Check if test has chaos decorators
        if hasattr(item.function, "_chaos_test"):
            # Add chaos marker
            item.add_marker(pytest.mark.chaos_inject)

            # Add additional metadata
            failure_type = getattr(item.function, "_failure_type", None)
            chaos_duration = getattr(item.function, "_chaos_duration", None)

            if failure_type:
                item.user_properties.append(("chaos_failure_type", failure_type.value))
            if chaos_duration:
                item.user_properties.append(("chaos_duration_ms", chaos_duration))


@pytest.fixture
def chaos_injector():
    """Fixture providing access to the chaos injector."""
    return _chaos_injector


# Convenience decorators for common chaos scenarios


def chaos_network_latency(latency_ms: int = 500, duration_ms: int = 5000):
    """Decorator for network latency chaos."""
    return chaos_inject(FailureType.NETWORK_LATENCY, duration_ms, latency_ms=latency_ms)


def chaos_packet_loss(loss_percent: float = 0.1, duration_ms: int = 5000):
    """Decorator for packet loss chaos."""
    return chaos_inject(FailureType.NETWORK_PACKET_LOSS, duration_ms, loss_percent=loss_percent)


def chaos_database_timeout(timeout_ms: int = 5000, duration_ms: int = 10000):
    """Decorator for database timeout chaos."""
    return chaos_inject(FailureType.DATABASE_SLOW_QUERY, duration_ms, timeout_ms=timeout_ms)
