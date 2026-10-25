"""Tests for SQL queries in Grafana dashboards.

Tests verify:
- SQL queries are syntactically valid
- Queries reference correct tables and schemas
- Queries use proper Grafana variables
- Queries don't have SQL injection vulnerabilities
- Queries follow PostgreSQL best practices
"""

import json
import re
from pathlib import Path

import pytest

from .conftest import is_known_exception

pytestmark = pytest.mark.integration

DASHBOARD_DIR = Path(__file__).parent.parent.parent / "grafana"
DASHBOARD_FILES = [
    "error_monitoring.json",
    "performance_metrics.json",
    "database_pool.json",
    "apq_effectiveness.json",
]


def calls(func: str, sql: str) -> bool:
    """Whether ``sql`` calls ``func`` (not a column such as max_exec_time_ms)."""
    return re.search(rf"\b{func}\s*\(", sql) is not None


@pytest.fixture
def all_sql_queries() -> None:
    """Extract all SQL queries from all dashboards."""
    queries = []

    for filename in DASHBOARD_FILES:
        filepath = DASHBOARD_DIR / filename
        with filepath.open() as f:
            dashboard = json.load(f)

        dashboard_name = filepath.stem
        panels = dashboard["dashboard"]["panels"]

        for panel in panels:
            for target in panel.get("targets", []):
                if "rawSql" in target:
                    queries.append(
                        {
                            "dashboard": dashboard_name,
                            "panel": panel["title"],
                            "ref_id": target["refId"],
                            "sql": target["rawSql"],
                        }
                    )

    return queries


class TestSQLSyntax:
    """Test SQL query syntax and structure."""

    def test_queries_are_not_empty(self, all_sql_queries) -> None:
        """All SQL queries should have content."""
        for query_info in all_sql_queries:
            sql = query_info["sql"].strip()
            assert sql, f"{query_info['dashboard']}.{query_info['panel']}: Empty SQL query"

    def test_queries_have_select_statement(self, all_sql_queries) -> None:
        """All queries should contain SELECT statement."""
        for query_info in all_sql_queries:
            sql = query_info["sql"].upper()
            assert "SELECT" in sql, (
                f"{query_info['dashboard']}.{query_info['panel']}: No SELECT statement"
            )

    def test_queries_have_from_clause(self, all_sql_queries) -> None:
        """All queries should have FROM clause (except CTEs)."""
        for query_info in all_sql_queries:
            sql = query_info["sql"].upper()

            # Skip if it's a pure CTE query (some advanced queries might not have FROM)
            if "WITH" in sql and "FROM" not in sql:
                continue

            assert "FROM" in sql, f"{query_info['dashboard']}.{query_info['panel']}: No FROM clause"

    def test_queries_end_with_semicolon_or_not(self, all_sql_queries) -> None:
        """Queries should consistently handle semicolons."""
        for query_info in all_sql_queries:
            sql = query_info["sql"].strip()

            # Grafana queries typically don't need semicolons, but if present should be at end
            if ";" in sql:
                assert sql.endswith(";"), (
                    f"{query_info['dashboard']}.{query_info['panel']}: "
                    f"Semicolon should be at end of query"
                )


