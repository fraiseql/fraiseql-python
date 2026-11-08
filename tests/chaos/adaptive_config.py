"""Adaptive configuration for chaos tests.

This module provides environment-specific configuration that adapts
to hardware capabilities and runtime environment.
"""

from dataclasses import dataclass
from typing import Any, Dict

from .environment import (
    EnvironmentInfo,
    detect_environment,
    get_load_multiplier,
)


@dataclass
class ChaosConfig:
    """Configuration for chaos engineering tests."""

    # Concurrent operation settings
    concurrent_requests: int
    concurrent_queries: int
    concurrent_transactions: int

    # Connection pool settings
    connection_pool_size: int
    connection_pool_max: int

    # Timeout settings (seconds)
    timeout_seconds: float
    operation_timeout: float
    connection_timeout: float

    # Retry settings
    retry_attempts: int
    retry_delay: float

    # Cache settings
    cache_size: int
    cache_ttl: int

    # Load settings
    load_multiplier: float

    # Environment info
    environment: EnvironmentInfo

    def __str__(self) -> str:
        """String representation."""
        return (
            f"ChaosConfig(env={self.environment.environment_type}, "
            f"concurrent={self.concurrent_requests}, "
            f"pool={self.connection_pool_size}, "
            f"multiplier={self.load_multiplier:.2f}x)"
        )


def create_ci_config(env: EnvironmentInfo, multiplier: float) -> ChaosConfig:
    """Create configuration for CI/CD environment.

    CI environments are typically resource-constrained, so we use
    more conservative settings with longer timeouts.

    Args:
        env: Environment information
        multiplier: Load multiplier based on hardware

    Returns:
        ChaosConfig optimized for CI/CD
    """
    return ChaosConfig(
        # Concurrent operations (lower for CI)
        concurrent_requests=int(50 * multiplier),
        concurrent_queries=int(30 * multiplier),
        concurrent_transactions=int(20 * multiplier),
        # Connection pools (smaller for CI)
        connection_pool_size=10,
        connection_pool_max=20,
        # Timeouts (more lenient for CI)
        timeout_seconds=10.0 / multiplier,  # Slower systems = longer timeout
        operation_timeout=5.0 / multiplier,
        connection_timeout=3.0 / multiplier,
        # Retries (more forgiving in CI)
        retry_attempts=5,
        retry_delay=0.5,
        # Cache (smaller in CI)
        cache_size=1000,
        cache_ttl=300,
        # Metadata
        load_multiplier=multiplier,
        environment=env,
    )


def create_local_config(env: EnvironmentInfo, multiplier: float) -> ChaosConfig:
    """Create configuration for local development.

    Local environments typically have more resources and we want
    to stress the system to find issues.

    Args:
        env: Environment information
        multiplier: Load multiplier based on hardware

    Returns:
        ChaosConfig optimized for local development
    """
    return ChaosConfig(
        # Concurrent operations (scaled with hardware)
        concurrent_requests=int(100 * multiplier),
        concurrent_queries=int(60 * multiplier),
        concurrent_transactions=int(40 * multiplier),
        # Connection pools (intentionally small to create contention)
        connection_pool_size=10,  # Fixed to ensure contention
        connection_pool_max=30,
        # Timeouts (strict for local)
        timeout_seconds=5.0 / multiplier,  # Faster hardware = stricter timeout
        operation_timeout=2.0 / multiplier,
        connection_timeout=1.0 / multiplier,
        # Retries (less forgiving locally)
        retry_attempts=3,
        retry_delay=0.1,
        # Cache (larger for local)
        cache_size=10000,
        cache_ttl=600,
        # Metadata
        load_multiplier=multiplier,
        environment=env,
    )


def create_container_config(env: EnvironmentInfo, multiplier: float) -> ChaosConfig:
    """Create configuration for containerized environment.

    Containers have varying resources but typically good networking.

    Args:
        env: Environment information
        multiplier: Load multiplier based on hardware

    Returns:
        ChaosConfig optimized for containers
    """
    return ChaosConfig(
        # Concurrent operations (moderate)
        concurrent_requests=int(75 * multiplier),
        concurrent_queries=int(45 * multiplier),
        concurrent_transactions=int(30 * multiplier),
        # Connection pools (moderate)
        connection_pool_size=15,
        connection_pool_max=25,
        # Timeouts (moderate)
        timeout_seconds=7.0 / multiplier,
        operation_timeout=3.0 / multiplier,
        connection_timeout=2.0 / multiplier,
        # Retries (moderate)
        retry_attempts=4,
        retry_delay=0.2,
        # Cache (moderate)
        cache_size=5000,
        cache_ttl=450,
        # Metadata
        load_multiplier=multiplier,
        environment=env,
    )


