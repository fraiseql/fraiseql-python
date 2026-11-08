"""A @fraiseql.field resolver on a type db.find returns runs, with the row as self.

db.find / find_one answer with the rows Rust builds from the view, which never
pass through graphql-core field by field: the docs' ``post_count`` resolver
(docs/architecture/integration/extension-points.md) wasn't called, and
``postCount`` was missing from the response. When the selection holds a field
resolver, at any depth, find returns typed objects that graphql-core completes,
so the resolver runs; a selection of plain fields still goes out as Rust bytes.
"""

import logging
import uuid
from enum import Enum

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from psycopg.sql import SQL

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
import fraiseql.db as fraiseql_db
from fraiseql.db import DatabaseQuery
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.optimization.dataloader import DataLoader

pytestmark = [pytest.mark.integration, pytest.mark.database]

_USER_VIEW = "v_fr_user"
_POST_VIEW = "v_fr_post"
_U1 = uuid.UUID("00000000-0000-0000-0000-000000000001")
_U2 = uuid.UUID("00000000-0000-0000-0000-000000000002")
_NOBODY = uuid.UUID("00000000-0000-0000-0000-000000000009")


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def views(class_db_pool, test_schema):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(
            f"CREATE VIEW {_USER_VIEW} AS SELECT v.id, jsonb_build_object('id', v.id, "
            "'name', v.name, 'status', v.status, 'profile', jsonb_build_object('bio', v.bio)) "
            "AS data FROM (VALUES "
            f"('{_U1}'::uuid, 'ann', 'active', 'hi'), ('{_U2}'::uuid, 'bob', 'away', 'yo')) "
            "AS v(id, name, status, bio)"
        )
        await conn.execute(
            f"CREATE VIEW {_POST_VIEW} AS SELECT v.id, v.author_id, jsonb_build_object("
            "'id', v.id, 'author_id', v.author_id) AS data FROM (VALUES "
            f"(1, '{_U1}'::uuid), (2, '{_U1}'::uuid), (3, '{_U2}'::uuid)) AS v(id, author_id)"
        )
        await conn.commit()
    yield


def _build_app(class_db_pool, *, auto_camel_case: bool) -> TestClient:
    from fraiseql.fastapi.dependencies import set_db_pool

    @fraiseql.enum
    class FrStatus(Enum):
        ACTIVE = "active"
        AWAY = "away"

    @fraiseql.type
    class FrProfile:
        bio: str

        @fraiseql.field
        def loud_bio(self, info) -> str:
            return self.bio.upper()

    @fraiseql.type(sql_source=_USER_VIEW)
    class FrUser:
        id: uuid.UUID
        name: str
        status: FrStatus
        profile: FrProfile | None

        @fraiseql.field(description="Number of posts authored by this user")
        async def post_count(self, info) -> int:
            db = info.context["db"]
            return await db.count(_POST_VIEW, where={"author_id": {"eq": self.id}})

    class FrUserLoader(DataLoader[uuid.UUID, dict]):
        def __init__(self, db) -> None:
            super().__init__()
            self.db = db

        async def batch_load(self, user_ids: list[uuid.UUID]) -> list[dict | None]:
            rows = await self.db.run(
                DatabaseQuery(
                    SQL(f"SELECT id, data FROM {_USER_VIEW} WHERE id = ANY(%s)"),
                    [list(user_ids)],
                )
            )
            by_id = {row["id"]: row["data"] for row in rows}
            return [by_id.get(user_id) for user_id in user_ids]

    @fraiseql.type(sql_source=_POST_VIEW)
    class FrPost:
        id: int
        author_id: uuid.UUID

        @fraiseql.dataloader_field(FrUserLoader, key_field="author_id")
        async def author(self, info) -> FrUser | None:
            """Loaded in batch for every post in the response"""

    @fraiseql.type
    class FrUserPage:
        users: list[FrUser]

    @fraiseql.query
    async def fr_users(info) -> list[FrUser]:
        return await info.context["db"].find(_USER_VIEW, "frUsers", info)

    @fraiseql.query
    async def fr_user(info, id: uuid.UUID) -> FrUser | None:
        return await info.context["db"].find_one(
            _USER_VIEW, "frUser", info, where={"id": {"eq": id}}
        )

    @fraiseql.query
    async def fr_posts(info) -> list[FrPost]:
        return await info.context["db"].find(_POST_VIEW, "frPosts", info)

    @fraiseql.query
    async def fr_user_page(info) -> FrUserPage:
        return FrUserPage(users=await info.context["db"].find(_USER_VIEW))

    @fraiseql.query
    async def fr_hello(info) -> str:
        return "hi"

    set_db_pool(class_db_pool)
    config = FraiseQLConfig(database_url="postgresql://test/test", auto_camel_case=auto_camel_case)
    app = create_fraiseql_app(
        config=config, types=[FrUser, FrPost, FrProfile, FrUserPage], production=False
    )
    return TestClient(app)


def _data(client: TestClient, query: str) -> dict:
    body = client.post("/graphql", json={"query": query}).json()
    assert "errors" not in body, body
    return body["data"]


