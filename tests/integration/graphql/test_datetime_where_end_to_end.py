"""A ``where`` on a datetime or date field compares dates, not text.

A view built with ``jsonb_build_object('created_at', created_at)`` holds the
string ``"2025-01-01T00:00:00+00:00"``. Compared as text against
``"2025-01-01T00:00:00Z"`` it is smaller (``'+' < 'Z'``), so ``gte`` left the
row out, and ``"2025-01-01T01:00:00+01:00"`` -- the same instant -- matched
nothing at all. The field's declared type says it is a timestamp, so the
comparison casts both sides: ``(data ->> 'created_at')::timestamptz >= %s::timestamptz``.
"""

import json
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.sql import create_graphql_where_input

pytestmark = pytest.mark.integration

# Three spellings of the boundary instant 2025-01-01T00:00:00Z.
_BOUNDARIES = [
    "2025-01-01T00:00:00Z",
    "2025-01-01T00:00:00+00:00",
    "2025-01-01T01:00:00+01:00",
]

# id 1 is a second before the boundary, id 2 on it, id 3 a second after.
_EXPECTED = {"gte": [2, 3], "lt": [1], "eq": [2]}


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def note_tables(class_db_pool, test_schema) -> None:
    async with class_db_pool.connection() as conn:
        await conn.execute(
            f"""
            CREATE TABLE {test_schema}.tb_note (
                id int PRIMARY KEY, created_at timestamptz NOT NULL, due_on date NOT NULL,
                author_id int NOT NULL
            );
            CREATE VIEW {test_schema}.v_note AS
                SELECT id, jsonb_build_object(
                    'id', id,
                    'created_at', to_char(created_at AT TIME ZONE 'UTC',
                                          'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
                    'due_on', due_on,
                    'author', jsonb_build_object(
                        'id', author_id,
                        'joined_at', to_char(created_at AT TIME ZONE 'UTC',
                                             'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'))
                ) AS data
                FROM {test_schema}.tb_note;
            INSERT INTO {test_schema}.tb_note VALUES
                (1, '2024-12-31T23:59:59Z', '2024-12-31', 1),
                (2, '2025-01-01T00:00:00Z', '2025-01-01', 2),
                (3, '2025-01-01T00:00:01Z', '2025-01-02', 3);

            CREATE TABLE {test_schema}.tb_flat_note (
                id int PRIMARY KEY, created_at timestamptz NOT NULL
            );
            CREATE VIEW {test_schema}.v_flat_note AS
                SELECT id, created_at FROM {test_schema}.tb_flat_note;
            INSERT INTO {test_schema}.tb_flat_note VALUES
                (1, '2024-12-31T23:59:59Z'),
                (2, '2025-01-01T00:00:00Z'),
                (3, '2025-01-01T00:00:01Z');
            """
        )
        await conn.commit()


@pytest.fixture
def note_types(test_schema, clear_registry):
    @fraiseql.type
    class Author:
        id: int
        joined_at: datetime | None

    @fraiseql.type(sql_source=f"{test_schema}.v_note", jsonb_column="data")
    class Note:
        id: int
        created_at: datetime
        due_on: date | None
        author: Author

    @fraiseql.type(sql_source=f"{test_schema}.v_flat_note", jsonb_column=None)
    class FlatNote:
        id: int
        created_at: datetime

    return Note, FlatNote


@pytest.fixture
def client(class_db_pool, test_schema, note_tables, note_types) -> TestClient:
    from fraiseql.fastapi.dependencies import set_db_pool

    note_type, _ = note_types
    note_where = create_graphql_where_input(note_type)

    @fraiseql.query
    async def notes(info, where: note_where | None = None) -> list[note_type]:
        db = info.context["db"]
        return await db.find(f"{test_schema}.v_note", "notes", info, where=where)

    set_db_pool(class_db_pool)

    async def context_getter(request, user=None):
        return {"db": FraiseQLRepository(class_db_pool), "user": user}

    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[note_type],
        queries=[notes],
        production=False,
        context_getter=context_getter,
    )
    return TestClient(app)


