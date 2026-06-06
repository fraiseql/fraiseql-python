"""Optional TTL+LRU memoization of authorization decisions (issue #367).

**Opt-in.** The always-evaluate default is the safe one — a stale *allow* briefly authorizes
a now-revoked principal — so caching is never implicit. The module is kept dependency-light
(no ``graphql`` / ``fastapi`` imports) like :mod:`fraiseql.security.authorization`, so it can
be reused and tested headless.

CORRECTNESS CONTRACT (read before enabling): a cache hit replays a prior decision, so caching
is only correct if the authorizer is a **pure function of the key** — ``(principal_key(context),
operation_type, operation_name, arguments)``. An authorizer that also reads tenant, request IP,
time-of-day, feature flags, or resource state from ``context`` (anything beyond what
``principal_key`` captures) will be served a **wrong** decision on a hit — including a *stale
allow*, the cardinal risk. This is a correctness bug, not merely a TTL staleness window: a
non-pure authorizer is broken under caching regardless of how short the TTL is. Fold the extra
inputs into ``principal_key``, or leave caching off.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Hashable

if TYPE_CHECKING:
    from fraiseql.security.authorization import AuthorizationDecision


@dataclass(frozen=True)
class AuthorizationCacheConfig:
    """Configuration for opt-in authorization decision caching (issue #367).

    Attributes:
        principal_key: Extracts a stable, hashable principal identity from the opaque
            ``context`` dict (e.g. ``lambda ctx: ctx["user"]["id"]``). The framework cannot
            derive this itself — ``context`` is unhashable and request-specific. Return
            ``None`` for an anonymous/unknown principal; such calls are **never cached** (an
            entry must never be shared across unidentified principals).
        ttl_seconds: How long a cached decision stays fresh. Keep it short (e.g. 1-30s): a
            stale *allow* is a security risk, a stale *deny* only an availability nuisance.
        max_entries: LRU bound on the number of cached decisions.
        clock: Monotonic time source, injectable for deterministic tests. Defaults to
            :func:`time.monotonic`; never read wall-clock directly in the cache.

    Enable caching only if your ``Authorizer`` is a **pure function of principal + operation +
    arguments** (see the module docstring's correctness contract); otherwise a cache hit
    returns a wrong decision.
    """

    principal_key: Callable[[dict[str, Any]], Hashable | None]
    ttl_seconds: float = 5.0
    max_entries: int = 10_000
    clock: Callable[[], float] = time.monotonic


def _stable_arguments_hash(arguments: dict[str, Any]) -> str | None:
    """Canonical JSON (``sort_keys=True``) → sha256 hex of ``arguments``.

    Returns ``None`` if ``arguments`` is not JSON-serializable, which disables caching for
    that call (the caller falls through to evaluate). Canonicalization makes dict ordering
    irrelevant so logically identical argument sets key identically.
    """
    try:
        canonical = json.dumps(arguments, sort_keys=True)
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(canonical.encode()).hexdigest()


class DecisionCache:
    """Opt-in TTL+LRU memoization of :class:`AuthorizationDecision`s.

    Not installed by default. The whole (frozen, immutable) decision is cached — including
    row-scoping ``filters``, which are principal- and argument-derived and therefore already
    captured by the key. Denies are cached too (TTL bounds the staleness); only an authorizer
    that *raises* is never cached, so a transient PDP error can neither pin a deny nor leak an
    allow.
    """

    def __init__(self, config: AuthorizationCacheConfig) -> None:
        """Initialize an empty cache governed by ``config``."""
        self._config = config
        # key -> (expires_at, decision). OrderedDict insertion order is the LRU order.
        self._entries: OrderedDict[Hashable, tuple[float, AuthorizationDecision]] = OrderedDict()

    def make_key(
        self,
        context: dict[str, Any],
        operation_type: str,
        operation_name: str,
        arguments: dict[str, Any],
    ) -> Hashable | None:
        """Build the cache key, or ``None`` when the call must not be cached.

        Returns ``None`` if ``principal_key(context)`` is ``None`` (anonymous/unknown — never
        share an entry across unidentified principals) or if ``arguments`` is not
        JSON-serializable. Otherwise returns
        ``(principal, operation_type, operation_name, stable_hash(arguments))``.
        """
        principal = self._config.principal_key(context)
        if principal is None:
            return None
        args_hash = _stable_arguments_hash(arguments)
        if args_hash is None:
            return None
        return (principal, operation_type, operation_name, args_hash)

    def get(self, key: Hashable) -> AuthorizationDecision | None:
        """Return the cached decision for ``key``, or ``None`` on a miss or expiry.

        TTL is checked lazily: an expired entry is dropped and reported as a miss.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, decision = entry
        if self._config.clock() >= expires_at:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return decision

    def put(self, key: Hashable, decision: AuthorizationDecision) -> None:
        """Store ``decision`` under ``key`` with a fresh TTL; evict LRU entries past the bound."""
        self._entries[key] = (self._config.clock() + self._config.ttl_seconds, decision)
        self._entries.move_to_end(key)
        while len(self._entries) > self._config.max_entries:
            self._entries.popitem(last=False)
