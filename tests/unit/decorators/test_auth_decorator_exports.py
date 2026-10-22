"""The auth decorators are importable from ``fraiseql.auth`` and ``fraiseql`` (issue #577).

``requires_any_role`` and ``requires_any_permission`` lived only in
``fraiseql.auth.decorators``, while the docs imported them from ``fraiseql.auth``.
The ``__init__.pyi`` stub must declare each decorator with its runtime signature.
"""

import ast
import inspect
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


def _stub_functions() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(_STUB.read_text())
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _stub_all() -> list[str]:
    tree = ast.parse(_STUB.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("__init__.pyi has no __all__")


@pytest.mark.parametrize("name", _DECORATORS)
def test_stub_matches_runtime_signature(name: str) -> None:
    stub = _stub_functions()[name]
    runtime = inspect.signature(getattr(decorators, name))

    stub_params = [(arg.arg, "positional") for arg in stub.args.args]
    if stub.args.vararg:
        stub_params.append((stub.args.vararg.arg, "var"))
    stub_params += [(arg.arg, "keyword") for arg in stub.args.kwonlyargs]
    kinds = {
        inspect.Parameter.POSITIONAL_OR_KEYWORD: "positional",
        inspect.Parameter.VAR_POSITIONAL: "var",
        inspect.Parameter.KEYWORD_ONLY: "keyword",
    }
    runtime_params = [(p.name, kinds[p.kind]) for p in runtime.parameters.values()]

    assert stub_params == runtime_params
    assert name in _stub_all()
