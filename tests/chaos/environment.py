"""Environment detection for chaos tests.

This module detects hardware capabilities and runtime environment
to provide adaptive configuration for chaos engineering tests.
"""

import multiprocessing
import os
from dataclasses import dataclass
from typing import Optional

import psutil


@dataclass
class HardwareProfile:
    """Hardware capabilities of the system."""

    cpu_count: int
    memory_gb: float
    cpu_freq_mhz: float

    @property
    def profile_name(self) -> str:
        """Get a human-readable profile name."""
        if self.cpu_count <= 2 or self.memory_gb <= 4:
            return "low"
        if self.cpu_count <= 4 or self.memory_gb <= 8:
            return "medium"
        return "high"

    def __str__(self) -> str:
        """String representation."""
        return (
            f"HardwareProfile(cpu={self.cpu_count}, "
            f"memory={self.memory_gb:.1f}GB, "
            f"freq={self.cpu_freq_mhz:.0f}MHz, "
            f"profile={self.profile_name})"
        )


@dataclass
class EnvironmentInfo:
    """Complete environment information."""

    hardware: HardwareProfile
    is_ci: bool
    is_containerized: bool
    platform: str

    @property
    def environment_type(self) -> str:
        """Get environment type label."""
        if self.is_ci:
            return "ci"
        if self.is_containerized:
            return "container"
        return "local"

    def __str__(self) -> str:
        """String representation."""
        return (
            f"EnvironmentInfo(type={self.environment_type}, "
            f"{self.hardware})"
        )


def detect_hardware_profile() -> HardwareProfile:
    """Detect hardware capabilities for test tuning.

    Returns:
        HardwareProfile with CPU, memory, and frequency info
    """
    cpu_count = multiprocessing.cpu_count()
    memory_bytes = psutil.virtual_memory().total
    memory_gb = memory_bytes / (1024**3)

    # Try to get CPU frequency, fall back to estimate if not available
    try:
        cpu_freq = psutil.cpu_freq()
        cpu_freq_mhz = cpu_freq.max if cpu_freq else 2000.0
    except (AttributeError, NotImplementedError):
        # Some systems don't support cpu_freq()
        cpu_freq_mhz = 2000.0  # Reasonable default

    return HardwareProfile(
        cpu_count=cpu_count,
        memory_gb=memory_gb,
        cpu_freq_mhz=cpu_freq_mhz,
    )


def is_ci_environment() -> bool:
    """Detect if running in CI/CD environment.

    Returns:
        True if running in CI/CD, False otherwise
    """
    ci_indicators = [
        os.getenv("CI") == "true",
        os.getenv("GITHUB_ACTIONS") == "true",
        os.getenv("GITLAB_CI") == "true",
        os.getenv("CIRCLECI") == "true",
        os.getenv("TRAVIS") == "true",
        os.getenv("JENKINS_URL") is not None,
        os.getenv("BUILDKITE") == "true",
    ]

    return any(ci_indicators)


def is_containerized() -> bool:
    """Detect if running in a container (Docker, Podman, etc.).

    Returns:
        True if running in container, False otherwise
    """
    # Check for .dockerenv file
    if os.path.exists("/.dockerenv"):
        return True

    # Check cgroup for docker/podman
    try:
        with open("/proc/1/cgroup") as f:
            content = f.read()
            if "docker" in content or "podman" in content:
                return True
    except (FileNotFoundError, PermissionError):
        pass

    # Check for Kubernetes
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        return True

    return False


def get_platform() -> str:
    """Get platform name.

    Returns:
        Platform string (linux, darwin, windows, etc.)
    """
    import sys

    return sys.platform


def detect_environment() -> EnvironmentInfo:
    """Detect complete environment information.

    Returns:
        EnvironmentInfo with all detected information
    """
    hardware = detect_hardware_profile()
    is_ci = is_ci_environment()
    is_container = is_containerized()
    platform = get_platform()

    return EnvironmentInfo(
        hardware=hardware,
        is_ci=is_ci,
        is_containerized=is_container,
        platform=platform,
    )


def get_load_multiplier(
    hardware: Optional[HardwareProfile] = None,
) -> float:
    """Calculate load multiplier based on hardware.

    The multiplier scales concurrent operations based on available resources.
    Baseline is 4 CPUs with 8GB RAM.

    Args:
        hardware: Hardware profile (auto-detected if None)

    Returns:
        Multiplier for scaling concurrent operations (typically 0.5 to 4.0)

    Examples:
        >>> # Low-end: 2 CPUs, 4GB = 0.5x
        >>> # Baseline: 4 CPUs, 8GB = 1.0x
        >>> # High-end: 16 CPUs, 32GB = 4.0x
    """
    if hardware is None:
        hardware = detect_hardware_profile()

    # Baseline: 4 CPUs, 8GB RAM
    baseline_cpus = 4
    baseline_memory = 8

    cpu_multiplier = hardware.cpu_count / baseline_cpus
    memory_multiplier = hardware.memory_gb / baseline_memory

    # Use the higher multiplier to stress the system
    multiplier = max(cpu_multiplier, memory_multiplier)

    # Clamp between 0.5x and 4.0x
    return max(0.5, min(4.0, multiplier))


if __name__ == "__main__":
    """CLI tool to display environment information."""
    env = detect_environment()
    multiplier = get_load_multiplier(env.hardware)

    print("=" * 80)
    print("CHAOS TEST ENVIRONMENT DETECTION")
    print("=" * 80)
    print()
    print(f"Environment Type: {env.environment_type.upper()}")
    print(f"Platform:         {env.platform}")
    print(f"CI/CD:            {env.is_ci}")
    print(f"Containerized:    {env.is_containerized}")
    print()
    print("Hardware Profile:")
    print(f"  CPUs:           {env.hardware.cpu_count}")
    print(f"  Memory:         {env.hardware.memory_gb:.1f} GB")
    print(f"  CPU Frequency:  {env.hardware.cpu_freq_mhz:.0f} MHz")
    print(f"  Profile:        {env.hardware.profile_name.upper()}")
    print()
    print(f"Load Multiplier:  {multiplier:.2f}x")
    print()
    print("This will be used to scale concurrent operations in chaos tests.")
    print("=" * 80)
