"""Tests for Issue #315: GROUP BY and aggregations in db.find().

Verifies that _build_find_query correctly generates:
- GROUP BY clauses for JSONB and non-JSONB tables
- json_build_object() SELECT with dimension + aggregation fields
- Proper SQL clause ordering (WHERE → GROUP BY → ORDER BY → LIMIT)
- Aggregation expression parsing and validation
"""

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from fraiseql.db import (
    FraiseQLRepository,
    _build_jsonb_field_expr,
    _build_non_jsonb_field_expr,
    _parse_aggregation_expr,
)

# ── Helper function tests ──────────────────────────────────────────────


class TestParseAggregationExpr:
    """Tests for _parse_aggregation_expr."""

    def test_sum(self) -> None:
        assert _parse_aggregation_expr("SUM(cost)") == ("SUM", "cost")

    def test_avg(self) -> None:
        assert _parse_aggregation_expr("AVG(price)") == ("AVG", "price")

    def test_count_star(self) -> None:
        assert _parse_aggregation_expr("COUNT(*)") == ("COUNT", "*")

    def test_min_max(self) -> None:
        assert _parse_aggregation_expr("MIN(age)") == ("MIN", "age")
        assert _parse_aggregation_expr("MAX(age)") == ("MAX", "age")

    def test_case_insensitive(self) -> None:
        assert _parse_aggregation_expr("sum(cost)") == ("SUM", "cost")

    def test_nested_field(self) -> None:
        assert _parse_aggregation_expr("SUM(stats.cost)") == ("SUM", "stats.cost")

    def test_whitespace_handling(self) -> None:
        assert _parse_aggregation_expr("  SUM( cost )  ") == ("SUM", "cost")

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid aggregation expression"):
            _parse_aggregation_expr("not_valid")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid aggregation expression"):
            _parse_aggregation_expr("")

    def test_disallowed_function_raises(self) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            _parse_aggregation_expr("DROP(table)")

    def test_json_agg(self) -> None:
        assert _parse_aggregation_expr("JSON_AGG(items)") == ("JSON_AGG", "items")


class TestBuildJsonbFieldExpr:
    """Tests for _build_jsonb_field_expr."""

    def test_single_field(self) -> None:
        expr = _build_jsonb_field_expr("date", "data")
        sql_str = expr.as_string(None)
        assert sql_str == '"data"->>\'date\''

    def test_nested_field(self) -> None:
        expr = _build_jsonb_field_expr("date_info.date", "data")
        sql_str = expr.as_string(None)
        assert sql_str == '"data"->\'date_info\'->>\'date\''

    def test_deeply_nested(self) -> None:
        expr = _build_jsonb_field_expr("a.b.c", "data")
        sql_str = expr.as_string(None)
        assert sql_str == '"data"->\'a\'->\'b\'->>\'c\''

    def test_custom_jsonb_column(self) -> None:
        expr = _build_jsonb_field_expr("name", "payload")
        sql_str = expr.as_string(None)
        assert sql_str == '"payload"->>\'name\''


class TestBuildNonJsonbFieldExpr:
    """Tests for _build_non_jsonb_field_expr."""

    def test_simple_field(self) -> None:
        expr = _build_non_jsonb_field_expr("date", "t")
        sql_str = expr.as_string(None)
        assert sql_str == '"t"."date"'


# ── _build_find_query GROUP BY tests ────────────────────────────────────


