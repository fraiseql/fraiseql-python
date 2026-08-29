"""Declared floors for packages with published security advisories.

A `uv.lock` bump fixes *our* installs. It does nothing for a downstream resolver,
which reads `pyproject.toml` — so every advisory we close has to move the declared
floor too, or the next person to `pip install fraiseql` under their own constraints
can resolve straight back onto the vulnerable version.

The floors below are the Dependabot alerts open on `dev` at 1.23.12 (#465 track).
Each entry names why the package is in the tree, because the exposure differs: a
core dependency of every install is not the same finding as an optional extra.
"""

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

# package -> (first patched version, why it is in the tree)
REQUIRED_FLOORS = {
    "sqlparse": ("0.6.0", "dev-only: used by scripts/, imported nowhere in src/"),
    "nltk": ("3.10.0", "optional: transitive through the llamaindex extra"),
    "pypdf": ("6.15.0", "optional: declared by the llamaindex extra"),
    "cryptography": ("50.0.0", "core in practice: pulled in by pyjwt[crypto]"),
    "aiohttp": ("3.14.3", "optional: dev extra, and transitive via llama-index-core"),
    # Not a Dependabot alert — found by making the pip-audit CI gate authoritative,
    # which is the point of that change. `click.edit()` is a command injection, and
    # FraiseQL's CLI never calls it; the floor moves because the package is core.
    "click": ("8.3.3", "core: the CLI's argument parser"),
}


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def _declarations(pyproject: dict, package: str) -> list[tuple[str, Requirement]]:
    """Every place *package* is declared, as (location, requirement)."""
    found: list[tuple[str, Requirement]] = []

    def scan(location: str, requirements: list[str]) -> None:
        for raw in requirements:
            req = Requirement(raw)
            if req.name.lower() == package:
                found.append((location, req))

    project = pyproject["project"]
    scan("project.dependencies", project.get("dependencies", []))
    for extra, requirements in project.get("optional-dependencies", {}).items():
        scan(f"project.optional-dependencies.{extra}", requirements)
    for group, requirements in pyproject.get("dependency-groups", {}).items():
        scan(f"dependency-groups.{group}", requirements)
    return found


def _floor(specifier: SpecifierSet) -> Version | None:
    """The lowest version the specifier admits, as declared by its `>=` / `==` bound."""
    lower = [Version(s.version) for s in specifier if s.operator in (">=", "==")]
    return max(lower) if lower else None


@pytest.mark.parametrize(("package", "fixed", "why"), [(p, *v) for p, v in REQUIRED_FLOORS.items()])
def test_every_declaration_is_at_or_above_the_fixed_version(
    pyproject: dict, package: str, fixed: str, why: str
) -> None:
    declarations = _declarations(pyproject, package)
    assert declarations, f"{package} is no longer declared anywhere ({why})"

    for location, req in declarations:
        floor = _floor(req.specifier)
        assert floor is not None, f"{location}: {req} has no lower bound ({why})"
        assert floor >= Version(fixed), (
            f"{location}: {req} admits a version below the fixed {fixed} ({why})"
        )


def test_sqlparse_is_not_a_runtime_dependency(pyproject: dict) -> None:
    """It is imported nowhere in ``src/`` — only by ``scripts/validate_code_examples.py``,
    which already degrades gracefully when it is absent.

    Declaring it under ``project.dependencies`` put four advisories in the runtime
    surface of every install for a script-only tool. It still arrives transitively
    via ``fraiseql-confiture``, so moving it does not remove the package — it moves
    where the floor is enforced and what the scope of the finding is.
    """
    runtime = [name for name, _ in _declarations(pyproject, "sqlparse")]
    assert "project.dependencies" not in runtime


def test_cryptography_floor_is_declared_on_the_default_install(pyproject: dict) -> None:
    """``pyjwt[crypto]`` is a core dependency, so cryptography is installed by default.

    The advisory (a Bleichenbacher oracle in PKCS#7 ``EnvelopedData`` decryption) is
    not code FraiseQL calls, but the package is in every install's tree and the
    ``kms`` extras are the only place a floor was declared. An extras-only floor
    leaves a default install free to resolve a vulnerable version.
    """
    runtime = [name for name, _ in _declarations(pyproject, "cryptography")]
    assert "project.dependencies" in runtime