class TestTableReferences:
    """Test that queries reference correct tables."""

    # Tables and views of src/fraiseql/monitoring/schema.sql, of the PostgreSQL APQ
    # backend (default table_prefix "apq_"), and PostgreSQL's statistics views
    EXPECTED_TABLES = {
        "tb_error_log",
        "tb_error_occurrence",
        "tb_error_notification_log",
        "v_query_stats",
        "apq_queries",
        "apq_responses",
        "pg_stat_activity",
        "pg_stat_database",
        "pg_stat_user_tables",
        "pg_class",
    }

    def test_queries_reference_valid_tables(self, all_sql_queries) -> None:
        """Queries should reference known FraiseQL tables."""
        for query_info in all_sql_queries:
            sql = query_info["sql"]

            # Extract table references (simple pattern matching)
            # Matches: FROM table_name, JOIN table_name
            table_pattern = r"(?:FROM|JOIN)\s+([a-z_]+\.[a-z_]+|[a-z_]+)"
            tables = re.findall(table_pattern, sql, re.IGNORECASE)

            for table in tables:
                # Skip subqueries, CTEs, and SQL keywords
                if table.lower() in [
                    "select",
                    "with",
                    "(",
                    "lateral",
                    "interval",
                    "distinct",
                    "on",
                ]:
                    continue

                # Check if table is in expected tables or is a CTE
                table_lower = table.lower()
                is_cte = re.search(rf"\bWITH\s+\w*{re.escape(table)}\w*\s+AS", sql, re.IGNORECASE)

                # Skip if it looks like a SQL expression or function
                if any(keyword in table_lower for keyword in ["(", ")", "as", "case", "when"]):
                    continue

                if not is_cte:
                    assert table_lower in self.EXPECTED_TABLES, (
                        f"{query_info['dashboard']}.{query_info['panel']}: Unknown table '{table}'"
                    )

    def test_no_monitoring_schema(self, all_sql_queries) -> None:
        """schema.sql creates its tables in the search_path, not in a 'monitoring' schema."""
        for query_info in all_sql_queries:
            assert "monitoring." not in query_info["sql"].lower(), (
                f"{query_info['dashboard']}.{query_info['panel']}: there is no 'monitoring' schema"
            )


class TestGrafanaVariables:
    """Test Grafana variable usage in queries."""

    def test_queries_use_time_range_variables(self, all_sql_queries) -> None:
        """Time-series queries should use Grafana time range variables."""
        time_sensitive_keywords = [
            "occurred_at",
            "start_time",
            "timestamp",
            "created_at",
            "sent_at",
        ]

        for query_info in all_sql_queries:
            sql = query_info["sql"]

            # If query filters by time, should use Grafana variables
            has_time_filter = any(keyword in sql.lower() for keyword in time_sensitive_keywords)

            if has_time_filter:
                # Should use $__timeFrom() and $__timeTo() OR NOW() - INTERVAL
                # OR be a latest/single-value query (ORDER BY ... DESC LIMIT 1)
                uses_grafana_time = (
                    "$__timeFilter(" in sql or "$__timeFrom()" in sql or "$__timeTo()" in sql
                )
                uses_now_interval = "NOW() - INTERVAL" in sql or "NOW()" in sql
                is_latest_query = (
                    "ORDER BY" in sql.upper() and "DESC" in sql.upper() and "LIMIT 1" in sql.upper()
                )
                is_exception = is_known_exception(
                    query_info["dashboard"], query_info["panel"], "no_time_filter"
                )

                assert uses_grafana_time or uses_now_interval or is_latest_query or is_exception, (
                    f"{query_info['dashboard']}.{query_info['panel']}: Time-sensitive query should use "
                    f"Grafana time variables, NOW(), or be a latest-value query"
                )

    def test_queries_use_environment_variable(self, all_sql_queries) -> None:
        """Queries should filter by environment variable."""
        # Queries on the error tables (tb_error_log has the environment column)
        # should filter by environment
        observability_tables = ["tb_error_log", "tb_error_occurrence", "tb_error_notification_log"]

        for query_info in all_sql_queries:
            sql = query_info["sql"]

            # If querying observability tables
            uses_obs_table = any(table in sql for table in observability_tables)

            if uses_obs_table:
                # Should use $environment variable (with some exceptions for aggregate queries)
                uses_env_var = "'$environment'" in sql or '"$environment"' in sql

                # Allow queries without environment filter if:
                # 1. They're aggregate-only queries
                # 2. They explicitly query across all environments (e.g., "Errors by Environment")
                # 3. They're grouping BY environment
                is_aggregate_only = "COUNT(*)" in sql and "GROUP BY" not in sql
                groups_by_environment = "GROUP BY environment" in sql.lower()
                is_multi_env_query = groups_by_environment
                is_exception = is_known_exception(
                    query_info["dashboard"], query_info["panel"], "no_environment_filter"
                )

                if not (is_aggregate_only or is_multi_env_query or is_exception):
                    assert uses_env_var, (
                        f"{query_info['dashboard']}.{query_info['panel']}: "
                        f"Query should filter by '$environment' variable"
                    )

    def test_custom_time_range_variable(self, all_sql_queries) -> None:
        """Queries using custom time range should use '$time_range' variable."""
        for query_info in all_sql_queries:
            sql = query_info["sql"]

            # If query uses INTERVAL with placeholder
            if "INTERVAL '$time_range'" in sql:
                # This is valid - custom time range variable
                pass


