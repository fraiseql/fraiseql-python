"""Regression tests for issue #448.

A multi-field GraphQL query crashes when one top-level field is ``find_one()``-backed
and it is combined with *any* sibling top-level field.

Two independent root causes (see
``.phases/2026-07-28_issue-448-multifield-findone/``):

* **Bug A** — ``find_one()`` calls ``_is_rust_response_null(result)`` on a plain
  ``dict``/``list`` in field-only mode (``include_wrapper=False``, i.e. any multi-field
  query), which does ``result.bytes`` and raises
  ``'dict' object has no attribute 'bytes'``.
* **Bug B** — a scalar top-level resolver (e.g. a count) yields ``json_rows=[<int>]``;
  the Rust FFI (``Vec<String>``) rejects the raw int at argument-extraction time with
  ``TypeError: 'int' object is not an instance of 'str'``, aborting the whole merge.
"""

import json
from unittest.mock import AsyncMock, Mock, patch

import fraiseql._fraiseql_rs as fraiseql_rs
import pytest
from graphql import (
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)

from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.db import FraiseQLRepository
from fraiseql.fastapi.routers import execute_multi_field_query


@pytest.fixture(scope="module", autouse=True)
def _init_schema_registry() -> None:
    """Register a minimal ``Thing`` type so object-field transforms resolve."""
    fraiseql_rs.reset_schema_registry_for_testing()
    schema_ir = {
        "version": "1.0",
        "features": ["type_resolution"],
        "types": {
            "Thing": {
                "fields": {
                    "id": {"type_name": "Int", "is_nested_object": False, "is_list": False},
                    "name": {"type_name": "String", "is_nested_object": False, "is_list": False},
                }
            },
        },
    }
    fraiseql_rs.initialize_schema_registry(json.dumps(schema_ir))


# ---------------------------------------------------------------------------
# Bug B — the Rust FFI contract for multi-field rows
# ---------------------------------------------------------------------------


def test_ffi_rejects_raw_scalar_row() -> None:
    """Documents the FFI contract: json_rows must be strings, not raw scalars.

    This is the root of Bug B — the Python executor must JSON-encode scalar rows
    before crossing the FFI. Kept as a guard so the contract can't silently drift.
    """
    with pytest.raises(TypeError, match="'int' object is not an instance of 'str'"):
        fraiseql_rs.build_multi_field_response([("count", "Int", [284], None, False)])


@pytest.mark.parametrize(
    ("value", "expected"),
    [(284, 284), ("active", "active"), (True, True), (3.14, 3.14), (None, None)],
)
def test_ffi_round_trips_json_encoded_scalar_rows(value, expected) -> None:
    """Rust already transforms scalar ``type_name``s correctly — no Rust change needed."""
    row = json.dumps(value)
    result = fraiseql_rs.build_multi_field_response([("count", "Int", [row], None, False)])
    assert json.loads(bytes(result)) == {"data": {"count": expected}}


# ---------------------------------------------------------------------------
# Bug B — through the Python multi-field executor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_field_two_scalar_siblings_merge() -> None:
    """Two scalar root fields must merge via the Rust path, not raise (Bug B)."""

    async def count_resolver(info):
        return 284

    async def total_resolver(info):
        return 100

    query_type = GraphQLObjectType(
        "Query",
        {
            "count": GraphQLField(GraphQLInt, resolve=count_resolver),
            "total": GraphQLField(GraphQLInt, resolve=total_resolver),
        },
    )
    schema = GraphQLSchema(query=query_type)

    result = await execute_multi_field_query(schema, "{ count total }", None, {})

    assert isinstance(result, RustResponseBytes)
    assert json.loads(bytes(result))["data"] == {"count": 284, "total": 100}


@pytest.mark.asyncio
async def test_multi_field_object_plus_scalar_sibling_merge() -> None:
    """Object field + scalar sibling — the reporter's exact shape (Bug B)."""

    async def things_resolver(info):
        return [{"id": 1, "name": "widget"}]

    async def things_count_resolver(info):
        return 284

    thing_type = GraphQLObjectType(
        "Thing",
        {"id": GraphQLField(GraphQLInt), "name": GraphQLField(GraphQLString)},
    )
    query_type = GraphQLObjectType(
        "Query",
        {
            "things": GraphQLField(GraphQLList(thing_type), resolve=things_resolver),
            "thingsCount": GraphQLField(GraphQLInt, resolve=things_count_resolver),
        },
    )
    schema = GraphQLSchema(query=query_type)

    result = await execute_multi_field_query(schema, "{ things { id name } thingsCount }", None, {})

    assert isinstance(result, RustResponseBytes)
    data = json.loads(bytes(result))["data"]
    assert data["thingsCount"] == 284
    assert len(data["things"]) == 1
    assert data["things"][0]["id"] == 1


# ---------------------------------------------------------------------------
# Bug A — find_one() in field-only mode (multi-field query)
# ---------------------------------------------------------------------------


def _mock_repo(*, multi_field: bool) -> FraiseQLRepository:
    """Build a repository whose pool/connection are mocked (no real DB)."""
    mock_conn = AsyncMock()
    mock_pool = Mock()
    mock_pool.connection.return_value = AsyncMock()
    mock_pool.connection.return_value.__aenter__.return_value = mock_conn
    # __aexit__ must return falsy: a truthy value would SUPPRESS exceptions raised
    # inside the `async with`, masking the very crash this test targets (Bug A).
    mock_pool.connection.return_value.__aexit__.return_value = False

    mock_info = Mock()
    mock_info.field_name = "thing"
    mock_info.field_nodes = []  # empty -> skip field-path extraction
    mock_info.context = {"__has_multiple_root_fields__": True} if multi_field else {}

    return FraiseQLRepository(mock_pool, context={"graphql_info": mock_info})


@pytest.mark.asyncio
async def test_find_one_field_only_found_returns_dict() -> None:
    """Bug A: field-only mode returns a dict; find_one must not treat it as bytes."""
    repo = _mock_repo(multi_field=True)
    field_only = {"__typename": "Thing", "id": 1, "name": "widget"}

    with patch("fraiseql.db.execute_via_rust_pipeline") as mock_exec:
        mock_exec.return_value = field_only  # field-only mode returns a plain dict
        result = await repo.find_one("tv_thing")

    assert result == field_only


@pytest.mark.asyncio
async def test_find_one_field_only_not_found_returns_none() -> None:
    """Bug A: field-only not-found is the empty list ``[]`` -> None (no crash)."""
    repo = _mock_repo(multi_field=True)

    with patch("fraiseql.db.execute_via_rust_pipeline") as mock_exec:
        mock_exec.return_value = []  # field-only null sentinel
        result = await repo.find_one("tv_thing")

    assert result is None


@pytest.mark.asyncio
async def test_find_one_wrapped_mode_unchanged() -> None:
    """Single-field path (include_wrapper=True) still returns bytes / None as before."""
    repo = _mock_repo(multi_field=False)

    found = RustResponseBytes(b'{"data":{"thing":{"id":"123"}}}')
    with patch("fraiseql.db.execute_via_rust_pipeline") as mock_exec:
        mock_exec.return_value = found
        result = await repo.find_one("tv_thing")
    assert result is found

    not_found = RustResponseBytes(b'{"data":{"thing":[]}}')
    with patch("fraiseql.db.execute_via_rust_pipeline") as mock_exec:
        mock_exec.return_value = not_found
        result = await repo.find_one("tv_thing")
    assert result is None
