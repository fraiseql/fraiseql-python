"""Tests for the fail-closed operation-enforcement helper (issue #362, phase 2)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from graphql import GraphQLError

from fraiseql.security.authorization import (
    AuthorizationDecision,
    enforce_operation,
    resolve_authorizer,
)


def _info(context: dict[str, Any] | None = None, field_name: str = "op") -> Any:
    return SimpleNamespace(context=context if context is not None else {}, field_name=field_name)


async def test_no_authorizer_returns_allow() -> None:
    decision = await enforce_operation(
        info=_info(),
        operation_type="query",
        operation_name="q",
        arguments={},
        authorizer=None,
    )
    assert decision.allowed is True


async def test_allow_decision_is_returned_with_filters() -> None:
    class AllowWithFilters:
        async def authorize_operation(self, **_: Any) -> AuthorizationDecision:
            return AuthorizationDecision.allow(filters={"tenant_id": "t1"})

    decision = await enforce_operation(
        info=_info(),
        operation_type="query",
        operation_name="q",
        arguments={},
        authorizer=AllowWithFilters(),
    )
    assert decision.allowed is True
    assert decision.filters == {"tenant_id": "t1"}


async def test_deny_decision_raises_with_code_and_message() -> None:
    class Deny:
        async def authorize_operation(self, **_: Any) -> AuthorizationDecision:
            return AuthorizationDecision.deny(code="NOPE", message="go away")

    with pytest.raises(GraphQLError) as exc:
        await enforce_operation(
            info=_info(),
            operation_type="mutation",
            operation_name="m",
            arguments={},
            authorizer=Deny(),
        )
    assert exc.value.extensions["code"] == "NOPE"
    assert exc.value.message == "go away"


async def test_sync_bool_authorizer_accepted() -> None:
    class SyncDeny:
        def authorize_operation(self, **_: Any) -> bool:
            return False

    with pytest.raises(GraphQLError) as exc:
        await enforce_operation(
            info=_info(),
            operation_type="query",
            operation_name="q",
            arguments={},
            authorizer=SyncDeny(),
        )
    assert exc.value.extensions["code"] == "FORBIDDEN"


async def test_async_bool_authorizer_allow() -> None:
    class AsyncAllow:
        async def authorize_operation(self, **_: Any) -> bool:
            return True

    decision = await enforce_operation(
        info=_info(),
        operation_type="query",
        operation_name="q",
        arguments={},
        authorizer=AsyncAllow(),
    )
    assert decision.allowed is True


async def test_arguments_and_context_forwarded_verbatim() -> None:
    captured: dict[str, Any] = {}

    class Spy:
        async def authorize_operation(
            self,
            *,
            context: dict[str, Any],
            operation_type: str,
            operation_name: str,
            arguments: dict[str, Any],
        ) -> bool:
            captured.update(
                context=context,
                operation_type=operation_type,
                operation_name=operation_name,
                arguments=arguments,
            )
            return True

    await enforce_operation(
        info=_info(context={"user": "alice"}),
        operation_type="mutation",
        operation_name="createWidget",
        arguments={"name": "x"},
        authorizer=Spy(),
    )
    assert captured["context"] == {"user": "alice"}
    assert captured["operation_type"] == "mutation"
    assert captured["operation_name"] == "createWidget"
    assert captured["arguments"] == {"name": "x"}


async def test_authorizer_raising_denies_fail_closed() -> None:
    class Boom:
        async def authorize_operation(self, **_: Any) -> bool:
            raise RuntimeError("internal secret detail")

    with pytest.raises(GraphQLError) as exc:
        await enforce_operation(
            info=_info(),
            operation_type="query",
            operation_name="q",
            arguments={},
            authorizer=Boom(),
        )
    assert exc.value.extensions["code"] == "FORBIDDEN"
    # No internal leakage of the raw exception text.
    assert "internal secret detail" not in (exc.value.message or "")
    assert "internal secret detail" not in str(exc.value.extensions)


async def test_authorizer_raising_graphqlerror_propagates() -> None:
    class CustomError:
        async def authorize_operation(self, **_: Any) -> bool:
            raise GraphQLError("custom", extensions={"code": "CUSTOM"})

    with pytest.raises(GraphQLError) as exc:
        await enforce_operation(
            info=_info(),
            operation_type="query",
            operation_name="q",
            arguments={},
            authorizer=CustomError(),
        )
    assert exc.value.extensions["code"] == "CUSTOM"
    assert exc.value.message == "custom"


def test_resolve_authorizer_prefers_per_operation_attribute() -> None:
    registry = SimpleNamespace(default_authorizer="GLOBAL")

    def fn() -> None: ...

    assert resolve_authorizer(fn, registry) == "GLOBAL"

    fn.__fraiseql_authorizer__ = "PER_OP"
    assert resolve_authorizer(fn, registry) == "PER_OP"


def test_resolve_authorizer_falls_back_to_default() -> None:
    registry = SimpleNamespace(default_authorizer="GLOBAL")

    def fn() -> None: ...

    assert resolve_authorizer(fn, registry) == "GLOBAL"
