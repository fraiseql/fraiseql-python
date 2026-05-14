"""Chaos Engineering Fixtures

This module provides fixtures for chaos engineering tests, particularly
for network chaos injection using Toxiproxy.
"""

from typing import Any, Dict, Optional

import requests


class ToxiproxyManager:
    """Manager for Toxiproxy network chaos injection.

    Supports both real Toxiproxy service and mock mode (when service unavailable).
    """

    def __init__(self, host: str = "localhost", port: int = 8474, mock_mode: bool = None):
        self.base_url = f"http://{host}:{port}"
        self.proxies: Dict[str, Dict[str, Any]] = {}
        self.toxics: Dict[str, Dict[str, Any]] = {}

        # Auto-detect mock mode if not specified
        if mock_mode is None:
            self.mock_mode = not self._can_connect()
        else:
            self.mock_mode = mock_mode

    def _can_connect(self) -> bool:
        """Check if we can connect to Toxiproxy."""
        try:
            response = requests.get(f"{self.base_url}/version", timeout=1)
            return response.status_code == 200
        except:
            return False

    def create_proxy(self, name: str, listen_addr: str, upstream_addr: str) -> Dict[str, Any]:
        """Create a new Toxiproxy proxy.

        Args:
            name: Proxy name
            listen_addr: Address to listen on (e.g., "0.0.0.0:5432")
            upstream_addr: Upstream address to proxy to (e.g., "postgres:5432")

        Returns:
            Proxy configuration
        """
        if self.mock_mode:
            # Return mock proxy config
            proxy = {
                "name": name,
                "listen": listen_addr,
                "upstream": upstream_addr,
                "enabled": True,
                "toxics": []
            }
            self.proxies[name] = proxy
            return proxy

        payload = {"name": name, "listen": listen_addr, "upstream": upstream_addr}
        try:
            response = requests.post(f"{self.base_url}/proxies", json=payload, timeout=2)
            response.raise_for_status()
            proxy = response.json()
        except Exception:
            # Fallback to mock mode
            proxy = {
                "name": name,
                "listen": listen_addr,
                "upstream": upstream_addr,
                "enabled": True,
                "toxics": []
            }
            self.mock_mode = True

        self.proxies[name] = proxy
        return proxy

    def delete_proxy(self, name: str):
        """Delete a Toxiproxy proxy."""
        if self.mock_mode:
            self.proxies.pop(name, None)
            self.toxics.pop(name, None)
            return

        try:
            response = requests.delete(f"{self.base_url}/proxies/{name}", timeout=2)
            if response.status_code == 200:
                self.proxies.pop(name, None)
                self.toxics.pop(name, None)
        except:
            # Silently fail if not in real mode
            self.proxies.pop(name, None)
            self.toxics.pop(name, None)

    def list_proxies(self) -> Dict[str, Any]:
        """List all Toxiproxy proxies."""
        if self.mock_mode:
            return self.proxies

        try:
            response = requests.get(f"{self.base_url}/proxies", timeout=2)
            response.raise_for_status()
            return response.json()
        except:
            return self.proxies

    def get_proxy(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a specific proxy configuration."""
        if self.mock_mode:
            return self.proxies.get(name)

        try:
            response = requests.get(f"{self.base_url}/proxies/{name}", timeout=2)
            if response.status_code == 200:
                return response.json()
        except:
            pass

        return self.proxies.get(name)

    def enable_proxy(self, name: str):
        """Enable a proxy (remove all toxics)."""
        if self.mock_mode:
            if name in self.proxies:
                self.proxies[name]["toxics"] = []
                self.toxics.pop(name, None)
            return

        try:
            response = requests.post(f"{self.base_url}/proxies/{name}/toxics", json=[], timeout=2)
            response.raise_for_status()
        except:
            # Fallback to mock mode
            self.mock_mode = True
            if name in self.proxies:
                self.proxies[name]["toxics"] = []
                self.toxics.pop(name, None)

    def disable_proxy(self, name: str):
        """Disable a proxy completely."""
        if self.mock_mode:
            if name in self.proxies:
                self.proxies[name]["enabled"] = False
            return

        try:
            payload = {"upstream": "127.0.0.1:0"}
            response = requests.post(f"{self.base_url}/proxies/{name}", json=payload, timeout=2)
            response.raise_for_status()
        except:
            # Fallback to mock mode
            self.mock_mode = True
            if name in self.proxies:
                self.proxies[name]["enabled"] = False

    def add_latency_toxic(
        self, proxy_name: str, latency_ms: int, jitter_ms: int = 0
    ) -> Dict[str, Any]:
        """Add latency toxic to a proxy.

        Args:
            proxy_name: Name of the proxy
            latency_ms: Base latency in milliseconds
            jitter_ms: Jitter variation in milliseconds

        Returns:
            Toxic configuration
        """
        toxic = {
            "name": "latency",
            "type": "latency",
            "attributes": {"latency": latency_ms, "jitter": jitter_ms},
            "stream": "upstream",
            "toxicity": 1.0,
        }

        if self.mock_mode:
            if proxy_name not in self.toxics:
                self.toxics[proxy_name] = []
            self.toxics[proxy_name].append(toxic)
            if proxy_name in self.proxies:
                self.proxies[proxy_name]["toxics"] = self.toxics[proxy_name]
            return toxic

        try:
            response = requests.post(f"{self.base_url}/proxies/{proxy_name}/toxics", json=toxic, timeout=2)
            response.raise_for_status()
            return response.json()
        except:
            self.mock_mode = True
            if proxy_name not in self.toxics:
                self.toxics[proxy_name] = []
            self.toxics[proxy_name].append(toxic)
            if proxy_name in self.proxies:
                self.proxies[proxy_name]["toxics"] = self.toxics[proxy_name]
            return toxic

    def add_packet_loss_toxic(self, proxy_name: str, loss_percent: float) -> Dict[str, Any]:
        """Add packet loss toxic to a proxy.

        Args:
            proxy_name: Name of the proxy
            loss_percent: Percentage of packets to drop (0.0-1.0)

        Returns:
            Toxic configuration
        """
        toxic = {
            "name": "packet_loss",
            "type": "timeout",
            "attributes": {
                "timeout": 1  # Very short timeout to simulate packet loss
            },
            "stream": "upstream",
            "toxicity": loss_percent,
        }

        if self.mock_mode:
            if proxy_name not in self.toxics:
                self.toxics[proxy_name] = []
            self.toxics[proxy_name].append(toxic)
            if proxy_name in self.proxies:
                self.proxies[proxy_name]["toxics"] = self.toxics[proxy_name]
            return toxic

        try:
            response = requests.post(f"{self.base_url}/proxies/{proxy_name}/toxics", json=toxic, timeout=2)
            response.raise_for_status()
            return response.json()
        except:
            self.mock_mode = True
            if proxy_name not in self.toxics:
                self.toxics[proxy_name] = []
            self.toxics[proxy_name].append(toxic)
            if proxy_name in self.proxies:
                self.proxies[proxy_name]["toxics"] = self.toxics[proxy_name]
            return toxic

    def add_bandwidth_limit_toxic(self, proxy_name: str, rate_kbps: int) -> Dict[str, Any]:
        """Add bandwidth limit toxic to a proxy.

        Args:
            proxy_name: Name of the proxy
            rate_kbps: Bandwidth limit in kbps

        Returns:
            Toxic configuration
        """
        toxic = {
            "name": "bandwidth_limit",
            "type": "bandwidth",
            "attributes": {"rate": rate_kbps},
            "stream": "upstream",
            "toxicity": 1.0,
        }

        if self.mock_mode:
            if proxy_name not in self.toxics:
                self.toxics[proxy_name] = []
            self.toxics[proxy_name].append(toxic)
            if proxy_name in self.proxies:
                self.proxies[proxy_name]["toxics"] = self.toxics[proxy_name]
            return toxic

        try:
            response = requests.post(f"{self.base_url}/proxies/{proxy_name}/toxics", json=toxic, timeout=2)
            response.raise_for_status()
            return response.json()
        except:
            self.mock_mode = True
            if proxy_name not in self.toxics:
                self.toxics[proxy_name] = []
            self.toxics[proxy_name].append(toxic)
            if proxy_name in self.proxies:
                self.proxies[proxy_name]["toxics"] = self.toxics[proxy_name]
            return toxic

    def remove_all_toxics(self, proxy_name: str):
        """Remove all toxics from a proxy."""
        if self.mock_mode:
            self.toxics.pop(proxy_name, None)
            if proxy_name in self.proxies:
                self.proxies[proxy_name]["toxics"] = []
            return

        try:
            response = requests.delete(f"{self.base_url}/proxies/{proxy_name}/toxics", timeout=2)
            response.raise_for_status()
        except:
            self.mock_mode = True
            self.toxics.pop(proxy_name, None)
            if proxy_name in self.proxies:
                self.proxies[proxy_name]["toxics"] = []

    def reset_proxy(self, proxy_name: str):
        """Reset a proxy to normal operation."""
        self.remove_all_toxics(proxy_name)
        self.enable_proxy(proxy_name)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - clean up all proxies."""
        for proxy_name in list(self.proxies.keys()):
            try:
                self.reset_proxy(proxy_name)
                self.delete_proxy(proxy_name)
            except:
                pass  # Ignore cleanup errors


# Convenience fixtures for common chaos scenarios


def chaos_database_latency(toxiproxy: ToxiproxyManager):
    """Fixture for database latency chaos."""
    proxy_name = "postgres_chaos"
    toxiproxy.create_proxy(proxy_name, "0.0.0.0:5432", "postgres:5432")
    return lambda latency_ms: toxiproxy.add_latency_toxic(proxy_name, latency_ms)


def chaos_packet_loss(toxiproxy: ToxiproxyManager):
    """Fixture for packet loss chaos."""
    proxy_name = "postgres_chaos"
    toxiproxy.create_proxy(proxy_name, "0.0.0.0:5432", "postgres:5432")
    return lambda loss_percent: toxiproxy.add_packet_loss_toxic(proxy_name, loss_percent)


def chaos_slow_database(toxiproxy: ToxiproxyManager):
    """Fixture for slow database operations."""
    proxy_name = "postgres_chaos"
    toxiproxy.create_proxy(proxy_name, "0.0.0.0:5432", "postgres:5432")
    return lambda delay_ms: toxiproxy.add_latency_toxic(
        proxy_name, delay_ms, jitter_ms=delay_ms // 4
    )
