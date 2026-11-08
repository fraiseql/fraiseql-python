"""Query depth and complexity limits on the HTTP request path.

``FraiseQLConfig.max_query_depth`` and the ``complexity_*`` settings were
validated and stored, but no request ever checked them: a query of any depth
or size ran.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from graphql import get_introspection_query

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.builders import SchemaRegistry

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.integration

_ran: list[str] = []


@fraiseql.type
class Node:
    id: int
    name: str
    children: list[Node]
    parent: Node | None


def _tree() -> Node:
    root = Node(id=1, name="root", children=[], parent=None)
    root.children = [Node(id=2, name="child", children=[root], parent=root)]
    return root


@fraiseql.query
async def nodes(info, limit: int = 10) -> list[Node]:
    _ran.append("nodes")
    return [_tree()]


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


@pytest.fixture(autouse=True)
def _clean_registry():
    import fraiseql.fastapi.app as app_mod
    import fraiseql.fastapi.dependencies as deps
    from fraiseql.core.graphql_type import _graphql_type_cache

    def _reset() -> None:
        SchemaRegistry.get_instance().clear()
        _graphql_type_cache.clear()
        deps._db_pool = None
        deps._auth_provider = None
        deps._fraiseql_config = None
        app_mod._global_turbo_registry = None
        _ran.clear()

    _reset()
    yield
    _reset()


def _post(query: str, **config: Any) -> dict[str, Any]:
    app = create_fraiseql_app(
        config=FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="development",
            **config,
        ),
        types=[Node],
        queries=[nodes],
        lifespan=_noop_lifespan,
    )
    with TestClient(app) as client:
        return client.post("/graphql", json={"query": query}).json()


def _codes(body: dict[str, Any]) -> list[str]:
    return [(e.get("extensions") or {}).get("code") for e in body.get("errors") or []]


# depth 1: nodes { ... }; each nested object selection adds one
_DEPTH_3 = "{ nodes { children { parent { name } } } }"
_DEPTH_5 = "{ nodes { children { parent { children { parent { name } } } } } }"


def test_a_query_deeper_than_max_query_depth_is_rejected() -> None:
    body = _post(_DEPTH_5, max_query_depth=4)
    assert _codes(body) == ["QUERY_TOO_DEEP"]
    assert body["errors"][0]["extensions"]["depth"] == 5
    assert body["errors"][0]["extensions"]["maxDepth"] == 4
    assert "data" not in body
    assert _ran == []


def test_a_query_at_max_query_depth_runs() -> None:
    body = _post(_DEPTH_3, max_query_depth=3)
    assert "errors" not in body
    assert body["data"]["nodes"][0]["children"][0]["parent"]["name"] == "root"


def test_fragments_count_toward_the_depth() -> None:
    query = """
        query { nodes { ...A } }
        fragment A on Node { children { parent { children { parent { name } } } } }
    """
    assert _codes(_post(query, max_query_depth=4)) == ["QUERY_TOO_DEEP"]
    assert _ran == []


def test_complexity_max_depth_is_enforced_when_set() -> None:
    assert _codes(_post(_DEPTH_5, complexity_max_depth=4)) == ["QUERY_TOO_DEEP"]
    assert _ran == []


def test_the_lower_depth_limit_wins() -> None:
    body = _post(_DEPTH_5, max_query_depth=8, complexity_max_depth=4)
    assert body["errors"][0]["extensions"]["maxDepth"] == 4


def test_a_query_over_complexity_max_score_is_rejected() -> None:
    # nodes (10, the limit default) x children (10, the default list size) x parent
    query = "{ nodes { children { parent { id name } } } }"
    body = _post(query, complexity_max_score=100)
    assert _codes(body) == ["QUERY_TOO_COMPLEX"]
    assert body["errors"][0]["extensions"]["complexity"] == 311
    assert body["errors"][0]["extensions"]["maxComplexity"] == 100
    assert _ran == []


def test_an_explicit_limit_lowers_the_complexity() -> None:
    query = "{ nodes(limit: 1) { children { parent { id name } } } }"
    body = _post(query, complexity_max_score=100)
    assert "errors" not in body, body


def test_a_limit_passed_as_a_variable_counts() -> None:
    query = "query Q($n: Int) { nodes(limit: $n) { children { parent { id name } } } }"
    app = create_fraiseql_app(
        config=FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="development",
            complexity_max_score=100,
        ),
        types=[Node],
        queries=[nodes],
        lifespan=_noop_lifespan,
    )
    with TestClient(app) as client:
        small = client.post("/graphql", json={"query": query, "variables": {"n": 1}}).json()
        large = client.post("/graphql", json={"query": query, "variables": {"n": 50}}).json()
    assert "errors" not in small, small
    assert _codes(large) == ["QUERY_TOO_COMPLEX"]


def test_complexity_enabled_false_turns_the_complexity_limits_off() -> None:
    body = _post(_DEPTH_5, complexity_enabled=False, complexity_max_depth=2)
    assert "errors" not in body, body


def test_introspection_is_not_limited() -> None:
    body = _post(get_introspection_query(), max_query_depth=2, complexity_max_score=10)
    assert "errors" not in body, body
    assert body["data"]["__schema"]["queryType"]["name"] == "Query"


def test_the_defaults_do_not_limit_a_normal_query() -> None:
    query = "{ nodes { children { parent { children { parent { children { name } } } } } } }"
    body = _post(query)
    assert "errors" not in body, body


def test_a_get_request_is_limited_too() -> None:
    app = create_fraiseql_app(
        config=FraiseQLConfig(
            database_url="postgresql://test:test@localhost/test",
            environment="development",
            max_query_depth=4,
        ),
        types=[Node],
        queries=[nodes],
        lifespan=_noop_lifespan,
    )
    with TestClient(app) as client:
        body = client.get("/graphql", params={"query": _DEPTH_5}).json()
    assert _codes(body) == ["QUERY_TOO_DEEP"]
    assert _ran == []
