"""Comprehensive tests for array operator SQL building."""

from psycopg.sql import SQL, Literal

from fraiseql.sql.where.operators.arrays import (
    build_array_all_eq_sql,
    build_array_any_eq_sql,
    build_array_contained_by_sql,
    build_array_contains_sql,
    build_array_eq_sql,
    build_array_len_eq_sql,
    build_array_len_gt_sql,
    build_array_len_gte_sql,
    build_array_len_lt_sql,
    build_array_len_lte_sql,
    build_array_len_neq_sql,
    build_array_neq_sql,
    build_array_overlaps_sql,
)


class TestArrayBasicOperators:
    """Test basic array comparison operators."""

    def test_eq_array(self):
        """Test array equality."""
        path_sql = SQL("tags")
        value = ["python", "testing", "sql"]
        result = build_array_eq_sql(path_sql, value)
        result_str = str(result)
        assert "::jsonb" in result_str
        assert "=" in result_str
        assert "python" in result_str
        assert "testing" in result_str
        assert "sql" in result_str

    def test_neq_array(self):
        """Test array inequality."""
        path_sql = SQL("categories")
        value = ["news", "tech"]
        result = build_array_neq_sql(path_sql, value)
        result_str = str(result)
        assert "!=" in result_str
        assert "::jsonb" in result_str
        assert "news" in result_str
        assert "tech" in result_str

    def test_eq_quote_is_escaped_once(self):
        """The JSON goes in a Literal as is: escaping it first doubled each quote."""
        result = build_array_eq_sql(SQL("tags"), ["it's"])
        assert result.as_string(None) == "tags = '[\"it''s\"]'::jsonb"

    def test_neq_value_is_a_literal(self):
        """The value is a Literal, not text pasted into the SQL template."""
        result = build_array_neq_sql(SQL("tags"), ["it's", "100%"])
        assert result.as_string(None) == "tags != '[\"it''s\", \"100%\"]'::jsonb"
        assert Literal('["it\'s", "100%"]') in list(result)


class TestArrayContainmentOperators:
    """Test array containment operators."""

    def test_contains_array(self):
        """Test array contains operator (@>)."""
        path_sql = SQL("permissions")
        value = ["read", "write"]
        result = build_array_contains_sql(path_sql, value)
        result_str = str(result)
        assert " @> " in result_str
        assert "::jsonb" in result_str
        assert "read" in result_str
        assert "write" in result_str

    def test_contained_by_array(self):
        """Test array contained by operator (<@)."""
        path_sql = SQL("user_roles")
        value = ["admin", "moderator", "user"]
        result = build_array_contained_by_sql(path_sql, value)
        result_str = str(result)
        assert " <@ " in result_str
        assert "::jsonb" in result_str
        assert "admin" in result_str
        assert "moderator" in result_str
        assert "user" in result_str


class TestArrayOverlapsOperators:
    """Test array overlaps operators."""

    def test_overlaps_native_array(self):
        """Test overlaps with native PostgreSQL array column."""
        path_sql = SQL("tags_array")  # Native column (using SQL for simplicity)
        value = ["python", "javascript"]
        result = build_array_overlaps_sql(path_sql, value)
        result_str = str(result)
        assert " ?| " in result_str  # JSONB array overlap operator (fallback for SQL type)
        assert '"python"' in result_str
        assert '"javascript"' in result_str

    def test_overlaps_jsonb_array(self):
        """Test overlaps with JSONB array field."""
        path_sql = SQL("data->tags")  # JSONB path
        value = ["react", "vue"]
        result = build_array_overlaps_sql(path_sql, value)
        result_str = str(result)
        assert " ?| " in result_str  # JSONB array overlap operator
        assert '"react"' in result_str
        assert '"vue"' in result_str


