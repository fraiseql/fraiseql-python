"""Regression tests for Issue #370: type stub drops ``@dataclass_transform``.

The hand-written stub ``src/fraiseql/__init__.pyi`` shadows the runtime ``.py``
for type checkers. It used to re-declare the core type decorators *without* the
``@dataclass_transform`` annotation the runtime carries, so checkers resolved a
``@fraiseql.type``-decorated class's ``__init__`` to ``object.__init__`` and
reported ``unknown-argument`` / ``reportCallIssue`` on every keyword
construction. A second drift left ``mutation()`` missing ``enable_cascade`` and
``authorizer``.

This module also guards a pre-existing defect fixed in the same change: the
FastAPI block used ``type FraiseQLConfig = None`` (a PEP 695 alias) in the
``except`` branch, which collided with the class imported in ``try``
(``reportAssignmentType``), and ``__all__`` exported a phantom
``CreateFraiseQLApp`` while omitting the real ``create_fraiseql_app``
(``reportUnsupportedDunderAll``).

These tests drive a real type checker (pyright) over a consumer snippet and the
stub itself. They are skipped when no pyright binary is available so the suite
stays runnable without the dev type-checking toolchain.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STUB = _REPO_ROOT / "src" / "fraiseql" / "__init__.pyi"

# A consumer module that exercises every decorator the stub must keep
# dataclass-transform-aware, the synced ``mutation()`` signature, and the
# FastAPI symbols that the ``__all__`` / import block must expose correctly.
CONSUMER_SNIPPET = """\
import fraiseql
from fraiseql import FraiseQLConfig, create_fraiseql_app


@fraiseql.type
class Foo:
    id: str
    name: str | None = None


@fraiseql.input
class FooInput:
    id: str
    name: str | None = None


@fraiseql.success
class FooSuccess:
    foo: Foo | None = None


@fraiseql.error
class FooError:
    message: str = ""


@fraiseql.mutation(enable_cascade=True, authorizer=None, schema="app")
class CreateFoo:
    pass


@fraiseql.mutation
class DeleteFoo:
    pass


def _use() -> None:
    Foo(id="1", name="bar")
    FooInput(id="1", name="bar")
    FooSuccess(foo=None)
    FooError(message="boom")
    _ = FraiseQLConfig
    _ = create_fraiseql_app
"""


def _pyright_binary() -> str | None:
    """Locate a pyright executable, preferring the project venv."""
    venv_pyright = Path(sys.executable).parent / "pyright"
    if venv_pyright.exists():
        return str(venv_pyright)
    return shutil.which("pyright")


def _run_pyright(target: Path) -> dict:
    """Run pyright over ``target`` and return the parsed JSON report."""
    pyright = _pyright_binary()
    if pyright is None:
        pytest.skip("pyright not available")

    # Inherit the environment so pyright (run from the venv where fraiseql is
    # installed editable) resolves ``import fraiseql`` → src/fraiseql/*.pyi.
    proc = subprocess.run(
        [pyright, "--outputjson", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    # pyright exits non-zero when diagnostics exist; parse rather than trust rc.
    return json.loads(proc.stdout)


@pytest.fixture
def consumer_module(tmp_path: Path) -> Path:
    module = tmp_path / "consumer.py"
    module.write_text(CONSUMER_SNIPPET)
    return module


def test_decorated_constructions_have_no_call_issues(consumer_module: Path) -> None:
    """Pyright must not flag keyword construction or mutation kwargs.

    This fails on the pre-#370 stub (216 ``reportCallIssue`` in the wild) and
    passes once ``@dataclass_transform`` is restored and ``mutation()`` is
    synced to the runtime signature.
    """
    payload = _run_pyright(consumer_module)
    call_issues = [
        d for d in payload.get("generalDiagnostics", []) if d.get("rule") == "reportCallIssue"
    ]
    assert not call_issues, (
        "stub regressed — pyright reported call issues on decorated "
        f"constructions:\n{json.dumps(call_issues, indent=2)}"
    )


def test_stub_module_has_no_type_errors() -> None:
    """The stub itself must type-check cleanly.

    Guards the FastAPI block fix: ``reportAssignmentType`` (the old
    ``type X = None`` alias colliding with the imported class) and
    ``reportUnsupportedDunderAll`` (the phantom ``CreateFraiseQLApp``).
    """
    payload = _run_pyright(_STUB)
    errors = [d for d in payload.get("generalDiagnostics", []) if d.get("severity") == "error"]
    assert not errors, f"stub {_STUB} has type errors:\n{json.dumps(errors, indent=2)}"