class TestBuildFindQueryGroupBy:
    """Tests for GROUP BY support in _build_find_query."""

    def setup_method(self) -> None:
        self.mock_conn = MagicMock()
        self.repo = FraiseQLRepository(self.mock_conn)

    def test_group_by_single_field_jsonb(self) -> None:
        """GROUP BY single field on JSONB table."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["date"],
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "json_build_object(" in sql_str
        assert "'date'" in sql_str
        assert 'GROUP BY "data"->>\'date\'' in sql_str

    def test_group_by_multiple_fields_jsonb(self) -> None:
        """GROUP BY multiple fields on JSONB table."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["date", "category"],
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "GROUP BY" in sql_str
        assert "\"data\"->>'date'" in sql_str
        assert "\"data\"->>'category'" in sql_str

    def test_group_by_nested_field_jsonb(self) -> None:
        """GROUP BY nested JSONB field path."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["date_info.date"],
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "\"data\"->'date_info'->>'date'" in sql_str

    def test_group_by_with_aggregations_jsonb(self) -> None:
        """GROUP BY with SUM aggregation on JSONB table."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["date"],
            aggregations={"total_cost": "SUM(cost)"},
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "json_build_object(" in sql_str
        assert "'date'" in sql_str
        assert "'total_cost'" in sql_str
        assert "SUM" in sql_str
        assert "::numeric" in sql_str
        assert "GROUP BY" in sql_str

    def test_group_by_with_count_star(self) -> None:
        """GROUP BY with COUNT(*) aggregation."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["category"],
            aggregations={"count": "COUNT(*)"},
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "COUNT(*)" in sql_str
        assert "'count'" in sql_str

    def test_group_by_with_multiple_aggregations(self) -> None:
        """GROUP BY with multiple aggregation functions."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["date"],
            aggregations={
                "total_cost": "SUM(cost)",
                "total_volume": "SUM(volume)",
                "avg_price": "AVG(price)",
            },
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "'total_cost'" in sql_str
        assert "'total_volume'" in sql_str
        assert "'avg_price'" in sql_str
        assert sql_str.count("SUM") == 2
        assert "AVG" in sql_str

    def test_group_by_non_jsonb_table(self) -> None:
        """GROUP BY on non-JSONB table (row_to_json path)."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["date"],
            aggregations={"total": "SUM(cost)"},
            jsonb_column=None,
        )
        sql_str = query.statement.as_string(None)
        assert "json_build_object(" in sql_str
        assert '"t"."date"' in sql_str
        assert '"t"."cost"' in sql_str
        assert "AS t" in sql_str

    def test_aggregations_without_group_by_raises(self) -> None:
        """Aggregations without group_by should raise ValueError."""
        with pytest.raises(ValueError, match="aggregations requires group_by"):
            self.repo._build_find_query(
                "v_stats",
                aggregations={"total": "SUM(cost)"},
                jsonb_column="data",
            )

    def test_clause_order_where_groupby_orderby_limit(self) -> None:
        """Verify SQL clause ordering: WHERE → GROUP BY → ORDER BY → LIMIT."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["date"],
            aggregations={"total": "SUM(cost)"},
            jsonb_column="data",
            where={"tenant_id": {"eq": str(uuid.uuid4())}},
            order_by="date ASC",
            limit=100,
            offset=10,
        )
        sql_str = query.statement.as_string(None)

        where_pos = sql_str.find("WHERE")
        group_pos = sql_str.find("GROUP BY")
        order_pos = sql_str.find("ORDER BY")
        limit_pos = sql_str.find("LIMIT")
        offset_pos = sql_str.find("OFFSET")

        assert where_pos > 0
        assert group_pos > where_pos
        assert order_pos > group_pos
        assert limit_pos > order_pos
        assert offset_pos > limit_pos

    def test_group_by_without_aggregations_jsonb(self) -> None:
        """GROUP BY without aggregations — dimensions only in json_build_object."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["date", "category"],
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "json_build_object(" in sql_str
        assert "'date'" in sql_str
        assert "'category'" in sql_str
        assert "GROUP BY" in sql_str
        # No aggregation functions
        assert "SUM" not in sql_str
        assert "AVG" not in sql_str

    def test_group_by_params_not_leaked_to_where_clause(self) -> None:
        """Ensure group_by/aggregations are popped before _build_where_clause."""
        original_bwc = self.repo._build_where_clause
        received_kwargs = {}

        def capture_kwargs(view_name: str, **kwargs: Any) -> Any:
            received_kwargs.update(kwargs)
            return original_bwc(view_name, **kwargs)

        from unittest.mock import patch

        with patch.object(
            self.repo, "_build_where_clause", side_effect=capture_kwargs
        ):
            self.repo._build_find_query(
                "v_stats",
                group_by=["date"],
                aggregations={"total": "SUM(cost)"},
                jsonb_column="data",
            )

        assert "group_by" not in received_kwargs
        assert "aggregations" not in received_kwargs

    def test_aggregation_with_nested_field(self) -> None:
        """Aggregation referencing a nested JSONB field path."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["date"],
            aggregations={"total": "SUM(metrics.cost)"},
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "\"data\"->'metrics'->>'cost'" in sql_str

    def test_non_numeric_aggregation_no_cast(self) -> None:
        """MIN/MAX/COUNT should not cast to numeric."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["category"],
            aggregations={
                "min_name": "MIN(name)",
                "max_name": "MAX(name)",
                "count": "COUNT(*)",
            },
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        # MIN and MAX should not have ::numeric
        # Find each aggregation context
        min_idx = sql_str.find("MIN(")
        max_idx = sql_str.find("MAX(")
        count_idx = sql_str.find("COUNT(*)")

        assert min_idx > 0
        assert max_idx > 0
        assert count_idx > 0

        # The numeric cast should not appear near MIN/MAX
        # (SUM/AVG are the only ones that get ::numeric)
        assert "MIN(" in sql_str
        assert "MAX(" in sql_str
        # Only SUM and AVG get numeric cast - none used here
        assert "::numeric" not in sql_str
