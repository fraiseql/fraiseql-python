"""Client IP resolution for rate limiting, with an explicit list of trusted proxies.

``X-Forwarded-For`` and ``X-Real-IP`` are request headers: any client that reaches
the application directly can set them to anything. A rate limiter keyed on them can
be bypassed by changing the header on every request. So the client IP is the socket
peer (``request.client.host``) unless that peer is a proxy the application was told
to trust.

Two ways to run behind a reverse proxy or load balancer:

1. Let the ASGI server rewrite the peer. uvicorn does this by default for
   ``127.0.0.1`` (``--proxy-headers``) and for the addresses given to
   ``--forwarded-allow-ips`` (or ``FORWARDED_ALLOW_IPS``); ``request.client.host``
   is then already the client, and no FraiseQL setting is needed.
2. Pass ``trusted_proxies`` (addresses or CIDR networks) to the rate limiter. When
   the socket peer is one of them, the client IP is the right-most address in
   ``X-Forwarded-For`` that is not a trusted proxy (each proxy appends the address
   it received the request from, so the addresses left of it may be forged).
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from starlette.requests import HTTPConnection

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network

UNKNOWN_CLIENT = "unknown"


def _strip_port(value: str) -> str:
    """Return the host part of ``host``, ``host:port``, ``[v6]`` or ``[v6]:port``."""
    value = value.strip()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end != -1 else value
    if value.count(":") == 1:  # IPv4 with a port; a bare IPv6 address has several colons
        return value.split(":", 1)[0]
    return value


class TrustedProxies:
    """A set of proxy addresses and networks whose forwarding headers are believed.

    Args:
        proxies: IP addresses or CIDR networks (``"10.0.0.0/8"``), as an iterable or a
            comma-separated string. ``"*"`` is refused: trusting every peer means
            trusting every client's ``X-Forwarded-For``.

    Raises:
        ValueError: If an entry is ``"*"`` or not an IP address or network.
    """

    def __init__(self, proxies: Iterable[str] | str) -> None:
        if isinstance(proxies, str):
            proxies = proxies.split(",")
        self._networks: list[_Network] = []
        for raw in proxies:
            entry = raw.strip()
            if not entry:
                continue
            if entry == "*":
                msg = (
                    "trusted_proxies does not accept '*': it would let any client choose "
                    "its rate-limit key. List the proxy addresses or networks."
                )
                raise ValueError(msg)
            try:
                self._networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError as e:
                msg = f"trusted_proxies entry {entry!r} is not an IP address or network"
                raise ValueError(msg) from e

    def __bool__(self) -> bool:
        return bool(self._networks)

    def __contains__(self, host: object) -> bool:
        if not isinstance(host, str) or not host:
            return False
        try:
            address = ipaddress.ip_address(_strip_port(host))
        except ValueError:
            return False
        return any(address in network for network in self._networks)

    @classmethod
    def coerce(cls, value: TrustedProxies | Iterable[str] | str | None) -> TrustedProxies | None:
        """Build a ``TrustedProxies`` from a setting value; ``None`` or empty gives None."""
        if value is None or isinstance(value, TrustedProxies):
            return value or None
        trusted = cls(value)
        return trusted or None


def get_client_ip(
    request: HTTPConnection,
    trusted_proxies: TrustedProxies | None = None,
) -> str:
    """Return the IP address to rate-limit ``request`` on.

    Without ``trusted_proxies``, or when the socket peer is not a trusted proxy, this
    is the socket peer and forwarding headers are ignored. When the peer is a trusted
    proxy, it is the right-most ``X-Forwarded-For`` address that is not a trusted
    proxy (the left-most one if they all are), else ``X-Real-IP``, else the peer.

    Args:
        request: The incoming request (or WebSocket).
        trusted_proxies: The proxies whose forwarding headers are believed.

    Returns:
        The client IP, or ``"unknown"`` if the server gives no peer address.
    """
    peer = request.client.host if request.client else None
    if not trusted_proxies or peer not in trusted_proxies:
        return peer or UNKNOWN_CLIENT

    forwarded = [
        _strip_port(hop)
        for value in request.headers.getlist("x-forwarded-for")
        for hop in value.split(",")
        if hop.strip()
    ]
    if forwarded:
        for hop in reversed(forwarded):
            if hop not in trusted_proxies:
                return hop
        return forwarded[0]

    real_ip = request.headers.get("x-real-ip", "").strip()
    return real_ip or peer or UNKNOWN_CLIENT
