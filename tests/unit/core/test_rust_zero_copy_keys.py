"""The zero-copy response path camelCases keys through one scratch buffer (#579).

build_graphql_response takes the zero-copy path when it has no type name. Its
keys used to be converted into a bump arena; they are now converted into a
buffer the transformer reuses, and the arena and its Python test exports are
gone.
"""

import json
from typing import Any

import pytest

from fraiseql import _get_fraiseql_rs


@pytest.fixture
def rs() -> Any:
    module = _get_fraiseql_rs()
    if module is None:
        pytest.skip("Rust extension not available")
    return module


def _rows(rs: Any, rows: list[dict]) -> list[dict]:
    out = rs.build_graphql_response(
        [json.dumps(row) for row in rows], "items", None, None, None, True
    )
    return json.loads(bytes(out))["data"]["items"]


def test_keys_are_camel_cased(rs: Any) -> None:
    rows = _rows(
        rs, [{"user_name": "a", "address_line_1": "b", "a_1b": 1, "nested_obj": {"x_y": 2}}]
    )

    assert rows == [{"userName": "a", "addressLine1": "b", "a1b": 1, "nestedObj": {"xY": 2}}]


def test_each_row_keeps_its_own_keys(rs: Any) -> None:
    rows = [{f"field_{i}_{'x' * (i % 40)}": i} for i in range(200)]

    converted = _rows(rs, rows)

    assert [next(iter(row)) for row in converted] == [
        f"field{i}{'X' if i % 40 else ''}{'x' * max(i % 40 - 1, 0)}" for i in range(200)
    ]


def test_arena_test_exports_are_gone(rs: Any) -> None:
    assert not hasattr(rs, "Arena")
    assert not hasattr(rs, "test_snake_to_camel")
