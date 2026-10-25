"""A @fraiseql.field resolver on a type db.find returns is reported, not dropped silently.

db.find / find_one answer with the rows Rust builds from the view, which never
pass through graphql-core field by field: the docs' ``post_count`` resolver
(docs/architecture/integration/extension-points.md) wasn't called, and
``postCount`` was missing from the response without a word. Running those
resolvers is not done yet; until then a warning names the field, once.
"""

import logging
import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import create_fraiseql_app

pytestmark = [pytest.mark.integration, pytest.mark.database]

_USER_VIEW = "v_fr_user"
_POST_VIEW = "v_fr_post"
_U1 = uuid.UUID("00000000-0000-0000-0000-000000000001")
_U2 = uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def views(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(
            f"CREATE VIEW {_USER_VIEW} AS SELECT v.id, jsonb_build_object('id', v.id, "
            "'name', v.name) AS data FROM (VALUES "
            f"('{_U1}'::uuid, 'ann'), ('{_U2}'::uuid, 'bob')) AS v(id, name)"
        )
        await conn.execute(
            f"CREATE VIEW {_POST_VIEW} AS SELECT v.id, v.author_id, jsonb_build_object("
            "'id', v.id, 'author_id', v.author_id) AS data FROM (VALUES "
            f"(1, '{_U1}'::uuid), (2, '{_U1}'::uuid), (3, '{_U2}'::uuid)) AS v(id, author_id)"
        )
        await conn.commit()
    yield


@pytest.mark.usefixtures("clear_registry_class")
class TestFieldResolverOnFind:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, views):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.type(sql_source=_USER_VIEW)
        class FrUser:
            id: uuid.UUID
            name: str

            @fraiseql.field(description="Number of posts authored by this user")
            async def post_count(self, info) -> int:
                db = info.context["db"]
                return await db.count(_POST_VIEW, where={"author_id": {"eq": self.id}})

        @fraiseql.query
        async def fr_users(info) -> list[FrUser]:
            return await info.context["db"].find(_USER_VIEW, "frUsers", info)

        @fraiseql.query
        async def fr_user(info, id: uuid.UUID) -> FrUser | None:
            return await info.context["db"].find_one(
                _USER_VIEW, "frUser", info, where={"id": {"eq": id}}
            )

        @fraiseql.query
        async def fr_hello(info) -> str:
            return "hi"

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",  # the pool above is used
            types=[FrUser],
            production=False,
        )
        return TestClient(app)

    @pytest.mark.parametrize(
        "query",
        [
            "{ frUsers { name postCount } }",
            f'{{ frUser(id: "{_U1}") {{ name postCount }} }}',
            "{ frUsers { name postCount } frHello }",
        ],
    )
    def test_selected_field_resolver_is_reported(self, client, caplog, query) -> None:
        from fraiseql.core import unresolved_fields

        unresolved_fields._warned.clear()
        with caplog.at_level(logging.WARNING, logger=unresolved_fields.__name__):
            body = client.post("/graphql", json={"query": query}).json()
            client.post("/graphql", json={"query": query})

        assert "errors" not in body, body
        messages = [r.getMessage() for r in caplog.records if r.name == unresolved_fields.__name__]
        assert len(messages) == 1, messages  # once, not per request
        assert "FrUser.post_count is a field resolver" in messages[0]
        assert "postCount is left out of the response" in messages[0]

    def test_without_it_nothing_is_reported(self, client, caplog) -> None:
        from fraiseql.core import unresolved_fields

        unresolved_fields._warned.clear()
        with caplog.at_level(logging.WARNING, logger=unresolved_fields.__name__):
            body = client.post("/graphql", json={"query": "{ frUsers { id name } }"}).json()

        assert [u["name"] for u in body["data"]["frUsers"]] == ["ann", "bob"]
        assert not [r for r in caplog.records if r.name == unresolved_fields.__name__]
