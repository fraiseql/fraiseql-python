"""Tests for _build_trunc_expr — SQL expression dispatch for time grain truncation.

Verifies that:
- Standard PostgreSQL truncations use date_trunc().
- semester uses MAKE_DATE with month-based CASE.
- half_month uses CASE with day-based branching.
- Unsupported values raise ValueError.
"""

import pytest
from psycopg.sql import Identifier

from fraiseql.db import _build_trunc_expr


class TestStandardTruncations:
    """Standard PostgreSQL intervals delegate to date_trunc()."""

    @pytest.mark.parametrize(
        "trunc",
        ["day", "week", "month", "quarter", "year"],
    )
    def test_uses_date_trunc(self, trunc: str) -> None:
        expr = _build_trunc_expr(trunc, Identifier("date"))
        sql_str = expr.as_string(None)
        assert "date_trunc" in sql_str
        assert f"'{trunc}'" in sql_str
        assert 't."date"' in sql_str


class TestSemesterTruncation:
    """semester uses MAKE_DATE to produce Jan 1 or Jul 1."""

    def test_uses_make_date(self) -> None:
        expr = _build_trunc_expr("semester", Identifier("date"))
        sql_str = expr.as_string(None)
        assert "MAKE_DATE" in sql_str

    def test_contains_month_extraction(self) -> None:
        expr = _build_trunc_expr("semester", Identifier("date"))
        sql_str = expr.as_string(None)
        assert "EXTRACT(MONTH FROM" in sql_str

    def test_contains_year_extraction(self) -> None:
        expr = _build_trunc_expr("semester", Identifier("date"))
        sql_str = expr.as_string(None)
        assert "EXTRACT(YEAR FROM" in sql_str

    def test_references_column(self) -> None:
        expr = _build_trunc_expr("semester", Identifier("my_date"))
        sql_str = expr.as_string(None)
        assert '"my_date"' in sql_str


class TestHalfMonthTruncation:
    """half_month uses CASE to produce 1st or 16th of the month."""

    def test_uses_case(self) -> None:
        expr = _build_trunc_expr("half_month", Identifier("date"))
        sql_str = expr.as_string(None)
        assert "CASE" in sql_str

    def test_contains_day_extraction(self) -> None:
        expr = _build_trunc_expr("half_month", Identifier("date"))
        sql_str = expr.as_string(None)
        assert "EXTRACT(DAY FROM" in sql_str

    def test_adds_15_for_second_half(self) -> None:
        expr = _build_trunc_expr("half_month", Identifier("date"))
        sql_str = expr.as_string(None)
        assert "+ 15" in sql_str

    def test_references_column(self) -> None:
        expr = _build_trunc_expr("half_month", Identifier("my_date"))
        sql_str = expr.as_string(None)
        assert '"my_date"' in sql_str


class TestUnsupportedTruncation:
    def test_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unsupported time_grain_trunc"):
            _build_trunc_expr("fortnight", Identifier("date"))