@pytest.mark.usefixtures("clear_registry_class")
class TestFieldResolverOnFind:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, views):
        return _build_app(class_db_pool, auto_camel_case=True)

    def test_list_runs_the_resolver(self, client) -> None:
        users = _data(client, "{ frUsers { id postCount } }")["frUsers"]

        assert users == [{"id": str(_U1), "postCount": 2}, {"id": str(_U2), "postCount": 1}]

    def test_the_resolver_reads_fields_the_query_does_not_select(self, client) -> None:
        users = _data(client, "{ frUsers { postCount } }")["frUsers"]

        assert users == [{"postCount": 2}, {"postCount": 1}]

    def test_find_one_runs_the_resolver(self, client) -> None:
        data = _data(client, f'{{ frUser(id: "{_U2}") {{ postCount }} }}')

        assert data == {"frUser": {"postCount": 1}}

    def test_find_one_without_a_row_is_null(self, client) -> None:
        data = _data(client, f'{{ frUser(id: "{_NOBODY}") {{ postCount }} }}')

        assert data == {"frUser": None}

    def test_aliased_resolver_and_root_field(self, client) -> None:
        data = _data(client, "{ people: frUsers { who: name pc: postCount } }")

        assert data == {"people": [{"who": "ann", "pc": 2}, {"who": "bob", "pc": 1}]}

    def test_resolver_mixed_with_plain_fields(self, client) -> None:
        users = _data(client, "{ frUsers { name status postCount id } }")["frUsers"]

        assert users[0] == {"name": "ann", "status": "ACTIVE", "postCount": 2, "id": str(_U1)}
        assert list(users[0]) == ["name", "status", "postCount", "id"]

    def test_resolver_on_a_nested_type(self, client) -> None:
        users = _data(client, "{ frUsers { name profile { bio loudBio } } }")["frUsers"]

        assert users == [
            {"name": "ann", "profile": {"bio": "hi", "loudBio": "HI"}},
            {"name": "bob", "profile": {"bio": "yo", "loudBio": "YO"}},
        ]

    def test_resolver_in_a_fragment(self, client) -> None:
        query = (
            "query { frUsers { ...U } } fragment U on FrUser { name ... on FrUser { postCount } }"
        )
        users = _data(client, query)["frUsers"]

        assert users == [{"name": "ann", "postCount": 2}, {"name": "bob", "postCount": 1}]

    def test_skipped_resolver_is_not_selected(self, client) -> None:
        query = "query($s: Boolean!) { frUsers { name postCount @skip(if: $s) } }"
        body = client.post("/graphql", json={"query": query, "variables": {"s": True}}).json()

        assert body == {"data": {"frUsers": [{"name": "ann"}, {"name": "bob"}]}}

    def test_with_another_root_field(self, client, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="fraiseql.fastapi.routers"):
            data = _data(client, "{ frUsers { name postCount } frHello }")

        # graphql-core runs the query once, not after a failed Rust merge
        assert not [r for r in caplog.records if "Falling back" in r.getMessage()]

        assert data == {
            "frUsers": [{"name": "ann", "postCount": 2}, {"name": "bob", "postCount": 1}],
            "frHello": "hi",
        }

    def test_two_root_finds_one_with_a_resolver(self, client) -> None:
        data = _data(client, f'{{ frUsers {{ name }} one: frUser(id: "{_U1}") {{ postCount }} }}')

        assert data == {"frUsers": [{"name": "ann"}, {"name": "bob"}], "one": {"postCount": 2}}

    def test_dataloader_field_on_find_results(self, client) -> None:
        posts = _data(client, "{ frPosts { id author { name postCount } } }")["frPosts"]

        assert posts == [
            {"id": 1, "author": {"name": "ann", "postCount": 2}},
            {"id": 2, "author": {"name": "ann", "postCount": 2}},
            {"id": 3, "author": {"name": "bob", "postCount": 1}},
        ]

    def test_find_wrapped_in_another_object(self, client) -> None:
        data = _data(client, "{ frUserPage { users { name postCount } } }")

        assert data == {
            "frUserPage": {
                "users": [{"name": "ann", "postCount": 2}, {"name": "bob", "postCount": 1}]
            }
        }

    def test_plain_fields_still_go_out_as_rust_bytes(self, client, monkeypatch) -> None:
        calls: list[str] = []
        real = fraiseql_db.execute_via_rust_pipeline

        async def spy(*args, **kwargs):
            calls.append(args[3])
            return await real(*args, **kwargs)

        monkeypatch.setattr(fraiseql_db, "execute_via_rust_pipeline", spy)

        users = _data(client, "{ frUsers { id name } }")["frUsers"]
        assert [u["name"] for u in users] == ["ann", "bob"]
        assert calls == ["frUsers"]

        calls.clear()
        _data(client, "{ frUsers { name postCount } }")
        assert calls == []


@pytest.mark.usefixtures("clear_registry_class")
class TestFieldResolverOnFindSnakeCase:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, views):
        return _build_app(class_db_pool, auto_camel_case=False)

    def test_list_runs_the_resolver(self, client) -> None:
        users = _data(client, "{ fr_users { name post_count } }")["fr_users"]

        assert users == [{"name": "ann", "post_count": 2}, {"name": "bob", "post_count": 1}]

    def test_find_one_and_nested_resolver(self, client) -> None:
        data = _data(
            client, f'{{ fr_user(id: "{_U1}") {{ pc: post_count profile {{ loud_bio }} }} }}'
        )

        assert data == {"fr_user": {"pc": 2, "profile": {"loud_bio": "HI"}}}

    def test_dataloader_field(self, client) -> None:
        posts = _data(client, "{ fr_posts { author { name } } }")["fr_posts"]

        assert [p["author"]["name"] for p in posts] == ["ann", "ann", "bob"]
