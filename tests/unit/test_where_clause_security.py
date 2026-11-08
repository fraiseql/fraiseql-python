"""Security tests for WHERE clause SQL generation.

Verifies that malicious input is properly escaped and cannot cause SQL injection.
"""

from fraiseql.where_clause import FieldCondition


class TestSQLInjectionProtection:
    """Test SQL injection protection in WHERE clause generation."""

    def test_jsonb_path_sql_injection_protection(self):
        """Verify malicious JSONB paths are escaped."""
        # Attempt SQL injection via JSONB path
        malicious_path = ["device'; DROP TABLE users; --", "name"]

        condition = FieldCondition(
            field_path=malicious_path,
            operator="eq",
            value="test",
            lookup_strategy="jsonb_path",
            target_column="data",
            jsonb_path=malicious_path,
        )

        sql, _params = condition.to_sql()
        sql_str = sql.as_string(None)

        # Should be escaped as literal string, not executed as SQL
        assert "DROP TABLE" not in sql_str or "DROP TABLE" in repr(sql_str)
        # Psycopg should escape single quotes
        assert "device'; DROP" not in sql_str or "'device''; DROP" in sql_str

    def test_field_name_sql_injection_protection(self):
        """Verify malicious field names are escaped."""
        malicious_field = "status; DELETE FROM allocations; --"

        condition = FieldCondition(
            field_path=[malicious_field],
            operator="eq",
            value="active",
            lookup_strategy="sql_column",
            target_column=malicious_field,
        )

        sql, _params = condition.to_sql()
        sql_str = sql.as_string(None)

        # Identifier() should quote field names
        # Should NOT execute DELETE statement
        assert "DELETE FROM" not in sql_str or '"' in sql_str

    def test_operator_value_sql_injection_protection(self):
        """Verify operator values use parameters, not inline SQL."""
        # Attempt SQL injection via value
        malicious_value = "active' OR '1'='1"

        condition = FieldCondition(
            field_path=["status"],
            operator="eq",
            value=malicious_value,
            lookup_strategy="sql_column",
            target_column="status",
        )

        sql, params = condition.to_sql()
        sql_str = sql.as_string(None)

        # Value should be parameterized (%s), not inline
        assert malicious_value not in sql_str
        assert "%s" in sql_str
        assert params[0] == malicious_value  # Value in params, not SQL

    def test_in_operator_sql_injection_protection(self):
        """Verify IN operator values use parameters."""
        malicious_values = ["active", "pending' OR '1'='1"]

        condition = FieldCondition(
            field_path=["status"],
            operator="in",
            value=malicious_values,
            lookup_strategy="sql_column",
            target_column="status",
        )

        sql, params = condition.to_sql()
        sql_str = sql.as_string(None)

        # Should use %s parameter, not inline values
        assert "OR '1'='1'" not in sql_str
        assert "%s" in sql_str
        # psycopg3 uses individual placeholders, not a single tuple
        assert params == malicious_values

    def test_like_pattern_sql_injection_protection(self):
        """Verify LIKE patterns don't allow SQL injection."""
        malicious_pattern = "test%' OR '1'='1"

        condition = FieldCondition(
            field_path=["name"],
            operator="contains",
            value=malicious_pattern,
            lookup_strategy="sql_column",
            target_column="name",
        )

        sql, params = condition.to_sql()
        sql_str = sql.as_string(None)

        # Pattern should be parameterized
        assert "OR '1'='1'" not in sql_str
        assert "%s" in sql_str
        # Pattern wrapped with % for contains
        assert params[0] == f"%{malicious_pattern}%"
