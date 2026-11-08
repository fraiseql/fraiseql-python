"""How ``QueryLimits`` measures a query's depth (no database, no HTTP)."""

import time

import pytest
from graphql import build_schema

from fraiseql.gql.query_limits import QueryLimits

_SCHEMA = build_schema(
    """
    type Node {
      id: Int!
      name: String
      children(limit: Int): [Node!]!
      parent: Node
    }
    union Thing = Node
    type Query {
      nodes(limit: Int = 10): [Node!]!
      node: Node
      thing: Thing
    }
    """
)


def _depth(query: str, **kwargs) -> int:
    cost = QueryLimits().measure(_SCHEMA, query, **kwargs)
    assert cost is not None
    return cost.depth


@pytest.mark.parametrize(
    ("query", "depth"),
    [
        ("{ __typename }", 0),
        ("{ node { id } }", 1),
        ("{ node { parent { id } } }", 2),
        ("{ node { parent { id } children { parent { id } } } }", 3),
        ("{ thing { ... on Node { parent { id } } } }", 2),
        ("{ node { ...F } } fragment F on Node { parent { parent { id } } }", 3),
        # unknown fields still count: validation rejects them later
        ("{ node { nope { deeper { id } } } }", 3),
    ],
)
def test_depth(query: str, depth: int) -> None:
    assert _depth(query) == depth


def test_introspection_fields_are_not_counted() -> None:
    assert _depth("{ __schema { types { fields { type { ofType { name } } } } } }") == 0
    assert _depth('{ __type(name: "Node") { fields { type { name } } } }') == 0


def test_the_named_operation_is_measured() -> None:
    query = "query A { node { id } } query B { node { parent { parent { id } } } }"
    assert _depth(query, operation_name="A") == 1
    assert _depth(query, operation_name="B") == 3
    assert _depth(query) == 3  # no name: the deepest one


def test_a_query_that_does_not_parse_is_left_to_execution() -> None:
    assert QueryLimits(max_depth=1).measure(_SCHEMA, "{ node {") is None
    assert QueryLimits(max_depth=1).check(_SCHEMA, "{ node {") is None
    assert QueryLimits(max_depth=1).measure(_SCHEMA, "{ node { id } }", "Missing") is None


def test_cyclic_fragments_do_not_recurse_forever() -> None:
    query = "{ node { ...A } } fragment A on Node { parent { ...B } } fragment B on Node { ...A }"
    assert _depth(query) == 2


def test_nested_fragment_spreads_are_measured_once_each() -> None:
    # each fragment spreads the next one twice: 2**40 paths if walked naively
    fragments = [
        f"fragment F{i} on Node {{ parent {{ ...F{i + 1} }} children {{ ...F{i + 1} }} }}"
        for i in range(40)
    ]
    query = "{ node { ...F0 } } " + " ".join(fragments) + " fragment F40 on Node { id }"
    started = time.perf_counter()
    assert _depth(query) == 41
    assert time.perf_counter() - started < 1


def test_check_reports_the_depth() -> None:
    error = QueryLimits(max_depth=1).check(_SCHEMA, "{ node { parent { id } } }")
    assert error is not None
    assert error["errors"][0]["extensions"] == {
        "code": "QUERY_TOO_DEEP",
        "depth": 2,
        "maxDepth": 1,
    }
    assert QueryLimits(max_depth=2).check(_SCHEMA, "{ node { parent { id } } }") is None


def _complexity(query: str, **limits) -> int:
    cost = QueryLimits(**limits).measure(_SCHEMA, query)
    assert cost is not None
    return cost.complexity


@pytest.mark.parametrize(
    ("query", "complexity"),
    [
        ("{ __typename }", 0),
        ("{ node { id name } }", 3),  # 1 + (1 + 1)
        ("{ node { parent { id } } }", 3),  # 1 + (1 + 1)
        ("{ nodes { id } }", 11),  # 1 + 10 (the limit default) * 1
        ("{ nodes(limit: 2) { id } }", 3),
        ("{ node { children { id } } }", 12),  # children: 1 + 10 (default list size) * 1
        ("{ node { children(limit: 3) { id name } } }", 8),
        ("{ __schema { types { name } } }", 0),
    ],
)
def test_complexity(query: str, complexity: int) -> None:
    assert _complexity(query) == complexity


def test_the_default_list_size_applies_without_a_limit() -> None:
    assert _complexity("{ node { children { id } } }", default_list_size=4) == 6


def test_field_multipliers_by_name_or_type_and_name() -> None:
    assert _complexity("{ node { name } }", field_multipliers={"name": 5}) == 6
    assert _complexity("{ node { name } }", field_multipliers={"Node.name": 7}) == 8


def test_check_reports_the_complexity() -> None:
    error = QueryLimits(max_complexity=10).check(_SCHEMA, "{ nodes { id } }")
    assert error is not None
    assert error["errors"][0]["extensions"] == {
        "code": "QUERY_TOO_COMPLEX",
        "complexity": 11,
        "maxComplexity": 10,
    }
