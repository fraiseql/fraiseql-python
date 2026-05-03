"""Partial-period awareness utilities for pre-aggregated time-series views.

When a date filter is applied to a coarse-grain view (e.g. monthly aggregates),
the lower-bound date may fall in the middle of a period. This module provides
helpers to detect that situation and build UNION ALL queries that combine:

  - Branch 1: fine-grain rows for the partial leading period (when present)
  - Branch 2: coarse-grain rows for complete intermediate periods
  - Branch 3: fine-grain rows for the current in-progress period

All functions in this module are pure (no database calls) and importable without
creating circular dependencies with the query layer.
"""

from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fraiseql.where_clause import WhereClause

_VALID_GRAIN_TRUNCS = frozenset({"day", "week", "month", "quarter", "year"})


def _validate_grain_trunc(value: str) -> str:
    """Validate and return the time_grain_trunc value.

    Args:
        value: One of "day", "week", "month", "quarter", "year".

    Returns:
        The validated value (unchanged).

    Raises:
        ValueError: If the value is not in the allowed set.
    """
    if value not in _VALID_GRAIN_TRUNCS:
        allowed = ", ".join(sorted(_VALID_GRAIN_TRUNCS))
        msg = f"Invalid time_grain_trunc {value!r}. Must be one of: {allowed}"
        raise ValueError(msg)
    return value


def _is_period_aligned(dt: date, trunc: str) -> bool:
    """Return True when *dt* is exactly at the start of a period boundary.

    Period boundaries:
      - day:     always aligned (every date is a day start)
      - week:    Monday only (dt.weekday() == 0)
      - month:   first day of month (dt.day == 1)
      - quarter: first day of a quarter month (dt.day == 1 and dt.month in {1,4,7,10})
      - year:    January 1st (dt.day == 1 and dt.month == 1)

    Args:
        dt:    The date to test.
        trunc: One of "day", "week", "month", "quarter", "year".

    Returns:
        True when dt is at a period boundary.

    Raises:
        ValueError: If trunc is not a recognised granularity.
    """
    _validate_grain_trunc(trunc)
    if trunc == "day":
        return True
    if trunc == "week":
        return dt.weekday() == 0
    if trunc == "month":
        return dt.day == 1
    if trunc == "quarter":
        return dt.day == 1 and dt.month in {1, 4, 7, 10}
    # trunc == "year"
    return dt.day == 1 and dt.month == 1


def _period_start(dt: date, trunc: str) -> date:
    """Return the start of the period containing *dt*.

    Args:
        dt:    The date to find the period start for.
        trunc: One of "day", "week", "month", "quarter", "year".

    Returns:
        The start date of the period containing *dt*.
    """
    _validate_grain_trunc(trunc)
    if trunc == "day":
        return dt
    if trunc == "week":
        return dt - timedelta(days=dt.weekday())
    if trunc == "month":
        return date(dt.year, dt.month, 1)
    if trunc == "quarter":
        quarter_month = ((dt.month - 1) // 3) * 3 + 1
        return date(dt.year, quarter_month, 1)
    # year
    return date(dt.year, 1, 1)


def _next_period_start(dt: date, trunc: str) -> date:
    """Return the start of the period immediately after the period containing *dt*.

    Args:
        dt:    Any date within the period.
        trunc: One of "day", "week", "month", "quarter", "year".

    Returns:
        The start date of the next period.
    """
    start = _period_start(dt, trunc)
    if trunc == "day":
        return start + timedelta(days=1)
    if trunc == "week":
        return start + timedelta(weeks=1)
    if trunc == "month":
        if start.month == 12:
            return date(start.year + 1, 1, 1)
        return date(start.year, start.month + 1, 1)
    if trunc == "quarter":
        if start.month == 10:
            return date(start.year + 1, 1, 1)
        return date(start.year, start.month + 3, 1)
    # year
    return date(start.year + 1, 1, 1)


def _extract_lower_date_bound(
    where_clause: "WhereClause",
    column: str,
) -> date | None:
    """Extract the effective lower-bound date from a WhereClause.

    Scans *where_clause.conditions* for the first ``gte`` or ``gt`` condition
    whose ``target_column`` matches *column*.  Returns:

      - For ``gte``: the value directly.
      - For ``gt``:  the value incremented by one day (because
        ``date > '2025-01-14'`` is equivalent to ``date >= '2025-01-15'``
        for DATE-typed columns).
      - ``None`` if no matching condition is found.

    Only top-level conditions are scanned (nested_clauses are ignored) because
    partial-period awareness applies to the primary time-grain filter, which is
    always a simple top-level condition.

    Args:
        where_clause: The normalised WHERE clause to scan.
        column:       The database column name to match (e.g. ``"date"``).

    Returns:
        The effective lower-bound date, or None.
    """
    for cond in where_clause.conditions:
        if cond.target_column != column:
            continue
        if cond.operator not in ("gte", "gt"):
            continue

        value = cond.value
        # Accept both date objects and ISO strings
        if isinstance(value, str):
            value = date.fromisoformat(value)
        if not isinstance(value, date):
            continue

        if cond.operator == "gt":
            value = value + timedelta(days=1)
        return value

    return None
