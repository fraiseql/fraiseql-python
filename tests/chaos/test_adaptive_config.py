"""Test adaptive configuration fixtures.

This test verifies that the environment detection and adaptive config
fixtures work correctly.
"""

import pytest


@pytest.mark.chaos
def test_environment_info_fixture(environment_info):
    """Test that environment_info fixture works."""
    assert environment_info is not None
    assert hasattr(environment_info, "hardware")
    assert hasattr(environment_info, "is_ci")
    assert hasattr(environment_info, "is_containerized")
    assert hasattr(environment_info, "platform")
    assert hasattr(environment_info, "environment_type")

    # Hardware should be detected
    assert environment_info.hardware.cpu_count > 0
    assert environment_info.hardware.memory_gb > 0
    # CPU frequency might not be available in CI/containerized environments
    assert environment_info.hardware.cpu_freq_mhz >= 0


def test_chaos_config_fixture(chaos_config):
    """Test that chaos_config fixture works."""
    assert chaos_config is not None

    # Should have all required fields
    assert hasattr(chaos_config, "concurrent_requests")
    assert hasattr(chaos_config, "concurrent_queries")
    assert hasattr(chaos_config, "concurrent_transactions")
    assert hasattr(chaos_config, "connection_pool_size")
    assert hasattr(chaos_config, "timeout_seconds")
    assert hasattr(chaos_config, "load_multiplier")

    # Values should be sensible
    assert chaos_config.concurrent_requests > 0
    assert chaos_config.connection_pool_size > 0
    assert chaos_config.timeout_seconds > 0
    assert 0.5 <= chaos_config.load_multiplier <= 4.0


def test_config_scales_with_environment(chaos_config, environment_info):
    """Test that config adapts to environment."""
    # High-end systems should have higher concurrent values
    if environment_info.hardware.profile_name == "high":
        assert chaos_config.concurrent_requests >= 100

    # CI environments should have more lenient timeouts
    if environment_info.is_ci:
        assert chaos_config.timeout_seconds >= 5.0

    # Local environments should have strict timeouts
    if environment_info.environment_type == "local":
        assert chaos_config.timeout_seconds <= 10.0
