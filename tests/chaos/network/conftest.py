# Conftest for tests/chaos/network
import os
import sys

import pytest

tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)


@pytest.fixture(autouse=True)
def inject_chaos_config(request, chaos_config):
    """Auto-inject chaos_config into unittest-style test classes.

    This fixture makes chaos_config available as self.chaos_config in all
    test methods, enabling adaptive scaling based on hardware profile.
    """
    if hasattr(request, "instance") and request.instance is not None:
        request.instance.chaos_config = chaos_config


@pytest.fixture
def toxiproxy():
    """Toxiproxy fixture that skips tests if Toxiproxy is not available.

    Toxiproxy is a framework for simulating network conditions (latency, packet loss, etc.).
    These tests require Toxiproxy infrastructure to be set up.
    For now, we skip these tests as Toxiproxy is not configured.
    """
    pytest.skip("Toxiproxy infrastructure not configured - test requires Toxiproxy")
