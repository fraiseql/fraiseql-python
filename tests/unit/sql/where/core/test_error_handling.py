"""Test error handling and validation for operator SQL building."""

import pytest
from psycopg.sql import SQL

from fraiseql.sql.where.core.field_detection import FieldType
from fraiseql.sql.where.operators import get_operator_function


class TestInvalidOperators:
    """Test invalid operator name handling."""

    def test_invalid_operator_name_text(self):
        """Test that invalid operator names raise appropriate errors for text fields."""
        with pytest.raises(ValueError, match=r"unsupported|invalid|not found"):
            get_operator_function(FieldType.STRING, "invalid_op")

    def test_invalid_operator_name_numeric(self):
        """Test invalid operators for numeric fields."""
        with pytest.raises(ValueError):
            get_operator_function(FieldType.INTEGER, "invalid_op")

    def test_typo_in_operator(self):
        """Test common typos in operator names."""
        with pytest.raises(ValueError):
            get_operator_function(FieldType.INTEGER, "eqauls")  # typo: equals


class TestTypeMismatches:
    """Test type mismatch handling."""

    def test_in_requires_list_text(self):
        """Test that 'in' operator requires a list for text fields."""
        func = get_operator_function(FieldType.STRING, "in")
        with pytest.raises((TypeError, ValueError), match=r"list|iterable|array"):
            func(SQL("field"), "not-a-list")

    def test_in_requires_list_numeric(self):
        """Test that 'in' operator requires a list for numeric fields."""
        func = get_operator_function(FieldType.INTEGER, "in")
        with pytest.raises((TypeError, ValueError)):
            func(SQL("field"), 42)  # single value instead of list


class TestInvalidIPAddresses:
    """Test invalid IP address handling."""

    def test_invalid_ipv4_format(self):
        """Test malformed IPv4 address."""
        func = get_operator_function(FieldType.IP_ADDRESS, "eq")
        # PostgreSQL might handle validation, but test what our code does
        result = func(SQL("ip_address"), "999.999.999.999")
        # Either should raise, or pass through and let PostgreSQL handle it
        assert "999.999.999.999" in str(result)

    def test_invalid_ipv6_format(self):
        """Test malformed IPv6 address."""
        func = get_operator_function(FieldType.IP_ADDRESS, "eq")
        result = func(SQL("ip_address"), "gggg::1")
        assert "gggg::1" in str(result)  # Pass through to PostgreSQL


class TestInvalidDates:
    """Test invalid date handling."""

    def test_invalid_date_format_daterange(self):
        """Test malformed date string for daterange."""
        func = get_operator_function(FieldType.DATE_RANGE, "eq")
        result = func(SQL("period"), "[invalid-date,2024-12-31]")
        # Pass through to PostgreSQL or raise
        assert "invalid-date" in str(result)

    def test_invalid_range_format(self):
        """Test malformed range format."""
        func = get_operator_function(FieldType.DATE_RANGE, "eq")
        result = func(SQL("period"), "not-a-range")
        assert "not-a-range" in str(result)


class TestNullHandling:
    """Test NULL value handling across strategies."""

    def test_null_numeric(self):
        """Test NULL with numeric strategy."""
        func = get_operator_function(FieldType.INTEGER, "eq")
        result = func(SQL("value"), None)
        # NULL is passed through as literal, not converted to IS NULL
        assert "None" in str(result) or "NULL" in str(result)

    def test_null_text(self):
        """Test NULL with text strategy."""
        func = get_operator_function(FieldType.STRING, "eq")
        result = func(SQL("message"), None)
        # NULL is passed through as literal, not converted to IS NULL
        assert "None" in str(result) or "NULL" in str(result)

    def test_null_boolean(self):
        """Test NULL with boolean strategy."""
        func = get_operator_function(FieldType.BOOLEAN, "eq")
        result = func(SQL("active"), None)
        # NULL is passed through as literal, not converted to IS NULL
        assert "None" in str(result) or "NULL" in str(result)

    def test_isnull_operator(self):
        """Test proper NULL checking with isnull operator."""
        func = get_operator_function(FieldType.ANY, "isnull")
        result = func(SQL("value"), True)
        assert "IS NULL" in str(result).upper()


class TestEdgeCaseValues:
    """Test edge case values."""

    def test_empty_string(self):
        """Test empty string value."""
        func = get_operator_function(FieldType.STRING, "eq")
        result = func(SQL("message"), "")
        assert '""' in str(result) or "''" in str(result)

    def test_zero_value(self):
        """Test zero numeric value."""
        func = get_operator_function(FieldType.INTEGER, "eq")
        result = func(SQL("count"), 0)
        assert "0" in str(result)

    def test_negative_value(self):
        """Test negative numeric value."""
        func = get_operator_function(FieldType.INTEGER, "eq")
        result = func(SQL("temperature"), -100)
        assert "-100" in str(result)

    def test_very_large_number(self):
        """Test very large number."""
        func = get_operator_function(FieldType.INTEGER, "eq")
        large = 10**18
        result = func(SQL("bigint_field"), large)
        assert str(large) in str(result)


class TestUnsupportedOperators:
    """Test operators not supported for certain field types."""

    def test_regex_on_numeric(self):
        """Test that regex operators don't exist for numeric fields."""
        with pytest.raises(ValueError):
            get_operator_function(FieldType.INTEGER, "matches")

    def test_daterange_on_text(self):
        """Test that daterange operators don't exist for text fields."""
        with pytest.raises(ValueError):
            get_operator_function(FieldType.STRING, "overlaps")

    def test_network_on_text(self):
        """Test that network operators don't exist for text fields."""
        with pytest.raises(ValueError):
            get_operator_function(FieldType.STRING, "isPrivate")


class TestOperatorCaseSensitivity:
    """Test operator name case sensitivity."""

    def test_operator_case_sensitive(self):
        """Test that operator names are case-sensitive."""
        # This should fail since operators are case-sensitive
        with pytest.raises(ValueError):
            get_operator_function(FieldType.STRING, "EQ")

    def test_mixed_case_operators_fail(self):
        """Test that mixed case operator names fail."""
        with pytest.raises(ValueError):
            get_operator_function(FieldType.STRING, "Contains")
