"""One canonical convention for invoking a field resolver.

Both ``@field`` and ``@authorize_field`` wrap field methods, and historically each decided
*how* to call what it wrapped independently — duplicated, and subtly disagreeing. That
disagreement is the field-authorization signature-adaptation bug: an outer decorator would
call an inner wrapper with the wrong number of arguments.

This module is the single source of truth. :func:`resolver_call_spec` inspects a target
*once*; :func:`invoke_resolver` calls it with the arguments its real signature expects.
Kept dependency-light on purpose (only :mod:`inspect`/:mod:`functools`) so the decorator and
security layers can both depend on it without import cycles.

Detection rules, in priority order:

1. ``__fraiseql_field__`` — the target is an already-normalized ``@field`` wrapper that
   self-adapts; call it ``target(root, info, *args, **kwargs)``. This rule is what makes the
   two decorator orders behave identically.
2. bound method (``__self__``) — ``self`` is already bound; pass ``info`` only if declared.
3. otherwise inspect the target's *own* parameters: a leading ``self`` takes ``root``; an
   ``info`` parameter takes ``info``.

The target is **always inspected itself** — never via ``__fraiseql_original_func__``.
Falling back to the original function's arity would re-derive a ``self``-only shape for a
wrapper whose real interface is ``(root, info, *args, **kwargs)``, re-introducing the very
"missing ``info``" bug this convention removes. Any wrapper that genuinely self-adapts
already carries ``__fraiseql_field__`` and is caught by rule 1.
"""

from __future__ import annotations

import functools
import inspect
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Callable


class CallSpec(NamedTuple):
    """How a resolver target wants to be called (computed once, then dispatched)."""

    is_field_wrapper: bool
    is_bound: bool
    has_self: bool
    expects_info: bool


def _compute_call_spec(target: Callable[..., Any]) -> CallSpec:
    if getattr(target, "__fraiseql_field__", False):
        return CallSpec(is_field_wrapper=True, is_bound=False, has_self=False, expects_info=False)

    is_bound = hasattr(target, "__self__")
    try:
        params = list(inspect.signature(target).parameters.keys())
    except (TypeError, ValueError):
        params = []
    return CallSpec(
        is_field_wrapper=False,
        is_bound=is_bound,
        has_self="self" in params,
        expects_info="info" in params,
    )


@functools.lru_cache(maxsize=1024)
def _cached_call_spec(target: Callable[..., Any]) -> CallSpec:
    return _compute_call_spec(target)


def resolver_call_spec(target: Callable[..., Any]) -> CallSpec:
    """Return how ``target`` should be called, memoized on the (stable) target identity.

    Resolvers are decorated once and called many times, so the inspection is cached. An
    unhashable target falls back to recomputing each call instead of raising.
    """
    try:
        return _cached_call_spec(target)
    except TypeError:
        return _compute_call_spec(target)


def invoke_resolver(
    target: Callable[..., Any],
    root: Any,
    info: Any,
    /,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Call ``target`` with the arguments its real signature expects.

    Returns the target's result directly — a coroutine if the target is async (the caller
    awaits it), a plain value otherwise. Argument adaptation only; the permission-check
    contract lives in the security layer and is untouched here.
    """
    spec = resolver_call_spec(target)
    if spec.is_field_wrapper:
        return target(root, info, *args, **kwargs)
    if spec.is_bound:
        if spec.expects_info:
            return target(info, *args, **kwargs)
        return target(*args, **kwargs)
    if spec.has_self:
        if spec.expects_info:
            return target(root, info, *args, **kwargs)
        return target(root, *args, **kwargs)
    return target(root, info, *args, **kwargs)
