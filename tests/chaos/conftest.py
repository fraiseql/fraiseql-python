# Chaos Engineering Test Configuration
#
# This module provides fixtures and configuration for chaos engineering tests.
# Chaos tests inject failures into FraiseQL to validate resilience and recovery.

import sys
import os
import pytest

# Add tests directory to Python path for chaos module imports
tests_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)

from chaos.base import ChaosTestCase
from chaos.fixtures import ToxiproxyManager
from chaos.base import ChaosMetrics
from chaos.adaptive_config import get_chaos_config, ChaosConfig
from chaos.environment import detect_environment, EnvironmentInfo

# Note: pytest_plugins moved to top-level tests/conftest.py
# to comply with pytest plugin loading requirements


@pytest.fixture
def chaos_test_case():
    """Base test case for chaos engineering tests."""
    return ChaosTestCase()


@pytest.fixture
def toxiproxy():
    """Toxiproxy manager for network chaos injection."""
    manager = ToxiproxyManager()
    yield manager
    # Cleanup all proxies after test
    for proxy_name in list(manager.proxies.keys()):
        try:
            manager.delete_proxy(proxy_name)
        except:
            pass


# For unittest-style tests, provide a default toxiproxy instance
_default_toxiproxy = ToxiproxyManager()


@pytest.fixture
def chaos_metrics():
    """Chaos metrics collector."""
    return ChaosMetrics()


@pytest.fixture(scope="session")
def environment_info() -> EnvironmentInfo:
    """
    Detect environment information once per test session.

    This fixture provides hardware and environment details for adaptive
    test configuration.

    Returns:
        EnvironmentInfo with detected capabilities
    """
    env = detect_environment()
    print(f"\n[Environment Detection] {env}")
    return env


@pytest.fixture(scope="session")
def chaos_config(environment_info: EnvironmentInfo) -> ChaosConfig:
    """
    Adaptive chaos test configuration based on environment.

    This fixture provides environment-specific configuration that scales
    concurrent operations, timeouts, and pool sizes based on detected
    hardware capabilities and runtime environment (CI/CD, container, local).

    The configuration adapts to:
    - Hardware: CPU count, memory, frequency
    - Environment: CI/CD vs local development
    - Containerization: Docker, Podman, Kubernetes

    Args:
        environment_info: Detected environment information

    Returns:
        ChaosConfig with adaptive settings

    Examples:
        >>> async def test_concurrent_load(chaos_config):
        ...     # Use adaptive concurrent request count
        ...     tasks = [
        ...         make_request()
        ...         for _ in range(chaos_config.concurrent_requests)
        ...     ]
        ...     await asyncio.gather(*tasks)
        ...
        >>> async def test_with_timeout(chaos_config):
        ...     # Use adaptive timeout
        ...     async with asyncio.timeout(chaos_config.timeout_seconds):
        ...         await long_operation()
    """
    config = get_chaos_config(environment_info)
    print(f"\n[Chaos Config] {config}")
    return config


# Register chaos test markers
def pytest_configure(config):
    config.addinivalue_line("markers", "chaos: marks tests as chaos engineering tests")
    config.addinivalue_line("markers", "chaos_network: network-related chaos tests")
    config.addinivalue_line("markers", "chaos_database: database-related chaos tests")
    config.addinivalue_line("markers", "chaos_cache: cache-related chaos tests")
    config.addinivalue_line("markers", "chaos_auth: authentication-related chaos tests")
    config.addinivalue_line("markers", "chaos_resources: resource-related chaos tests")
    config.addinivalue_line("markers", "chaos_concurrency: concurrency-related chaos tests")
