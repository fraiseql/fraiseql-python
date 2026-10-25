"""The loaders of ``fraiseql.optimization.loaders`` against a real PostgreSQL.

They called ``db.fetch_all``, which ``FraiseQLRepository`` doesn't have, so the
first ``load`` failed. They now read through ``db.run``.
"""

import uuid
from collections.abc import AsyncIterator

import pytest

from fraiseql.db import FraiseQLRepository
from fraiseql.optimization.loaders import (
    GenericForeignKeyLoader,
    ProjectLoader,
    TasksByProjectLoader,
    UserLoader,
)

pytestmark = [pytest.mark.integration, pytest.mark.database]

ALICE, BOB, NOBODY = (uuid.UUID(int=i) for i in (1, 2, 99))
APOLLO, GEMINI = (uuid.UUID(int=i) for i in (11, 12))


@pytest.fixture
async def schema(class_db_pool, test_schema) -> AsyncIterator[str]:
    """``users``, ``projects`` and ``tasks`` tables in the test schema."""
    async with class_db_pool.connection() as conn:
        await conn.execute(f"""
            CREATE TABLE {test_schema}.users (id uuid PRIMARY KEY, name text);
            CREATE TABLE {test_schema}.projects (id uuid PRIMARY KEY, name text);
            CREATE TABLE {test_schema}.tasks (
                id serial PRIMARY KEY, project_id uuid, title text, created_at timestamptz
            );
            INSERT INTO {test_schema}.users VALUES ('{ALICE}', 'alice'), ('{BOB}', 'bob');
            INSERT INTO {test_schema}.projects VALUES ('{APOLLO}', 'apollo');
            INSERT INTO {test_schema}.tasks (project_id, title, created_at) VALUES
                ('{APOLLO}', 'first', '2025-01-01'),
                ('{APOLLO}', 'second', '2025-01-02'),
                ('{APOLLO}', 'third', '2025-01-03');
        """)
        await conn.commit()

    yield test_schema

    async with class_db_pool.connection() as conn:
        await conn.execute(
            f"DROP TABLE {test_schema}.users, {test_schema}.projects, {test_schema}.tasks"
        )
        await conn.commit()


class TestCommonLoaders:
    async def test_user_loader(self, class_db_pool, schema) -> None:
        loader = UserLoader(FraiseQLRepository(class_db_pool), table=f"{schema}.users")

        users = await loader.load_many([BOB, NOBODY, ALICE])

        assert [u and u["name"] for u in users] == ["bob", None, "alice"]

    async def test_project_loader(self, class_db_pool, schema) -> None:
        loader = ProjectLoader(FraiseQLRepository(class_db_pool), table=f"{schema}.projects")

        assert (await loader.load(APOLLO))["name"] == "apollo"
        assert await loader.load(GEMINI) is None

    async def test_tasks_by_project_loader(self, class_db_pool, schema) -> None:
        loader = TasksByProjectLoader(
            FraiseQLRepository(class_db_pool), limit=2, table=f"{schema}.tasks"
        )

        apollo, gemini = await loader.load_many([APOLLO, GEMINI])

        assert [t["title"] for t in apollo] == ["third", "second"]
        assert gemini == []

    async def test_generic_foreign_key_loader(self, class_db_pool, schema) -> None:
        loader = GenericForeignKeyLoader(FraiseQLRepository(class_db_pool), f"{schema}.users")

        users = await loader.load_many([ALICE, BOB])

        assert [u["name"] for u in users] == ["alice", "bob"]

    async def test_generic_loader_on_another_key(self, class_db_pool, schema) -> None:
        loader = GenericForeignKeyLoader(
            FraiseQLRepository(class_db_pool), f"{schema}.tasks", key_field="project_id"
        )

        (task,) = await loader.load_many([APOLLO])

        assert task["project_id"] == APOLLO