def get_chaos_config(env: EnvironmentInfo | None = None) -> ChaosConfig:
    """Get adaptive chaos configuration based on environment.

    This is the main entry point for getting configuration.
    It detects the environment and returns appropriate settings.

    Args:
        env: Environment info (auto-detected if None)

    Returns:
        ChaosConfig appropriate for the current environment

    Examples:
        >>> config = get_chaos_config()
        >>> # Use in tests:
        >>> async def test_concurrent_load(chaos_config):
        ...     for _ in range(chaos_config.concurrent_requests):
        ...         await make_request()
    """
    if env is None:
        env = detect_environment()

    multiplier = get_load_multiplier(env.hardware)

    # Select config based on environment type
    if env.is_ci:
        return create_ci_config(env, multiplier)
    if env.is_containerized:
        return create_container_config(env, multiplier)
    return create_local_config(env, multiplier)


def get_config_for_profile(profile: str) -> ChaosConfig:
    """Get configuration for a specific hardware profile.

    Useful for testing or when you want to override auto-detection.

    Args:
        profile: Profile name ("low", "medium", "high")

    Returns:
        ChaosConfig for the specified profile
    """
    from .environment import HardwareProfile

    # Profile definitions
    profiles: Dict[str, Dict[str, Any]] = {
        "low": {"cpu_count": 2, "memory_gb": 4.0, "cpu_freq_mhz": 1800.0},
        "medium": {"cpu_count": 4, "memory_gb": 8.0, "cpu_freq_mhz": 2400.0},
        "high": {"cpu_count": 16, "memory_gb": 32.0, "cpu_freq_mhz": 3600.0},
    }

    if profile not in profiles:
        raise ValueError(f"Unknown profile: {profile}. Use: low, medium, or high")

    # Create mock environment
    hw_params = profiles[profile]
    hardware = HardwareProfile(**hw_params)

    env = EnvironmentInfo(
        hardware=hardware,
        is_ci=False,
        is_containerized=False,
        platform="linux",
    )

    return get_chaos_config(env)


if __name__ == "__main__":
    """CLI tool to display configuration."""
    env = detect_environment()
    config = get_chaos_config(env)

    print("=" * 80)
    print("CHAOS TEST ADAPTIVE CONFIGURATION")
    print("=" * 80)
    print()
    print(f"Environment: {env.environment_type.upper()}")
    print(f"Hardware:    {env.hardware.profile_name.upper()}")
    print(f"Multiplier:  {config.load_multiplier:.2f}x")
    print()
    print("Configuration:")
    print(f"  Concurrent Requests:     {config.concurrent_requests}")
    print(f"  Concurrent Queries:      {config.concurrent_queries}")
    print(f"  Concurrent Transactions: {config.concurrent_transactions}")
    print()
    print(f"  Connection Pool Size:    {config.connection_pool_size}")
    print(f"  Connection Pool Max:     {config.connection_pool_max}")
    print()
    print(f"  Timeout (seconds):       {config.timeout_seconds:.1f}s")
    print(f"  Operation Timeout:       {config.operation_timeout:.1f}s")
    print(f"  Connection Timeout:      {config.connection_timeout:.1f}s")
    print()
    print(f"  Retry Attempts:          {config.retry_attempts}")
    print(f"  Retry Delay:             {config.retry_delay:.2f}s")
    print()
    print(f"  Cache Size:              {config.cache_size}")
    print(f"  Cache TTL:               {config.cache_ttl}s")
    print()
    print("=" * 80)
    print()
    print("Profile Comparison:")
    print("-" * 80)
    for profile_name in ["low", "high"]:
        p_config = get_config_for_profile(profile_name)
        print(
            f"{profile_name.upper():6} profile: "
            f"{p_config.concurrent_requests:3} concurrent, "
            f"{p_config.timeout_seconds:.1f}s timeout"
        )
    print("=" * 80)
