"""Tests for Issue #341 Phase 02: Period-alignment detection helpers.

Verifies that:
- _is_period_aligned returns correct booleans for all five trunc values.
- _is_period_aligned raises ValueError for unknown trunc.
- _extract_lower_date_bound returns the date for gte conditions.
- _extract_lower_date_bound returns value+1 day for gt conditions.
- _extract_lower_date_bound returns None when no matching condition exists.
"""

from datetime import date

import pytest

from fraiseql.partial_period import _extract_lower_date_bound, _is_period_aligned
from fraiseql.where_clause import FieldCondition, WhereClause

# ── _is_period_aligned ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "dt, trunc, expected",
    [
        (date(2025, 2, 1), "month", True),
        (date(2025, 1, 15), "month", False),
        (date(2025, 1, 1), "year", True),
        (date(2025, 3, 1), "year", False),
        (date(2025, 4, 1), "quarter", True),
        (date(2025, 5, 1), "quarter", False),
        (date(2025, 1, 1), "quarter", True),
        (date(2025, 7, 1), "quarter", True),
        (date(2025, 10, 1), "quarter", True),
        # week: Monday aligned
        (date(2025, 3, 3), "week", True),   # 2025-03-03 is a Monday
        (date(2025, 3, 4), "week", False),  # Tuesday
        # day: always aligned
        (date(2025, 3, 3), "day", True),
        (date(2025, 12, 31), "day", True),
    ],
)
def test_is_period_aligned(dt: date, trunc: str, expected: bool) -> None:
    assert _is_period_aligned(dt, trunc) == expected


def test_is_period_aligned_unknown_trunc_raises() -> None:
    with pytest.raises(ValueError):
        _is_period_aligned(date(2025, 1, 1), "decade")


# ── _extract_lower_date_bound ────────────────────────────────────────────────


def _make_wc_with_date_gte(col: str, value: date) -> WhereClause:
    cond = FieldCondition(
        field_path=[col],
        operator="gte",
        value=value,
        lookup_strategy="sql_column",
        target_column=col,
    )
    return WhereClause(conditions=[cond])


def _make_wc_with_date_gt(col: str, value: date) -> WhereClause:
    cond = FieldCondition(
        field_path=[col],
        operator="gt",
        value=value,
        lookup_strategy="sql_column",
        target_column=col,
    )
    return WhereClause(conditions=[cond])


def _make_wc_with_date_eq(col: str, value: date) -> WhereClause:
    cond = FieldCondition(
        field_path=[col],
        operator="eq",
        value=value,
        lookup_strategy="sql_column",
        target_column=col,
    )
    return WhereClause(conditions=[cond])


def _make_wc_no_date() -> WhereClause:
    cond = FieldCondition(
        field_path=["tenant_id"],
        operator="eq",
        value=42,
        lookup_strategy="sql_column",
        target_column="tenant_id",
    )
    return WhereClause(conditions=[cond])


def test_extracts_gte_date_filter() -> None:
    wc = _make_wc_with_date_gte("date", date(2025, 1, 15))
    result = _extract_lower_date_bound(wc, "date")
    assert result == date(2025, 1, 15)


def test_extracts_gt_date_filter_with_day_increment() -> None:
    """Strict > on a DATE column: date > '2025-01-14' → effective bound '2025-01-15'."""
    wc = _make_wc_with_date_gt("date", date(2025, 1, 14))
    result = _extract_lower_date_bound(wc, "date")
    assert result == date(2025, 1, 15)


def test_returns_none_when_no_date_filter() -> None:
    wc = _make_wc_no_date()
    assert _extract_lower_date_bound(wc, "date") is None


def test_returns_none_for_equality_filter() -> None:
    wc = _make_wc_with_date_eq("date", date(2025, 1, 15))
    assert _extract_lower_date_bound(wc, "date") is None


def test_returns_none_when_column_differs() -> None:
    wc = _make_wc_with_date_gte("event_date", date(2025, 1, 15))
    assert _extract_lower_date_bound(wc, "date") is None


def test_accepts_iso_string_value() -> None:
    cond = FieldCondition(
        field_path=["date"],
        operator="gte",
        value="2025-03-15",
        lookup_strategy="sql_column",
        target_column="date",
    )
    wc = WhereClause(conditions=[cond])
    result = _extract_lower_date_bound(wc, "date")
    assert result == date(2025, 3, 15)


def test_first_matching_condition_wins() -> None:
    """When multiple gte conditions on the same column exist, the first wins."""
    cond1 = FieldCondition(
        field_path=["date"],
        operator="gte",
        value=date(2025, 1, 1),
        lookup_strategy="sql_column",
        target_column="date",
    )
    cond2 = FieldCondition(
        field_path=["date"],
        operator="gte",
        value=date(2025, 6, 1),
        lookup_strategy="sql_column",
        target_column="date",
    )
    wc = WhereClause(conditions=[cond1, cond2])
    result = _extract_lower_date_bound(wc, "date")
    assert result == date(2025, 1, 1)
