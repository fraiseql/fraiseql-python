"""Every ltree filter works on a JSONB field and on a native ltree column.

``data ->> 'path'`` is text, and the hierarchy and pattern operators were written
with an untyped value: ``(data ->> 'path') <@ %s`` failed with ``operator is not
unique: text <@ unknown`` (``descendant_of``, ``in_array``), ``text @> unknown``
(``ancestor_of``), and likewise for ``matches_ltxtquery`` / ``matches_any_lquery``;
``in_array`` failed on a native column too. Both sides are cast now. A JSONB
field declared ``LTree`` also compares as ``ltree`` (``eq``, ``lt``, ``in``...):
as text, ``top.sciences`` sorts before ``top.science.zoology``.
"""

import json

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.sql import create_graphql_where_input
from fraiseql.types import LTree

pytestmark = [pytest.mark.integration, pytest.mark.database]

_PATHS = {
    1: "top",
    2: "top.science",
    3: "top.science.zoology",
    4: "top.art",
    5: "top.sciences",
}

# (operator, Python value, GraphQL value, expected ids)
_CASES = [
    ("eq", "top.science", '"top.science"', [2]),
    ("neq", "top.science", '"top.science"', [1, 3, 4, 5]),
    # ltree order: top < top.art < top.science < top.science.zoology < top.sciences
    ("lt", "top.sciences", '"top.sciences"', [1, 2, 3, 4]),
    ("lte", "top.science", '"top.science"', [1, 2, 4]),
    ("gt", "top.science", '"top.science"', [3, 5]),
    ("gte", "top.science.zoology", '"top.science.zoology"', [3, 5]),
    ("in", ["top.science", "top.art"], '["top.science", "top.art"]', [2, 4]),
    ("nin", ["top.science"], '["top.science"]', [1, 3, 4, 5]),
    ("isnull", False, "false", [1, 2, 3, 4, 5]),
    ("ancestor_of", "top.science.zoology", '"top.science.zoology"', [1, 2, 3]),
    ("descendant_of", "top.science", '"top.science"', [2, 3]),
    ("isdescendant", "top.science", '"top.science"', [2, 3]),
    ("matches_lquery", "*.science.*", '"*.science.*"', [2, 3]),
    ("matches_ltxtquery", "zoology | art", '"zoology | art"', [3, 4]),
    ("matches_any_lquery", ["top.art", "*.zoology"], '["top.art", "*.zoology"]', [3, 4]),
    ("in_array", ["top.art", "top.science"], '["top.art", "top.science"]', [2, 3, 4]),
    ("nlevel", 2, "2", [2, 4, 5]),
    ("nlevel_eq", 2, "2", [2, 4, 5]),
    ("nlevel_neq", 2, "2", [1, 3]),
    ("nlevel_gt", 2, "2", [3]),
    ("nlevel_gte", 2, "2", [2, 3, 4, 5]),
    ("nlevel_lt", 2, "2", [1]),
    ("nlevel_lte", 2, "2", [1, 2, 4, 5]),
    ("depth_eq", 3, "3", [3]),
    ("depth_gt", 1, "1", [2, 3, 4, 5]),
    ("index_eq", ("zoology", 2), '{label: "zoology", position: 2}', [3]),
    ("index_gte", ("science", 1), '{label: "science", position: 1}', [2, 3]),
    # lca: the path is the lowest common ancestor of the given paths
    (
        "lca",
        ["top.science.zoology", "top.sciences"],
        '["top.science.zoology", "top.sciences"]',
        [1],
    ),
]


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def category_tables(class_db_pool, test_schema) -> None:
    values = ", ".join(f"({i}, '{p}')" for i, p in _PATHS.items())
    async with class_db_pool.connection() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS ltree")
        await conn.execute(
            f"""
            CREATE TABLE {test_schema}.tb_lt_category (id int PRIMARY KEY, path ltree NOT NULL);
            INSERT INTO {test_schema}.tb_lt_category VALUES {values};
            CREATE VIEW {test_schema}.v_lt_category AS
                SELECT id, jsonb_build_object('id', id, 'path', path) AS data
                FROM {test_schema}.tb_lt_category;
            CREATE VIEW {test_schema}.v_lt_flat_category AS
                SELECT id, path FROM {test_schema}.tb_lt_category;
            """
        )
        await conn.commit()


