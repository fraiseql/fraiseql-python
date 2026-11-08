"""CQRSRepository binds filter keys and order_by fields as SQL literals.

A key reaches ``data->>'key'``. It used to be pasted between quotes, so a key
holding a ``'`` ended the literal and the rest of the key ran as SQL.
"""

import pytest

from fraiseql.cqrs.repository import CQRSRepository

pytestmark = [pytest.mark.integration, pytest.mark.database]

INJECTED_KEY = "x' IS NULL OR data->>'x"


class Thing:
    """Its view is ``vw_thing`` (CQRSRepository._get_view_name)."""


@pytest.fixture
async def repo(db_connection) -> CQRSRepository:
    await db_connection.execute(
        """
        CREATE TABLE tb_thing (id UUID DEFAULT gen_random_uuid() PRIMARY KEY, data JSONB);
        INSERT INTO tb_thing (data) VALUES
            ('{"it''s": "a", "rank": "1", "tags": ["red"]}'),
            ('{"it''s": "b", "rank": "2", "tags": ["blue"]}');
        CREATE VIEW vw_thing AS SELECT id, data FROM tb_thing;
        """
    )
    return CQRSRepository(db_connection)


@pytest.mark.asyncio
class TestQuotedKeys:
    async def test_query_eq_key_with_quote(self, repo) -> None:
        rows = await repo.query("vw_thing", filters={"it's": "a"})
        assert [r["it's"] for r in rows] == ["a"]

    async def test_query_list_key_with_quote(self, repo) -> None:
        rows = await repo.query("vw_thing", filters={"it's": ["b", "z"]})
        assert [r["it's"] for r in rows] == ["b"]

    async def test_query_order_by_key_with_quote(self, repo) -> None:
        rows = await repo.query("vw_thing", order_by="it's_desc")
        assert [r["it's"] for r in rows] == ["b", "a"]

    async def test_query_interface_key_with_quote(self, repo) -> None:
        rows = await repo.query_interface(
            "vw_thing", filters={"it's": "b", "rank": {"$gt": "0"}}, order_by="it's DESC"
        )
        assert [r["it's"] for r in rows] == ["b"]

    async def test_count_key_with_quote(self, repo) -> None:
        assert await repo.count(Thing, where={"it's": {"eq": "a"}}) == 1

    async def test_injected_key_matches_nothing(self, repo) -> None:
        assert await repo.query("vw_thing", filters={INJECTED_KEY: "zzz"}) == []
        assert await repo.query_interface("vw_thing", filters={INJECTED_KEY: "zzz"}) == []
        assert await repo.count(Thing, where={INJECTED_KEY: "zzz"}) == 0