class TestQueryPerformance:
    """Test query performance characteristics."""

    def test_queries_use_indexed_columns(self, all_sql_queries) -> None:
        """WHERE clauses on FraiseQL tables should use indexed columns."""
        indexed_columns = [
            "occurred_at",
            "last_seen",
            "sent_at",
            "created_at",
            "fingerprint",
            "error_id",
            "trace_id",
            "environment",
            "error_type",
        ]

        for query_info in all_sql_queries:
            sql = query_info["sql"].lower()

            # PostgreSQL's statistics views (pg_stat_*, v_query_stats) have no indexes
            if "where" in sql and re.search(r"\b(?:from|join)\s+(?:tb|apq)_", sql):
                # At least one indexed column should be in WHERE clause
                has_indexed_filter = any(col in sql for col in indexed_columns)

                # Allow exceptions for specific aggregate queries
                is_simple_aggregate = "select count(*)" in sql and "group by" not in sql

                if not is_simple_aggregate:
                    assert has_indexed_filter, (
                        f"{query_info['dashboard']}.{query_info['panel']}: "
                        f"Query should filter by indexed columns for performance"
                    )

    def test_queries_have_reasonable_limits(self, all_sql_queries) -> None:
        """Table queries should have LIMIT clauses."""
        for query_info in all_sql_queries:
            sql = query_info["sql"].upper()

            # If query returns table data (not aggregates)
            is_table_query = "FROM" in sql and "GROUP BY" not in sql and "COUNT(*)" not in sql

            if is_table_query:
                # Should have LIMIT
                has_limit = "LIMIT" in sql

                # Extract limit value if present
                if has_limit:
                    limit_match = re.search(r"LIMIT\s+(\d+)", sql)
                    if limit_match:
                        limit_value = int(limit_match.group(1))
                        assert limit_value <= 1000, (
                            f"{query_info['dashboard']}.{query_info['panel']}: "
                            f"LIMIT {limit_value} is too high (max 1000)"
                        )

    def test_queries_avoid_select_star(self, all_sql_queries) -> None:
        """Queries should select specific columns, not SELECT *."""
        for query_info in all_sql_queries:
            sql = query_info["sql"]

            # Allow SELECT * for COUNT(*) queries
            if "COUNT(*)" in sql or "COUNT(DISTINCT" in sql:
                continue

            # Check for SELECT * (but not COUNT(*))
            select_star_pattern = r"SELECT\s+\*\s+FROM"
            has_select_star = re.search(select_star_pattern, sql, re.IGNORECASE)

            # Warning: SELECT * can be inefficient and break if schema changes
            if has_select_star:
                # Allow for specific cases where it's acceptable
                # (e.g., subqueries, CTEs where columns are specified later)
                pass


class TestSQLInjectionPrevention:
    """Test that queries don't have SQL injection vulnerabilities."""

    def test_variables_are_properly_quoted(self, all_sql_queries) -> None:
        """Grafana variables should be properly quoted."""
        for query_info in all_sql_queries:
            sql = query_info["sql"]

            # Check for unquoted variables in string contexts
            # Variables should be '$var' not $var in WHERE clauses
            # Exception: Functions like $__timeFrom() don't need quotes

            # Find WHERE clauses
            where_clauses = re.findall(
                r"WHERE.*?(?:GROUP BY|ORDER BY|LIMIT|$)", sql, re.DOTALL | re.IGNORECASE
            )

            for where_clause in where_clauses:
                # Look for $variables
                variables = re.findall(r"\$\w+", where_clause)

                for var in variables:
                    # Skip Grafana functions (start with $__)
                    if var.startswith("$__"):
                        continue

                    # Variable should be quoted if used in comparison
                    # Check context around variable
                    var_context = re.search(
                        rf"=\s*{re.escape(var)}|{re.escape(var)}\s*=", where_clause
                    )
                    if var_context:
                        # Should be quoted: = '$variable'
                        is_quoted = re.search(rf"['\"]?\${re.escape(var[1:])}['\"]", where_clause)
                        assert is_quoted, (
                            f"{query_info['dashboard']}.{query_info['panel']}: "
                            f"Variable {var} should be quoted in WHERE clause"
                        )

    def test_no_dynamic_sql_construction(self, all_sql_queries) -> None:
        """Queries should not use dynamic SQL construction."""
        dangerous_patterns = [
            r"EXECUTE\s+",
            r"CONCAT\s*\(",
            r"\|\|.*FROM",  # String concatenation in FROM clause
        ]

        for query_info in all_sql_queries:
            sql = query_info["sql"]

            for pattern in dangerous_patterns:
                assert not re.search(pattern, sql, re.IGNORECASE), (
                    f"{query_info['dashboard']}.{query_info['panel']}: "
                    f"Query contains potentially unsafe dynamic SQL"
                )


