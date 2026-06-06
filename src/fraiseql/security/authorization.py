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

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

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