class TestArrayLengthOperators:
    """Test array length comparison operators."""

    def test_len_eq_array(self):
        """Test array length equality."""
        path_sql = SQL("items")
        result = build_array_len_eq_sql(path_sql, 5)
        result_str = str(result)
        assert "jsonb_array_length(" in result_str
        assert ") = " in result_str
        assert "5" in result_str

    def test_len_neq_array(self):
        """Test array length inequality."""
        path_sql = SQL("tags")
        result = build_array_len_neq_sql(path_sql, 0)
        result_str = str(result)
        assert "jsonb_array_length(" in result_str
        assert ") != " in result_str
        assert "0" in result_str

    def test_len_gt_array(self):
        """Test array length greater than."""
        path_sql = SQL("comments")
        result = build_array_len_gt_sql(path_sql, 10)
        result_str = str(result)
        assert "jsonb_array_length(" in result_str
        assert ") > " in result_str
        assert "10" in result_str

    def test_len_gte_array(self):
        """Test array length greater than or equal."""
        path_sql = SQL("replies")
        result = build_array_len_gte_sql(path_sql, 1)
        result_str = str(result)
        assert "jsonb_array_length(" in result_str
        assert ") >= " in result_str
        assert "1" in result_str

    def test_len_lt_array(self):
        """Test array length less than."""
        path_sql = SQL("images")
        result = build_array_len_lt_sql(path_sql, 3)
        result_str = str(result)
        assert "jsonb_array_length(" in result_str
        assert ") < " in result_str
        assert "3" in result_str

    def test_len_lte_array(self):
        """Test array length less than or equal."""
        path_sql = SQL("attachments")
        result = build_array_len_lte_sql(path_sql, 5)
        result_str = str(result)
        assert "jsonb_array_length(" in result_str
        assert ") <= " in result_str
        assert "5" in result_str


class TestArrayElementOperators:
    """Test array element comparison operators."""

    def test_any_eq_array(self):
        """Test array any element equals."""
        path_sql = SQL("keywords")
        result = build_array_any_eq_sql(path_sql, "python")
        result_str = str(result)
        assert " = ANY(" in result_str
        assert "jsonb_array_elements_text(" in result_str
        assert "python" in result_str

    def test_all_eq_array(self):
        """Test array all elements equal."""
        path_sql = SQL("categories")
        result = build_array_all_eq_sql(path_sql, "featured")
        result_str = str(result)
        assert " = ALL(" in result_str
        assert "jsonb_array_elements_text(" in result_str
        assert "featured" in result_str


class TestArrayEdgeCases:
    """Test array operator edge cases."""

    def test_empty_array(self):
        """Test operations with empty array."""
        path_sql = SQL("tags")
        value = []
        result = build_array_eq_sql(path_sql, value)
        result_str = str(result)
        assert "[]" in result_str or "[]" in result_str

    def test_single_element_array(self):
        """Test operations with single element array."""
        path_sql = SQL("status")
        value = ["active"]
        result = build_array_contains_sql(path_sql, value)
        result_str = str(result)
        assert "active" in result_str
        assert " @> " in result_str

    def test_array_with_numbers(self):
        """Test array with numeric values."""
        path_sql = SQL("scores")
        value = [85, 92, 78]
        result = build_array_eq_sql(path_sql, value)
        result_str = str(result)
        assert "85" in result_str
        assert "92" in result_str
        assert "78" in result_str

    def test_array_with_special_chars(self):
        """Test array with special characters."""
        path_sql = SQL("names")
        value = ["O'Connor", "Smith-Jones", "user@example.com"]
        result = build_array_contains_sql(path_sql, value)
        sql_str = result.as_string(None)
        # JSON escaping: single quotes become double quotes in JSON
        assert "O''Connor" in sql_str or "O'Connor" in sql_str
        assert "Smith-Jones" in sql_str
        assert "user@example.com" in sql_str

    def test_overlaps_fallback(self):
        """Test overlaps operator fallback for non-list values."""
        path_sql = SQL("data->tags")
        value = "single_value"  # Not a list
        result = build_array_overlaps_sql(path_sql, value)  # type: ignore
        result_str = str(result)
        assert " ? " in result_str
        assert "single_value" in result_str