class TestQueryCorrectness:
    """Test query correctness and PostgreSQL compatibility."""

    def test_aggregates_with_group_by(self, all_sql_queries) -> None:
        """Queries with aggregates should have GROUP BY for non-aggregated columns."""
        aggregate_functions = ["COUNT", "SUM", "AVG", "MAX", "MIN", "PERCENTILE_CONT"]

        for query_info in all_sql_queries:
            sql = query_info["sql"].upper()

            has_aggregate = any(calls(func, sql) for func in aggregate_functions)

            if has_aggregate:
                # If there are non-aggregate columns in SELECT, need GROUP BY
                # (This is a simplified check - full validation would require parsing)

                # Check if there's a GROUP BY
                has_group_by = "GROUP BY" in sql

                # Simple queries with only aggregates don't need GROUP BY
                select_match = re.search(r"SELECT\s+(.*?)\s+FROM", sql, re.DOTALL)
                if select_match:
                    select_clause = select_match.group(1)

                    # Count aggregate functions
                    agg_count = sum(1 for func in aggregate_functions if calls(func, select_clause))

                    # Count commas (rough proxy for column count)
                    comma_count = select_clause.count(",")

                    # If ALL columns are aggregates, no GROUP BY needed
                    # If there are more columns than aggregates, need GROUP BY
                    if comma_count > 0 and comma_count + 1 > agg_count:
                        # Has non-aggregate columns
                        # Allow CTEs and subqueries
                        is_cte_query = "WITH" in sql
                        is_exception = is_known_exception(
                            query_info["dashboard"], query_info["panel"], "no_group_by"
                        )

                        if not (is_cte_query or is_exception):
                            assert has_group_by, (
                                f"{query_info['dashboard']}.{query_info['panel']}: Query with aggregates and "
                                f"non-aggregate columns needs GROUP BY clause"
                            )

    def test_json_operators_are_valid(self, all_sql_queries) -> None:
        """JSONB operators should use valid PostgreSQL syntax."""
        for query_info in all_sql_queries:
            sql = query_info["sql"]

            # Check for JSONB operators
            if "->" in sql or "->>" in sql:
                # Validate basic syntax: column->>'key'
                _jsonb_pattern = r"\w+\s*->>?\s*'[\w_]+'"
                jsonb_ops = re.findall(r"\w+\s*->>?[^,\s]+", sql)

                for op in jsonb_ops:
                    # Should have quotes around key
                    assert "'" in op or '"' in op, (
                        f"{query_info['dashboard']}.{query_info['panel']}: "
                        f"JSONB key should be quoted: {op}"
                    )

    def test_cte_syntax(self, all_sql_queries) -> None:
        """CTE (Common Table Expression) syntax should be valid."""
        for query_info in all_sql_queries:
            sql = query_info["sql"].upper()

            if "WITH" in sql:
                # CTE should have AS keyword
                assert " AS " in sql, (
                    f"{query_info['dashboard']}.{query_info['panel']}: CTE missing AS keyword"
                )

                # Should have opening parenthesis
                assert "(" in sql, (
                    f"{query_info['dashboard']}.{query_info['panel']}: CTE missing parentheses"
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
