"""Examples build without the mutation rename warning.

Users copy the examples, so an example whose mutation names change in fraiseql
2.0.0 teaches them code that warns on first run. Each example is imported and
built in its own process: examples register types and mutations at import, and
importing several into one registry would mix their schemas.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.examples

_ROOT = Path(__file__).resolve().parents[3]

# Import the example, then build a schema from everything it registered.
_BUILD = """
import importlib, json, sys, warnings
from pathlib import Path

root, module = Path(sys.argv[1]), sys.argv[2]
example_dir = root / Path(*module.split(".")[:-1])
sys.path[:0] = [str(example_dir), str(root)]

warnings.filterwarnings(
    "error", message="These mutation names will change", category=FutureWarning
)
importlib.import_module(module)

import fraiseql
from fraiseql.gql.builders.registry import SchemaRegistry

@fraiseql.query
async def example_ping(info) -> str:
    return "ok"

fraiseql.build_fraiseql_schema()
print(json.dumps({"mutations": len(SchemaRegistry.get_instance().mutations)}))
"""

# Examples that build without a database.
_BUILDABLE = [
    "examples.authorization.app",
    "examples.auto_field_descriptions",
    "examples.blog_api.mutations",
    "examples.blog_simple.models",
    "examples.context_parameters.mutations",
    "examples.documented_api",
    "examples.graphql-cascade.main",
    "examples.hybrid_tables",
    "examples.mutations_demo.demo",
    "examples.native_auth_app",
    "examples.quickstart_5min",
    "examples.todo_quickstart",
    "examples.where_input_filtering_example",
]

# Examples with mutations that don't build on the current API. Their mutation
# names are already 2.0.0-clean; move one to _BUILDABLE once it builds.
_BROKEN = {
    "examples.ecommerce.mutations": "decorates a function where a class is expected",
    "examples.enterprise_patterns.mutations": "uses a pydantic FieldInfo as a type",
    "examples.saas-starter.main": "imports fraiseql.Info, which fraiseql doesn't have",
    "examples.security.secure_graphql_api": "uses fraiseql.union, which fraiseql doesn't have",
}


@pytest.mark.parametrize(
    "module",
    [
        *_BUILDABLE,
        *(
            pytest.param(module, marks=pytest.mark.skip(reason=f"example is broken: {reason}"))
            for module, reason in _BROKEN.items()
        ),
    ],
)
def test_example_builds_without_rename_warning(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _BUILD, str(_ROOT), module],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert json.loads(result.stdout.splitlines()[-1])["mutations"] > 0
