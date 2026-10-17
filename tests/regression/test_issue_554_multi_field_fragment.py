"""Regression tests for issue #554, against a real PostgreSQL.

A query with more than one root field and a named fragment spread returned the list
field empty, with "Fragment 'X' not found":

    query { products(limit: 2) { ...ProductFields } productsCount }
    fragment ProductFields on Product { id name }

``execute_multi_field_query`` called each root resolver with a hand-built resolve info
whose ``fragments`` was always empty. ``db.find()`` reads its field selection from that
info (``extract_field_paths_from_info``), met the spread and raised. The error was
returned as a partial result, so the graphql-core fallback never ran.

The unit-level reproduction lives in ``tests/unit/fastapi/test_multi_field_fragments.py``.
Fixture shape mirrors ``tests/integration/fastapi/test_issue_448_multi_field_find_one.py``.
"""

import json

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.fastapi.routers import create_graphql_router, execute_multi_field_query
from fraiseql.gql.schema_builder import build_fraiseql_schema

pytestmark = [pytest.mark.integration, pytest.mark.database]

_VIEW = "test_issue554_product_view"

_P1 = "00000000-0000-0000-0000-000000000001"
_P2 = "00000000-0000-0000-0000-000000000002"

_QUERY = """
query { products(limit: 2) { ...ProductFields } productsCount }
fragment ProductFields on Product { id name }
"""


@fraiseql.type
class Product:
    """Product entity backed by a JSONB view."""

    id: str
    name: str
    color: str


def _repo(info) -> FraiseQLRepository:
    return FraiseQLRepository(info.context.get("pool"), context={"mode": "development"})


@fraiseql.query
async def products(info, limit: int = 10) -> list[Product]:
    """List lookup through db.find(), which reads the selection from info."""
    return await _repo(info).find(_VIEW, info=info, limit=limit)


@fraiseql.query
async def products_count(info) -> int:
    """Scalar sibling root field."""
    return await _repo(info).count(_VIEW)


class TestIssue554MultiFieldFragment:
    """Named fragment spreads must resolve in multi-field queries backed by db.find()."""

    @pytest.fixture(scope="class")
    def clear_registry_fixture(self, clear_registry_class) -> None:
        """Clear registry before the class runs."""
        return

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_data(self, class_db_pool, test_schema) -> None:
        """Create the JSONB table and view, and seed two products."""
        register_type_for_view(
            _VIEW,
            Product,
            table_columns={"id", "name", "data"},
            has_jsonb_data=True,
            jsonb_column="data",
        )

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_issue554_product (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL,
                    data JSONB NOT NULL
                )
                """
            )
            await conn.execute(
                f"""
                CREATE OR REPLACE VIEW {_VIEW} AS
                SELECT
                    id,
                    name,
                    jsonb_build_object(
                        'id', id,
                        'name', name,
                        'color', data->>'color'
                    ) AS data
                FROM test_issue554_product
                """
            )
            await conn.execute(
                f"""
                INSERT INTO test_issue554_product (id, name, data)
                VALUES
                    ('{_P1}', 'Widget', '{{"color": "red"}}'),
                    ('{_P2}', 'Gadget', '{{"color": "blue"}}')
                ON CONFLICT (id) DO NOTHING
                """
            )
            await conn.commit()

        yield

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            await conn.execute(f"DROP VIEW IF EXISTS {_VIEW}")
            await conn.execute("DROP TABLE IF EXISTS test_issue554_product")
            await conn.commit()

    @pytest.fixture
    def schema(self):
        return build_fraiseql_schema(query_types=[products, products_count])

    @pytest.fixture
    def app(self, class_db_pool, schema) -> FastAPI:
        """Build a real FastAPI app whose context injects the test pool."""
        from fraiseql.fastapi.dependencies import set_db_pool, set_fraiseql_config

        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost:5432/test",
            environment="development",
        )
        set_db_pool(class_db_pool)
        set_fraiseql_config(config)

        async def context_getter(request) -> dict:
            return {"pool": class_db_pool}

        router = create_graphql_router(schema=schema, config=config, context_getter=context_getter)
        fastapi_app = FastAPI()
        fastapi_app.include_router(router)

        yield fastapi_app

        set_db_pool(None)
        set_fraiseql_config(None)

    @staticmethod
    def _assert_products(body: dict) -> None:
        assert "errors" not in body, body
        data = body["data"]
        assert {p["id"] for p in data["products"]} == {_P1, _P2}
        assert {p["name"] for p in data["products"]} == {"Widget", "Gadget"}
        assert data["productsCount"] == 2

    @pytest.mark.asyncio
    async def test_fragment_spread_over_http(self, class_db_pool, setup_data, app) -> None:
        """The reporter's query, through POST /graphql."""
        response = TestClient(app).post("/graphql", json={"query": _QUERY})

        assert response.status_code == 200, response.text
        self._assert_products(response.json())

    @pytest.mark.asyncio
    async def test_fragment_spread_direct(self, class_db_pool, setup_data, schema) -> None:
        """The reporter's query, through execute_multi_field_query directly.

        The HTTP route could mask a failure here by falling back to graphql-core, so the
        merge path is also checked on its own.
        """
        context = {"pool": class_db_pool, "__has_multiple_root_fields__": True}
        result = await execute_multi_field_query(schema, _QUERY, None, context)

        self._assert_products(json.loads(bytes(result)))
