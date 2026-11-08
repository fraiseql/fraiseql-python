"""Comprehensive tests for basic comparison operators."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from psycopg.sql import SQL

from fraiseql.sql.where.operators.basic import (
    build_eq_sql,
    build_gt_sql,
    build_gte_sql,
    build_lt_sql,
    build_lte_sql,
    build_neq_sql,
)


class TestBasicEqualityOperators:
    """Test basic equality and inequality operators."""

    def test_eq_with_strings(self):
        """Test equality with string values."""
        path_sql = SQL("data->>'name'")
        result = build_eq_sql(path_sql, "John Doe")
        sql_str = result.as_string(None)
        assert sql_str == "data->>'name' = 'John Doe'"

    def test_eq_with_integers(self):
        """Test equality with integer values."""
        path_sql = SQL("data->>'age'")
        result = build_eq_sql(path_sql, 25)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'age'::numeric = 25"

    def test_eq_with_floats(self):
        """Test equality with float values."""
        path_sql = SQL("data->>'score'")
        result = build_eq_sql(path_sql, 95.5)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'score'::numeric = 95.5"

    def test_eq_with_decimals(self):
        """Test equality with decimal values."""
        path_sql = SQL("data->>'price'")
        result = build_eq_sql(path_sql, Decimal("19.99"))
        sql_str = result.as_string(None)
        assert sql_str == "data->>'price'::numeric = 19.99"

    def test_eq_with_booleans(self):
        """Test equality with boolean values."""
        path_sql = SQL("data->>'is_active'")
        result = build_eq_sql(path_sql, True)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'is_active' = 'true'"

    def test_eq_with_uuid(self):
        """Test equality with UUID values."""
        path_sql = SQL("data->>'user_id'")
        uuid_val = UUID("550e8400-e29b-41d4-a716-446655440000")
        result = build_eq_sql(path_sql, uuid_val)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'user_id'::uuid = '550e8400e29b41d4a716446655440000'::uuid"

    def test_eq_with_date(self):
        """Test equality with date values."""
        path_sql = SQL("data->>'birth_date'")
        date_val = date(1990, 5, 15)
        result = build_eq_sql(path_sql, date_val)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'birth_date'::date = '1990-05-15'::date"

    def test_eq_with_datetime(self):
        """Test equality with datetime values."""
        path_sql = SQL("data->>'created_at'")
        dt_val = datetime(2023, 7, 15, 10, 30, 45)
        result = build_eq_sql(path_sql, dt_val)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'created_at'::timestamp = '2023-07-15 10:30:45'::timestamp"

    def test_neq_with_strings(self):
        """Test inequality with string values."""
        path_sql = SQL("data->>'status'")
        result = build_neq_sql(path_sql, "inactive")
        sql_str = result.as_string(None)
        assert sql_str == "data->>'status' != 'inactive'"

    def test_neq_with_integers(self):
        """Test inequality with integer values."""
        path_sql = SQL("data->>'count'")
        result = build_neq_sql(path_sql, 0)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'count'::numeric != 0"

    def test_neq_with_booleans(self):
        """Test inequality with boolean values."""
        path_sql = SQL("data->>'is_deleted'")
        result = build_neq_sql(path_sql, False)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'is_deleted' != 'false'"


class TestBasicComparisonOperators:
    """Test greater than, less than operators."""

    def test_gt_with_numbers(self):
        """Test greater than with numeric values."""
        path_sql = SQL("data->>'age'")
        result = build_gt_sql(path_sql, 18)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'age'::numeric > 18"

    def test_gt_with_dates(self):
        """Test greater than with date values."""
        path_sql = SQL("data->>'created_at'")
        dt_val = datetime(2023, 1, 1)
        result = build_gt_sql(path_sql, dt_val)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'created_at'::timestamp > '2023-01-01 00:00:00'::timestamp"

    def test_gte_with_numbers(self):
        """Test greater than or equal with numeric values."""
        path_sql = SQL("data->>'score'")
        result = build_gte_sql(path_sql, 90)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'score'::numeric >= 90"

    def test_gte_with_dates(self):
        """Test greater than or equal with date values."""
        path_sql = SQL("data->>'updated_at'")
        date_val = date(2023, 6, 1)
        result = build_gte_sql(path_sql, date_val)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'updated_at'::date >= '2023-06-01'::date"

    def test_lt_with_numbers(self):
        """Test less than with numeric values."""
        path_sql = SQL("data->>'temperature'")
        result = build_lt_sql(path_sql, 100)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'temperature'::numeric < 100"

    def test_lt_with_uuid(self):
        """Test less than with UUID values."""
        path_sql = SQL("data->>'id'")
        uuid_val = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        result = build_lt_sql(path_sql, uuid_val)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'id'::uuid < 'ffffffffffffffffffffffffffffffff'::uuid"

    def test_lte_with_numbers(self):
        """Test less than or equal with numeric values."""
        path_sql = SQL("data->>'quantity'")
        result = build_lte_sql(path_sql, 50)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'quantity'::numeric <= 50"

    def test_lte_with_datetime(self):
        """Test less than or equal with datetime values."""
        path_sql = SQL("data->>'expires_at'")
        dt_val = datetime(2024, 12, 31, 23, 59, 59)
        result = build_lte_sql(path_sql, dt_val)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'expires_at'::timestamp <= '2024-12-31 23:59:59'::timestamp"


class TestBasicOperatorsEdgeCases:
    """Test edge cases for basic operators."""

    def test_eq_with_zero(self):
        """Test equality with zero."""
        path_sql = SQL("data->>'count'")
        result = build_eq_sql(path_sql, 0)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'count'::numeric = 0"

    def test_eq_with_negative_numbers(self):
        """Test equality with negative numbers."""
        path_sql = SQL("data->>'balance'")
        result = build_eq_sql(path_sql, -100)
        sql_str = result.as_string(None)
        assert sql_str in {"data->>'balance'::numeric = -100", "data->>'balance'::numeric =  -100"}

    def test_eq_with_large_numbers(self):
        """Test equality with large numbers."""
        path_sql = SQL("data->>'big_number'")
        result = build_eq_sql(path_sql, 9223372036854775807)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'big_number'::numeric = 9223372036854775807"

    def test_eq_with_floating_point_precision(self):
        """Test equality with floating point precision."""
        path_sql = SQL("data->>'pi'")
        result = build_eq_sql(path_sql, 3.141592653589793)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'pi'::numeric = 3.141592653589793"

    def test_eq_with_empty_string(self):
        """Test equality with empty string."""
        path_sql = SQL("data->>'description'")
        result = build_eq_sql(path_sql, "")
        sql_str = result.as_string(None)
        assert sql_str == "data->>'description' = ''"

    def test_eq_with_special_characters(self):
        """Test equality with special characters."""
        path_sql = SQL("data->>'name'")
        result = build_eq_sql(path_sql, "O'Connor & Sons")
        sql_str = result.as_string(None)
        assert sql_str == "data->>'name' = 'O''Connor & Sons'"  # SQL escaping

    def test_eq_with_unicode(self):
        """Test equality with unicode characters."""
        path_sql = SQL("data->>'title'")
        result = build_eq_sql(path_sql, "café & naïve résumé")
        sql_str = result.as_string(None)
        assert "café" in sql_str
        assert "naïve" in sql_str
        assert "résumé" in sql_str

    def test_neq_with_null_like_values(self):
        """Test inequality with null-like values."""
        path_sql = SQL("data->>'optional_field'")
        result = build_neq_sql(path_sql, "null")
        sql_str = result.as_string(None)
        assert sql_str == "data->>'optional_field' != 'null'"

    def test_comparison_with_boundary_dates(self):
        """Test comparison with boundary dates."""
        path_sql = SQL("data->>'date_field'")

        # Unix epoch
        epoch = datetime(1970, 1, 1)
        result = build_gte_sql(path_sql, epoch)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'date_field'::timestamp >= '1970-01-01 00:00:00'::timestamp"

        # Far future date
        future = datetime(9999, 12, 31, 23, 59, 59)
        result = build_lt_sql(path_sql, future)
        sql_str = result.as_string(None)
        assert sql_str == "data->>'date_field'::timestamp < '9999-12-31 23:59:59'::timestamp"

    def test_comparison_with_min_max_values(self):
        """Test comparison with min/max numeric values."""
        path_sql = SQL("data->>'value'")

        # Python int min/max
        result = build_gte_sql(path_sql, -9223372036854775808)
        sql_str = result.as_string(None)
        assert "-9223372036854775808" in sql_str

        result = build_lte_sql(path_sql, 9223372036854775807)
        sql_str = result.as_string(None)
        assert "9223372036854775807" in sql_str
