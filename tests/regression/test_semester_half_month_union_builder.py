"""Tests for Issues #1516/#1517: UNION ALL builder with semester and half_month.

Verifies structural correctness of _build_partial_period_union_query for
the two new granularities: correct branch counts, date boundaries, and
edge cases (year boundary, short months, leap years).
"""

from datetime import date

from fraiseql.db import _build_partial_period_union_query

# ── base kwargs ──────────────────────────────────────────────────────────────

SEMESTER_BASE = {
    "coarse_view": "v_stats_semester",
    "fine_grain_view": "v_stats_day",
    "time_grain_column": "date",
    "time_grain_trunc": "semester",
    "group_by": ["date"],
    "aggregations": {"data.volume": "SUM(data.volume)"},
    "native_dimensions": {"date"},
    "native_measures": {"data.volume": "volume"},
    "native_dimension_mapping": None,
    "jsonb_col": "data",
    "extra_where": None,
}

HALF_MONTH_BASE = {
    "coarse_view": "v_stats_half_month",
    "fine_grain_view": "v_stats_day",
    "time_grain_column": "date",
    "time_grain_trunc": "half_month",
    "group_by": ["date"],
    "aggregations": {"data.volume": "SUM(data.volume)"},
    "native_dimensions": {"date"},
    "native_measures": {"data.volume": "volume"},
    "native_dimension_mapping": None,
    "jsonb_col": "data",
    "extra_where": None,
}


# ── semester UNION ALL structure ─────────────────────────────────────────────


class TestSemesterUnionBuilder:
    def test_mid_period_produces_three_branches(self) -> None:
        """Start Mar 15 2024 (mid-H1) → partial H1, complete H2 2024, current H1 2025."""
        query = _build_partial_period_union_query(
            **SEMESTER_BASE,
            lower_bound=date(2024, 3, 15),
            today=date(2025, 3, 20),
        )
        rendered = query.statement.as_string(None)
        assert rendered.count("UNION ALL") == 2
        assert "v_stats_day" in rendered
        assert "v_stats_semester" in rendered

    def test_aligned_start_skips_branch_1(self) -> None:
        """Start Jan 1 (H1 boundary) → no partial leading period."""
        query = _build_partial_period_union_query(
            **SEMESTER_BASE,
            lower_bound=date(2024, 1, 1),
            today=date(2025, 3, 20),
        )
        rendered = query.statement.as_string(None)
        assert rendered.count("UNION ALL") == 1
        assert "v_stats_day" in rendered
        assert "v_stats_semester" in rendered

    def test_aligned_on_jul_1_skips_branch_1(self) -> None:
        """Start Jul 1 (H2 boundary) → no partial leading period."""
        query = _build_partial_period_union_query(
            **SEMESTER_BASE,
            lower_bound=date(2024, 7, 1),
            today=date(2025, 3, 20),
        )
        rendered = query.statement.as_string(None)
        assert rendered.count("UNION ALL") == 1

    def test_year_boundary(self) -> None:
        """Start in H2 2023, today in H1 2025 → crosses year boundary."""
        query = _build_partial_period_union_query(
            **SEMESTER_BASE,
            lower_bound=date(2023, 9, 1),
            today=date(2025, 3, 20),
        )
        rendered = query.statement.as_string(None)
        # Non-aligned (Sep 1 is not a semester boundary) → three branches
        assert rendered.count("UNION ALL") == 2
        assert "v_stats_day" in rendered
        assert "v_stats_semester" in rendered

    def test_current_period_start_gives_one_branch(self) -> None:
        """Lower bound at current semester start → only fine-grain Branch 3."""
        query = _build_partial_period_union_query(
            **SEMESTER_BASE,
            lower_bound=date(2025, 7, 1),
            today=date(2025, 9, 20),
        )
        rendered = query.statement.as_string(None)
        assert "UNION ALL" not in rendered
        assert "v_stats_day" in rendered
        assert "v_stats_semester" not in rendered

    def test_two_branches_when_in_same_semester_not_aligned(self) -> None:
        """Start mid-H2, today still in H2 → Branch 1 + Branch 3, no coarse."""
        query = _build_partial_period_union_query(
            **SEMESTER_BASE,
            lower_bound=date(2025, 8, 15),
            today=date(2025, 11, 20),
        )
        rendered = query.statement.as_string(None)
        # Branch 1 and Branch 3 merge into fine-grain only (no coarse in between)
        assert "v_stats_day" in rendered
        assert "v_stats_semester" not in rendered

    def test_fine_grain_branch_uses_make_date(self) -> None:
        """Fine-grain branches must use MAKE_DATE for semester truncation."""
        query = _build_partial_period_union_query(
            **SEMESTER_BASE,
            lower_bound=date(2024, 3, 15),
            today=date(2025, 3, 20),
        )
        rendered = query.statement.as_string(None)
        assert "MAKE_DATE" in rendered


