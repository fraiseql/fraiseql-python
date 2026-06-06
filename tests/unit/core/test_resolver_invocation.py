"""Unit tests for the shared resolver-invocation convention.

Each target shape must be called with exactly the arguments its real signature declares,
inspecting the target *itself* — never an inner original function. This is the contract both
``@field`` and ``@authorize_field`` rely on to compose in either decorator order.
"""

from __future__ import annotations

from typing import Any

import pytest

from fraiseql.core.resolver_invocation import (
    invoke_resolver,
    resolver_call_spec,
)

_ROOT = object()
_INFO = object()


def test_field_wrapper_is_called_root_info() -> None:
    """A ``__fraiseql_field__`` target self-adapts: always called ``(root, info, ...)``."""
    seen: dict[str, Any] = {}

    def wrapper(root: Any, info: Any, *args: Any, **kwargs: Any) -> str:
        seen["args"] = (root, info, args, kwargs)
        return "ok"

    wrapper.__fraiseql_field__ = True  # type: ignore[attr-defined]

    assert invoke_resolver(wrapper, _ROOT, _INFO, extra=1) == "ok"
    assert seen["args"] == (_ROOT, _INFO, (), {"extra": 1})
    assert resolver_call_spec(wrapper).is_field_wrapper is True


def test_field_wrapper_priority_over_signature() -> None:
    """The field-wrapper rule short-circuits signature inspection entirely.

    A real ``@field`` wrapper always accepts ``(root, info, *args, **kwargs)``, so the
    passthrough is correct. The point here is that ``__fraiseql_field__`` is honoured *before*
    the parameter inspection that would otherwise classify the target as ``self``-only.
    """

    def self_only_looking(self) -> str:  # noqa: N805 - deliberately self-only shape
        return "ok"

    self_only_looking.__fraiseql_field__ = True  # type: ignore[attr-defined]

    spec = resolver_call_spec(self_only_looking)
    assert spec.is_field_wrapper is True
    assert spec.has_self is False  # never inspected — the field-wrapper rule wins first


def test_bound_method_with_info() -> None:
    class Obj:
        def m(self, info: Any) -> Any:
            return ("bound+info", info)

    bound = Obj().m
    assert invoke_resolver(bound, _ROOT, _INFO) == ("bound+info", _INFO)
    spec = resolver_call_spec(bound)
    assert spec.is_bound is True
    assert spec.expects_info is True


def test_bound_method_without_info() -> None:
    class Obj:
        def m(self) -> str:
            return "bound-noinfo"

    bound = Obj().m
    assert invoke_resolver(bound, _ROOT, _INFO) == "bound-noinfo"
    spec = resolver_call_spec(bound)
    assert spec.is_bound is True
    assert spec.expects_info is False


def test_unbound_self_and_info() -> None:
    seen: dict[str, Any] = {}

    def m(self, info: Any) -> str:  # noqa: N805 - unbound method shape
        seen["args"] = (self, info)
        return "self+info"

    assert invoke_resolver(m, _ROOT, _INFO) == "self+info"
    assert seen["args"] == (_ROOT, _INFO)
    spec = resolver_call_spec(m)
    assert spec.has_self is True
    assert spec.expects_info is True


def test_unbound_self_only() -> None:
    seen: dict[str, Any] = {}

    def m(self) -> str:  # noqa: N805 - unbound method shape, no info declared
        seen["args"] = (self,)
        return "self-only"

    assert invoke_resolver(m, _ROOT, _INFO) == "self-only"
    assert seen["args"] == (_ROOT,)  # info is NOT passed to a self-only method
    spec = resolver_call_spec(m)
    assert spec.has_self is True
    assert spec.expects_info is False


def test_regular_root_style_function() -> None:
    seen: dict[str, Any] = {}

    def r(root: Any, info: Any) -> str:
        seen["args"] = (root, info)
        return "root-style"

    assert invoke_resolver(r, _ROOT, _INFO) == "root-style"
    assert seen["args"] == (_ROOT, _INFO)
    spec = resolver_call_spec(r)
    assert spec.has_self is False
    assert spec.expects_info is True


def test_kwargs_are_threaded_through() -> None:
    def m(self, info: Any, *, limit: int = 0) -> int:  # noqa: N805
        return limit

    assert invoke_resolver(m, _ROOT, _INFO, limit=7) == 7


def test_async_target_returns_awaitable() -> None:
    async def m(self, info: Any) -> str:  # noqa: N805
        return "async"

    result = invoke_resolver(m, _ROOT, _INFO)
    import inspect as _inspect

    assert _inspect.isawaitable(result)
    result.close()  # avoid an un-awaited coroutine warning


def test_inspects_target_not_original_func() -> None:
    """A faithful wrapper carrying ``__fraiseql_original_func__`` is still inspected itself.

    Falling back to the original ``(self)``-only arity would call the wrapper as
    ``wrapper(root)`` and drop ``info`` — the exact bug. The wrapper has no
    ``__fraiseql_field__``, so it is inspected by its own ``(root, info, ...)`` signature.
    """
    seen: dict[str, Any] = {}

    def original(self) -> str:  # noqa: N805 - the inner, self-only method
        return "original"

    def faithful_wrapper(root: Any, info: Any, *args: Any, **kwargs: Any) -> str:
        seen["args"] = (root, info)
        return "wrapped"

    faithful_wrapper.__fraiseql_original_func__ = original  # type: ignore[attr-defined]

    assert invoke_resolver(faithful_wrapper, _ROOT, _INFO) == "wrapped"
    assert seen["args"] == (_ROOT, _INFO), "must use the wrapper's own signature, not original's"


@pytest.mark.parametrize("missing", [True, False])
def test_spec_memoization_is_consistent(missing: bool) -> None:
    """Repeated lookups return an equal spec (memoized, but value-stable)."""

    def r(root: Any, info: Any) -> None:
        return None

    first = resolver_call_spec(r)
    second = resolver_call_spec(r)
    assert first == second
