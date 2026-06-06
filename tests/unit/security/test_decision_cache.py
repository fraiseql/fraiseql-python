"""Decision cache primitive: key construction, TTL expiry, LRU eviction (issue #367).

Headless unit tests for :class:`DecisionCache` / :class:`AuthorizationCacheConfig` with an
injected monotonic clock. The end-to-end behavioral spec (counting authorizer invocations
through ``enforce_operation_value``) lives in ``test_decision_cache_paths.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from graphql import GraphQLError

from fraiseql.security.authorization import AuthorizationDecision, enforce_operation_value
from fraiseql.security.decision_cache import AuthorizationCacheConfig, DecisionCache

pytestmark = pytest.mark.unit


class _Clock:
    """Manually advanced monotonic clock for deterministic TTL tests."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _by_user(ctx: dict[str, Any]) -> Any:
    user = ctx.get("user")
    return user.get("id") if user else None


def _cache(*, ttl: float = 5.0, max_entries: int = 10_000, clock: Any = None) -> DecisionCache:
    config = AuthorizationCacheConfig(
        principal_key=_by_user,
        ttl_seconds=ttl,
        max_entries=max_entries,
        clock=clock or _Clock(),
    )
    return DecisionCache(config)


_CTX = {"user": {"id": "u1"}}


# --- make_key -------------------------------------------------------------------------


def test_make_key_none_when_principal_is_none() -> None:
    """An anonymous/unknown principal is never cached (no cross-principal sharing)."""
    cache = _cache()
    assert cache.make_key({"user": None}, "query", "users", {}) is None


def test_make_key_none_when_arguments_not_json_serializable() -> None:
    """Non-JSON-serializable arguments disable caching for that call."""
    cache = _cache()
    assert cache.make_key(_CTX, "query", "users", {"ids": {1, 2, 3}}) is None  # set → not JSON


def test_make_key_stable_across_argument_ordering() -> None:
    """Canonicalization makes dict ordering irrelevant."""
    cache = _cache()
    k1 = cache.make_key(_CTX, "query", "users", {"a": 1, "b": 2})
    k2 = cache.make_key(_CTX, "query", "users", {"b": 2, "a": 1})
    assert k1 == k2 is not None


def test_make_key_differs_by_principal_op_and_arguments() -> None:
    """Each axis of the key separates entries."""
    cache = _cache()
    base = cache.make_key(_CTX, "query", "users", {"x": 1})
    assert base != cache.make_key({"user": {"id": "u2"}}, "query", "users", {"x": 1})
    assert base != cache.make_key(_CTX, "mutation", "users", {"x": 1})
    assert base != cache.make_key(_CTX, "query", "posts", {"x": 1})
    assert base != cache.make_key(_CTX, "query", "users", {"x": 2})


# --- get / put / TTL / LRU ------------------------------------------------------------


def test_get_miss_returns_none() -> None:
    cache = _cache()
    assert cache.get(("u1", "query", "users", "deadbeef")) is None


def test_put_then_get_round_trips_decision() -> None:
    cache = _cache()
    key = cache.make_key(_CTX, "query", "users", {})
    decision = AuthorizationDecision.allow(filters={"tenant_id": "t1"})
    cache.put(key, decision)
    assert cache.get(key) is decision


def test_ttl_expiry_drops_entry() -> None:
    clock = _Clock()
    cache = _cache(ttl=5.0, clock=clock)
    key = cache.make_key(_CTX, "query", "users", {})
    cache.put(key, AuthorizationDecision.allow())
    clock.now += 4.99
    assert cache.get(key) is not None, "still fresh inside the TTL window"
    clock.now += 0.02  # now past the 5s TTL
    assert cache.get(key) is None, "expired entry must miss"
    # And the expired entry is dropped, not merely reported as a miss.
    assert cache.get(key) is None


def test_lru_eviction_past_max_entries() -> None:
    cache = _cache(max_entries=2)
    k1 = cache.make_key(_CTX, "query", "a", {})
    k2 = cache.make_key(_CTX, "query", "b", {})
    k3 = cache.make_key(_CTX, "query", "c", {})
    cache.put(k1, AuthorizationDecision.allow())
    cache.put(k2, AuthorizationDecision.allow())
    cache.put(k3, AuthorizationDecision.allow())  # evicts k1 (least recently used)
    assert cache.get(k1) is None
    assert cache.get(k2) is not None
    assert cache.get(k3) is not None


