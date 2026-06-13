"""Tests for Issues #1516/#1517: semester and half_month period helpers.

Verifies that _is_period_aligned, _period_start, and _next_period_start
handle semester (Jan/Jul boundaries) and half_month (1st/16th boundaries)
correctly, including edge cases for year boundaries, short months, and
leap years.
"""

from datetime import date

import pytest

from fraiseql.partial_period import (
    _is_period_aligned,
    _next_period_start,
    _period_start,
)

# ── semester: _is_period_aligned ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("dt", "expected"),
    [
        (date(2025, 1, 1), True),  # H1 start
        (date(2025, 7, 1), True),  # H2 start
        (date(2025, 3, 15), False),  # mid-H1
        (date(2025, 6, 30), False),  # last day of H1
        (date(2025, 9, 20), False),  # mid-H2
        (date(2025, 12, 31), False),  # last day of H2
    ],
)
def test_semester_is_period_aligned(dt: date, expected: bool) -> None:
    assert _is_period_aligned(dt, "semester") == expected


# ── semester: _period_start ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("dt", "expected"),
    [
        (date(2025, 3, 15), date(2025, 1, 1)),  # mid-H1 → Jan 1
        (date(2025, 9, 20), date(2025, 7, 1)),  # mid-H2 → Jul 1
        (date(2025, 1, 1), date(2025, 1, 1)),  # H1 start → itself
        (date(2025, 7, 1), date(2025, 7, 1)),  # H2 start → itself
        (date(2025, 12, 31), date(2025, 7, 1)),  # last day of year → Jul 1
        (date(2025, 6, 30), date(2025, 1, 1)),  # last day of H1 → Jan 1
    ],
)
def test_semester_period_start(dt: date, expected: date) -> None:
    assert _period_start(dt, "semester") == expected


# ── semester: _next_period_start ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("dt", "expected"),
    [
        (date(2025, 3, 15), date(2025, 7, 1)),  # mid-H1 → Jul 1
        (date(2025, 9, 20), date(2026, 1, 1)),  # mid-H2 → next year Jan 1
        (date(2025, 7, 1), date(2026, 1, 1)),  # H2 start → next year Jan 1
        (date(2025, 1, 1), date(2025, 7, 1)),  # H1 start → Jul 1
        (date(2025, 12, 31), date(2026, 1, 1)),  # year boundary
    ],
)
def test_semester_next_period_start(dt: date, expected: date) -> None:
    assert _next_period_start(dt, "semester") == expected


# ── half_month: _is_period_aligned ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("dt", "expected"),
    [
        (date(2025, 3, 1), True),  # 1st — boundary
        (date(2025, 3, 16), True),  # 16th — boundary
        (date(2025, 3, 15), False),  # 15th — NOT a boundary
        (date(2025, 3, 2), False),  # mid-first-half
        (date(2025, 2, 16), True),  # Feb 16 — short month, still boundary
        (date(2025, 12, 1), True),  # Dec 1st
        (date(2025, 12, 16), True),  # Dec 16th
    ],
)
def test_half_month_is_period_aligned(dt: date, expected: bool) -> None:
    assert _is_period_aligned(dt, "half_month") == expected


# ── half_month: _period_start ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("dt", "expected"),
    [
        (date(2025, 3, 10), date(2025, 3, 1)),  # mid-first-half → 1st
        (date(2025, 3, 16), date(2025, 3, 16)),  # 16th → itself
        (date(2025, 3, 25), date(2025, 3, 16)),  # mid-second-half → 16th
        (date(2025, 3, 1), date(2025, 3, 1)),  # 1st → itself
        (date(2025, 3, 15), date(2025, 3, 1)),  # day 15 → first half
        (date(2024, 2, 29), date(2024, 2, 16)),  # leap year Feb 29 → 16th
        (date(2025, 2, 28), date(2025, 2, 16)),  # non-leap Feb 28 → 16th
    ],
)
def test_half_month_period_start(dt: date, expected: date) -> None:
    assert _period_start(dt, "half_month") == expected


# ── half_month: _next_period_start ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("dt", "expected"),
    [
        (date(2025, 3, 10), date(2025, 3, 16)),  # first half → 16th
        (date(2025, 3, 20), date(2025, 4, 1)),  # second half → next month 1st
        (date(2025, 12, 20), date(2026, 1, 1)),  # Dec second half → Jan 1 next year
        (date(2025, 2, 10), date(2025, 2, 16)),  # Feb first half → Feb 16
        (date(2025, 2, 20), date(2025, 3, 1)),  # Feb second half → Mar 1
        (date(2025, 12, 10), date(2025, 12, 16)),  # Dec first half → Dec 16
        (date(2024, 2, 20), date(2024, 3, 1)),  # leap year Feb second half → Mar 1
    ],
)
def test_half_month_next_period_start(dt: date, expected: date) -> None:
    assert _next_period_start(dt, "half_month") == expected
