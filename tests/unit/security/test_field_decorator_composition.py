"""Characterization matrix for ``@field`` / ``@authorize_field`` composition.

Pins the full contract (rows 1-8) of how the two field-resolver decorators compose
across {decorator order} x {method shape} x {check kind}, sync and async. The matrix is
the regression guard for the working orders and the explicit ledger for the broken cells
the signature-adaptation fix repairs.

Assertions are deliberately on the GraphQL error **code** (``FIELD_AUTHORIZATION_ERROR``)
and the "resolver body ran / did not run" invariant -- never on a ``TypeError`` message
string. The broken cells fail with a missing-positional-argument ``TypeError`` whose text
uses the wrapper's ``co_qualname`` (``functools.wraps`` does not rewrite it), so asserting
on that text would be brittle and would not describe the contract.
"""

from __future__ import annotations

import asyncio
import inspect
import warnings
from types import SimpleNamespace
from typing import Any, NamedTuple

import pytest
from graphql import graphql, graphql_sync

import fraiseql
from fraiseql import field
from fraiseql.gql.builders import SchemaRegistry
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.security import authorize_field, field_authorizer_adapter
from fraiseql.security.authorization import AuthorizationDecision
from fraiseql.security.field_auth import FieldAuthorizationError

pytestmark = pytest.mark.security

# Proves whether a gated resolver body actually executed. The fail-closed invariant is
# "body did not run" on every deny cell; the allow cells require "body ran".
_executions: list[str] = []

_ALLOW = {"allow": True}
_DENY = {"allow": False}
_ASYNC_CHECK_WARNING = "async permission check"


class _CtxAuthorizer:
    """An operation-style authorizer that allows iff ``context['allow']`` is truthy.

    Adapted to a field check via :func:`field_authorizer_adapter` (which is async), so it
    exercises the async-check path in the matrix.
    """

    async def authorize_operation(
        self,
        *,
        context: dict[str, Any],
        operation_type: str,
        operation_name: str,
        arguments: dict[str, Any],
    ) -> bool:
        return bool(context.get("allow"))


# --- Row types: one gated field per type, distinct names so the type cache never collides.


# Row 1 -- Order A (@authorize_field outer / @field inner), ``def m(self)``, sync lambda.
@fraiseql.type
class T1:
    id: int

    @authorize_field(lambda info: info.context.get("allow", False))
    @field
    def data(self) -> str | None:
        _executions.append("T1")
        return "v1"


@fraiseql.query
def t1(info) -> T1:
    return T1(id=1)


# Row 2 -- Order A, ``async def m(self)``, sync lambda.
@fraiseql.type
class T2:
    id: int

    @authorize_field(lambda info: info.context.get("allow", False))
    @field
    async def data(self) -> str | None:
        _executions.append("T2")
        return "v2"


@fraiseql.query
def t2(info) -> T2:
    return T2(id=1)


# Row 3 -- Order A, ``def m(self, info)``, root-expecting sync check (``lambda info, root``).
@fraiseql.type
class T3:
    id: int

    @authorize_field(lambda info, root: info.context.get("allow", False))
    @field
    def data(self, info) -> str | None:
        _executions.append("T3")
        return "v3"


@fraiseql.query
def t3(info) -> T3:
    return T3(id=1)


# Row 4 -- standalone @authorize_field on a root-style ``async def r(root, info)``, decision
# check. Exercised by direct invocation (this is the custom-resolver usage, not a @field).
async def _r4(root: Any, info: Any) -> str | None:
    _executions.append("T4")
    return "v4"


def _check4(info: Any) -> AuthorizationDecision:
    if info.context.get("allow"):
        return AuthorizationDecision.allow()
    return AuthorizationDecision.deny(code="FIELD_AUTHORIZATION_ERROR")


_row4_wrapped = authorize_field(_check4)(_r4)


# Row 5 -- Order B (@field outer / @authorize_field inner), ``async def m(self, info)``,
# async adapter check.
@fraiseql.type
class T5:
    id: int

    @field
    @authorize_field(field_authorizer_adapter(_CtxAuthorizer(), field="T5.data"))
    async def data(self, info) -> str | None:
        _executions.append("T5")
        return "v5"


@fraiseql.query
def t5(info) -> T5:
    return T5(id=1)


