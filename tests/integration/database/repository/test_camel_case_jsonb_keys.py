"""A view with camelCase JSONB keys gets a development-mode warning.

``where`` and ``orderBy`` look a multi-word field up by its snake_case key
(``data ->> 'created_at'``). A view whose JSONB is built with camelCase keys
(``jsonb_build_object('createdAt', ...)``) silently matches nothing on those
fields. In development, the first query that filters or sorts on such a field
probes the view once and logs a warning naming the view and the key.
"""

import logging

import pytest
import pytest_asyncio

pytestmark = pytest.mark.database

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql import db as fraiseql_db
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.fastapi.config import FraiseQLConfig

_CAMEL_VIEW = "v_camel_key_note"
_SNAKE_VIEW = "v_snake_key_note"


def _repo(pool, environment: str = "development") -> FraiseQLRepository:
    config = FraiseQLConfig(database_url="postgresql://localhost/unused", environment=environment)
    return FraiseQLRepository(pool, context={"config": config})


def _key_warnings(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and "snake_case" in record.getMessage()
    ]


class TestCamelCaseJsonbKeyWarning:
    @pytest.fixture(scope="class")
    def note_types(self, clear_registry_class):
        @fraiseql.type(sql_source=_CAMEL_VIEW)
        class CamelNote:
            id: int
            created_at: str
            title: str

        @fraiseql.type(sql_source=_SNAKE_VIEW)
        class SnakeNote:
            id: int
            created_at: str
            title: str

        return {"CamelNote": CamelNote, "SnakeNote": SnakeNote}

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def note_views(self, class_db_pool, test_schema, note_types):
        for view, type_name in ((_CAMEL_VIEW, "CamelNote"), (_SNAKE_VIEW, "SnakeNote")):
            register_type_for_view(
                view,
                note_types[type_name],
                table_columns={"id", "data"},
                has_jsonb_data=True,
            )

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute(
                "CREATE TABLE key_notes (id INT PRIMARY KEY, created_at TEXT, title TEXT)"
            )
            await conn.execute(
                "INSERT INTO key_notes VALUES (1, '2024-01-01', 'a'), (2, '2024-06-01', 'b')"
            )
            await conn.execute(
                f"""
                CREATE VIEW {_CAMEL_VIEW} AS
                SELECT id, jsonb_build_object(
                    'id', id, 'createdAt', created_at, 'title', title,
                    'author', jsonb_build_object('name', 'x', 'firstName', 'x')
                ) AS data
                FROM key_notes
                """
            )
            await conn.execute(
                f"""
                CREATE VIEW {_SNAKE_VIEW} AS
                SELECT id, jsonb_build_object('id', id, 'created_at', created_at, 'title', title)
                    AS data
                FROM key_notes
                """
            )
            await conn.commit()
        yield

    @pytest.fixture(autouse=True)
    def _fresh_probes(self):
        probes = getattr(fraiseql_db, "_camel_case_key_probes", set())
        probes.clear()
        yield
        probes.clear()

    @pytest.mark.asyncio
    async def test_where_on_a_camel_case_key_warns_once(
        self, class_db_pool, note_views, caplog
    ) -> None:
        repo = _repo(class_db_pool)
        where = {"createdAt": {"gte": "2024-03-01"}}

        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            await repo.find(_CAMEL_VIEW, where=where)
            await repo.find(_CAMEL_VIEW, where=where)

        [message] = _key_warnings(caplog)
        assert _CAMEL_VIEW in message
        assert "'createdAt'" in message
        assert "'created_at'" in message

    @pytest.mark.asyncio
    async def test_order_by_on_a_camel_case_key_warns(
        self, class_db_pool, note_views, caplog
    ) -> None:
        repo = _repo(class_db_pool)

        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            await repo.find(_CAMEL_VIEW, order_by={"createdAt": "DESC"})

        [message] = _key_warnings(caplog)
        assert _CAMEL_VIEW in message
        assert "'createdAt'" in message

    @pytest.mark.asyncio
    async def test_probe_runs_inside_the_session_variable_transaction(
        self, class_db_pool, note_views, caplog
    ) -> None:
        repo = _repo(class_db_pool)
        repo.context["tenant_id"] = "00000000-0000-0000-0000-000000000001"

        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            result = await repo.find(
                _CAMEL_VIEW, where={"title": {"eq": "a"}}, order_by={"createdAt": "ASC"}
            )

        assert len(_key_warnings(caplog)) == 1
        assert b'"title":"a"' in result.bytes

    @pytest.mark.asyncio
    async def test_nested_camel_case_key_warns(self, class_db_pool, note_views, caplog) -> None:
        repo = _repo(class_db_pool)

        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            await repo.find(_CAMEL_VIEW, where={"author": {"firstName": {"eq": "x"}}})

        [message] = _key_warnings(caplog)
        assert "'author.firstName'" in message
        assert "'author.first_name'" in message

    @pytest.mark.asyncio
    async def test_find_one_warns(self, class_db_pool, note_views, caplog) -> None:
        repo = _repo(class_db_pool)

        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            await repo.find_one(_CAMEL_VIEW, where={"created_at": {"eq": "2024-01-01"}})

        assert len(_key_warnings(caplog)) == 1

    @pytest.mark.asyncio
    async def test_snake_case_view_does_not_warn(self, class_db_pool, note_views, caplog) -> None:
        repo = _repo(class_db_pool)

        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            await repo.find(
                _SNAKE_VIEW,
                where={"createdAt": {"gte": "2024-03-01"}},
                order_by={"createdAt": "DESC"},
            )

        assert _key_warnings(caplog) == []
        # probed, and found the snake_case key
        assert (_SNAKE_VIEW, "data", (), "created_at") in fraiseql_db._camel_case_key_probes

    @pytest.mark.asyncio
    async def test_single_word_field_is_not_probed(self, class_db_pool, note_views, caplog) -> None:
        repo = _repo(class_db_pool)

        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            await repo.find(_CAMEL_VIEW, where={"title": {"eq": "a"}})

        assert _key_warnings(caplog) == []
        assert fraiseql_db._camel_case_key_probes == set()

    @pytest.mark.asyncio
    async def test_production_does_not_probe(self, class_db_pool, note_views, caplog) -> None:
        repo = _repo(class_db_pool, environment="production")

        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            await repo.find(_CAMEL_VIEW, where={"createdAt": {"gte": "2024-03-01"}})

        assert _key_warnings(caplog) == []
        assert fraiseql_db._camel_case_key_probes == set()
