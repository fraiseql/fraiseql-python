"""The registry-leak guard fails a test whose schema holds another test module's types.

Each case runs a small test tree with pytester. The tree loads the guard
(tests/plugins/registry_guard.py) and a clear_registry fixture from its own
conftest, and has a pytest.ini so that its rootdir, and so its tests/
directory, is the pytester directory.
"""

import pytest

pytestmark = pytest.mark.usefixtures("clear_registry")

_INI = "[pytest]\n"

_CONFTEST = """
import pytest

pytest_plugins = ["tests.plugins.registry_guard"]


@pytest.fixture
def clear_registry():
    from fraiseql.testing import clear_fraiseql_state

    clear_fraiseql_state()
    yield
    clear_fraiseql_state()
"""

# Registers an input and a query at import, and never clears. A plain
# @fraiseql.type isn't registered by itself: the query brings User in.
_TEST_A = """
import fraiseql


@fraiseql.type
class User:
    id: int
    name: str


@fraiseql.input
class UserFilter:
    name: str


@fraiseql.query
async def users(info) -> list[User]:
    return []


def test_a():
    pass
"""

_TEST_B = """
import fraiseql
from fraiseql.gql.schema_builder import build_fraiseql_schema


def test_b({fixture}):
    @fraiseql.type
    class Thing:
        id: int

    @fraiseql.query
    async def thing(info) -> Thing:
        return Thing(id=1)

    build_fraiseql_schema(query_types=[thing])
"""


def _run(pytester: pytest.Pytester, **files: str) -> pytest.RunResult:
    pytester.makeini(_INI)
    tests_dir = pytester.mkdir("tests")
    for name, source in {"conftest": _CONFTEST, **files}.items():
        (tests_dir / f"{name}.py").write_text(source)
    return pytester.runpytest(
        "tests", "-p", "no:randomly", "-p", "no:xdist", "-p", "no:cacheprovider"
    )


def test_leak_is_reported(pytester: pytest.Pytester) -> None:
    result = _run(pytester, test_a=_TEST_A, test_b=_TEST_B.format(fixture=""))

    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(
        [
            "*tests/test_b.py::test_b built a schema holding objects from another test module:",
            "  query users — tests/test_a.py",
            "  type UserFilter — tests/test_a.py",
            "*use clear_registry / clear_registry_class*",
        ]
    )


def test_cleared_module_passes(pytester: pytest.Pytester) -> None:
    result = _run(pytester, test_a=_TEST_A, test_b=_TEST_B.format(fixture="clear_registry"))

    result.assert_outcomes(passed=2)


def test_fixture_types_allowed(pytester: pytest.Pytester) -> None:
    conftest_types = """
import fraiseql


@fraiseql.type
class SharedUser:
    id: int
"""
    result = _run(
        pytester,
        conftest=_CONFTEST + conftest_types,
        test_b=_TEST_B.format(fixture=""),
    )

    result.assert_outcomes(passed=1)


def test_opt_out_marker(pytester: pytest.Pytester) -> None:
    test_b = _TEST_B.format(fixture="").replace(
        "def test_b(", "@pytest.mark.shares_schema_types\ndef test_b("
    )
    result = _run(pytester, test_a=_TEST_A, test_b="import pytest\n" + test_b)

    result.assert_outcomes(passed=2)
