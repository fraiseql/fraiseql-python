"""Field-level authorization accepts the unified decision contract (issue #362, phase 7)."""

from __future__ import annotations

import warnings
from types import SimpleNamespace
from typing import Any

import pytest

from fraiseql.security.authorization import AuthorizationDecision
from fraiseql.security.field_auth import (
    FieldAuthorizationError,
    authorize_field,
    field_authorizer_adapter,
)


def _info(context: dict[str, Any] | None = None, field_name: str = "email") -> Any:
    return SimpleNamespace(context=context if context is not None else {}, field_name=field_name)


async def _resolver(root: Any, info: Any) -> str:
    return "secret"


async def test_decision_deny_surfaces_code_and_message() -> None:
    def check(info: Any) -> AuthorizationDecision:
        return AuthorizationDecision.deny(code="NOPE", message="no field for you")

    wrapped = authorize_field(check)(_resolver)
    with pytest.raises(FieldAuthorizationError) as exc:
        await wrapped(None, _info())
    assert exc.value.message == "no field for you"
    assert exc.value.extensions["code"] == "NOPE"


async def test_decision_allow_resolves_field() -> None:
    def check(info: Any) -> AuthorizationDecision:
        return AuthorizationDecision.allow()

    wrapped = authorize_field(check)(_resolver)
    assert await wrapped(None, _info()) == "secret"


async def test_legacy_bool_true_resolves() -> None:
    wrapped = authorize_field(lambda info: True)(_resolver)
    assert await wrapped(None, _info()) == "secret"


async def test_legacy_bool_false_keeps_field_authorization_error_code() -> None:
    wrapped = authorize_field(lambda info: False)(_resolver)
    with pytest.raises(FieldAuthorizationError) as exc:
        await wrapped(None, _info())
    # Back-compat: a plain bool deny keeps the original code, not "FORBIDDEN".
    assert exc.value.extensions["code"] == "FIELD_AUTHORIZATION_ERROR"


async def test_filters_at_field_granularity_are_ignored_and_warned() -> None:
    def check(info: Any) -> AuthorizationDecision:
        return AuthorizationDecision.allow(filters={"tenant_id": "t1"})

    wrapped = authorize_field(check)(_resolver)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await wrapped(None, _info())
    assert result == "secret"
    assert any("filter" in str(w.message).lower() for w in caught)


async def test_field_authorizer_adapter_delegates_to_operation_authorizer() -> None:
    class DenyAuthorizer:
        async def authorize_operation(
            self,
            *,
            context: dict[str, Any],
            operation_type: str,
            operation_name: str,
            arguments: dict[str, Any],
        ) -> AuthorizationDecision:
            assert operation_type == "field"
            assert operation_name == "email"
            return AuthorizationDecision.deny(code="FIELD_NOPE", message="adapter denied")

    check = field_authorizer_adapter(DenyAuthorizer(), field="email")
    wrapped = authorize_field(check)(_resolver)
    with pytest.raises(FieldAuthorizationError) as exc:
        await wrapped(None, _info())
    assert exc.value.extensions["code"] == "FIELD_NOPE"
    assert exc.value.message == "adapter denied"
