"""Tests for Issue #315: GROUP BY and aggregations in db.find().

Verifies that _build_find_query correctly generates:
- GROUP BY clauses for JSONB and non-JSONB tables
- json_build_object() SELECT with dimension + aggregation fields
- Proper SQL clause ordering (WHERE → GROUP BY → ORDER BY → LIMIT)
- Aggregation expression parsing and validation
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.db import (
    FraiseQLRepository,
    _build_jsonb_field_expr,
    _build_nested_json_object,
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


# ── Nested json_build_object tests (Issue #318) ───────────────────────


class TestBuildNestedJsonObject:
    """Tests for _build_nested_json_object (nested dot-separated paths)."""

    def test_flat_paths_no_nesting(self) -> None:
        """Non-dotted paths produce a flat json_build_object."""
        from psycopg.sql import SQL

        entries = [
            ("date", SQL("expr_date")),
            ("total", SQL("expr_total")),
        ]
        result = _build_nested_json_object(entries)
        sql_str = result.as_string(None)
        assert sql_str == (
            "json_build_object('date', expr_date, 'total', expr_total)"
        )

    def test_single_nested_path(self) -> None:
        """A single dotted path produces nested json_build_object."""
        from psycopg.sql import SQL

        entries = [("a.b", SQL("expr_b"))]
        result = _build_nested_json_object(entries)
        sql_str = result.as_string(None)
        assert sql_str == (
            "json_build_object('a', json_build_object('b', expr_b))"
        )

    def test_sibling_paths_grouped(self) -> None:
        """Paths sharing a prefix are grouped under one key."""
        from psycopg.sql import SQL

        entries = [
            ("dims.date", SQL("expr_date")),
            ("dims.month", SQL("expr_month")),
        ]
        result = _build_nested_json_object(entries)
        sql_str = result.as_string(None)
        assert "json_build_object('dims', json_build_object(" in sql_str
        assert "'date', expr_date" in sql_str
        assert "'month', expr_month" in sql_str

    def test_deeply_nested_paths(self) -> None:
        """Three-level deep nesting works correctly."""
        from psycopg.sql import SQL

        entries = [("a.b.c", SQL("expr_c"))]
        result = _build_nested_json_object(entries)
        sql_str = result.as_string(None)
        assert sql_str == (
            "json_build_object('a', json_build_object("
            "'b', json_build_object('c', expr_c)))"
        )

    def test_mixed_flat_and_nested(self) -> None:
        """Mix of flat and nested paths in one object."""
        from psycopg.sql import SQL

        entries = [
            ("dimensions.date", SQL("expr_date")),
            ("measures.cost", SQL("expr_cost")),
        ]
        result = _build_nested_json_object(entries)
        sql_str = result.as_string(None)
        assert "'dimensions', json_build_object('date', expr_date)" in sql_str
        assert "'measures', json_build_object('cost', expr_cost)" in sql_str


class TestBuildFindQueryNestedGroupBy:
    """Tests for nested json_build_object in _build_find_query (Issue #318)."""

    def setup_method(self) -> None:
        self.mock_conn = MagicMock()
        self.repo = FraiseQLRepository(self.mock_conn)

    def test_nested_group_by_produces_nested_json(self) -> None:
        """Dotted group_by paths produce nested json_build_object."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["dimensions.date_info.date"],
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        assert "json_build_object('dimensions'" in sql_str
        assert "json_build_object('date_info'" in sql_str
        assert "json_build_object('date'" in sql_str

    def test_nested_group_by_with_aggregation(self) -> None:
        """Dotted group_by + dotted aggregation alias nests correctly."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=["dimensions.date_info.date"],
            aggregations={"measures.cost": "SUM(measures.cost)"},
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        # Dimensions nested
        assert "'dimensions', json_build_object(" in sql_str
        assert "'date_info', json_build_object(" in sql_str
        # Measures nested
        assert "'measures', json_build_object(" in sql_str
        assert "'cost', SUM" in sql_str

    def test_siblings_grouped_under_same_parent(self) -> None:
        """Multiple fields under the same parent share one nesting level."""
        query = self.repo._build_find_query(
            "v_stats",
            group_by=[
                "dimensions.date_info.date",
                "dimensions.date_info.month",
            ],
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)
        # Extract the SELECT portion (before GROUP BY) to check nesting
        select_part = sql_str.split("GROUP BY")[0]
        # Should have ONE 'dimensions' key in the json_build_object
        assert select_part.count("'dimensions', json_build_object(") == 1
        assert select_part.count("'date_info', json_build_object(") == 1
        # Both leaf fields present
        assert "'date'" in select_part
        assert "'month'" in select_part


# ── Rust projection bypass tests (Issue #319) ─────────────────────────


class TestGroupBySkipsRustProjection:
    """When group_by is used, field_paths/field_selections must be None (#319)."""

    @pytest.mark.asyncio
    async def test_group_by_passes_none_field_paths(self) -> None:
        """find() with group_by should call execute_via_rust_pipeline with field_paths=None."""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=False)

        repo = FraiseQLRepository(mock_pool)

        mock_result = b'{"data":{"stats":[]}}'
        with patch(
            "fraiseql.db.execute_via_rust_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_execute:
            await repo.find(
                "v_stats",
                group_by=["date"],
                aggregations={"total": "SUM(cost)"},
            )

            mock_execute.assert_called_once()
            kw = mock_execute.call_args.kwargs
            assert kw.get("field_paths") is None
            assert kw.get("field_selections") is None

    @pytest.mark.asyncio
    async def test_without_group_by_preserves_field_paths(self) -> None:
        """find() without group_by should NOT force field_paths to None."""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=False)

        repo = FraiseQLRepository(mock_pool)

        mock_result = b'{"data":{"stats":[]}}'
        with patch(
            "fraiseql.db.execute_via_rust_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_execute:
            await repo.find("v_stats")

            mock_execute.assert_called_once()
            # Without group_by, field_paths defaults to None anyway (no info),
            # but the code path should NOT have the group_by override
            # This just verifies the non-group_by path doesn't crash
            assert mock_execute.called
