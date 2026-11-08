"""CachedRepository with PostgresCache against a real PostgreSQL.

``find`` / ``find_one`` return ``RustResponseBytes``; the cache must store them
and give the same bytes back, and writes through ``execute_function`` must
invalidate the keys ``find`` built.
"""

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.caching import CachedRepository, PostgresCache, ResultCache
from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.db import FraiseQLRepository
from fraiseql.fastapi import create_fraiseql_app

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def user_tables(class_db_pool, test_schema) -> None:
    async with class_db_pool.connection() as conn:
        await conn.execute(
            f"""
            CREATE TABLE {test_schema}.tb_user (id int PRIMARY KEY, name text NOT NULL);
            INSERT INTO {test_schema}.tb_user VALUES (1, 'Alice');
            CREATE VIEW {test_schema}.v_user AS
                SELECT id, jsonb_build_object('id', id, 'name', name) AS data
                FROM {test_schema}.tb_user;
            CREATE FUNCTION {test_schema}.fn_update_user(input jsonb) RETURNS jsonb AS $$
                UPDATE {test_schema}.tb_user SET name = input->>'name'
                WHERE id = (input->>'id')::int;
                SELECT jsonb_build_object('status', 'ok');
            $$ LANGUAGE sql;
            """
        )
        await conn.commit()


@pytest_asyncio.fixture(loop_scope="class")
async def cached(class_db_pool, test_schema, user_tables) -> CachedRepository:
    async with class_db_pool.connection() as conn:
        await conn.execute(
            f"TRUNCATE {test_schema}.tb_user; INSERT INTO {test_schema}.tb_user VALUES (1, 'Alice')"
        )
        await conn.commit()
    backend = PostgresCache(class_db_pool, table_name=f"{test_schema}.fraiseql_cache")
    await backend.clear_all()
    base = FraiseQLRepository(class_db_pool, context={"tenant_id": "t1"})
    return CachedRepository(base, ResultCache(backend))


def _names(response: RustResponseBytes, field: str) -> list[str]:
    """The user names in a find / find_one response (rows are whole without a type)."""
    rows = json.loads(bytes(response))["data"][field]
    rows = rows if isinstance(rows, list) else [rows]
    return [row.get("data", row)["name"] for row in rows]


async def _rename(pool, schema: str, name: str) -> None:
    """Change the row behind the cache's back."""
    async with pool.connection() as conn:
        await conn.execute(f"UPDATE {schema}.tb_user SET name = %s WHERE id = 1", (name,))
        await conn.commit()


@pytest.mark.usefixtures("test_schema")
class TestCachedRepositoryPostgres:
    @pytest.mark.asyncio(loop_scope="class")
    async def test_second_find_is_served_from_the_cache(
        self, cached, class_db_pool, test_schema
    ) -> None:
        view = f"{test_schema}.v_user"
        first = await cached.find(view, "users")
        await _rename(class_db_pool, test_schema, "Changed")
        second = await cached.find(view, "users")

        assert isinstance(second, RustResponseBytes)
        assert bytes(second) == bytes(first)
        assert _names(second, "users") == ["Alice"]
        stats = cached._cache.get_stats()
        assert (stats.hits, stats.misses, stats.errors) == (1, 1, 0)

    @pytest.mark.asyncio(loop_scope="class")
    async def test_find_one_is_cached(self, cached, class_db_pool, test_schema) -> None:
        view = f"{test_schema}.v_user"
        first = await cached.find_one(view, "user", where={"id": {"eq": 1}})
        await _rename(class_db_pool, test_schema, "Changed")
        second = await cached.find_one(view, "user", where={"id": {"eq": 1}})

        assert isinstance(second, RustResponseBytes)
        assert bytes(second) == bytes(first)
        assert cached._cache.get_stats().hits == 1

    @pytest.mark.asyncio(loop_scope="class")
    async def test_different_arguments_use_different_keys(self, cached, test_schema) -> None:
        view = f"{test_schema}.v_user"
        await cached.find(view, "users")
        await cached.find(view, "users", limit=1)

        assert cached._cache.get_stats().misses == 2

    @pytest.mark.asyncio(loop_scope="class")
    async def test_execute_function_invalidates_the_view(self, cached, test_schema) -> None:
        view = f"{test_schema}.v_user"
        await cached.find(view, "users")
        await cached.find_one(view, "user", where={"id": {"eq": 1}})

        await cached.execute_function(f"{test_schema}.fn_update_user", {"id": 1, "name": "Bob"})

        user = await cached.find_one(view, "user", where={"id": {"eq": 1}})
        assert _names(await cached.find(view, "users"), "users") == ["Bob"]
        assert _names(user, "user") == ["Bob"]
        assert cached._cache.get_stats().hits == 0

    @pytest.mark.asyncio(loop_scope="class")
    async def test_invalidate_view(self, cached, class_db_pool, test_schema) -> None:
        view = f"{test_schema}.v_user"
        await cached.find(view, "users")
        await _rename(class_db_pool, test_schema, "Carol")

        await cached.invalidate_view(view)

        assert _names(await cached.find(view, "users"), "users") == ["Carol"]


@pytest.fixture
def client(class_db_pool, test_schema, user_tables, clear_registry) -> TestClient:
    from fraiseql.fastapi.dependencies import set_db_pool

    @fraiseql.type(sql_source=f"{test_schema}.v_user", jsonb_column="data")
    class User:
        id: int
        name: str

    @fraiseql.query
    async def users(info) -> list[User]:
        return await info.context["db"].find(f"{test_schema}.v_user", "users", info)

    set_db_pool(class_db_pool)
    table = f"{test_schema}.cache_{uuid4().hex[:8]}"  # a fresh cache for each test
    cache = ResultCache(PostgresCache(class_db_pool, table_name=table))

    async def context_getter(request, user=None):
        return {"db": CachedRepository(FraiseQLRepository(class_db_pool), cache), "user": user}

    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[User],
        queries=[users],
        production=False,
        context_getter=context_getter,
    )
    client = TestClient(app)
    client.cache = cache  # type: ignore[attr-defined]
    return client


def _post(client: TestClient, query: str) -> dict:
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "errors" not in body, body["errors"]
    # The Rust pipeline adds __typename to each object; only the selection matters here
    return {
        field: [{k: v for k, v in row.items() if k != "__typename"} for row in rows]
        for field, rows in body["data"].items()
    }


@pytest.mark.usefixtures("test_schema")
class TestCachedRepositoryOverHttp:
    def test_hit_returns_the_same_response(self, client, class_db_pool, test_schema) -> None:
        first = _post(client, "{ users { id name } }")
        second = _post(client, "{ users { id name } }")

        assert first == second == {"users": [{"id": 1, "name": "Alice"}]}
        assert client.cache.get_stats().hits == 1

    def test_each_selection_gets_its_own_entry(self, client) -> None:
        assert _post(client, "{ users { id name } }") == {"users": [{"id": 1, "name": "Alice"}]}
        assert _post(client, "{ users { id } }") == {"users": [{"id": 1}]}
        assert _post(client, "{ people: users { name } }") == {"people": [{"name": "Alice"}]}
        assert client.cache.get_stats().hits == 0