# Row 6 -- Order B, ``def m(self)``, sync lambda. The self-only order that used to fail.
@fraiseql.type
class T6:
    id: int

    @field
    @authorize_field(lambda info: info.context.get("allow", False))
    def data(self) -> str | None:
        _executions.append("T6")
        return "v6"


@fraiseql.query
def t6(info) -> T6:
    return T6(id=1)


# Row 7 -- Order B, ``def m(self)``, async adapter check. A sync resolver gated by an async
# check: must resolve via an async wrapper, with no event-loop bridge and no warning.
@fraiseql.type
class T7:
    id: int

    @field
    @authorize_field(field_authorizer_adapter(_CtxAuthorizer(), field="T7.data"))
    def data(self) -> str | None:
        _executions.append("T7")
        return "v7"


@fraiseql.query
def t7(info) -> T7:
    return T7(id=1)


# Row 8 -- Order B, ``def m(self, info)`` sync, async adapter check. Same scenario as row 7
# (sync resolver + async check), differing only in the method shape.
@fraiseql.type
class T8:
    id: int

    @field
    @authorize_field(field_authorizer_adapter(_CtxAuthorizer(), field="T8.data"))
    def data(self, info) -> str | None:
        _executions.append("T8")
        return "v8"


@fraiseql.query
def t8(info) -> T8:
    return T8(id=1)


class _Exec(NamedTuple):
    value: Any
    body_ran: bool
    code: str | None
    warned: bool


class _Case(NamedTuple):
    name: str
    build: Any  # () -> (ctx -> _Exec)
    expected: Any
    expects_warning: bool


def _warned(caught: list[warnings.WarningMessage]) -> bool:
    return any(
        issubclass(w.category, RuntimeWarning) and _ASYNC_CHECK_WARNING in str(w.message)
        for w in caught
    )


def _graphql_runner(query_field: str, type_field: str, marker: str, type_cls: Any, query_fn: Any):
    """Build the schema once and return a ``run(ctx) -> _Exec`` closure.

    Picks ``graphql`` vs ``graphql_sync`` from the *built* field resolver's async-ness, so the
    runner adapts to whether the composed wrapper ended up sync or async without the matrix
    having to hard-code it per row.
    """
    schema = build_fraiseql_schema(query_types=[type_cls, query_fn])
    obj_type = schema.query_type.fields[query_field].type
    while hasattr(obj_type, "of_type"):
        obj_type = obj_type.of_type
    is_async = asyncio.iscoroutinefunction(obj_type.fields[type_field].resolve)
    query_str = f"{{ {query_field} {{ {type_field} }} }}"

    def run(ctx: dict[str, Any]) -> _Exec:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if is_async:
                result = asyncio.run(graphql(schema, query_str, context_value=ctx))
            else:
                result = graphql_sync(schema, query_str, context_value=ctx)
        code = None
        if result.errors:
            code = (result.errors[0].extensions or {}).get("code")
        value = None
        if result.data and result.data.get(query_field):
            value = result.data[query_field].get(type_field)
        return _Exec(value=value, body_ran=marker in _executions, code=code, warned=_warned(caught))

    return run


def _direct_runner(wrapped: Any, marker: str):
    """Return a ``run(ctx) -> _Exec`` closure that calls a standalone wrapper directly."""

    def run(ctx: dict[str, Any]) -> _Exec:
        info = SimpleNamespace(context=ctx, field_name="data")
        code = None
        value = None
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                res = wrapped(None, info)
                if inspect.isawaitable(res):
                    res = asyncio.run(res)
                value = res
            except FieldAuthorizationError as exc:
                code = (exc.extensions or {}).get("code")
        return _Exec(value=value, body_ran=marker in _executions, code=code, warned=_warned(caught))

    return run


