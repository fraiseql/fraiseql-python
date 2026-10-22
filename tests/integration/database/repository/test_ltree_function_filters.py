"""ltree filters built on ltree functions (index, lca) through db.find.

``index_eq`` / ``index_gte`` (a label and a position), and ``lca`` (a list of
paths), rendered invalid SQL such as ``"path" index = %s``. ``subpath``,
``index`` and ``concat`` compute a path or a number, not a condition: they are
rejected with a message instead of reaching PostgreSQL.
"""

import pytest
import pytest_asyncio

pytestmark = pytest.mark.database

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.types import LTree

_PATHS = ["a", "a.b", "a.b.c", "b.a", "x.y.b"]

_VIEWS = ["ltree_fn_column_view", "ltree_fn_json_view"]


class TestLTreeFunctionFilters:
    @pytest.fixture(scope="class")
    def node_types(self, clear_registry_class):
        @fraiseql.type(sql_source="ltree_fn_column_view")
        class ColumnFnNode:
            id: int
            path: LTree

        @fraiseql.type(sql_source="ltree_fn_json_view")
        class JsonFnNode:
            id: int
            path: LTree

        return {"ColumnFnNode": ColumnFnNode, "JsonFnNode": JsonFnNode}

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def ltree_views(self, class_db_pool, test_schema, node_types):
        # path is a real ltree column in the first view, a JSONB key in the second
        register_type_for_view(
            "ltree_fn_column_view",
            node_types["ColumnFnNode"],
            table_columns={"id", "path", "data"},
        )
        register_type_for_view("ltree_fn_json_view", node_types["JsonFnNode"])

        async with class_db_pool.connection() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS ltree SCHEMA public")
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute("CREATE TABLE ltree_fn_nodes (id INT PRIMARY KEY, path ltree)")
            for i, path in enumerate(_PATHS):
                await conn.execute("INSERT INTO ltree_fn_nodes VALUES (%s, %s)", (i, path))
            await conn.execute(
                """
                CREATE VIEW ltree_fn_column_view AS
                SELECT id, path, jsonb_build_object('id', id, 'path', path) AS data
                FROM ltree_fn_nodes
                """
            )
            await conn.execute(
                """
                CREATE VIEW ltree_fn_json_view AS
                SELECT id, jsonb_build_object('id', id, 'path', path) AS data
                FROM ltree_fn_nodes
                """
            )
            await conn.commit()
        yield

    async def _paths(self, pool, view: str, where) -> set[str]:
        repo = FraiseQLRepository(pool, context={"mode": "development"})
        rows = extract_graphql_data(await repo.find(view, where=where), view)
        return {row["path"] for row in rows}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("operator", "value", "expected"),
        [
            # index(path, 'b') is the position of label b, -1 without it
            ("index_eq", ("b", 1), {"a.b", "a.b.c"}),
            ("index_eq", ["b", 0], {"b.a"}),
            ("index_gte", ("b", 1), {"a.b", "a.b.c", "x.y.b"}),
            ("index_gte", ("b", 0), {"a.b", "a.b.c", "b.a", "x.y.b"}),
            ("index_eq", ("a.b", 0), {"a.b", "a.b.c"}),
            # lca(a.b.c, a.b.x) is a.b
            ("lca", ["a.b.c", "a.b.x"], {"a.b"}),
            ("lca", ["b.a", "x.y.b"], set()),
        ],
    )
    @pytest.mark.parametrize("view", _VIEWS)
    async def test_filter(self, class_db_pool, ltree_views, view, operator, value, expected):
        assert await self._paths(class_db_pool, view, {"path": {operator: value}}) == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("operator", "value"),
        [
            ("subpath", (0, 2)),
            ("index", "b"),
            ("concat", "z"),
            ("index_eq", 1),
            ("index_gte", "b"),
            ("lca", "a.b"),
            ("lca", []),
        ],
    )
    @pytest.mark.parametrize("view", _VIEWS)
    async def test_rejected(self, class_db_pool, ltree_views, view, operator, value):
        with pytest.raises(ValueError, match=operator):
            await self._paths(class_db_pool, view, {"path": {operator: value}})

    @pytest.mark.parametrize(
        ("where", "expected"),
        [
            ('{path: {indexEq: {label: "b", position: 1}}}', {"a.b", "a.b.c"}),
            ('{path: {indexGte: {label: "b", position: 1}}}', {"a.b", "a.b.c", "x.y.b"}),
            ('{path: {lca: ["a.b.c", "a.b.x"]}}', {"a.b"}),
        ],
    )
    def test_graphql(self, class_db_pool, ltree_views, node_types, where, expected) -> None:
        body = (
            self._client(class_db_pool, node_types)
            .post("/graphql", json={"query": f"{{ nodes(where: {where}) {{ path }} }}"})
            .json()
        )

        assert "errors" not in body, body
        assert {node["path"] for node in body["data"]["nodes"]} == expected

    def test_graphql_rejects_a_non_filter(self, class_db_pool, ltree_views, node_types) -> None:
        body = (
            self._client(class_db_pool, node_types)
            .post("/graphql", json={"query": '{ nodes(where: {path: {concat: "z"}}) { path } }'})
            .json()
        )

        assert "is not a filter" in body["errors"][0]["message"]

    def _client(self, pool, node_types):
        from fastapi.testclient import TestClient

        from fraiseql.fastapi import create_fraiseql_app
        from fraiseql.fastapi.dependencies import set_db_pool

        if not hasattr(type(self), "_app"):
            column_node = node_types["ColumnFnNode"]

            @fraiseql.query
            async def nodes(info, where=None) -> list[column_node]:
                db = info.context["db"]
                return await db.find("ltree_fn_column_view", info=info, where=where)

            set_db_pool(pool)
            type(self)._app = create_fraiseql_app(
                database_url="postgresql://test/test",  # the pool above is used
                types=[column_node],
                queries=[nodes],
                production=False,
            )
        return TestClient(type(self)._app)
