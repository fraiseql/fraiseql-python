"""An array eq / neq filter matches elements holding a quote.

build_array_eq_sql escaped the JSON's quotes and then wrapped it in a Literal,
which escaped them again, so ``tags: {eq: ["it's"]}`` matched no row.
"""

import pytest
from psycopg.sql import SQL

from fraiseql.sql.where_generator import _make_filter_field_composed

pytestmark = [pytest.mark.integration, pytest.mark.database]

ROWS = SQL(
    """SELECT data->>'name' FROM (VALUES
        ('{"name": "quote", "tags": ["it''s"]}'::jsonb),
        ('{"name": "plain", "tags": ["its"]}'::jsonb)
    ) AS t(data) WHERE """
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("op", "expected"), [("eq", ["quote"]), ("neq", ["plain"])])
async def test_array_filter_with_quote(db_connection, op: str, expected: list[str]) -> None:
    condition = _make_filter_field_composed("tags", {op: ["it's"]}, "data", list[str])
    cursor = await db_connection.execute(ROWS + condition)
    assert [row[0] for row in await cursor.fetchall()] == expected
