"""Tests for Issue #337: Native SQL column grouping in auto-aggregation.

Verifies that:
- native_dimensions in aggregation metadata are parsed and returned
- _derive_auto_aggregation returns a 3-tuple with native dimension set
- Mixed native + JSONB dimensions work together
- _build_find_query uses column refs for native dims, JSONB for others
- JSONB tables get AS t alias when native dimensions are present
- ORDER BY uses column refs for native dimensions
- Backward compatibility: no native_dimensions = unchanged behavior
"""

from typing import Any
from unittest.mock import MagicMock

from fraiseql.db import (
    FraiseQLRepository,
    _derive_auto_aggregation,
)
from fraiseql.sql.order_by_generator import OrderBy, OrderBySet, OrderDirection

# ── Phase 1: _derive_auto_aggregation with native_dimensions ─────────


class TestDeriveAutoAggregationNativeDimensions:
    """Tests for native_dimensions support in _derive_auto_aggregation."""

    def setup_method(self) -> None:
        self.meta: dict[str, Any] = {
            "measures": {
                "measures.total": "SUM",
                "measures.count": "SUM",
            },
            "dimensions": "dimensions",
            "native_dimensions": ["period_date", "category_id"],
        }

    def test_native_dimensions_returned_in_result(self) -> None:
        """Result 3-tuple element [2] contains native dimension set."""
        field_paths = [
            ["period_date"],
            ["dimensions", "subcategory"],
            ["measures", "total"],
        ]
        result = _derive_auto_aggregation(field_paths, self.meta)
        assert result is not None
        assert len(result) == 3
        _, _, native_set = result
        assert native_set == {"period_date"}

    def test_native_dimensions_in_group_by(self) -> None:
        """Native dimensions appear in group_by as plain column names."""
        field_paths = [
            ["period_date"],
            ["category_id"],
            ["measures", "total"],
        ]
        result = _derive_auto_aggregation(field_paths, self.meta)
        assert result is not None
        group_by, _, native_set = result
        assert "period_date" in group_by
        assert "category_id" in group_by
        assert native_set == {"period_date", "category_id"}

    def test_mixed_native_and_jsonb_dimensions(self) -> None:
        """Both native and JSONB dimensions coexist in group_by."""
        field_paths = [
            ["period_date"],
            ["dimensions", "subcategory"],
            ["measures", "total"],
        ]
        result = _derive_auto_aggregation(field_paths, self.meta)
        assert result is not None
        group_by, aggregations, native_set = result
        assert "period_date" in group_by
        assert "dimensions.subcategory" in group_by
        assert native_set == {"period_date"}
        assert aggregations == {"measures.total": "SUM(measures.total)"}

    def test_no_native_dimensions_returns_empty_set(self) -> None:
        """Without native_dimensions in metadata, third element is empty set."""
        meta: dict[str, Any] = {
            "measures": {"measures.total": "SUM"},
            "dimensions": "dimensions",
        }
        field_paths = [
            ["dimensions", "date"],
            ["measures", "total"],
        ]
        result = _derive_auto_aggregation(field_paths, meta)
        assert result is not None
        assert len(result) == 3
        _, _, native_set = result
        assert native_set == set()

    def test_native_dim_not_selected_not_in_result(self) -> None:
        """Only selected native dimensions appear in group_by and native set."""
        field_paths = [
            ["period_date"],
            ["measures", "total"],
        ]
        result = _derive_auto_aggregation(field_paths, self.meta)
        assert result is not None
        group_by, _, native_set = result
        assert "period_date" in group_by
        assert "category_id" not in group_by
        assert native_set == {"period_date"}

    def test_skip_when_still_works_with_native_dims(self) -> None:
        """Identity fields in skip_when still skip aggregation."""
        field_paths = [
            ["id"],
            ["period_date"],
            ["measures", "total"],
        ]
        result = _derive_auto_aggregation(field_paths, self.meta)
        assert result is None

    def test_only_native_dims_no_jsonb_dims(self) -> None:
        """Selecting only native dimensions (no JSONB dims) still returns group_by."""
        field_paths = [
            ["period_date"],
            ["measures", "total"],
        ]
        result = _derive_auto_aggregation(field_paths, self.meta)
        assert result is not None
        group_by, _, native_set = result
        assert group_by == ["period_date"]
        assert native_set == {"period_date"}


