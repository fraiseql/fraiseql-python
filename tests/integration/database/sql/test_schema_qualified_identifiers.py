"""Issue #488: schema-qualified names in the SQL, mutation and langchain generators.

The same defect as #472 and #486, in the three modules those fixes did not
touch. ``build_sql_query`` (both branches), ``generate_insert_json_call`` and
``FraiseQLVectorStore``'s two write paths handed the whole dotted name to a
single-argument ``Identifier``, so ``"myschema.v_posts"`` rendered as one quoted
relation name containing a dot instead of ``"myschema"."v_posts"``.

The two renderings differ by a single quote character and both read as plausible
in a diff, so a text assertion cannot tell them apart; only the server can. Each
class below therefore builds inside its own ``test_schema`` and leaves it *off*
the search path, so a mis-quoted or unqualified name has nothing to resolve
against, and opens with a guard test proving exactly that.

The three generators are off the live request path — the served query and
mutation paths go through Rust — but they are maintained, importable API that
eight test files exercise. The mutation site is the sharpest: mutation function
names are schema-qualified by construction in ``mutation_decorator``.
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest

from fraiseql.core.ast_parser import FieldPath
from fraiseql.integrations.langchain import FraiseQLVectorStore
from fraiseql.mutations.sql_generator import generate_insert_json_call
from fraiseql.sql.sql_generator import build_sql_query

pytestmark = [pytest.mark.integration, pytest.mark.database]

VIEW = "v_488_posts"
FUNCTION = "create_488_user"
DOCS = "tb_488_documents"

# (title, author)
ROWS = [
    ("post-a", "alice"),
    ("post-b", "bob"),
    ("post-c", "alice"),
]

ROW_IDS = [uuid.UUID(int=i) for i in range(1, len(ROWS) + 1)]

FIELD_PATHS = [
    FieldPath(alias="title", path=["title"]),
    FieldPath(alias="author", path=["author"]),
]


async def _fetch(pool: Any, statement: Any, params: Any = None) -> list[tuple]:
    async with pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(statement, params)
        return await cursor.fetchall()


@pytest.fixture
async def qualified_view(class_db_pool, test_schema) -> AsyncIterator[None]:
    """Build the posts table inside ``test_schema``, off the search path."""
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {test_schema}.{VIEW} (
                id UUID PRIMARY KEY,
                data JSONB NOT NULL
            )
        """)
        for row_id, (title, author) in zip(ROW_IDS, ROWS, strict=True):
            await cursor.execute(
                f"INSERT INTO {test_schema}.{VIEW} (id, data) VALUES (%s, %s::jsonb)",
                (row_id, json.dumps({"id": str(row_id), "title": title, "author": author})),
            )
        await conn.commit()

    yield

    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"DROP TABLE IF EXISTS {test_schema}.{VIEW} CASCADE")
        await conn.commit()


class TestBuildSqlQuery:
    """``sql/sql_generator.build_sql_query`` renders one view name on each branch."""

    async def test_the_unqualified_name_does_not_resolve(
        self, class_db_pool, test_schema, qualified_view
    ) -> None:
        """Without this, every test below could pass for the wrong reason."""
        query = build_sql_query(VIEW, FIELD_PATHS, json_output=True)

        with pytest.raises(psycopg.errors.UndefinedTable):
            await _fetch(class_db_pool, query)

    async def test_projection_branch_resolves_the_qualified_view(
        self, class_db_pool, test_schema, qualified_view
    ) -> None:
        """The jsonb_build_object branch — the one most callers reach."""
        query = build_sql_query(f"{test_schema}.{VIEW}", FIELD_PATHS, json_output=True)

        rows = [row[0] for row in await _fetch(class_db_pool, query)]

        assert sorted((r["title"], r["author"]) for r in rows) == sorted(ROWS)

    async def test_field_limit_threshold_branch_resolves_the_qualified_view(
        self, class_db_pool, test_schema, qualified_view
    ) -> None:
        """The second, easily-missed branch: exceeding the threshold selects ``data`` whole."""
        query = build_sql_query(
            f"{test_schema}.{VIEW}",
            FIELD_PATHS,
            json_output=True,
            field_limit_threshold=1,
        )

        rows = [row[0] for row in await _fetch(class_db_pool, query)]

        assert sorted((r["title"], r["author"]) for r in rows) == sorted(ROWS)

    async def test_unqualified_name_still_resolves_on_the_search_path(
        self, class_db_pool, test_schema, qualified_view
    ) -> None:
        """The bare-name form must keep working — the helper must not split what has no dot."""
        query = build_sql_query(VIEW, FIELD_PATHS, json_output=True)

        async with class_db_pool.connection() as conn, conn.cursor() as cursor:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await cursor.execute(query)
            rows = [row[0] for row in await cursor.fetchall()]

        assert len(rows) == len(ROWS)


@dataclass
class CreateUserInput:
    """Minimal mutation input — ``generate_insert_json_call`` needs a dataclass."""

    name: str