_CASES = [
    pytest.param(
        _Case(
            name="row1-orderA-self-synccheck",
            build=lambda: _graphql_runner("t1", "data", "T1", T1, t1),
            expected="v1",
            expects_warning=False,
        ),
        id="row1-orderA-self-synccheck",
    ),
    pytest.param(
        _Case(
            name="row2-orderA-asyncself-synccheck",
            build=lambda: _graphql_runner("t2", "data", "T2", T2, t2),
            expected="v2",
            expects_warning=False,
        ),
        id="row2-orderA-asyncself-synccheck",
    ),
    pytest.param(
        _Case(
            name="row3-orderA-selfinfo-rootcheck",
            build=lambda: _graphql_runner("t3", "data", "T3", T3, t3),
            expected="v3",
            expects_warning=False,
        ),
        id="row3-orderA-selfinfo-rootcheck",
    ),
    pytest.param(
        _Case(
            name="row4-standalone-rootstyle-decision",
            build=lambda: _direct_runner(_row4_wrapped, "T4"),
            expected="v4",
            expects_warning=False,
        ),
        id="row4-standalone-rootstyle-decision",
    ),
    pytest.param(
        _Case(
            name="row5-orderB-asyncselfinfo-asyncadapter",
            build=lambda: _graphql_runner("t5", "data", "T5", T5, t5),
            expected="v5",
            expects_warning=False,
        ),
        id="row5-orderB-asyncselfinfo-asyncadapter",
    ),
    pytest.param(
        _Case(
            name="row6-orderB-self-synccheck",
            build=lambda: _graphql_runner("t6", "data", "T6", T6, t6),
            expected="v6",
            expects_warning=False,
        ),
        id="row6-orderB-self-synccheck",
    ),
    pytest.param(
        _Case(
            name="row7-orderB-self-asyncadapter",
            build=lambda: _graphql_runner("t7", "data", "T7", T7, t7),
            expected="v7",
            # An async check produces an async wrapper end-to-end, so there is no
            # sync-resolver event-loop bridge and no warning.
            expects_warning=False,
        ),
        id="row7-orderB-self-asyncadapter",
    ),
    pytest.param(
        _Case(
            name="row8-orderB-selfinfo-asyncadapter",
            build=lambda: _graphql_runner("t8", "data", "T8", T8, t8),
            expected="v8",
            expects_warning=False,
        ),
        id="row8-orderB-selfinfo-asyncadapter",
    ),
]


@pytest.fixture(autouse=True)
def _clean_registry():
    registry = SchemaRegistry.get_instance()
    registry.clear()
    from fraiseql.core.graphql_type import _graphql_type_cache

    _graphql_type_cache.clear()
    _executions.clear()
    yield
    registry.clear()
    _graphql_type_cache.clear()
    _executions.clear()


@pytest.mark.parametrize("case", _CASES)
def test_field_decorator_composition_matrix(case: _Case) -> None:
    """Both decorator orders, every method shape: allow runs the body, deny fails closed."""
    run = case.build()

    # ALLOW: value present, body ran, no error.
    _executions.clear()
    allow = run(_ALLOW)
    assert allow.value == case.expected, f"{case.name}: allowed field should resolve its value"
    assert allow.body_ran, f"{case.name}: resolver body should run when allowed"
    assert allow.code is None, f"{case.name}: no authorization error when allowed"
    if case.expects_warning:
        assert allow.warned, f"{case.name}: expected the sync-resolver+async-check RuntimeWarning"
    else:
        assert not allow.warned, f"{case.name}: unexpected RuntimeWarning"

    # DENY: fail-closed -- the error code is surfaced and the body never runs.
    _executions.clear()
    deny = run(_DENY)
    assert deny.code == "FIELD_AUTHORIZATION_ERROR", f"{case.name}: deny surfaces the field code"
    assert not deny.body_ran, f"{case.name}: resolver body must NOT run when denied (fail-closed)"
    assert deny.value is None, f"{case.name}: denied field yields no value"


async def test_sync_resolver_async_check_under_running_loop() -> None:
    """A sync resolver gated by an async check resolves cleanly under a *running* loop.

    This is the scenario the removed run_until_complete/run_coroutine_threadsafe bridge
    handled badly (a deadlock risk + a RuntimeWarning). Now the async check produces an async
    wrapper that graphql-core awaits on the already-running loop. ``await graphql(...)`` here
    runs inside pytest-asyncio's loop, exercising exactly that path.
    """
    schema = build_fraiseql_schema(query_types=[T7, t7])
    query_str = "{ t7 { data } }"

    _executions.clear()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        allowed = await graphql(schema, query_str, context_value=_ALLOW)
    assert not allowed.errors
    assert allowed.data["t7"]["data"] == "v7"
    assert "T7" in _executions
    assert not _warned(caught), "the sync->async bridge warning must be gone"

    _executions.clear()
    denied = await graphql(schema, query_str, context_value=_DENY)
    codes = {(e.extensions or {}).get("code") for e in (denied.errors or [])}
    assert "FIELD_AUTHORIZATION_ERROR" in codes
    assert "T7" not in _executions, "fail-closed: denied body must not run"
