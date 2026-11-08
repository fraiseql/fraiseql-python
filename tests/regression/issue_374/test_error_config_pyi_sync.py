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

The stub is gone (1.31.0): type checkers read the annotated runtime module, so
it can't drift again. The pyright test drives a real type checker over a consumer
snippet; it skips when no pyright binary is available.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_no_hand_written_stub() -> None:
    """Type checkers read the annotated ``error_config.py`` itself.

    The stub added nothing over the module's inline annotations and drifted twice
    (issue #374, then field defaults typed ``...``), so it was removed.
    """
    assert not _STUB.exists()


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
        "pyright reported call issues on MutationErrorConfig "
        f"construction:\n{json.dumps(call_issues, indent=2)}"
    )
