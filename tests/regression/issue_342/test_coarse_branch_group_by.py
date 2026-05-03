"""Regression tests for Issue #342.

Bug: UNION ALL partial-period coarse branch missing GROUP BY clause.

When a view is registered with fine_grain_view / time_grain_trunc and a
query has a date lower-bound filter that triggers the UNION ALL path, the
coarse branch (v_events_month) SELECT included native_dimension columns in
json_build_object but omitted them from GROUP BY, producing:

    column "t.date" must appear in the GROUP BY clause or be used in
    an aggregate function

The fix ensures _build_coarse_branch tracks group_by_exprs and appends
GROUP BY exactly as _build_fine_grain_branch does.
"""

from datetime import date

from fraiseql.db import _build_coarse_branch, _build_partial_period_union_query


# ── _build_coarse_branch unit tests ──────────────────────────────────────────


def test_coarse_branch_includes_group_by_for_native_dimension() -> None:
    """Coarse branch must emit GROUP BY when group_by + aggregations are present."""
    sql, _ = _build_coarse_branch(
        coarse_view="v_events_month",
        time_grain_column="date",
        date_gte=date(2024, 2, 1),
        date_lt=date(2024, 3, 1),
        group_by=["date"],
        aggregations={"measures.volume": "SUM(measures.volume)"},
        native_dimensions={"date"},
        native_measures={"measures.volume": "volume"},
        native_dimension_mapping=None,
        jsonb_col="data",
        extra_where_sql=None,
    )
    rendered = sql.as_string(None)
    assert "GROUP BY" in rendered, (
        "_build_coarse_branch must include GROUP BY clause when dimensions and "
        "aggregations are both present (regression: issue #342)"
    )


def test_coarse_branch_group_by_contains_dimension_column() -> None:
    """The GROUP BY in the coarse branch must reference the native_dimension column."""
    sql, _ = _build_coarse_branch(
        coarse_view="v_events_month",
        time_grain_column="date",
        date_gte=date(2024, 2, 1),
        date_lt=date(2024, 3, 1),
        group_by=["date"],
        aggregations={"measures.volume": "SUM(measures.volume)"},
        native_dimensions={"date"},
        native_measures={"measures.volume": "volume"},
        native_dimension_mapping=None,
        jsonb_col="data",
        extra_where_sql=None,
    )
    rendered = sql.as_string(None)
    # The date column must appear after GROUP BY, not only in the SELECT list.
    group_by_pos = rendered.index("GROUP BY")
    assert "date" in rendered[group_by_pos:], (
        "The 'date' native_dimension must appear in GROUP BY (regression: issue #342)"
    )


def test_coarse_branch_no_group_by_without_group_by_list() -> None:
    """When group_by is empty, no GROUP BY clause should be emitted."""
    sql, _ = _build_coarse_branch(
        coarse_view="v_events_month",
        time_grain_column="date",
        date_gte=date(2024, 2, 1),
        date_lt=date(2024, 3, 1),
        group_by=[],
        aggregations={"measures.volume": "SUM(measures.volume)"},
        native_dimensions={"date"},
        native_measures={"measures.volume": "volume"},
        native_dimension_mapping=None,
        jsonb_col="data",
        extra_where_sql=None,
    )
    rendered = sql.as_string(None)
    assert "GROUP BY" not in rendered


# ── end-to-end UNION ALL tests ────────────────────────────────────────────────


BASE = dict(
    coarse_view="v_events_month",
    fine_grain_view="v_events_day",
    time_grain_column="date",
    time_grain_trunc="month",
    group_by=["date"],
    aggregations={"measures.volume": "SUM(measures.volume)"},
    native_dimensions={"date"},
    native_measures={"measures.volume": "volume"},
    native_dimension_mapping=None,
    jsonb_col="data",
    extra_where=None,
)


def test_coarse_branch_has_group_by_in_three_branch_union() -> None:
    """Coarse branch (middle branch) in a 3-branch UNION ALL must have GROUP BY."""
    query = _build_partial_period_union_query(
        **BASE,
        lower_bound=date(2024, 1, 15),  # non-aligned → triggers 3 branches
        today=date(2024, 3, 20),
    )
    rendered = query.statement.as_string(None)

    # Split on UNION ALL to inspect each branch independently.
    branches = rendered.split("UNION ALL")
    assert len(branches) == 3, "Expected three UNION ALL branches"

    coarse_branch = branches[1]
    assert "v_events_month" in coarse_branch, "Branch 2 should be the coarse branch"
    assert "GROUP BY" in coarse_branch, (
        "Coarse branch (Branch 2) must contain GROUP BY clause "
        "(regression: issue #342)"
    )


def test_coarse_branch_has_group_by_in_two_branch_union() -> None:
    """Coarse branch in a 2-branch UNION ALL (aligned lower bound) must have GROUP BY."""
    query = _build_partial_period_union_query(
        **BASE,
        lower_bound=date(2024, 2, 1),  # period-aligned → 2 branches
        today=date(2024, 3, 20),
    )
    rendered = query.statement.as_string(None)

    branches = rendered.split("UNION ALL")
    assert len(branches) == 2, "Expected two UNION ALL branches"

    coarse_branch = branches[0]
    assert "v_events_month" in coarse_branch, "Branch 1 should be the coarse branch"
    assert "GROUP BY" in coarse_branch, (
        "Coarse branch must contain GROUP BY clause (regression: issue #342)"
    )


def test_full_reproduction_from_issue_342() -> None:
    """Exact reproduction from the bug report: monthly aggregation with date gte filter."""
    query = _build_partial_period_union_query(
        coarse_view="v_events_month",
        fine_grain_view="v_events_day",
        time_grain_column="date",
        time_grain_trunc="month",
        group_by=["date"],
        aggregations={"measures.volume": "SUM(measures.volume)"},
        native_dimensions={"date"},
        native_measures=None,
        native_dimension_mapping=None,
        jsonb_col="data",
        extra_where=None,
        lower_bound=date(2024, 1, 1),  # date gte filter triggering UNION ALL
        today=date(2024, 3, 20),
    )
    rendered = query.statement.as_string(None)

    # Every branch that references v_events_month must have GROUP BY.
    for segment in rendered.split("UNION ALL"):
        if "v_events_month" in segment:
            assert "GROUP BY" in segment, (
                f"Coarse-grain segment is missing GROUP BY:\n{segment}"
            )