@pytest.fixture
async def qualified_function(class_db_pool, test_schema) -> AsyncIterator[None]:
    """Build the mutation function inside ``test_schema``, off the search path."""
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"""
            CREATE OR REPLACE FUNCTION {test_schema}.{FUNCTION}(input_json JSONB)
            RETURNS JSONB AS $$
                SELECT jsonb_build_object('status', 'created', 'name', input_json->>'name')
            $$ LANGUAGE sql
        """)
        await conn.commit()

    yield

    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"DROP FUNCTION IF EXISTS {test_schema}.{FUNCTION}(JSONB)")
        await conn.commit()


class TestGenerateInsertJsonCall:
    """``mutations/sql_generator`` names a function, which is qualified by construction."""

    async def test_the_unqualified_name_does_not_resolve(
        self, class_db_pool, test_schema, qualified_function
    ) -> None:
        """Without this, the test below could pass for the wrong reason."""
        query = generate_insert_json_call(
            input_object=CreateUserInput(name="alice"),
            context={},
            sql_function_name=FUNCTION,
        )

        with pytest.raises(psycopg.errors.UndefinedFunction):
            await _fetch(class_db_pool, query.statement, query.params)

    async def test_qualified_function_name_resolves(
        self, class_db_pool, test_schema, qualified_function
    ) -> None:
        """``mutation_decorator`` builds ``f"{schema}.{function_name}"``; this is that shape."""
        query = generate_insert_json_call(
            input_object=CreateUserInput(name="alice"),
            context={},
            sql_function_name=f"{test_schema}.{FUNCTION}",
        )

        rows = await _fetch(class_db_pool, query.statement, query.params)

        assert rows == [({"name": "alice", "status": "created"},)]

    async def test_unqualified_name_still_resolves_on_the_search_path(
        self, class_db_pool, test_schema, qualified_function
    ) -> None:
        """The bare-name form must keep working."""
        query = generate_insert_json_call(
            input_object=CreateUserInput(name="alice"),
            context={},
            sql_function_name=FUNCTION,
        )

        async with class_db_pool.connection() as conn, conn.cursor() as cursor:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await cursor.execute(query.statement, query.params)
            rows = await cursor.fetchall()

        assert rows == [({"name": "alice", "status": "created"},)]


class _StubEmbeddings:
    """Deterministic stand-in — the vector maths is irrelevant to identifier rendering."""

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 0.0, 1.0]


class _SearchPathPool:
    """Hands out the class pool's connections with ``test_schema`` on the search path.

    ``FraiseQLVectorStore`` opens its own connection, so the bare-name case has
    to be set up inside ``connection()`` rather than on a connection the test holds.
    """

    def __init__(self, pool: Any, schema: str) -> None:
        self._pool = pool
        self._schema = schema

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[Any]:
        async with self._pool.connection() as conn:
            await conn.execute(f"SET search_path TO {self._schema}, public")
            yield conn


@pytest.fixture
async def qualified_documents(class_db_pool, test_schema) -> AsyncIterator[None]:
    """Build the documents table inside ``test_schema``, off the search path."""
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {test_schema}.{DOCS} (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                embedding DOUBLE PRECISION[] NOT NULL
            )
        """)
        await conn.commit()

    yield

    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"DROP TABLE IF EXISTS {test_schema}.{DOCS} CASCADE")
        await conn.commit()


class TestLangchainVectorStore:
    """``integrations/langchain`` renders its table name on the insert and delete paths."""

    @staticmethod
    def _store(pool, table_name: str) -> FraiseQLVectorStore:
        return FraiseQLVectorStore(
            db_pool=pool,
            table_name=table_name,
            embedding_function=_StubEmbeddings(),
        )

    async def test_the_unqualified_name_does_not_resolve(
        self, class_db_pool, test_schema, qualified_documents
    ) -> None:
        """Without this, every test below could pass for the wrong reason."""
        store = self._store(class_db_pool, DOCS)

        with pytest.raises(psycopg.errors.UndefinedTable):
            await store.aadd_texts(["hello"])

    async def test_aadd_texts_resolves_the_qualified_table(
        self, class_db_pool, test_schema, qualified_documents
    ) -> None:
        store = self._store(class_db_pool, f"{test_schema}.{DOCS}")

        ids = await store.aadd_texts(["hello", "world"])

        rows = await _fetch(class_db_pool, f"SELECT id, content FROM {test_schema}.{DOCS}")
        assert sorted(rows) == sorted(zip(ids, ["hello", "world"], strict=True))

    async def test_adelete_resolves_the_qualified_table(
        self, class_db_pool, test_schema, qualified_documents
    ) -> None:
        store = self._store(class_db_pool, f"{test_schema}.{DOCS}")
        ids = await store.aadd_texts(["hello", "world"])

        await store.adelete([ids[0]])

        rows = await _fetch(class_db_pool, f"SELECT id FROM {test_schema}.{DOCS}")
        assert rows == [(ids[1],)]

    async def test_unqualified_name_still_resolves_on_the_search_path(
        self, class_db_pool, test_schema, qualified_documents
    ) -> None:
        """The bare-name form must keep working — the helper must not split what has no dot."""
        store = self._store(_SearchPathPool(class_db_pool, test_schema), DOCS)

        ids = await store.aadd_texts(["hello"])

        rows = await _fetch(class_db_pool, f"SELECT id FROM {test_schema}.{DOCS}")
        assert rows == [(ids[0],)]
