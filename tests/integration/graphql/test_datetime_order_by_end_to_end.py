"""An ``orderBy`` on a datetime or date field sorts by date, not by text.

A JSONB field holds an ISO string, and ``data -> 'created_at'`` compares two of
them as strings: ``"2025-01-01T00:30:00+01:00"`` (23:30Z the day before) sorts
after ``"2025-01-01T00:00:00+00:00"``. The field's declared type says it is a
timestamp, so the sort key is cast: ``(data ->> 'created_at')::timestamptz``.
"""

import json
from datetime import date, datetime

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.sql.order_by_generator import OrderBy, OrderBySet, OrderDirection

pytestmark = pytest.mark.integration

# Instants in id order; the strings sort 4, 2, 3, 1 as text.
_CREATED = {
    1: "2025-01-01T00:30:00+01:00",  # 2024-12-31T23:30Z
    2: "2025-01-01T00:00:00+00:00",  # 2025-01-01T00:00Z
    3: "2025-01-01T00:10:00Z",  # 2025-01-01T00:10Z
    4: "2024-12-31T23:59:00-02:00",  # 2025-01-01T01:59Z
}
# author.joined_at reverses them: instants sort 4, 3, 2, 1, text sorts 1, 3, 2, 4.
_JOINED = {i: _CREATED[5 - i] for i in _CREATED}
# closed_at is null on 2 and 4; the others sort 3, 1 by instant, 1, 3 as text.
_CLOSED = {1: "2025-03-01T10:00:00+05:00", 2: None, 3: "2025-03-01T06:00:00+02:00", 4: None}
_DUE = {1: "2025-02-10", 2: "2025-01-05", 3: "2025-12-01", 4: "2024-06-30"}

_EXPECTED = {
    ("created_at", "ASC"): [1, 2, 3, 4],
    ("created_at", "DESC"): [4, 3, 2, 1],
    ("author.joined_at", "ASC"): [4, 3, 2, 1],
    ("author.joined_at", "DESC"): [1, 2, 3, 4],
    ("due_on", "ASC"): [4, 2, 1, 3],
    ("due_on", "DESC"): [3, 1, 2, 4],
    # NULLs sort as PostgreSQL sorts them: last ascending, first descending.
    ("closed_at", "ASC"): [3, 1, None, None],
    ("closed_at", "DESC"): [None, None, 1, 3],
}

_GRAPHQL_FIELD = {
    "created_at": "{{createdAt: {d}}}",
    "author.joined_at": "{{author: {{joinedAt: {d}}}}}",
    "due_on": "{{dueOn: {d}}}",
    "closed_at": "{{closedAt: {d}}}",
}


def _sql_text(value: str | None) -> str:
    return "NULL" if value is None else f"'{value}'"


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def event_tables(class_db_pool, test_schema) -> None:
    rows = ", ".join(
        f"({i}, {_sql_text(_CREATED[i])}, {_sql_text(_JOINED[i])}, "
        f"{_sql_text(_CLOSED[i])}, '{_DUE[i]}')"
        for i in _CREATED
    )
    async with class_db_pool.connection() as conn:
        await conn.execute(
            f"""
            CREATE TABLE {test_schema}.tb_event (
                id int PRIMARY KEY, created_at text NOT NULL, joined_at text NOT NULL,
                closed_at text, due_on date NOT NULL
            );
            CREATE VIEW {test_schema}.v_event AS
                SELECT id, jsonb_build_object(
                    'id', id,
                    'created_at', created_at,
                    'closed_at', closed_at,
                    'due_on', due_on,
                    'author', jsonb_build_object('id', id, 'joined_at', joined_at)
                ) AS data
                FROM {test_schema}.tb_event;
            INSERT INTO {test_schema}.tb_event VALUES {rows};

            CREATE TABLE {test_schema}.tb_flat_event (
                id int PRIMARY KEY, created_at timestamptz NOT NULL
            );
            CREATE VIEW {test_schema}.v_flat_event AS
                SELECT id, created_at FROM {test_schema}.tb_flat_event;
            INSERT INTO {test_schema}.tb_flat_event
                SELECT id, created_at::timestamptz FROM {test_schema}.tb_event;
            """
        )
        await conn.commit()


@pytest.fixture
def event_types(test_schema, clear_registry):
    @fraiseql.type
    class Member:
        id: int
        joined_at: datetime

    @fraiseql.type(sql_source=f"{test_schema}.v_event", jsonb_column="data")
    class Event:
        id: int
        created_at: datetime
        closed_at: datetime | None
        due_on: date
        author: Member

    @fraiseql.type(sql_source=f"{test_schema}.v_flat_event", jsonb_column=None)
    class FlatEvent:
        id: int
        created_at: datetime

    return Event, FlatEvent