def _ids(client: TestClient, where: str) -> list[int]:
    response = client.post("/graphql", json={"query": f"{{ notes(where: {where}) {{ id }} }}"})
    assert response.status_code == 200, response.text
    body = json.loads(response.text)
    assert "errors" not in body, body["errors"]
    return sorted(row["id"] for row in body["data"]["notes"])


async def _find_ids(pool, view: str, where: dict) -> list[int]:
    repo = FraiseQLRepository(pool, context={"mode": "development"})
    rows = extract_graphql_data(await repo.find(view, where=where), view)
    return sorted(row["id"] for row in rows)


@pytest.mark.usefixtures("test_schema")
class TestDatetimeWhereGraphQL:
    @pytest.mark.parametrize("boundary", _BOUNDARIES)
    @pytest.mark.parametrize("op", ["gte", "lt", "eq"])
    def test_datetime_compares_as_timestamptz(
        self, client: TestClient, op: str, boundary: str
    ) -> None:
        assert _ids(client, f'{{createdAt: {{{op}: "{boundary}"}}}}') == _EXPECTED[op]

    @pytest.mark.parametrize("boundary", _BOUNDARIES)
    def test_datetime_in_compares_as_timestamptz(self, client: TestClient, boundary: str) -> None:
        assert _ids(client, f'{{createdAt: {{in: ["{boundary}"]}}}}') == [2]

    @pytest.mark.parametrize("boundary", _BOUNDARIES)
    def test_nested_datetime_compares_as_timestamptz(
        self, client: TestClient, boundary: str
    ) -> None:
        assert _ids(client, f'{{author: {{joinedAt: {{gte: "{boundary}"}}}}}}') == [2, 3]

    @pytest.mark.parametrize(("op", "expected"), [("gte", [2, 3]), ("lt", [1]), ("eq", [2])])
    def test_date_compares_as_date(self, client: TestClient, op: str, expected: list[int]) -> None:
        assert _ids(client, f'{{dueOn: {{{op}: "2025-01-01"}}}}') == expected


@pytest.mark.usefixtures("test_schema")
class TestDatetimeWhereDictFind:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("boundary", _BOUNDARIES)
    @pytest.mark.parametrize("op", ["gte", "lt", "eq"])
    async def test_datetime_string_compares_as_timestamptz(
        self, class_db_pool, test_schema, note_tables, note_types, op: str, boundary: str
    ) -> None:
        where = {"created_at": {op: boundary}}
        assert await _find_ids(class_db_pool, f"{test_schema}.v_note", where) == _EXPECTED[op]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("op", ["gte", "lt", "eq"])
    async def test_datetime_object_compares_as_timestamptz(
        self, class_db_pool, test_schema, note_tables, note_types, op: str
    ) -> None:
        where = {"created_at": {op: datetime(2025, 1, 1, tzinfo=UTC)}}
        assert await _find_ids(class_db_pool, f"{test_schema}.v_note", where) == _EXPECTED[op]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("boundary", _BOUNDARIES)
    async def test_nested_datetime_compares_as_timestamptz(
        self, class_db_pool, test_schema, note_tables, note_types, boundary: str
    ) -> None:
        where = {"author": {"joined_at": {"gte": boundary}}}
        assert await _find_ids(class_db_pool, f"{test_schema}.v_note", where) == [2, 3]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", ["2025-01-01", date(2025, 1, 1)])
    @pytest.mark.parametrize(("op", "expected"), [("gte", [2, 3]), ("lt", [1]), ("eq", [2])])
    async def test_date_compares_as_date(
        self, class_db_pool, test_schema, note_tables, note_types, op, expected, value
    ) -> None:
        where = {"due_on": {op: value}}
        assert await _find_ids(class_db_pool, f"{test_schema}.v_note", where) == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize("boundary", _BOUNDARIES)
    @pytest.mark.parametrize("op", ["gte", "lt", "eq"])
    async def test_flat_timestamptz_column_compares_as_timestamptz(
        self, class_db_pool, test_schema, note_tables, note_types, op: str, boundary: str
    ) -> None:
        where = {"created_at": {op: boundary}}
        ids = await _find_ids(class_db_pool, f"{test_schema}.v_flat_note", where)
        assert ids == _EXPECTED[op]
