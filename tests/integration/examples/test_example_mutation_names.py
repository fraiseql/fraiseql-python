"""Examples build without the mutation rename warning.

Users copy the examples, so an example whose mutations are named by the legacy
rule (after ``function=`` or the success type) teaches them code that warns on
first run. Each example is imported and
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
    "error", message="These mutations are named by fraiseql's legacy rule", category=FutureWarning
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
    "examples.blog_simple.models",
    "examples.context_parameters.mutations",
    "examples.graphql-cascade.main",
    "examples.mutations_demo.demo",
    "examples.native_auth_app",
    "examples.quickstart_5min",
    "examples.saas-starter.main",
    "examples.security.secure_graphql_api",
    "examples.todo_quickstart",
    "examples.where_input_filtering_example",
]

# Examples with mutations that don't build on the current API. Their mutation
# names already follow the preferred rule; move one to _BUILDABLE once it builds.
_BROKEN = {
    "examples.ecommerce.mutations": "Decimal fields: builds with #575's Decimal scalar",
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
