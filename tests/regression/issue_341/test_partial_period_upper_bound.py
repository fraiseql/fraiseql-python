"""Regression tests: partial-period UNION builder honours the upper bound.

Bug: when a coarse view is registered with ``fine_grain_view`` partial-period
awareness, a ``where`` date range with both ``gte`` and ``lte`` applied only the
``gte`` lower bound. The ``lte`` upper bound was silently dropped, so the query
returned every period from ``gte`` through *today* (including future periods).

These tests pin the symmetric upper-edge behaviour:
  - an aligned upper bound (period end) limits coarse rows to the requested window;
  - a straddling upper bound recomputes the final period from the fine-grain view;
  - an upper bound in the future is capped at today (no future periods);
  - omitting the upper bound preserves the original "up to today" behaviour.
"""

from datetime import date

from fraiseql.db import _build_partial_period_union_query

# A fixed "today" well after the test windows so the current-period logic does
# not interfere with the historical-window assertions.
TODAY = date(2026, 6, 14)

BASE = dict(
    coarse_view="v_events_month",
    fine_grain_view="v_events_day",
    time_grain_column="date",
    time_grain_trunc="month",
    group_by=["date"],
    aggregations={"data.volume": "SUM(data.volume)"},
    native_dimensions={"date"},
    native_measures={"data.volume": "volume"},
    native_dimension_mapping=None,
    jsonb_col="data",
    extra_where=None,
)


def _render(**overrides: object) -> str:
    query = _build_partial_period_union_query(**{**BASE, **overrides})
    return query.statement.as_string(None)


def test_aligned_lte_limits_to_coarse_window() -> None:
    """Range gte 2024-05-01, lte 2024-06-30 → only May & June from the coarse view."""
    rendered = _render(
        lower_bound=date(2024, 5, 1),
        upper_bound_exclusive=date(2024, 7, 1),  # lte 2024-06-30 → exclusive 07-01
        today=TODAY,
    )
    # Both edges aligned → a single coarse branch, no fine-grain recompute.
    assert "UNION ALL" not in rendered
    assert "v_events_month" in rendered
    assert "v_events_day" not in rendered
    # Window is [2024-05-01, 2024-07-01); must not run through to today.
    assert "2024-07-01" in rendered
    assert "2026" not in rendered


def test_straddling_lte_recomputes_upper_period_from_fine_grain() -> None:
    """Range gte 2024-05-01, lte 2024-06-15 → full May (coarse) + partial June (fine)."""
    rendered = _render(
        lower_bound=date(2024, 5, 1),
        upper_bound_exclusive=date(2024, 6, 16),  # lte 2024-06-15 → exclusive 06-16
        today=TODAY,
    )
    assert rendered.count("UNION ALL") == 1
    assert "v_events_month" in rendered  # full May
    assert "v_events_day" in rendered  # clamped June
    # The fine-grain branch is bounded by the (exclusive) upper bound.
    assert "2024-06-16" in rendered
    assert "2026" not in rendered


def test_non_aligned_lower_and_upper() -> None:
    """Range gte 2024-05-15, lte 2024-06-30 → partial May (fine) + full June (coarse)."""
    rendered = _render(
        lower_bound=date(2024, 5, 15),
        upper_bound_exclusive=date(2024, 7, 1),
        today=TODAY,
    )
    assert rendered.count("UNION ALL") == 1
    assert "v_events_day" in rendered  # partial leading May
    assert "v_events_month" in rendered  # full June
    assert "2024-05-15" in rendered
    assert "2024-07-01" in rendered
    assert "2026" not in rendered


def test_single_period_both_edges_partial() -> None:
    """A window inside one period is fully recomputed from the fine-grain view."""
    rendered = _render(
        lower_bound=date(2024, 6, 10),
        upper_bound_exclusive=date(2024, 6, 21),  # lte 2024-06-20
        today=TODAY,
    )
    assert "UNION ALL" not in rendered
    assert "v_events_day" in rendered
    assert "v_events_month" not in rendered
    assert "2024-06-10" in rendered
    assert "2024-06-21" in rendered


def test_future_lte_capped_at_today() -> None:
    """An lte beyond today never produces future periods (capped at today)."""
    rendered = _render(
        lower_bound=date(2026, 1, 1),
        upper_bound_exclusive=date(2027, 1, 1),  # lte 2026-12-31
        today=TODAY,
    )
    # Jan–May complete (coarse) + current June up to today (fine); nothing in 2027.
    assert "v_events_month" in rendered
    assert "v_events_day" in rendered
    assert "2027" not in rendered
    # Current in-progress period bounded by today_exclusive (2026-06-15).
    assert "2026-06-15" in rendered


def test_no_upper_bound_runs_through_today() -> None:
    """Omitting the upper bound preserves the original 'up to today' behaviour."""
    rendered = _render(
        lower_bound=date(2026, 1, 1),
        upper_bound_exclusive=None,
        today=TODAY,
    )
    assert "v_events_month" in rendered
    assert "v_events_day" in rendered
    # Branch 3 runs to today_exclusive = 2026-06-15.
    assert "2026-06-15" in rendered


def test_degenerate_window_returns_empty_branch() -> None:
    """An upper bound at/below the lower bound yields a single empty fine branch."""
    rendered = _render(
        lower_bound=date(2024, 6, 10),
        upper_bound_exclusive=date(2024, 6, 10),
        today=TODAY,
    )
    assert "UNION ALL" not in rendered
    assert "v_events_day" in rendered
    assert "v_events_month" not in rendered