# ── half_month UNION ALL structure ───────────────────────────────────────────


class TestHalfMonthUnionBuilder:
    def test_mid_period_produces_three_branches(self) -> None:
        """Start Mar 10 (mid-first-half) → partial, complete halves, current."""
        query = _build_partial_period_union_query(
            **HALF_MONTH_BASE,
            lower_bound=date(2025, 3, 10),
            today=date(2025, 5, 20),
        )
        rendered = query.statement.as_string(None)
        assert rendered.count("UNION ALL") == 2
        assert "v_stats_day" in rendered
        assert "v_stats_half_month" in rendered

    def test_aligned_on_16th_skips_branch_1(self) -> None:
        """Start on 16th → no partial leading period."""
        query = _build_partial_period_union_query(
            **HALF_MONTH_BASE,
            lower_bound=date(2025, 3, 16),
            today=date(2025, 5, 10),
        )
        rendered = query.statement.as_string(None)
        assert rendered.count("UNION ALL") == 1
        assert "v_stats_day" in rendered
        assert "v_stats_half_month" in rendered

    def test_aligned_on_1st_skips_branch_1(self) -> None:
        """Start on 1st → no partial leading period."""
        query = _build_partial_period_union_query(
            **HALF_MONTH_BASE,
            lower_bound=date(2025, 3, 1),
            today=date(2025, 5, 10),
        )
        rendered = query.statement.as_string(None)
        assert rendered.count("UNION ALL") == 1

    def test_february_boundary(self) -> None:
        """Start Feb 10 → partial first half, Feb 16 boundary, then complete halves."""
        query = _build_partial_period_union_query(
            **HALF_MONTH_BASE,
            lower_bound=date(2025, 2, 10),
            today=date(2025, 4, 10),
        )
        rendered = query.statement.as_string(None)
        assert rendered.count("UNION ALL") == 2
        # Verify Feb 16 appears as a date boundary
        assert "2025-02-16" in rendered

    def test_leap_year_february(self) -> None:
        """Leap year Feb 20 — second half, next period = Mar 1."""
        query = _build_partial_period_union_query(
            **HALF_MONTH_BASE,
            lower_bound=date(2024, 2, 20),
            today=date(2024, 5, 10),
        )
        rendered = query.statement.as_string(None)
        # Non-aligned (day 20) → three branches
        assert rendered.count("UNION ALL") == 2
        # Mar 1 should appear as next period boundary
        assert "2024-03-01" in rendered

    def test_december_year_boundary(self) -> None:
        """Start Dec 20 → next period is Jan 1 of next year."""
        query = _build_partial_period_union_query(
            **HALF_MONTH_BASE,
            lower_bound=date(2025, 12, 20),
            today=date(2026, 3, 10),
        )
        rendered = query.statement.as_string(None)
        assert rendered.count("UNION ALL") == 2
        # Jan 1 next year must appear
        assert "2026-01-01" in rendered

    def test_current_period_start_gives_one_branch(self) -> None:
        """Lower bound at current half_month start → only Branch 3."""
        query = _build_partial_period_union_query(
            **HALF_MONTH_BASE,
            lower_bound=date(2025, 4, 16),
            today=date(2025, 4, 25),
        )
        rendered = query.statement.as_string(None)
        assert "UNION ALL" not in rendered
        assert "v_stats_day" in rendered
        assert "v_stats_half_month" not in rendered

    def test_fine_grain_branch_uses_case(self) -> None:
        """Fine-grain branches must use CASE for half_month truncation."""
        query = _build_partial_period_union_query(
            **HALF_MONTH_BASE,
            lower_bound=date(2025, 3, 10),
            today=date(2025, 5, 20),
        )
        rendered = query.statement.as_string(None)
        assert "CASE" in rendered
        assert "EXTRACT(DAY FROM" in rendered


# ── dispatch: DatabaseQuery contract ─────────────────────────────────────────


class TestDatabaseQueryContract:
    def test_semester_returns_database_query(self) -> None:
        from fraiseql.db import DatabaseQuery

        query = _build_partial_period_union_query(
            **SEMESTER_BASE,
            lower_bound=date(2025, 3, 15),
            today=date(2025, 9, 20),
        )
        assert isinstance(query, DatabaseQuery)
        assert query.fetch_result is True

    def test_half_month_returns_database_query(self) -> None:
        from fraiseql.db import DatabaseQuery

        query = _build_partial_period_union_query(
            **HALF_MONTH_BASE,
            lower_bound=date(2025, 3, 10),
            today=date(2025, 4, 20),
        )
        assert isinstance(query, DatabaseQuery)
        assert query.fetch_result is True
