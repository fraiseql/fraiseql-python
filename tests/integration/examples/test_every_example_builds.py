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
# module shadows its package (examples/documented_api.py next to
# examples/documented_api/main.py): then it is loaded from its path.
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
    "examples/apq_multi_tenant/main.py": "uses typing.Any without importing it",
    "examples/blog_api/app.py": "opens a connection pool at import",
    "examples/complete_cqrs_blog/app.py": "written with Strawberry and asyncpg",
    "examples/complete_cqrs_blog/migrations/run_migrations.py": "needs asyncpg",
    "examples/complete_cqrs_blog/schema.py": "written with Strawberry",
    "examples/complete_cqrs_blog/sync.py": "needs asyncpg",
    "examples/complex_nested_where_clauses.py": "passes the SQL where type as an argument",
    "examples/documented_api/main.py": "imports fraiseql.FraiseQL, which fraiseql doesn't have",
    "examples/ecommerce/app.py": "calls input() with a lambda",
    "examples/ecommerce/models.py": "Decimal fields (#575)",
    "examples/ecommerce/mutations.py": "calls input() with a lambda",
    "examples/ecommerce/queries.py": "imports fraiseql.Info, which fraiseql doesn't have",
    "examples/enhanced_where_clauses.py": "passes the SQL where type as an argument",
    "examples/enterprise_patterns/cqrs/main.py": "its types.py is shadowed by the stdlib",
    "examples/enterprise_patterns/cqrs/mutations.py": "its types.py is shadowed by the stdlib",
    "examples/enterprise_patterns/cqrs/queries.py": "its types.py is shadowed by the stdlib",
    "examples/enterprise_patterns/models.py": "uses a pydantic FieldInfo as a type",
    "examples/enterprise_patterns/mutations.py": "uses a pydantic FieldInfo as a type",
    "examples/existing_complex_where_syntax.py": "Decimal fields (#575)",
    "examples/fastapi/main.py": "its types.py is shadowed by the stdlib",
    "examples/fastapi/mutations.py": "its types.py is shadowed by the stdlib",
    "examples/fastapi/queries.py": "its types.py is shadowed by the stdlib",
    "examples/federation/basic/orders-service/schema.py": "Apollo Federation, which v1 doesn't have",
    "examples/federation/basic/users-service/schema.py": "Apollo Federation, which v1 doesn't have",
    "examples/federation/composite-keys/orders-service/schema.py": (
        "Apollo Federation, which v1 doesn't have"
    ),
    "examples/federation/composite-keys/users-service/schema.py": (
        "Apollo Federation, which v1 doesn't have"
    ),
    "examples/federation/multi-cloud/orders-service/schema.py": (
        "Apollo Federation, which v1 doesn't have"
    ),
    "examples/federation/multi-cloud/products-service/schema.py": (
        "Apollo Federation, which v1 doesn't have"
    ),
    "examples/federation/multi-cloud/users-service/schema.py": (
        "Apollo Federation, which v1 doesn't have"
    ),
    "examples/federation/saga-basic/inventory-service/server.py": "Flask, not fraiseql",
    "examples/federation/saga-basic/orders-service/server.py": "Flask, not fraiseql",
    "examples/federation/saga-basic/users-service/server.py": "Flask, not fraiseql",
    "examples/federation/saga-manual-compensation/bank-service/server.py": "Flask, not fraiseql",
    "examples/filtering/main.py": "imports fraiseql.FraiseQL, which fraiseql doesn't have",
    "examples/hybrid_tables/main.py": "imports fraiseql.FraiseQL, which fraiseql doesn't have",
    "examples/ltree-hierarchical-data/organization-chart/schema.py": (
        "imports LTree from fraiseql.types.scalars"
    ),
    "examples/ltree-hierarchical-data/product-catalog/schema.py": (
        "imports LTree from fraiseql.types.scalars"
    ),
    "examples/python/fraiseql_client.py": "an Arrow Flight client; v1 has no Flight server",
    "examples/python/test_arrow_flight.py": "an Arrow Flight client; v1 has no Flight server",
    "examples/rag-system/app.py": "imports UUID from fraiseql.types.scalars",
    "examples/saas-starter/main.py": "imports fraiseql.Info, which fraiseql doesn't have",
    "examples/security/secure_graphql_api.py": "uses fraiseql.union, which fraiseql doesn't have",
    "examples/specialized_types/main.py": "imports fraiseql.FraiseQL, which fraiseql doesn't have",
    "examples/token_revocation_example.py": "needs redis",
    "examples/turbo_router_with_complexity.py": "uses fraise_type without importing it",
    "examples/turborouter/main.py": "imports fraiseql.FraiseQL, which fraiseql doesn't have",
    "examples/vector_search/main.py": "imports fraiseql.fraise_query, which fraiseql doesn't have",
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
