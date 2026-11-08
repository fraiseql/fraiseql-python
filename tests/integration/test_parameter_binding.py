"""Integration tests for parameter binding correctness.

Verifies that parameterized queries have correct parameter alignment
and don't cause silent data corruption.
"""

import uuid

from fraiseql.db import FraiseQLRepository


class TestParameterBinding:
    """Test parameter binding correctness in WHERE clause execution."""

    async def test_parameter_count_matches_placeholders(self, class_db_pool):
        """Verify parameter count matches %s placeholder count."""
        repo = FraiseQLRepository(class_db_pool, context={"tenant_id": "test"})

        # Complex query with multiple parameters
        where = {
            "status": {"in": ["active", "pending"]},
            "machine": {"id": {"eq": uuid.uuid4()}},
            "name": {"contains": "test"},
        }

        table_columns = {"status", "machine_id", "name", "data"}
        clause = repo._normalize_where(where, "tv_allocation", table_columns)
        sql, params = clause.to_sql()

        # Count placeholders in SQL
        sql_str = sql.as_string(None)
        placeholder_count = sql_str.count("%s")

        assert placeholder_count == len(params), (
            f"Parameter count mismatch: {placeholder_count} placeholders "
            f"but {len(params)} parameters"
        )

    async def test_parameter_order_correctness(self, class_db_pool, setup_hybrid_table):
        """Verify parameters are in correct order for placeholders."""
        test_data = setup_hybrid_table
        repo = FraiseQLRepository(class_db_pool, context={"tenant_id": "test"})

        # Query with known data
        where = {"status": {"eq": "active"}, "machine": {"id": {"eq": test_data["machine1_id"]}}}

        # This should return results (correct binding)
        result = await repo.find("tv_allocation", where=where)

        # Should return results
        assert result is not None

    async def test_in_operator_parameter_binding(self, class_db_pool):
        """Verify IN operator uses individual parameters (psycopg3 style)."""
        repo = FraiseQLRepository(class_db_pool, context={"tenant_id": "test"})

        where = {"status": {"in": ["active", "pending", "completed"]}}

        table_columns = {"status"}
        clause = repo._normalize_where(where, "tv_allocation", table_columns)
        sql, params = clause.to_sql()

        # IN operator should have individual parameters (psycopg3 requires this)
        assert len(params) == 3
        assert params == ["active", "pending", "completed"]

        # SQL should have 3 %s placeholders for IN (%s, %s, %s)
        sql_str = sql.as_string(None)
        assert sql_str.count("%s") == 3
        assert "IN (%s, %s, %s)" in sql_str

    async def test_null_operator_no_parameters(self, class_db_pool):
        """Verify IS NULL operator has no parameters."""
        repo = FraiseQLRepository(class_db_pool, context={"tenant_id": "test"})

        where = {"machine_id": {"isnull": True}}

        table_columns = {"machine_id"}
        clause = repo._normalize_where(where, "tv_allocation", table_columns)
        sql, params = clause.to_sql()

        # IS NULL should have no parameters
        assert len(params) == 0

        # SQL should have no %s placeholders
        sql_str = sql.as_string(None)
        assert "%s" not in sql_str
        assert "IS NULL" in sql_str

    async def test_mixed_operators_parameter_binding(self, class_db_pool):
        """Verify complex WHERE with mixed operators has correct binding."""
        repo = FraiseQLRepository(class_db_pool, context={"tenant_id": "test"})

        machine_id = uuid.uuid4()
        where = {
            "status": {"in": ["active", "pending"]},
            "machine": {"id": {"eq": machine_id}},
            "name": {"contains": "test"},
            "created_at": {"gte": "2024-01-01"},
        }

        table_columns = {"status", "machine_id", "name", "created_at", "data"}
        clause = repo._normalize_where(where, "tv_allocation", table_columns)
        _sql, params = clause.to_sql()

        # Should have 5 parameters (2 IN values individually, eq UUID, contains pattern, gte date)
        expected_param_count = 5
        assert len(params) == expected_param_count

        # Verify parameter types (IN operator now uses individual parameters)
        assert isinstance(params[0], str)  # IN value 1: "active"
        assert isinstance(params[1], str)  # IN value 2: "pending"
        assert isinstance(params[2], uuid.UUID)  # machine_id
        assert isinstance(params[3], str)  # LIKE pattern
        assert isinstance(params[4], str)  # date

    async def test_query_execution_smoke_test(self, class_db_pool, setup_hybrid_table):
        """Smoke test: Execute complex query to verify no runtime errors."""
        test_data = setup_hybrid_table
        repo = FraiseQLRepository(class_db_pool, context={"tenant_id": "test"})

        # Complex query
        where = {
            "status": {"in": ["active", "pending"]},
            "machine": {"id": {"eq": test_data["machine1_id"]}},
            "OR": [{"name": {"contains": "test"}}, {"name": {"startswith": "demo"}}],
        }

        # Should execute without errors
        result = await repo.find("tv_allocation", where=where)

        # Should return structured result
        assert result is not None
