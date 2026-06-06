"""TurboRouter bypass-path authorization gate (issue #362, phase 4 part A)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from graphql import GraphQLError

from fraiseql.fastapi.turbo import TurboQuery, TurboRegistry, TurboRouter
from fraiseql.fastapi.turbo_enhanced import EnhancedTurboRegistry, EnhancedTurboRouter

_QUERY = "query { widgets { id } }"


class _SpyDB:
    """Repository stand-in that records transaction execution."""

    def __init__(self) -> None:
        self.context: dict[str, Any] = {}
        self.tx_calls = 0

    async def run_in_transaction(self, fn: Any) -> list[dict[str, Any]]:
        self.tx_calls += 1
        return [{"result": [{"id": 1}]}]

    async def _set_session_variables(self, cursor: Any) -> None:
        return None


class DenyAll:
    async def authorize_operation(self, **_: Any) -> bool:
        return False


class AllowAll:
    async def authorize_operation(self, **_: Any) -> bool:
        return True


class Boom:
    async def authorize_operation(self, **_: Any) -> bool:
        raise RuntimeError("kaboom")


def _registry() -> TurboRegistry:
    registry = TurboRegistry()
    registry.register(
        TurboQuery(graphql_query=_QUERY, sql_template="SELECT 1 AS result", param_mapping={})
    )
    return registry


def _enhanced_registry() -> EnhancedTurboRegistry:
    registry = EnhancedTurboRegistry()
    registry.register(
        TurboQuery(graphql_query=_QUERY, sql_template="SELECT 1 AS result", param_mapping={})
    )
    return registry


async def test_deny_all_blocks_turbo_no_db_hit() -> None:
    spy = _SpyDB()
    router = TurboRouter(_registry(), default_authorizer=DenyAll())
    with pytest.raises(GraphQLError) as exc:
        await router.execute(_QUERY, {}, {"db": spy})
    assert exc.value.extensions["code"] == "FORBIDDEN"
    assert spy.tx_calls == 0


async def test_allow_all_executes_turbo() -> None:
    spy = _SpyDB()
    router = TurboRouter(_registry(), default_authorizer=AllowAll())
    await router.execute(_QUERY, {}, {"db": spy})
    assert spy.tx_calls == 1


async def test_no_authorizer_keeps_today_behavior() -> None:
    spy = _SpyDB()
    router = TurboRouter(_registry())
    await router.execute(_QUERY, {}, {"db": spy})
    assert spy.tx_calls == 1


async def test_authorizer_raising_fails_closed() -> None:
    spy = _SpyDB()
    router = TurboRouter(_registry(), default_authorizer=Boom())
    with pytest.raises(GraphQLError) as exc:
        await router.execute(_QUERY, {}, {"db": spy})
    assert exc.value.extensions["code"] == "FORBIDDEN"
    assert spy.tx_calls == 0


async def test_unregistered_query_falls_through() -> None:
    spy = _SpyDB()
    router = TurboRouter(_registry(), default_authorizer=DenyAll())
    # Not a turbo query -> returns None (falls through to the resolver-gated path),
    # the gate must not fire here.
    result = await router.execute("{ other { id } }", {}, {"db": spy})
    assert result is None
    assert spy.tx_calls == 0


async def test_enhanced_turbo_inherits_gate() -> None:
    spy = _SpyDB()
    router = EnhancedTurboRouter(_enhanced_registry(), default_authorizer=DenyAll())
    with pytest.raises(GraphQLError) as exc:
        await router.execute(_QUERY, {}, {"db": spy})
    assert exc.value.extensions["code"] == "FORBIDDEN"
    assert spy.tx_calls == 0


async def test_filters_on_turbo_warn_and_do_not_scope(caplog) -> None:
    class AllowWithFilters:
        async def authorize_operation(self, **_: Any) -> Any:
            from fraiseql.security.authorization import AuthorizationDecision

            return AuthorizationDecision.allow(filters={"tenant_id": "t1"})

    spy = _SpyDB()
    router = TurboRouter(_registry(), default_authorizer=AllowWithFilters())
    with caplog.at_level(logging.WARNING):
        await router.execute(_QUERY, {}, {"db": spy})
    assert spy.tx_calls == 1
    assert any("filter" in record.message.lower() for record in caplog.records)
