"""A string ``order_by`` is a list of column names, never SQL put into the query.

``db.find(view, order_by="date DESC")`` used to append the string after
``ORDER BY`` as is, so a resolver that forwarded a client-supplied sort string
let the client write SQL. The string is now parsed: comma-separated column
names (optionally qualified, optionally double-quoted), each followed by an
optional ``ASC``/``DESC`` and an optional ``NULLS FIRST``/``NULLS LAST``.
Anything else raises ``ValueError`` before a query is built.
"""

from unittest.mock import MagicMock

import pytest

from fraiseql.db import FraiseQLRepository


def _order_by_sql(order_by: str, **kwargs) -> str:
    repo = FraiseQLRepository(MagicMock())
    query = repo._build_find_query("v_item", jsonb_column="data", order_by=order_by, **kwargs)
    sql = query.statement.as_string(None)
    return sql[sql.index(" ORDER BY ") :]


class TestAcceptedStrings:
    @pytest.mark.parametrize(
        ("order_by", "expected"),
        [
            ("date", ' ORDER BY "date"'),
            ("date ASC", ' ORDER BY "date" ASC'),
            ("date desc", ' ORDER BY "date" DESC'),
            # PostgreSQL folds an unquoted name to lower case; so does the parser.
            ("createdAt DESC", ' ORDER BY "createdat" DESC'),
            ('"createdAt" DESC', ' ORDER BY "createdAt" DESC'),
            ('"a ""b"", c"', ' ORDER BY "a ""b"", c"'),
            ("t.date, id DESC", ' ORDER BY "t"."date", "id" DESC'),
            ("s.v.col asc nulls last", ' ORDER BY "s"."v"."col" ASC NULLS LAST'),
            ("  rank   NULLS  FIRST ,id  ", ' ORDER BY "rank" NULLS FIRST, "id"'),
            ("price_$1 DESC", ' ORDER BY "price_$1" DESC'),
        ],
    )
    def test_renders_quoted_identifiers(self, order_by: str, expected: str) -> None:
        assert _order_by_sql(order_by) == expected

    def test_after_group_by_and_before_limit(self) -> None:
        sql = _order_by_sql(
            "date ASC", group_by=["date"], aggregations={"total": "SUM(cost)"}, limit=5
        )

        assert sql == ' ORDER BY "date" ASC LIMIT 5'


class TestRejectedStrings:
    @pytest.mark.parametrize(
        "order_by",
        [
            "id; DROP TABLE victim; --",
            "id DESC; DELETE FROM victim",
            "(SELECT 1)",
            "CASE WHEN true THEN id END",
            "data->>'name'",
            "lower(name)",
            "count(*)",
            "1",
            "id -- comment",
            "id /* c */",
            'id"',
            '"unterminated',
            '""',
            "id DESC DESC",
            "id NULLS",
            "id NULLS MIDDLE",
            "a.b.c.d",
            "a.",
            "a,",
            ",a",
            "a,,b",
            "   ",
            "id\x00",
            "名前",
        ],
    )
    def test_raises_value_error(self, order_by: str) -> None:
        repo = FraiseQLRepository(MagicMock())

        with pytest.raises(ValueError, match="order_by"):
            repo._build_find_query("v_item", jsonb_column="data", order_by=order_by)

    def test_message_points_to_the_dict_form(self) -> None:
        repo = FraiseQLRepository(MagicMock())

        with pytest.raises(ValueError, match=r"dict"):
            repo._build_find_query("v_item", jsonb_column="data", order_by="data->>'x'")
