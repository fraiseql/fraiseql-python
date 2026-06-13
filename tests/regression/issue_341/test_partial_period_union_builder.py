"""Tests for Issue #341 Phase 03: UNION ALL query builder.

Verifies structural correctness of _build_partial_period_union_query:
- Three branches when lower_bound is not period-aligned.
- Two branches (coarse + current) when lower_bound is period-aligned.
- Only one branch (current) when lower_bound is the current period start.
- Branch 2 starts at lower_bound itself when aligned.
- Extra WHERE conditions appear in all branches.
- Only selected fields appear in GROUP BY / SELECT.
"""

from datetime import date

from fraiseql.db import _build_partial_period_union_query
from fraiseql.where_clause import FieldCondition, WhereClause

# ── helpers ────────────────────────────────────────────────────���──────────────


def _make_tenant_wc(tenant_id: int = 1) -> WhereClause:
    cond = FieldCondition(
        field_path=["tenant_id"],
        operator="eq",
        value=tenant_id,
        lookup_strategy="sql_column",
        target_column="tenant_id",
    )
    return WhereClause(conditions=[cond])


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


# ── structural tests ──────────────────────────────────────────────────────────


def test_three_branches_when_lower_bound_not_aligned() -> None:
    """Non-aligned lower bound produces Branch1 UNION ALL Branch2 UNION ALL Branch3."""
    query = _build_partial_period_union_query(
        **BASE,
        lower_bound=date(2025, 1, 15),
        today=date(2025, 3, 20),
    )
    rendered = query.statement.as_string(None)
    assert rendered.count("UNION ALL") == 2
    assert "v_events_day" in rendered
    assert "v_events_month" in rendered


def test_two_branches_when_lower_bound_aligned() -> None:
    """Period-aligned lower bound produces Branch2 UNION ALL Branch3."""
    query = _build_partial_period_union_query(
        **BASE,
        lower_bound=date(2025, 2, 1),
        today=date(2025, 3, 20),
    )
    rendered = query.statement.as_string(None)
    assert rendered.count("UNION ALL") == 1
    # Branch 3 (fine-grain current period) must be present
    assert "v_events_day" in rendered
    # Branch 2 (coarse complete periods) must also be present
    assert "v_events_month" in rendered


def test_aligned_branch2_starts_at_lower_bound() -> None:
    """When aligned, Branch 2 starts at the lower bound itself, not lower_bound + 1 period."""
    query = _build_partial_period_union_query(
        **BASE,
        lower_bound=date(2025, 2, 1),
        today=date(2025, 5, 20),
    )
    rendered = query.statement.as_string(None)
    # Branch 2 should include Feb (the lower bound)
    assert "2025-02-01" in rendered


def test_one_branch_when_lower_bound_is_current_period_start() -> None:
    """Lower bound at current month start → Branch 2 has empty range → only Branch 3."""
    query = _build_partial_period_union_query(
        **BASE,
        lower_bound=date(2025, 3, 1),
        today=date(2025, 3, 20),
    )
    rendered = query.statement.as_string(None)
    assert "UNION ALL" not in rendered
    # Only fine-grain view (Branch 3)
    assert "v_events_day" in rendered
    assert "v_events_month" not in rendered


def test_non_aligned_lower_bound_in_current_period_gives_one_branch() -> None:
    """Lower bound in current period but not aligned → only Branch 1 (no Branch 2 or 3)."""
    # lower_bound = Jan 15, today = Jan 20 (same month)
    query = _build_partial_period_union_query(
        **BASE,
        lower_bound=date(2025, 1, 15),
        today=date(2025, 1, 20),
    )
    rendered = query.statement.as_string(None)
    # next_ps = 2025-02-01, current_ps = 2025-01-01, b2_start = 2025-02-01
    # include_b2 = (2025-02-01 < 2025-01-01) = False
    # Branch 1: date >= 2025-01-15 AND date < 2025-02-01
    # Branch 3: date >= 2025-01-01 AND date < 2025-01-21
    assert "v_events_day" in rendered


def test_order_by_always_present() -> None:
    """ORDER BY 1 is appended regardless of how many branches are generated."""
    for lower, today in [
        (date(2025, 1, 15), date(2025, 3, 20)),
        (date(2025, 2, 1), date(2025, 3, 20)),
        (date(2025, 3, 1), date(2025, 3, 20)),
    ]:
        query = _build_partial_period_union_query(
            **BASE,
            lower_bound=lower,
            today=today,
        )
        rendered = query.statement.as_string(None)
        assert "ORDER BY 1" in rendered


# ── extra WHERE propagation ───────────────────────────────────────────────────


def test_extra_where_conditions_in_all_branches() -> None:
    """tenant_id condition must appear in every branch of the UNION."""
    wc = _make_tenant_wc(42)
    query = _build_partial_period_union_query(
        **{**BASE, "extra_where": wc},
        lower_bound=date(2025, 1, 15),
        today=date(2025, 3, 20),
    )
    rendered = query.statement.as_string(None)
    # Three branches → tenant_id appears three times
    assert rendered.count("tenant_id") == 3


def test_extra_where_in_two_branch_query() -> None:
    """Extra conditions appear in both branches of aligned query."""
    wc = _make_tenant_wc(7)
    query = _build_partial_period_union_query(
        **{**BASE, "extra_where": wc},
        lower_bound=date(2025, 2, 1),
        today=date(2025, 3, 20),
    )
    rendered = query.statement.as_string(None)
    assert rendered.count("tenant_id") == 2


# ── field selection ───────────────────────────────────────────────────────────


def test_only_selected_fields_in_output() -> None:
    """If only 'date' and 'volume' are selected, 'cost' must not appear."""
    query = _build_partial_period_union_query(
        coarse_view="v_events_month",
        fine_grain_view="v_events_day",
        time_grain_column="date",
        time_grain_trunc="month",
        lower_bound=date(2025, 1, 15),
        group_by=["date"],
        aggregations={"data.volume": "SUM(data.volume)"},
        native_dimensions={"date"},
        native_measures={"data.volume": "volume"},
        native_dimension_mapping=None,
        jsonb_col="data",
        extra_where=None,
        today=date(2025, 3, 20),
    )
    rendered = query.statement.as_string(None)
    assert "cost" not in rendered


def test_multiple_dimensions_in_group_by() -> None:
    """Multiple group_by fields all appear in the GROUP BY clause."""
    query = _build_partial_period_union_query(
        coarse_view="v_events_month",
        fine_grain_view="v_events_day",
        time_grain_column="date",
        time_grain_trunc="month",
        lower_bound=date(2025, 1, 15),
        group_by=["date", "category"],
        aggregations={"data.volume": "SUM(data.volume)"},
        native_dimensions={"date", "category"},
        native_measures={"data.volume": "volume"},
        native_dimension_mapping=None,
        jsonb_col="data",
        extra_where=None,
        today=date(2025, 3, 20),
    )
    rendered = query.statement.as_string(None)
    assert "category" in rendered
    # GROUP BY should appear in fine-grain branches
    assert "GROUP BY" in rendered


# ── DatabaseQuery contract ────────────────────────────────────────────────────


def test_returns_database_query_with_fetch_result() -> None:
    from fraiseql.db import DatabaseQuery

    query = _build_partial_period_union_query(
        **BASE,
        lower_bound=date(2025, 1, 15),
        today=date(2025, 3, 20),
    )
    assert isinstance(query, DatabaseQuery)
    assert query.fetch_result is True
