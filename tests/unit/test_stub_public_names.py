"""Each ``.pyi`` stub under src/fraiseql declares the public names of its runtime module.

Type checkers read a stub instead of the module beside it, so a stub that misses a
name hides it (``fraiseql.connection``, ``CQRSRepository.paginate`` were reported as
missing) and one that keeps a removed name promises an API that fails at runtime.
"""

import ast
import importlib
import inspect
from pathlib import Path
from types import ModuleType

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
_STUBS = sorted((_SRC / "fraiseql").rglob("*.pyi"))


def _module_name(stub: Path) -> str:
    parts = list(stub.relative_to(_SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple):
        return [name for elt in target.elts for name in _target_names(elt)]
    return []


def _declared(body: list[ast.stmt]) -> dict[str, ast.stmt]:
    """Names a stub body declares (a ``from m import x`` re-exports only ``as x``)."""
    names: dict[str, ast.stmt] = {}
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(dict.fromkeys(_target_names(target), node))
        elif isinstance(node, ast.AnnAssign):
            names.update(dict.fromkeys(_target_names(node.target), node))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname is not None:
                    names[alias.asname] = node
        elif isinstance(node, ast.If):
            names.update(_declared(node.body))
            names.update(_declared(node.orelse))
    return names


def _stub_all(tree: ast.Module) -> list[str] | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return list(ast.literal_eval(node.value))
    return None


def _public(names: object) -> set[str]:
    return {name for name in names if not name.startswith("_")}  # type: ignore[attr-defined]


def _defined_here(module: ModuleType) -> set[str]:
    """Public functions and classes the module itself defines."""
    return {
        name
        for name, value in vars(module).items()
        if not name.startswith("_")
        and (inspect.isfunction(value) or inspect.isclass(value))
        and value.__module__ == module.__name__
    }


@pytest.mark.parametrize("stub", _STUBS, ids=lambda p: str(p.relative_to(_SRC)))
def test_stub_declares_the_module_public_names(stub: Path) -> None:
    module = importlib.import_module(_module_name(stub))
    tree = ast.parse(stub.read_text())
    declared = _declared(tree.body)
    stub_public = _public(declared) - {"__all__"}

    runtime_all = getattr(module, "__all__", None)
    if runtime_all is not None:
        assert sorted(_stub_all(tree) or []) == sorted(runtime_all), "stub __all__ != module"
        expected = set(runtime_all)
    else:
        expected = _defined_here(module)
    missing = sorted(expected - set(declared))
    assert not missing, f"{stub.name} lacks {missing}"

    phantom = sorted(name for name in stub_public if not hasattr(module, name))
    assert not phantom, f"{stub.name} declares names the module doesn't have: {phantom}"


@pytest.mark.parametrize("stub", _STUBS, ids=lambda p: str(p.relative_to(_SRC)))
def test_stub_classes_declare_their_public_members(stub: Path) -> None:
    module = importlib.import_module(_module_name(stub))
    tree = ast.parse(stub.read_text())
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        cls = getattr(module, node.name)
        members = _public(_declared(node.body))
        own = _public(vars(cls)) - {"model_config", "model_fields"}
        missing = sorted(own - members)
        assert not missing, f"{stub.name}: {node.name} lacks {missing}"
        fields = inspect.get_annotations(cls)  # dataclass fields with a default_factory
        phantom = sorted(name for name in members if not hasattr(cls, name) and name not in fields)
        assert not phantom, f"{stub.name}: {node.name} declares {phantom}, which it doesn't have"


def test_stubs_exist() -> None:
    """The glob finds the stubs (an empty parametrization would pass silently)."""
    assert _SRC / "fraiseql" / "__init__.pyi" in _STUBS
