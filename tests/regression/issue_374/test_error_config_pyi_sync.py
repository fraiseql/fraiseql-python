"""Regression tests for Issue #374: ``error_config.pyi`` drifted from runtime.

The hand-written stub ``src/fraiseql/mutations/error_config.pyi`` shadows the
runtime ``error_config.py`` ``@dataclass`` for type checkers. It used to:

1. declare a non-existent required field/param ``error_as_data_prefixes``;
2. omit the real fields ``error_pattern`` and ``always_return_as_data``;
3. mark every ``__init__`` param required (runtime: all have defaults);
4. expose methods that do not exist at runtime (``is_success`` / ``is_error`` /
   ``should_return_as_data`` instead of ``is_error_status`` / ``get_error_code``).

So the documented construction
``MutationErrorConfig(success_keywords=..., error_prefixes=..., error_keywords=...)``
was flagged ``missing-argument`` for the phantom ``error_as_data_prefixes`` in
every downstream consumer.

Two layers of guard:

* ``test_stub_matches_runtime_dataclass`` is a pure-Python introspection check
  (always runs) — it parses the stub and compares the declared field set and
  method names against the runtime dataclass.
* The pyright tests drive a real type checker over a consumer snippet and the
  stub itself; they skip when no pyright binary is available.
"""

import ast
import dataclasses
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fraiseql.mutations.error_config import MutationErrorConfig

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STUB = _REPO_ROOT / "src" / "fraiseql" / "mutations" / "error_config.pyi"

# A consumer module exercising the documented constructor (keyword args, the
# real fields) plus the runtime method names. None of this should raise a
# type-checker diagnostic once the stub mirrors the runtime dataclass.
CONSUMER_SNIPPET = """\
import re

from fraiseql.mutations.error_config import MutationErrorConfig


def _use() -> None:
    cfg = MutationErrorConfig(
        success_keywords={"ok"},
        error_prefixes={"failed:"},
        error_keywords=set(),
        error_pattern=re.compile(r"^x"),
        always_return_as_data=False,
    )
    # documented minimal construction (was flagged missing-argument)
    _ = MutationErrorConfig(success_keywords={"ok"})
    _ = MutationErrorConfig()
    _is_err: bool = cfg.is_error_status("failed:boom")
    _code: int = cfg.get_error_code("not_found:x")
"""


def _stub_class_node() -> ast.ClassDef:
    tree = ast.parse(_STUB.read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MutationErrorConfig":
            return node
    raise AssertionError("MutationErrorConfig not found in stub")


def test_stub_matches_runtime_dataclass() -> None:
    """The stub's fields and methods must mirror the runtime dataclass."""
    runtime_fields = {f.name for f in dataclasses.fields(MutationErrorConfig)}
    runtime_methods = {"is_error_status", "get_error_code"}

    cls = _stub_class_node()
    stub_fields = {
        node.target.id
        for node in cls.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    stub_methods = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}
    stub_methods.discard("__init__")

    assert stub_fields == runtime_fields, (
        f"stub fields {sorted(stub_fields)} != runtime "
        f"{sorted(runtime_fields)} (drift reintroduced)"
    )
    assert stub_methods == runtime_methods, (
        f"stub methods {sorted(stub_methods)} != runtime {sorted(runtime_methods)}"
    )


def test_fields_have_defaults() -> None:
    """Every field must carry a default so the synthesized ``__init__`` is all-optional.

    The stub marks the class ``@dataclass`` (mirroring the runtime), so the
    constructor is synthesized from the field defaults rather than hand-written.
    Each field annotated ``name: T = ...`` becomes an optional ``__init__`` param,
    matching the runtime dataclass where every field has a default.
    """
    cls = _stub_class_node()
    undefaulted = [
        node.target.id
        for node in cls.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.value is None
    ]
    assert not undefaulted, (
        f"fields without a default {undefaulted} would force required "
        "constructor args, diverging from the runtime dataclass"
    )


def _pyright_binary() -> str | None:
    venv_pyright = Path(sys.executable).parent / "pyright"
    if venv_pyright.exists():
        return str(venv_pyright)
    return shutil.which("pyright")


def _run_pyright(target: Path) -> dict:
    pyright = _pyright_binary()
    if pyright is None:
        pytest.skip("pyright not available")
    proc = subprocess.run(
        [pyright, "--outputjson", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(proc.stdout)


@pytest.fixture
def consumer_module(tmp_path: Path) -> Path:
    module = tmp_path / "consumer.py"
    module.write_text(CONSUMER_SNIPPET)
    return module


def test_construction_has_no_call_issues(consumer_module: Path) -> None:
    """Pyright must not flag the documented keyword construction."""
    payload = _run_pyright(consumer_module)
    call_issues = [
        d
        for d in payload.get("generalDiagnostics", [])
        if d.get("rule") in {"reportCallIssue", "reportArgumentType"}
    ]
    assert not call_issues, (
        "stub regressed — pyright reported call issues on MutationErrorConfig "
        f"construction:\n{json.dumps(call_issues, indent=2)}"
    )


def test_stub_module_has_no_type_errors() -> None:
    """The stub itself must type-check cleanly."""
    payload = _run_pyright(_STUB)
    errors = [d for d in payload.get("generalDiagnostics", []) if d.get("severity") == "error"]
    assert not errors, f"stub {_STUB} has type errors:\n{json.dumps(errors, indent=2)}"