def test_get_refreshes_lru_recency() -> None:
    """A read marks an entry as recently used, protecting it from the next eviction."""
    cache = _cache(max_entries=2)
    k1 = cache.make_key(_CTX, "query", "a", {})
    k2 = cache.make_key(_CTX, "query", "b", {})
    k3 = cache.make_key(_CTX, "query", "c", {})
    cache.put(k1, AuthorizationDecision.allow())
    cache.put(k2, AuthorizationDecision.allow())
    assert cache.get(k1) is not None  # touch k1 → k2 is now least recently used
    cache.put(k3, AuthorizationDecision.allow())  # evicts k2, not k1
    assert cache.get(k1) is not None
    assert cache.get(k2) is None
    assert cache.get(k3) is not None


# --- behavioral spec through enforce_operation_value (headless, no DB) -----------------


class _CountingAuthorizer:
    """Counts invocations; returns a fixed result (bool or AuthorizationDecision)."""

    def __init__(self, result: Any = True) -> None:
        self.calls = 0
        self._result = result

    async def authorize_operation(self, **_: Any) -> Any:
        self.calls += 1
        return self._result


class _FlakyAuthorizer:
    """Raises on the first call (transient PDP error), allows thereafter."""

    def __init__(self) -> None:
        self.calls = 0

    async def authorize_operation(self, **_: Any) -> bool:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient PDP error")
        return True


async def _enforce(authorizer: Any, cache: Any, *, context: Any = None, arguments: Any = None):
    return await enforce_operation_value(
        authorizer=authorizer,
        context=_CTX if context is None else context,
        operation_type="query",
        operation_name="users",
        arguments={} if arguments is None else arguments,
        cache=cache,
    )


async def test_identical_calls_invoke_authorizer_once() -> None:
    auth = _CountingAuthorizer()
    cache = _cache()
    await _enforce(auth, cache, arguments={"x": 1})
    await _enforce(auth, cache, arguments={"x": 1})
    assert auth.calls == 1, "second identical call should be served from cache"


async def test_different_arguments_invoke_separately() -> None:
    auth = _CountingAuthorizer()
    cache = _cache()
    await _enforce(auth, cache, arguments={"x": 1})
    await _enforce(auth, cache, arguments={"x": 2})
    assert auth.calls == 2


async def test_different_principal_invoke_separately() -> None:
    auth = _CountingAuthorizer()
    cache = _cache()
    await _enforce(auth, cache, context={"user": {"id": "u1"}})
    await _enforce(auth, cache, context={"user": {"id": "u2"}})
    assert auth.calls == 2


async def test_ttl_expiry_reinvokes_authorizer() -> None:
    clock = _Clock()
    auth = _CountingAuthorizer()
    cache = _cache(ttl=5.0, clock=clock)
    await _enforce(auth, cache)
    clock.now += 6.0
    await _enforce(auth, cache)
    assert auth.calls == 2


async def test_raising_authorizer_denied_and_not_cached() -> None:
    """A raising authorizer fails closed and is never cached: the retry can allow."""
    auth = _FlakyAuthorizer()
    cache = _cache()
    with pytest.raises(GraphQLError) as exc:
        await _enforce(auth, cache)
    assert exc.value.extensions["code"] == "FORBIDDEN"
    decision = await _enforce(auth, cache)  # not served from a cached deny
    assert decision.allowed
    assert auth.calls == 2


async def test_deny_decision_served_from_cache() -> None:
    auth = _CountingAuthorizer(result=AuthorizationDecision.deny(code="NO_READS"))
    cache = _cache()
    for _ in range(2):
        with pytest.raises(GraphQLError):
            await _enforce(auth, cache)
    assert auth.calls == 1, "a clean deny decision is cached and re-enforced"


async def test_none_principal_never_cached() -> None:
    auth = _CountingAuthorizer()
    cache = _cache()
    ctx = {"user": None}
    await _enforce(auth, cache, context=ctx)
    await _enforce(auth, cache, context=ctx)
    assert auth.calls == 2


async def test_no_cache_invokes_every_time() -> None:
    """With no cache configured, behavior is exactly today's: evaluate every call."""
    auth = _CountingAuthorizer()
    await _enforce(auth, None)
    await _enforce(auth, None)
    assert auth.calls == 2