@pytest.fixture
def client(class_db_pool, test_schema, event_tables, event_types) -> TestClient:
    from fraiseql.fastapi.dependencies import set_db_pool

    event_type, _ = event_types

    @fraiseql.query
    async def events(info, order_by=None) -> list[event_type]:
        db = info.context["db"]
        return await db.find(f"{test_schema}.v_event", "events", info, order_by=order_by)

    set_db_pool(class_db_pool)

    async def context_getter(request, user=None):
        return {"db": FraiseQLRepository(class_db_pool), "user": user}

    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[event_type],
        queries=[events],
        production=False,
        context_getter=context_getter,
    )
    return TestClient(app)


def _graphql_ids(client: TestClient, field: str, direction: str) -> list[int]:
    order_by = _GRAPHQL_FIELD[field].format(d=direction)
    query = f"{{ events(orderBy: [{order_by}]) {{ id }} }}"
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200, response.text
    body = json.loads(response.text)
    assert "errors" not in body, body["errors"]
    return [row["id"] for row in body["data"]["events"]]


async def _find_ids(pool, view: str, order_by) -> list[int]:
    repo = FraiseQLRepository(pool, context={"mode": "development"})
    rows = extract_graphql_data(await repo.find(view, order_by=order_by), view)
    return [row["id"] for row in rows]


def _matches(ids: list[int], expected: list[int | None]) -> bool:
    """Compare a sort result, treating each None as any row with a NULL key."""
    nulls = [i for i, value in _CLOSED.items() if value is None]
    return len(ids) == len(expected) and all(
        (want is None and got in nulls) or got == want
        for got, want in zip(ids, expected, strict=True)
    )


def _nested_dict(field: str, direction: str) -> dict:
    head, _, rest = field.partition(".")
    return {head: _nested_dict(rest, direction) if rest else direction}


_CASES = list(_EXPECTED)


@pytest.mark.usefixtures("test_schema")
class TestDatetimeOrderByGraphQL:
    @pytest.mark.parametrize(("field", "direction"), _CASES)
    def test_sorts_by_instant(self, client: TestClient, field: str, direction: str) -> None:
        ids = _graphql_ids(client, field, direction)
        assert _matches(ids, _EXPECTED[field, direction]), ids


@pytest.mark.usefixtures("test_schema")
class TestDatetimeOrderByFind:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("field", "direction"), _CASES)
    async def test_dict_sorts_by_instant(
        self, class_db_pool, test_schema, event_tables, event_types, field, direction
    ) -> None:
        order_by = _nested_dict(field, direction)
        ids = await _find_ids(class_db_pool, f"{test_schema}.v_event", order_by)
        assert _matches(ids, _EXPECTED[field, direction]), ids

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("field", "direction"), _CASES)
    async def test_list_sorts_by_instant(
        self, class_db_pool, test_schema, event_tables, event_types, field, direction
    ) -> None:
        order_by = [_nested_dict(field, direction)]
        ids = await _find_ids(class_db_pool, f"{test_schema}.v_event", order_by)
        assert _matches(ids, _EXPECTED[field, direction]), ids

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("field", "direction"), _CASES)
    async def test_order_by_set_sorts_by_instant(
        self, class_db_pool, test_schema, event_tables, event_types, field, direction
    ) -> None:
        order_by = OrderBySet([OrderBy(field, OrderDirection(direction.lower()))])
        ids = await _find_ids(class_db_pool, f"{test_schema}.v_event", order_by)
        assert _matches(ids, _EXPECTED[field, direction]), ids

    @pytest.mark.asyncio
    async def test_secondary_key_keeps_its_jsonb_sort(
        self, class_db_pool, test_schema, event_tables, event_types
    ) -> None:
        order_by = [{"closed_at": "ASC"}, {"id": "DESC"}]
        ids = await _find_ids(class_db_pool, f"{test_schema}.v_event", order_by)
        assert ids == [3, 1, 4, 2]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("direction", ["ASC", "DESC"])
    async def test_flat_timestamptz_column_sorts_by_instant(
        self, class_db_pool, test_schema, event_tables, event_types, direction
    ) -> None:
        ids = await _find_ids(
            class_db_pool, f"{test_schema}.v_flat_event", {"created_at": direction}
        )
        assert ids == _EXPECTED["created_at", direction]
