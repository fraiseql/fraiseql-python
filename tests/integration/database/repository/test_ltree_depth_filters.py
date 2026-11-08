"""ltree depth filters (nlevel_* and their depth_* aliases) through db.find.

Each operator compares nlevel(path), the number of labels in the path, with the
value. They rendered invalid SQL: depth_* as ``"path" depth > %s`` (a path
operator map overrode the ltree one) and nlevel_* as ``"path" nlevel({}) > %s``
(the function template was never filled in).
"""

import pytest
import pytest_asyncio

pytestmark = pytest.mark.database

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.sql.where_generator import safe_create_where_type
from fraiseql.types import LTree

# Paths of depth 1 to 4: a, a.b, a.b.c, a.b.c.d
_DEPTHS = {"a": 1, "a.b": 2, "a.b.c": 3, "a.b.c.d": 4}

# Operator -> the depths it keeps when compared with 2
_EXPECTED = {
    "nlevel": {2},
    "nlevel_eq": {2},
    "nlevel_neq": {1, 3, 4},
    "nlevel_gt": {3, 4},
    "nlevel_gte": {2, 3, 4},
    "nlevel_lt": {1},
    "nlevel_lte": {1, 2},
    "depth_eq": {2},
    "depth_neq": {1, 3, 4},
    "depth_gt": {3, 4},
    "depth_gte": {2, 3, 4},
    "depth_lt": {1},
    "depth_lte": {1, 2},
}


class TestLTreeDepthFilters:
    @pytest.fixture(scope="class")
    def node_types(self, clear_registry_class):
        @fraiseql.type(sql_source="ltree_node_column_view")
        class ColumnNode:
            id: int
            path: LTree

        @fraiseql.type(sql_source="ltree_node_json_view")
        class JsonNode:
            id: int
            path: LTree

        return {"ColumnNode": ColumnNode, "JsonNode": JsonNode}

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def ltree_views(self, class_db_pool, test_schema, node_types):
        # path is a real ltree column in the first view, a JSONB key in the second
        register_type_for_view(
            "ltree_node_column_view",
            node_types["ColumnNode"],
            table_columns={"id", "path", "data"},
        )
        register_type_for_view("ltree_node_json_view", node_types["JsonNode"])

        async with class_db_pool.connection() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS ltree SCHEMA public")
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute("CREATE TABLE ltree_nodes (id INT PRIMARY KEY, path ltree)")
            await conn.execute(
                "INSERT INTO ltree_nodes VALUES (1, 'a'), (2, 'a.b'), (3, 'a.b.c'), (4, 'a.b.c.d')"
            )
            await conn.execute(
                """
                CREATE VIEW ltree_node_column_view AS
                SELECT id, path, jsonb_build_object('id', id, 'path', path) AS data
                FROM ltree_nodes
                """
            )
            await conn.execute(
                """
                CREATE VIEW ltree_node_json_view AS
                SELECT id, jsonb_build_object('id', id, 'path', path) AS data
                FROM ltree_nodes
                """
            )
            await conn.commit()
        yield

    async def _depths(self, pool, view: str, where) -> set[int]:
        repo = FraiseQLRepository(pool, context={"mode": "development"})
        rows = extract_graphql_data(await repo.find(view, where=where), view)
        return {_DEPTHS[row["path"]] for row in rows}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("operator", sorted(_EXPECTED))
    @pytest.mark.parametrize("view", ["ltree_node_column_view", "ltree_node_json_view"])
    async def test_depth_operator_on_dict_where(
        self, class_db_pool, ltree_views, view: str, operator: str
    ) -> None:
        depths = await self._depths(class_db_pool, view, {"path": {operator: 2}})

        assert depths == _EXPECTED[operator]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("operator", ["depth_gt", "depth_lte", "nlevel_eq"])
    async def test_depth_operator_on_generated_where_type(
        self, class_db_pool, ltree_views, node_types, operator: str
    ) -> None:
        # The where input GraphQL clients send, as fraiseql generates it
        where_type = safe_create_where_type(node_types["ColumnNode"])
        where = where_type(path={operator: 2})

        depths = await self._depths(class_db_pool, "ltree_node_column_view", where)

        assert depths == _EXPECTED[operator]