# ── Phase 2: _build_find_query with native_dimensions ────────────────


class TestBuildFindQueryNativeDimensions:
    """Tests for native_dimensions support in _build_find_query."""

    def setup_method(self) -> None:
        self.mock_conn = MagicMock()
        self.repo = FraiseQLRepository(self.mock_conn)

    def test_native_dimension_uses_column_ref(self) -> None:
        """Native dimensions use t."col" instead of JSONB extraction."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["period_date", "dimensions.category"],
            native_dimensions={"period_date"},
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        # Native dim: t."period_date"
        assert '"t"."period_date"' in sql_str
        # JSONB dim: "data"->'dimensions'->>'category' (nested path)
        assert "\"data\"->'dimensions'->>'category'" in sql_str

    def test_jsonb_table_gets_alias_when_native_dims(self) -> None:
        """JSONB tables get AS t alias when native_dimensions is non-empty."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["period_date"],
            native_dimensions={"period_date"},
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "AS t" in sql_str

    def test_no_alias_without_native_dims(self) -> None:
        """JSONB tables do NOT get AS t when no native_dimensions."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["date"],
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "AS t" not in sql_str

    def test_native_dim_in_json_build_object(self) -> None:
        """Native dimensions appear in json_build_object using column ref."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["period_date"],
            native_dimensions={"period_date"},
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "json_build_object(" in sql_str
        assert "'period_date'" in sql_str
        assert '"t"."period_date"' in sql_str

    def test_native_dim_in_group_by_clause(self) -> None:
        """GROUP BY uses column ref for native dimensions."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["period_date", "dimensions.category"],
            native_dimensions={"period_date"},
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert 'GROUP BY "t"."period_date"' in sql_str or (
            '"t"."period_date"' in sql_str and "GROUP BY" in sql_str
        )

    def test_measures_still_jsonb_with_native_dims(self) -> None:
        """Aggregation measures remain JSONB-extracted even with native dims."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["period_date"],
            aggregations={"total": "SUM(measures.total)"},
            native_dimensions={"period_date"},
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "SUM" in sql_str
        assert "::numeric" in sql_str
        # Measure should use JSONB extraction, not column ref
        assert "\"data\"->>'total'" in sql_str or "\"data\"->'measures'->>'total'" in sql_str

    def test_empty_native_dimensions_unchanged(self) -> None:
        """Empty native_dimensions set behaves like no native_dimensions."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["date"],
            native_dimensions=set(),
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "AS t" not in sql_str
        assert "\"data\"->>'date'" in sql_str


# ── Phase 3: ORDER BY with native dimensions ─────────────────────────


class TestOrderByNativeDimensions:
    """Tests for native_columns support in OrderBy.to_sql()."""

    def test_native_column_uses_column_ref(self) -> None:
        """ORDER BY native column uses t."col" instead of JSONB extraction."""
        ob = OrderBy(field="period_date", direction=OrderDirection.ASC)
        result = ob.to_sql("data", native_columns={"period_date"})
        sql_str = result.as_string(None)
        assert '"t"."period_date"' in sql_str
        assert "ASC" in sql_str
        # Should NOT contain JSONB extraction
        assert "data ->" not in sql_str

    def test_non_native_column_unchanged(self) -> None:
        """ORDER BY non-native column still uses JSONB extraction."""
        ob = OrderBy(field="category", direction=OrderDirection.DESC)
        result = ob.to_sql("data", native_columns={"period_date"})
        sql_str = result.as_string(None)
        assert "data -> " in sql_str
        assert "DESC" in sql_str

    def test_no_native_columns_unchanged(self) -> None:
        """Without native_columns, behavior is identical to current."""
        ob = OrderBy(field="period_date", direction=OrderDirection.ASC)
        result = ob.to_sql("data")
        sql_str = result.as_string(None)
        assert "data -> " in sql_str

    def test_order_by_set_passes_native_columns(self) -> None:
        """OrderBySet passes native_columns through to each OrderBy."""
        obs = OrderBySet(
            instructions=[
                OrderBy(field="period_date", direction=OrderDirection.ASC),
                OrderBy(field="category", direction=OrderDirection.DESC),
            ]
        )
        result = obs.to_sql("data", native_columns={"period_date"})
        sql_str = result.as_string(None)
        assert "ORDER BY" in sql_str
        assert '"t"."period_date"' in sql_str
        assert "data -> " in sql_str  # category still JSONB


class TestBuildFindQueryOrderByNativeDims:
    """Tests for ORDER BY + native_dimensions in _build_find_query."""

    def setup_method(self) -> None:
        self.mock_conn = MagicMock()
        self.repo = FraiseQLRepository(self.mock_conn)

    def test_order_by_native_dim_in_full_query(self) -> None:
        """Full query with ORDER BY on native dimension produces column ref."""
        ob = OrderBySet(
            instructions=[
                OrderBy(field="period_date", direction=OrderDirection.ASC),
            ]
        )
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["period_date"],
            native_dimensions={"period_date"},
            order_by=ob,
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "ORDER BY" in sql_str
        assert '"t"."period_date"' in sql_str
        # ORDER BY should NOT use JSONB extraction for native dim
        order_idx = sql_str.index("ORDER BY")
        order_clause = sql_str[order_idx:]
        assert "data ->" not in order_clause


# ── Phase 4: Integration + backward compatibility ────────────────────


class TestNativeDimensionsIntegration:
    """End-to-end tests for native_dimensions through the full pipeline."""

    def setup_method(self) -> None:
        self.mock_conn = MagicMock()
        self.repo = FraiseQLRepository(self.mock_conn)

    def test_full_mixed_query(self) -> None:
        """Complete query with native dims, JSONB dims, measures, and ORDER BY."""
        ob = OrderBySet(
            instructions=[
                OrderBy(field="period_date", direction=OrderDirection.ASC),
                OrderBy(field="dimensions.subcategory", direction=OrderDirection.DESC),
            ]
        )
        query = self.repo._build_find_query(
            "v_orders_by_period",
            group_by=["period_date", "category_id", "dimensions.subcategory"],
            aggregations={
                "measures.total": "SUM(measures.total)",
                "measures.count": "SUM(measures.count)",
            },
            native_dimensions={"period_date", "category_id"},
            order_by=ob,
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)

        # SELECT: native dims use column ref
        assert '"t"."period_date"' in sql_str
        assert '"t"."category_id"' in sql_str

        # SELECT: JSONB dim uses JSONB extraction
        assert "\"data\"->'dimensions'->>'subcategory'" in sql_str

        # SELECT: measures use JSONB extraction with numeric cast
        assert "SUM" in sql_str
        assert "::numeric" in sql_str

        # FROM: has AS t
        assert "AS t" in sql_str

        # GROUP BY: native dims use column ref
        group_idx = sql_str.index("GROUP BY")
        order_idx = sql_str.index("ORDER BY")
        group_clause = sql_str[group_idx:order_idx]
        assert '"t"."period_date"' in group_clause
        assert '"t"."category_id"' in group_clause

        # ORDER BY: native dim uses column ref, JSONB dim uses extraction
        order_clause = sql_str[order_idx:]
        assert '"t"."period_date"' in order_clause
        assert "data ->" in order_clause  # subcategory still JSONB

    def test_backward_compat_no_native_dims(self) -> None:
        """Without native_dimensions, behavior is identical to pre-change."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["dimensions.date", "dimensions.category"],
            aggregations={"measures.cost": "SUM(measures.cost)"},
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)

        # No AS t for pure JSONB
        assert "AS t" not in sql_str

        # All fields via JSONB extraction
        assert "\"data\"->'dimensions'->>'date'" in sql_str
        assert "\"data\"->'dimensions'->>'category'" in sql_str
        assert "SUM" in sql_str

        # No column refs
        assert '"t".' not in sql_str
