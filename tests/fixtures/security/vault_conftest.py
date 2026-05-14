"""Vault integration test fixtures using testcontainers.

Provides automatic Vault container management for integration tests.
Tests automatically skip if Docker is unavailable.
"""

from collections.abc import Generator

import httpx
import pytest

try:
    from testcontainers.vault import VaultContainer

    HAS_VAULT_CONTAINER = True
except ImportError:
    HAS_VAULT_CONTAINER = False
    VaultContainer = None  # type: ignore[assignment, misc]


@pytest.fixture(scope="session")
def vault_container() -> Generator[VaultContainer | None]:
    """Start Vault container for testing.

    Scope: session - container is started once per test session
    Skips: Automatically if Docker unavailable or testcontainers not installed

    Yields:
        VaultContainer instance with running Vault server
    """
    if not HAS_VAULT_CONTAINER:
        pytest.skip(
            "Vault testcontainer not available (install with: pip install testcontainers[vault])"
        )

    container = VaultContainer()
    try:
        container.start()
    except TimeoutError:
        pytest.skip("Vault container did not become ready in time")

    yield container

    container.stop()


@pytest.fixture(scope="session")
def vault_token(vault_container: VaultContainer | None) -> str:
    """Get Vault root token.

    Returns:
        Root token for Vault authentication
    """
    if not vault_container:
        pytest.skip("Vault not available")

    return vault_container.root_token


@pytest.fixture(scope="session")
def vault_url(vault_container: VaultContainer | None) -> str:
    """Get Vault HTTP URL.

    Returns:
        HTTP URL for Vault API (e.g., http://localhost:8200)
    """
    if not vault_container:
        pytest.skip("Vault not available")

    return vault_container.get_connection_url()


@pytest.fixture(scope="session")
def vault_transit_ready(vault_url: str, vault_token: str) -> None:
    """Enable Vault transit engine and create test keys.

    This fixture ensures the transit secrets engine is enabled
    and creates keys needed by the tests.
    """
    client = httpx.Client(base_url=vault_url, headers={"X-Vault-Token": vault_token})

    try:
        # Enable transit secrets engine
        response = client.post("/v1/sys/mounts/transit", json={"type": "transit"})
        # 200 = success, 204 = success, 400 = already enabled (ok)
        if response.status_code not in (200, 204, 400):
            response.raise_for_status()

        # Create test keys that will be used by the integration tests
        test_keys = [
            "test-integration-key",
            "test-data-key",
            "test-key-1",
            "test-key-2",
        ]

        for key_name in test_keys:
            # Create key (idempotent - returns 204 even if exists)
            client.post(f"/v1/transit/keys/{key_name}")

    finally:
        client.close()
