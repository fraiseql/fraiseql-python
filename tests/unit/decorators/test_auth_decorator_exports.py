"""The auth decorators are importable from ``fraiseql.auth`` and ``fraiseql`` (issue #577).

``requires_any_role`` and ``requires_any_permission`` lived only in
``fraiseql.auth.decorators``, while the docs imported them from ``fraiseql.auth``.
The ``__init__.pyi`` stub re-exports each decorator, so type checkers read its signature.
"""

import ast
from pathlib import Path

import pytest

import fraiseql
import fraiseql.auth
from fraiseql.auth import decorators

_STUB = Path(fraiseql.__file__).with_name("__init__.pyi")

_DECORATORS = (
    "requires_auth",
    "requires_permission",
    "requires_role",
    "requires_any_permission",
    "requires_any_role",
)


@pytest.mark.parametrize("name", _DECORATORS)
def test_exported_from_fraiseql_auth(name: str) -> None:
    assert getattr(fraiseql.auth, name) is getattr(decorators, name)
    assert name in fraiseql.auth.__all__


@pytest.mark.parametrize("name", _DECORATORS)
def test_exported_from_fraiseql(name: str) -> None:
    assert getattr(fraiseql, name) is getattr(decorators, name)
    assert name in fraiseql.__all__


def _stub_reexports() -> dict[str, str]:
    """``from M import name as name`` lines of the stub: name -> M."""
    tree = ast.parse(_STUB.read_text())
    return {
        alias.asname: node.module or ""
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.asname == alias.name
    }


@pytest.mark.parametrize("name", _DECORATORS)
def test_stub_reexports_the_runtime_decorator(name: str) -> None:
    assert _stub_reexports()[name] == "auth"
