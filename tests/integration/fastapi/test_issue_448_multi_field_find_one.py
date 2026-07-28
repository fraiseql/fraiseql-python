"""End-to-end regression for issue #448 through the full FastAPI HTTP stack.

A multi-field GraphQL query combining a ``find_one()``-backed top-level field with any
sibling top-level field used to crash:

* Bug A — ``find_one()`` ran ``_is_rust_response_null()`` on the plain dict/list that
  field-only mode returns, raising ``'dict' object has no attribute 'bytes'``.
* Bug B — a scalar sibling (a count) produced ``json_rows=[<int>]`` that the Rust FFI
  rejected with ``'int' object is not an instance of 'str'``, aborting the merge.

These tests exercise the real path that reproduced the bug end-to-end:
    HTTP POST /graphql -> multi-field routing -> execute_multi_field_query
    -> resolver -> FraiseQLRepository.find_one()/count() -> Rust pipeline -> HTTP response

The resolvers are deliberately **argument-free single-row lookups**, mirroring the
reporter's ``me`` / ``machineInventoryStatistics`` fields (single-row-per-tenant). The
multi-field executor extracts arguments from the AST without scalar coercion, so keeping
the fields argument-free isolates the merge fix from unrelated argument-coercion concerns.

Requires a real PostgreSQL (markers: integration + database). The unit-level reproduction
that runs without a database lives in ``tests/regression/test_issue_448_multifield_findone.py``.
Fixture shape mirrors ``test_fastapi_jsonb_integration.py`` (JSONB view +
``has_jsonb_data=True``), matching the reporter's ``tv_*`` dual typed-column/jsonb table.
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.fastapi.routers import create_graphql_router
from fraiseql.gql.schema_builder import build_fraiseql_schema

pytestmark = [pytest.mark.integration, pytest.mark.database]

_VIEW = "test_issue448_widget_view"
_EMPTY_VIEW = "test_issue448_empty_view"

_W1 = "00000000-0000-0000-0000-000000000001"
_W2 = "00000000-0000-0000-0000-000000000002"


@fraiseql.type
class Widget:
    """Widget entity backed by a JSONB view (id/name typed, rest in JSONB)."""

    id: str
    name: str
    color: str  # stored in JSONB


def _repo(info) -> FraiseQLRepository:
    return FraiseQLRepository(info.context.get("pool"), context={"mode": "development"})


# ``info`` is passed explicitly so find_one()/find() see the multi-field context
# (``__has_multiple_root_fields__``) and the GraphQL field name. In a real app the
# graphql_info_injector middleware stashes this on the repository; here each resolver
# builds its own repository, so we thread ``info`` through directly.
@fraiseql.query
async def widget(info) -> Widget | None:
    """Single-row lookup — the find_one()-backed field (Bug A path)."""
    return await _repo(info).find_one(_VIEW, info=info)


@fraiseql.query
async def empty_widget(info) -> Widget | None:
    """find_one() over an empty view — must resolve to null, not crash."""
    return await _repo(info).find_one(_EMPTY_VIEW, info=info)


@fraiseql.query
async def widgets(info, limit: int = 10) -> list[Widget]:
    """List lookup — a second find-backed sibling."""
    return await _repo(info).find(_VIEW, info=info, limit=limit)


@fraiseql.query
async def widgets_count(info) -> int:
    """Scalar count — the scalar sibling (Bug B path)."""
    return await _repo(info).count(_VIEW)


class TestIssue448MultiFieldFindOne:
    """Multi-field queries mixing find_one, find, and scalar siblings must merge cleanly."""

    @pytest.fixture(scope="class")
    def clear_registry_fixture(self, clear_registry_class) -> None:
        """Clear registry before the class runs."""
        return

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_data(self, class_db_pool, test_schema) -> None:
        """Create the JSONB table + populated/empty views and seed two widgets."""
        for view in (_VIEW, _EMPTY_VIEW):
            register_type_for_view(
                view,
                Widget,
                table_columns={"id", "name", "data"},
                has_jsonb_data=True,
                jsonb_column="data",
            )

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_issue448_widget (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL,
                    data JSONB NOT NULL
                )
                """
            )
            for view, predicate in ((_VIEW, "TRUE"), (_EMPTY_VIEW, "FALSE")):
                await conn.execute(
                    f"""
                    CREATE OR REPLACE VIEW {view} AS
                    SELECT
                        id,
                        name,
                        jsonb_build_object(
                            'id', id,
                            'name', name,
                            'color', data->>'color'
                        ) AS data
                    FROM test_issue448_widget
                    WHERE {predicate}
                    """
                )
            await conn.execute(
                f"""
                INSERT INTO test_issue448_widget (id, name, data)
                VALUES
                    ('{_W1}', 'Alpha', '{{"color": "red"}}'),
                    ('{_W2}', 'Beta',  '{{"color": "blue"}}')
                ON CONFLICT (id) DO NOTHING
                """
            )
            await conn.commit()

        yield

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            await conn.execute(f"DROP VIEW IF EXISTS {_VIEW}")
            await conn.execute(f"DROP VIEW IF EXISTS {_EMPTY_VIEW}")
            await conn.execute("DROP TABLE IF EXISTS test_issue448_widget")
            await conn.commit()

    @pytest.fixture
    def app(self, class_db_pool) -> FastAPI:
        """Build a real FastAPI app whose context injects the test pool."""
        from fraiseql.fastapi.dependencies import set_db_pool, set_fraiseql_config

        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost:5432/test",
            environment="development",
        )
        set_db_pool(class_db_pool)
        set_fraiseql_config(config)

        schema = build_fraiseql_schema(query_types=[widget, empty_widget, widgets, widgets_count])

        async def context_getter(request) -> dict:
            return {"pool": class_db_pool}

        router = create_graphql_router(schema=schema, config=config, context_getter=context_getter)
        fastapi_app = FastAPI()
        fastapi_app.include_router(router)

        yield fastapi_app

        set_db_pool(None)
        set_fraiseql_config(None)

    @staticmethod
    def _post(app: FastAPI, query: str) -> dict:
        response = TestClient(app).post("/graphql", json={"query": query})
        assert response.status_code == 200, response.text
        return response.json()

    @pytest.mark.asyncio
    async def test_find_one_plus_scalar_sibling(self, class_db_pool, setup_data, app) -> None:
        """Reporter's exact shape: object field + scalar count (Bug A + Bug B).

        Selects typed columns (id/name). The response also carries ``__typename`` (normal
        FraiseQL behaviour), so assert on values rather than an exact key set. (Whether
        JSONB-derived sub-fields project through the multi-field path is a separate
        concern from the #448 crash and is not asserted here.)
        """
        body = self._post(app, "{ widget { id name } widgetsCount }")

        assert "errors" not in body, body
        data = body["data"]
        assert data["widget"] is not None
        assert data["widget"]["id"] in {_W1, _W2}
        assert data["widget"]["name"] in {"Alpha", "Beta"}
        assert data["widgetsCount"] == 2

    @pytest.mark.asyncio
    async def test_find_one_plus_list_sibling(self, class_db_pool, setup_data, app) -> None:
        """Two find-backed siblings (single object + list)."""
        body = self._post(app, "{ widget { id } widgets(limit: 5) { id } }")

        assert "errors" not in body, body
        data = body["data"]
        assert data["widget"]["id"] in {_W1, _W2}
        assert {w["id"] for w in data["widgets"]} == {_W1, _W2}

    @pytest.mark.asyncio
    async def test_find_one_null_plus_scalar_sibling(self, class_db_pool, setup_data, app) -> None:
        """A find_one that returns null must render null and not break siblings."""
        body = self._post(app, "{ emptyWidget { id name } widgetsCount }")

        assert "errors" not in body, body
        data = body["data"]
        assert data["emptyWidget"] is None
        assert data["widgetsCount"] == 2

    @pytest.mark.asyncio
    async def test_aliased_find_one_plus_scalar(self, class_db_pool, setup_data, app) -> None:
        """Aliases on both fields resolve to the alias keys."""
        body = self._post(app, "{ w: widget { name } n: widgetsCount }")

        assert "errors" not in body, body
        data = body["data"]
        assert data["w"]["name"] in {"Alpha", "Beta"}
        assert data["n"] == 2
