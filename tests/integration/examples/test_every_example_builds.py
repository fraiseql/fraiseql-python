"""Every example file imports, and the schema it registers builds (#574).

Users copy the examples, so an example that fails to import, or registers types
that can't build, teaches them code that doesn't run. Each git-tracked
``examples/**.py`` is imported in its own process (examples register types at
import, and importing several into one registry would mix their schemas), then
the schema is built from what it registered.

Known failures are listed in ``_KNOWN_FAILURES`` with the reason. They are marked
``xfail(strict=True)``: an example that starts to build fails the run until it
is taken off the list, so the list only shrinks.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.examples

_ROOT = Path(__file__).resolve().parents[3]

# Import the example, then build a schema from everything it registered. A module
# is imported by its dotted name (examples use relative imports), unless a sibling
# module shadows its package (examples/foo.py next to examples/foo/main.py):
# then it is loaded from its path.
_BUILD = """
import importlib, importlib.util, sys
from pathlib import Path

root, rel = Path(sys.argv[1]), Path(sys.argv[2])
sys.path[:0] = [str(root / rel.parent), str(root)]
parts = rel.with_suffix("").parts
shadowed = any((root / Path(*parts[:i])).with_suffix(".py").exists() for i in range(2, len(parts)))
if shadowed:
    spec = importlib.util.spec_from_file_location("example_under_test", root / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
else:
    importlib.import_module(".".join(parts))

import fraiseql

@fraiseql.query
async def example_ping(info) -> str:
    return "ok"

fraiseql.build_fraiseql_schema()
"""

_KNOWN_FAILURES = {
    "examples/ecommerce/app.py": "Decimal fields: builds with #575's Decimal scalar",
    "examples/ecommerce/models.py": "Decimal fields: builds with #575's Decimal scalar",
    "examples/ecommerce/mutations.py": "Decimal fields: builds with #575's Decimal scalar",
    "examples/ecommerce/queries.py": "Decimal fields: builds with #575's Decimal scalar",
    "examples/enterprise_patterns/models.py": "uses a pydantic FieldInfo as a type",
    "examples/enterprise_patterns/mutations.py": "uses a pydantic FieldInfo as a type",
    "examples/existing_complex_where_syntax.py": "Decimal fields (#575)",
    "examples/security/secure_graphql_api.py": "uses fraiseql.union, which fraiseql doesn't have",
    "examples/token_revocation_example.py": "needs redis",
}


def _example_files() -> list[str]:
    if shutil.which("git") is None or not (_ROOT / ".git").exists():
        return []
    out = subprocess.run(
        ["git", "ls-files", "examples/**.py"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [path for path in out.splitlines() if path]


_FILES = _example_files()


def test_known_failures_are_example_files() -> None:
    if not _FILES:
        pytest.skip("needs a git checkout to list the examples")
    assert sorted(set(_KNOWN_FAILURES) - set(_FILES)) == []


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(
            path,
            marks=pytest.mark.xfail(strict=True, reason=_KNOWN_FAILURES[path]),
        )
        if path in _KNOWN_FAILURES
        else path
        for path in _FILES
    ],
)
def test_example_imports_and_builds(path: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _BUILD, str(_ROOT), path],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=_ROOT,
    )

    assert result.returncode == 0, result.stderr[-3000:]