@pytest.fixture
def category_types(test_schema, clear_registry):
    @fraiseql.type(sql_source=f"{test_schema}.v_lt_category", jsonb_column="data")
    class LtCategory:
        id: int
        path: LTree

    @fraiseql.type(sql_source=f"{test_schema}.v_lt_flat_category", jsonb_column=None)
    class LtFlatCategory:
        id: int
        path: LTree

    return LtCategory, LtFlatCategory


@pytest.fixture
def client(class_db_pool, test_schema, category_tables, category_types) -> TestClient:
    from fraiseql.fastapi.dependencies import set_db_pool

    jsonb_type, flat_type = category_types
    jsonb_where = create_graphql_where_input(jsonb_type)
    flat_where = create_graphql_where_input(flat_type)

    @fraiseql.query
    async def lt_categories(info, where: jsonb_where | None = None) -> list[jsonb_type]:
        return await info.context["db"].find(
            f"{test_schema}.v_lt_category", "ltCategories", info, where=where
        )

    @fraiseql.query
    async def lt_flat_categories(info, where: flat_where | None = None) -> list[flat_type]:
        return await info.context["db"].find(
            f"{test_schema}.v_lt_flat_category", "ltFlatCategories", info, where=where
        )

    set_db_pool(class_db_pool)

    async def context_getter(request, user=None):
        return {"db": FraiseQLRepository(class_db_pool), "user": user}

    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[jsonb_type, flat_type],
        queries=[lt_categories, lt_flat_categories],
        production=False,
        context_getter=context_getter,
    )
    return TestClient(app)


_ROOTS = ["ltCategories", "ltFlatCategories"]
_VIEWS = ["v_lt_category", "v_lt_flat_category"]


@pytest.mark.usefixtures("test_schema")
class TestLTreeWhereGraphQL:
    @pytest.mark.parametrize("root", _ROOTS)
    @pytest.mark.parametrize(
        ("op", "_value", "gql", "expected"), _CASES, ids=[c[0] for c in _CASES]
    )
    def test_operator(self, client: TestClient, root, op, _value, gql, expected) -> None:
        name = "isdescendant" if op == "isdescendant" else _camel(op)
        query = f"{{ {root}(where: {{path: {{{name}: {gql}}}}}) {{ id }} }}"
        response = client.post("/graphql", json={"query": query})
        body = json.loads(response.text)

        assert "errors" not in body, body["errors"]
        assert sorted(row["id"] for row in body["data"][root]) == expected


@pytest.mark.usefixtures("test_schema")
class TestLTreeWhereDictFind:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("view", _VIEWS)
    @pytest.mark.parametrize(
        ("op", "value", "_gql", "expected"), _CASES, ids=[c[0] for c in _CASES]
    )
    async def test_operator(
        self,
        class_db_pool,
        test_schema,
        category_tables,
        category_types,
        view,
        op,
        value,
        _gql,
        expected,
    ) -> None:
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})
        result = await repo.find(f"{test_schema}.{view}", where={"path": {op: value}})
        rows = extract_graphql_data(result, f"{test_schema}.{view}")

        assert sorted(row["id"] for row in rows) == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize("op", ["matches_any_lquery", "in_array"])
    async def test_list_operator_takes_a_list(
        self, class_db_pool, test_schema, category_tables, category_types, op
    ) -> None:
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})
        with pytest.raises(ValueError, match=f"'{op}' takes a non-empty list"):
            await repo.find(f"{test_schema}.v_lt_category", where={"path": {op: "top"}})
