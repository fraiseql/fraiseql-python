"""Regression test for issue #370: type stub drops ``@dataclass_transform``.

The hand-written ``src/fraiseql/__init__.pyi`` shadows the runtime decorators for
every *external* consumer of fraiseql. fraiseql's own type-check (pyright/ty) only
reads the ``.py`` sources, so a stub that omits ``@dataclass_transform`` type-checks
clean here while breaking downstream: ``@fraiseql.type`` classes lose their
synthesised ``__init__`` and every keyword construction is flagged ``unknown-argument``.

This guards against silent re-drift by asserting, structurally, that the stub keeps
``@dataclass_transform`` on the field-bearing decorators and that ``mutation()`` stays
in sync with the runtime signature.
"""

import ast
from pathlib import Path

import pytest

import fraiseql

pytestmark = pytest.mark.regression

# Decorators whose runtime counterparts use @dataclass_transform and whose decorated
# classes are constructed by consumers with keyword arguments.
TRANSFORM_DECORATORS = {
    "fraise_type_decorator",
    "fraise_input_decorator",
    "success",
    "error",
    "interface",
}
# enum (not a dataclass) and result (a factory, not a class decorator) must NOT carry it.
NON_TRANSFORM_DECORATORS = {"enum", "result"}

REQUIRED_MUTATION_KWARGS = {
    "function",
    "schema",
    "context_params",
    "error_config",
    "enable_cascade",
    "authorizer",
}


def _load_stub() -> ast.Module:
    stub = Path(fraiseql.__file__).with_name("__init__.pyi")
    assert stub.exists(), f"type stub not found next to package: {stub}"
    return ast.parse(stub.read_text())


def _functions(tree: ast.Module, name: str) -> list[ast.FunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]


def _dataclass_transform_call(node: ast.FunctionDef) -> ast.Call | None:
    for dec in node.decorator_list:
        func = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(func, ast.Name) and func.id == "dataclass_transform":
            return dec if isinstance(dec, ast.Call) else None
    return None


def _has_dataclass_transform(node: ast.FunctionDef) -> bool:
    for dec in node.decorator_list:
        func = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(func, ast.Name) and func.id == "dataclass_transform":
            return True
    return False


class TestStubDataclassTransform:
    """The stub must model fraiseql's dataclass-style, keyword-only constructors."""

    @pytest.mark.parametrize("name", sorted(TRANSFORM_DECORATORS))
    def test_field_bearing_decorators_carry_dataclass_transform(self, name: str) -> None:
        nodes = _functions(_load_stub(), name)
        assert nodes, f"decorator {name!r} not found in stub"
        assert any(_has_dataclass_transform(n) for n in nodes), (
            f"stub decorator {name!r} is missing @dataclass_transform"
        )

    @pytest.mark.parametrize("name", sorted(TRANSFORM_DECORATORS))
    def test_kw_only_default_is_true(self, name: str) -> None:
        # Runtime generates a keyword-only __init__ (constructor.py: kw_only=True).
        for node in _functions(_load_stub(), name):
            call = _dataclass_transform_call(node)
            if call is None:
                continue
            kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg}
            value = kwargs.get("kw_only_default")
            assert isinstance(value, ast.Constant), f"{name}: kw_only_default must be set"
            assert value.value is True, f"{name}: kw_only_default must be True"

    @pytest.mark.parametrize("name", sorted(NON_TRANSFORM_DECORATORS))
    def test_non_field_decorators_are_not_transformed(self, name: str) -> None:
        for node in _functions(_load_stub(), name):
            assert not _has_dataclass_transform(node), f"{name} must not carry @dataclass_transform"

    def test_mutation_signature_in_sync_with_runtime(self) -> None:
        # mutation() must expose every runtime keyword, else @mutation(...) calls error.
        seen: set[str] = set()
        for node in _functions(_load_stub(), "mutation"):
            seen |= {arg.arg for arg in node.args.kwonlyargs}
        missing = REQUIRED_MUTATION_KWARGS - seen
        assert not missing, f"stub mutation() missing keyword params: {sorted(missing)}"
