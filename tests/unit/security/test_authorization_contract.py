"""Contract tests for the operation-authorization primitives (issue #362, phase 1)."""

from __future__ import annotations

from typing import Any

import pytest

from fraiseql.security.authorization import (
    AuthorizationDecision,
    Authorizer,
    normalize_decision,
)


def test_decision_allow_deny_constructors() -> None:
    allow = AuthorizationDecision.allow()
    assert allow.allowed is True
    assert allow.code is None

    deny = AuthorizationDecision.deny()
    assert deny.allowed is False
    assert deny.code == "FORBIDDEN"

    custom = AuthorizationDecision.deny(code="NOPE", message="go away")
    assert custom.code == "NOPE"
    assert custom.message == "go away"


def test_allow_carries_filters() -> None:
    allow = AuthorizationDecision.allow(filters={"tenant_id": "t1"})
    assert allow.allowed is True
    assert allow.filters == {"tenant_id": "t1"}


def test_decision_is_frozen() -> None:
    decision = AuthorizationDecision.allow()
    with pytest.raises((AttributeError, TypeError)):
        decision.allowed = False  # type: ignore[misc]


def test_normalize_bool_true_is_allow() -> None:
    decision = normalize_decision(True)
    assert isinstance(decision, AuthorizationDecision)
    assert decision.allowed is True


def test_normalize_bool_false_is_deny() -> None:
    decision = normalize_decision(False)
    assert decision.allowed is False
    assert decision.code == "FORBIDDEN"


def test_normalize_passthrough_decision() -> None:
    original = AuthorizationDecision.deny(code="X", message="m")
    assert normalize_decision(original) is original


def test_plain_object_with_authorize_operation_is_authorizer() -> None:
    class MyAuth:
        async def authorize_operation(
            self,
            *,
            context: dict[str, Any],
            operation_type: str,
            operation_name: str,
            arguments: dict[str, Any],
        ) -> bool:
            return True

    assert isinstance(MyAuth(), Authorizer)


def test_missing_method_is_not_authorizer() -> None:
    class NotAuth:
        pass

    assert not isinstance(NotAuth(), Authorizer)
