"""When PostgresCache creates its table and detects pg_fraiseql_cache."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from graphql import GraphQLField, GraphQLList, GraphQLObjectType, GraphQLSchema, GraphQLString

from fraiseql.caching import PostgresCache, setup_auto_cascade_rules


def _pool_with_extension(version: str | None) -> tuple[MagicMock, list[str]]:
    """A pool whose pg_extension lookup returns ``version``; records the SQL run."""
    executed: list[str] = []
    cursor = AsyncMock()

    async def execute(sql, *args, **kwargs) -> None:
        executed.append(" ".join(str(sql).split()))

    cursor.execute = execute
    cursor.fetchone = AsyncMock(return_value=(version,) if version else None)
    cursor.rowcount = 1
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=None)
    conn = AsyncMock()
    conn.cursor = MagicMock(return_value=cursor)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.connection = MagicMock(return_value=conn)
    return pool, executed


class TestExtensionDetectedBeforeUse:
    @pytest.mark.asyncio
    async def test_register_cascade_rule_as_first_call(self) -> None:
        pool, executed = _pool_with_extension("1.0")
        cache = PostgresCache(pool)

        registered = await cache.register_cascade_rule("user", "post")

        assert registered is True
        assert any("INSERT INTO fraiseql_cache.cascade_rules" in sql for sql in executed)

    @pytest.mark.asyncio
    async def test_register_cascade_rule_without_extension(self) -> None:
        pool, executed = _pool_with_extension(None)
        cache = PostgresCache(pool)

        assert await cache.register_cascade_rule("user", "post") is False
        assert not any("cascade_rules" in sql for sql in executed)

    @pytest.mark.asyncio
    async def test_setup_table_trigger_as_first_call(self) -> None:
        pool, executed = _pool_with_extension("1.0")
        cache = PostgresCache(pool)

        await cache.setup_table_trigger("tb_user", domain_name="user")

        assert any("setup_table_invalidation" in sql for sql in executed)

    @pytest.mark.asyncio
    async def test_get_domain_versions_as_first_call(self) -> None:
        pool, executed = _pool_with_extension("1.0")
        cache = PostgresCache(pool)

        await cache.get_domain_versions("t1", ["user"])

        assert any("fraiseql_cache.domain_version" in sql for sql in executed)

    @pytest.mark.asyncio
    async def test_ping_detects_the_extension(self) -> None:
        pool, _ = _pool_with_extension("1.0")
        cache = PostgresCache(pool)

        assert await cache.ping() is True
        assert cache.has_domain_versioning is True
        assert cache.extension_version == "1.0"


class TestAutoInitialize:
    @pytest.mark.asyncio
    async def test_default_creates_the_table(self) -> None:
        pool, executed = _pool_with_extension(None)

        await PostgresCache(pool).get("k")

        assert any("CREATE UNLOGGED TABLE IF NOT EXISTS fraiseql_cache" in s for s in executed)

    @pytest.mark.asyncio
    async def test_false_leaves_the_table_alone(self) -> None:
        pool, executed = _pool_with_extension("1.0")
        cache = PostgresCache(pool, auto_initialize=False)

        await cache.get("k")

        assert not any("CREATE" in sql for sql in executed)
        assert cache.has_domain_versioning is True  # still detected

    @pytest.mark.asyncio
    async def test_initialize_creates_the_table(self) -> None:
        pool, executed = _pool_with_extension(None)

        await PostgresCache(pool, auto_initialize=False).initialize()

        assert any("CREATE UNLOGGED TABLE IF NOT EXISTS fraiseql_cache" in s for s in executed)

    @pytest.mark.asyncio
    async def test_schema_qualified_table_gets_a_valid_index_name(self) -> None:
        pool, executed = _pool_with_extension(None)

        await PostgresCache(pool, table_name="app.cache").initialize()

        index = next(sql for sql in executed if "CREATE INDEX" in sql)
        assert "IF NOT EXISTS cache_expires_idx ON app.cache" in index


def _schema_with_relationship() -> GraphQLSchema:
    user = GraphQLObjectType("User", {"name": GraphQLField(GraphQLString)})
    post = GraphQLObjectType(
        "Post", {"title": GraphQLField(GraphQLString), "author": GraphQLField(user)}
    )
    return GraphQLSchema(GraphQLObjectType("Query", {"posts": GraphQLField(GraphQLList(post))}))


class TestSetupAutoCascadeRules:
    @pytest.mark.asyncio
    async def test_counts_only_registered_rules(self) -> None:
        pool, _ = _pool_with_extension(None)  # no extension: every rule is skipped

        count = await setup_auto_cascade_rules(PostgresCache(pool), _schema_with_relationship())

        assert count == 0

    @pytest.mark.asyncio
    async def test_counts_registered_rules(self) -> None:
        pool, _ = _pool_with_extension("1.0")

        count = await setup_auto_cascade_rules(PostgresCache(pool), _schema_with_relationship())

        assert count >= 1
