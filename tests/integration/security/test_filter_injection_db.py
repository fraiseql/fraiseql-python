"""Authorization filter injection against a real PostgreSQL view (issue #362, phase 5)."""

import pytest
import pytest_asyncio

pytestmark = pytest.mark.database

from tests.fixtures.database.database_conftest import *  # noqa: F403
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.sql.where_generator import safe_create_where_type


class TestFilterInjectionAgainstView:
    """Row scoping: authorization filters in repo context reach SQL and scope rows."""

    @pytest.fixture(scope="class")
    def test_types(self, clear_registry_class):
        @fraiseql.type
        class Widget:
            id: str
            name: str

        return {"Widget": Widget, "WidgetWhere": safe_create_where_type(Widget)}

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_view(self, class_db_pool, test_schema, test_types) -> None:
        Widget = test_types["Widget"]
        register_type_for_view("test_widget_view", Widget)

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute(
                """
                CREATE TABLE test_widgets (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE VIEW test_widget_view AS
                SELECT
                    id, tenant_id, name,
                    jsonb_build_object('id', id, 'name', name) AS data
                FROM test_widgets
                """
            )
            await conn.execute(
                """
                INSERT INTO test_widgets (id, tenant_id, name) VALUES
                    ('w1', 'A', 'Alpha'),
                    ('w2', 'A', 'Beta'),
                    ('w3', 'B', 'Gamma')
                """
            )
            await conn.commit()
        yield

    def _repo(self, pool, *, auth_filters=None):
        context = {"mode": "development", "graphql_field_name": "widgets"}
        if auth_filters is not None:
            context["_fraiseql_auth_filters"] = {"widgets": auth_filters}
        return FraiseQLRepository(pool, context=context)

    @pytest.mark.asyncio
    async def test_no_scope_returns_all_rows(self, class_db_pool, setup_view) -> None:
        repo = self._repo(class_db_pool)
        result = await repo.find("test_widget_view")
        rows = extract_graphql_data(result, "test_widget_view")
        assert {r["name"] for r in rows} == {"Alpha", "Beta", "Gamma"}

    @pytest.mark.asyncio
    async def test_auth_filter_scopes_rows(self, class_db_pool, setup_view) -> None:
        repo = self._repo(class_db_pool, auth_filters={"tenant_id": "A"})
        result = await repo.find("test_widget_view")
        rows = extract_graphql_data(result, "test_widget_view")
        assert {r["name"] for r in rows} == {"Alpha", "Beta"}

    @pytest.mark.asyncio
    async def test_user_where_is_anded_with_auth_scope(
        self, class_db_pool, setup_view, test_types
    ) -> None:
        WidgetWhere = test_types["WidgetWhere"]
        repo = self._repo(class_db_pool, auth_filters={"tenant_id": "A"})
        # User asks for name = "Gamma" (tenant B); the AND-ed scope must exclude it.
        where = WidgetWhere(name={"eq": "Gamma"})
        result = await repo.find("test_widget_view", where=where)
        rows = extract_graphql_data(result, "test_widget_view")
        assert rows == []
