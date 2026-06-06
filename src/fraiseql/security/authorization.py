"""First-class operation authorization contract for FraiseQL (issue #362).

This module defines the supported Policy Enforcement Point (PEP) for
operation-level authorization. The framework *enforces*; the *decision* is
delegated to an app-supplied :class:`Authorizer`, which reads everything it
needs from ``context`` (populated by the app's ``context_getter``) and is
therefore principal-agnostic.

The contract deliberately mirrors the v2 (Rust) counterpart so a single policy
implementation can serve both runtimes. The module is kept dependency-light (no
``graphql`` / ``fastapi`` imports at top level) so it can be reused by
v2-aligned tooling and tested headless.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo

    from fraiseql.gql.builders.registry import SchemaRegistry

logger = logging.getLogger(__name__)

OperationType = str  # "query" | "mutation" (| "subscription" later)

# Shared defaults so every enforcement site denies with the same shape.
DEFAULT_DENY_CODE = "FORBIDDEN"
DEFAULT_DENY_MESSAGE = "Operation not authorized"


@dataclass(frozen=True)
class AuthorizationDecision:
    """The result of an authorization check.

    Decisions are immutable values. ``filters`` are row-scoping filters that are
    AND-ed into the repository's ``mandatory_filters`` on the read path (see the
    filter-injection mechanism); they are ignored on mutations and bypass paths.
    """

    allowed: bool
    code: str | None = None
    message: str | None = None
    filters: dict[str, Any] | None = None

    @classmethod
    def allow(cls, *, filters: dict[str, Any] | None = None) -> AuthorizationDecision:
        """Return an allow decision, optionally carrying row-scoping filters."""
        return cls(allowed=True, filters=filters)

    @classmethod
    def deny(
        cls,
        *,
        code: str = DEFAULT_DENY_CODE,
        message: str | None = None,
    ) -> AuthorizationDecision:
        """Return a deny decision with a stable ``code`` surfaced as a GraphQL extension."""
        return cls(allowed=False, code=code, message=message)


@runtime_checkable
class Authorizer(Protocol):
    """Structural protocol for an operation authorizer.

    Implementations decide whether a top-level GraphQL operation may run. The
    return value may be a plain ``bool`` (sugar) or an :class:`AuthorizationDecision`.
    Implementations may be sync or async; the enforcement layer awaits awaitables.
    """

    async def authorize_operation(
        self,
        *,
        context: dict[str, Any],
        operation_type: OperationType,
        operation_name: str,
        arguments: dict[str, Any],
    ) -> AuthorizationDecision | bool:
        """Decide whether the named operation may run for the given context."""
        ...


def normalize_decision(result: AuthorizationDecision | bool) -> AuthorizationDecision:
    """Coerce an authorizer result into a canonical :class:`AuthorizationDecision`.

    ``True`` -> ``allow()``; ``False`` -> ``deny()``; an existing decision passes
    through unchanged.
    """
    if isinstance(result, AuthorizationDecision):
        return result
    return AuthorizationDecision.allow() if result else AuthorizationDecision.deny()


def resolve_authorizer(fn: Any, registry: SchemaRegistry) -> Authorizer | None:
    """Resolve the effective authorizer: a per-operation override beats the global default.

    The per-operation override is attached by ``@query(authorizer=...)`` /
    ``@mutation(authorizer=...)`` as ``fn.__fraiseql_authorizer__``; it is read
    defensively (the attribute may be absent).
    """
    return getattr(fn, "__fraiseql_authorizer__", None) or registry.default_authorizer


async def enforce_operation_value(
    *,
    authorizer: Authorizer | None,
    context: dict[str, Any],
    operation_type: str,
    operation_name: str,
    arguments: dict[str, Any],
) -> AuthorizationDecision:
    """Run the authorizer and enforce its decision, fail-closed.

    This is the single place the fail-closed semantic lives, so every enforcement
    site — the resolver wrap *and* the three resolver-bypass gates — inherits it:

    - No authorizer configured -> ``allow()`` (no-op fast path).
    - Sync or async authorizer -> awaited as needed.
    - Authorizer raises a ``GraphQLError`` -> propagated unchanged.
    - Authorizer raises anything else -> denied (never falls through to allow); the
      raw exception is logged but never surfaced to the client.
    - Deny -> ``GraphQLError`` carrying ``extensions={"code": ...}``.

    Returns the (allow) decision so callers can read ``decision.filters``.
    """
    if authorizer is None:
        return AuthorizationDecision.allow()

    from graphql import GraphQLError

    try:
        raw = authorizer.authorize_operation(
            context=context,
            operation_type=operation_type,
            operation_name=operation_name,
            arguments=arguments,
        )
        raw = await raw if inspect.isawaitable(raw) else raw
        decision = normalize_decision(raw)
    except GraphQLError:
        raise
    except Exception as exc:  # FAIL CLOSED: any error denies, never allows.
        logger.warning("authorizer raised; denying operation", exc_info=exc)
        decision = AuthorizationDecision.deny(code=DEFAULT_DENY_CODE)

    if not decision.allowed:
        raise GraphQLError(
            decision.message or DEFAULT_DENY_MESSAGE,
            extensions={"code": decision.code or DEFAULT_DENY_CODE},
        )
    return decision


async def enforce_operation(
    *,
    info: GraphQLResolveInfo,
    operation_type: str,
    operation_name: str,
    arguments: dict[str, Any],
    authorizer: Authorizer | None,
) -> AuthorizationDecision:
    """Resolver-side wrapper around :func:`enforce_operation_value`.

    Reads ``context`` from the GraphQL resolve info; otherwise identical semantics
    (including fail-closed). Returns the decision.
    """
    context = getattr(info, "context", None) or {}
    return await enforce_operation_value(
        authorizer=authorizer,
        context=context,
        operation_type=operation_type,
        operation_name=operation_name,
        arguments=arguments,
    )


# Callback invoked after enforcement (and before the resolver body) with the decision,
# used by the query builder to inject filters and by the mutation builder to warn on
# meaningless filters. Signature: (decision, root, info, kwargs) -> None.
OnDecision = Callable[[AuthorizationDecision, Any, "GraphQLResolveInfo", dict[str, Any]], None]


async def enforce_around_async(
    coerced_fn: Callable[..., Any],
    root: Any,
    info: GraphQLResolveInfo,
    kwargs: dict[str, Any],
    *,
    fn: Any,
    registry: SchemaRegistry,
    operation_type: str,
    on_decision: OnDecision | None = None,
) -> Any:
    """Enforce, then run an async resolver body. Shared by the query and mutation builders."""
    authorizer = resolve_authorizer(fn, registry)
    decision = await enforce_operation(
        info=info,
        operation_type=operation_type,
        operation_name=getattr(info, "field_name", ""),
        arguments=kwargs,
        authorizer=authorizer,
    )
    if on_decision is not None:
        on_decision(decision, root, info, kwargs)
    return await coerced_fn(root, info, **kwargs)


def enforce_around_sync(
    coerced_fn: Callable[..., Any],
    root: Any,
    info: GraphQLResolveInfo,
    kwargs: dict[str, Any],
    *,
    fn: Any,
    registry: SchemaRegistry,
    operation_type: str,
    on_decision: OnDecision | None = None,
) -> Any:
    """Enforce around a sync resolver body, shared by the query and mutation builders.

    When no authorizer is in effect (resolved live), the pure-sync path is left
    untouched. When an authorizer is in effect, a coroutine is returned that awaits
    enforcement before running the sync body — graphql-core awaits returned coroutines.
    """
    authorizer = resolve_authorizer(fn, registry)
    if authorizer is None:
        if on_decision is not None:
            on_decision(AuthorizationDecision.allow(), root, info, kwargs)
        return coerced_fn(root, info, **kwargs)

    async def _run() -> Any:
        decision = await enforce_operation(
            info=info,
            operation_type=operation_type,
            operation_name=getattr(info, "field_name", ""),
            arguments=kwargs,
            authorizer=authorizer,
        )
        if on_decision is not None:
            on_decision(decision, root, info, kwargs)
        result = coerced_fn(root, info, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    return _run()
