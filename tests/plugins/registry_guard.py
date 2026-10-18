"""Fail a test whose schema holds types or resolvers from another test module.

FraiseQL's schema registry is process-wide. A test module that registers types
and doesn't clear them leaves them in the registry, and a later test that builds
a schema picks them up. Whether it does depends on test order and on how
pytest-xdist splits the files, so the failures it causes are hard to trace.

The guard wraps ``SchemaComposer.__init__``: every schema build creates a
composer and calls ``compose()`` on it. It hooks ``__init__`` rather than
``compose`` so that no guard frame is on the stack while the schema is built,
where it would become the caller that fraiseql's warnings point at. On each
build during a test, it looks up the file that defines each
registered type, enum, interface, query, mutation and subscription. The test
fails if one comes from a file under ``tests/`` other than the test's own,
except:

- shared files: ``conftest*.py``, ``__init__.py``, and anything under
  ``tests/fixtures/`` or a ``utils/`` or ``helpers/`` directory
- objects the test module imports itself
- tests marked ``@pytest.mark.shares_schema_types``

The fix is to clear the registry: the ``clear_registry`` or
``clear_registry_class`` fixture.
"""

from __future__ import annotations

import sys
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Any

import pytest

_SHARED_DIRS = ("utils", "helpers")

_state: dict[str, Any] = {"item": None, "tests_dir": None, "original": None, "installs": 0}


def _file_of(module_name: str) -> Path | None:
    module_file = getattr(sys.modules.get(module_name), "__file__", None)
    return Path(module_file).resolve() if module_file else None


def _is_shared(path: Path, tests_dir: Path) -> bool:
    rel = path.relative_to(tests_dir)
    return (
        path.name.startswith("conftest")
        or path.name == "__init__.py"
        or rel.parts[0] == "fixtures"
        or any(part in _SHARED_DIRS for part in rel.parts[:-1])
    )


def _registered_objects(registry: Any) -> Iterator[tuple[str, Any]]:
    for kind, attr in (("type", "_types"), ("enum", "_enums"), ("interface", "_interfaces")):
        for obj in list(getattr(registry, attr)):
            yield kind, obj
    for kind, attr in (("query", "_queries"), ("subscription", "_subscriptions")):
        for obj in list(getattr(registry, attr).values()):
            yield kind, obj
    for resolver in list(registry._mutations.values()):
        definition = getattr(resolver, "__fraiseql_mutation__", None)
        yield "mutation", getattr(definition, "mutation_class", None) or resolver


def _foreign_objects(registry: Any, item: pytest.Item, tests_dir: Path) -> list[str]:
    test_file = Path(item.path).resolve()
    test_module = getattr(item, "module", None)
    imported = {id(value) for value in vars(test_module).values()} if test_module else set()
    files: dict[str, Path | None] = {}
    foreign = []
    for kind, obj in _registered_objects(registry):
        module_name = getattr(obj, "__module__", None)
        if not module_name:
            continue
        if module_name not in files:
            files[module_name] = _file_of(module_name)
        path = files[module_name]
        if (
            path is None
            or path == test_file
            or not path.is_relative_to(tests_dir)
            or _is_shared(path, tests_dir)
            or id(obj) in imported
        ):
            continue
        name = getattr(obj, "__qualname__", repr(obj))
        foreign.append(f"  {kind} {name} — {path.relative_to(tests_dir.parent)}")
    return foreign


def _check(registry: Any) -> None:
    item = _state["item"]
    if item is None or item.get_closest_marker("shares_schema_types"):
        return
    foreign = _foreign_objects(registry, item, _state["tests_dir"])
    if foreign:
        pytest.fail(
            f"{item.nodeid} built a schema holding objects from another test module:\n"
            + "\n".join(sorted(foreign))
            + "\nThat module didn't clear the schema registry: use clear_registry / "
            "clear_registry_class.",
            pytrace=False,
        )


def pytest_configure(config: pytest.Config) -> None:
    from fraiseql.gql.builders.schema_composer import SchemaComposer

    # A pytester run in the same process configures the plugin again: wrap once.
    _state["installs"] += 1
    if _state["installs"] > 1:
        return
    original = SchemaComposer.__init__
    _state["original"] = original

    def init(self: SchemaComposer, registry: Any) -> None:
        original(self, registry)
        _check(registry)

    SchemaComposer.__init__ = init  # type: ignore[method-assign]


def pytest_unconfigure(config: pytest.Config) -> None:
    from fraiseql.gql.builders.schema_composer import SchemaComposer

    _state["installs"] -= 1
    if _state["installs"] == 0 and _state["original"] is not None:
        SchemaComposer.__init__ = _state["original"]  # type: ignore[method-assign]
        _state["original"] = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None]:
    outer = _state["item"], _state["tests_dir"]
    _state["item"], _state["tests_dir"] = item, (item.config.rootpath / "tests").resolve()
    try:
        yield
    finally:
        _state["item"], _state["tests_dir"] = outer
