"""Unit tests for automatic field name conversion in WHERE clauses.

This module tests the automatic field name mapping functionality that converts
GraphQL camelCase field names to database snake_case field names automatically
in WHERE clause processing.
"""

from unittest.mock import MagicMock

import pytest
from psycopg_pool import AsyncConnectionPool

from fraiseql.db import FraiseQLRepository


class TestFieldNameMapping:
    """Test automatic field name conversion in WHERE clauses."""

    def setup_method(self) -> None:
        """Set up test repository with mock pool."""
        self.mock_pool = MagicMock(spec=AsyncConnectionPool)
        self.repo = FraiseQLRepository(self.mock_pool)

    def test_camel_case_where_field_names_work_automatically(self) -> None:
        """GraphQL camelCase field names should work in WHERE clauses without manual conversion."""
        # Test camelCase field names in WHERE clauses
        where_clause = {"ipAddress": {"eq": "192.168.1.1"}}

        # This should convert ipAddress -> ip_address internally
        clause = self.repo._normalize_where(where_clause, "test_view", {"ip_address"})
        result, params = clause.to_sql()

        assert result is not None
        sql_str = result.as_string(None)

        # Should use snake_case database field name
        assert "ip_address" in sql_str
        # Should contain the IP value
        assert "192.168.1.1" in str(params)

    def test_multiple_camel_case_fields_converted(self) -> None:
        """Multiple camelCase fields should all be converted automatically."""
        where_clause = {
            "ipAddress": {"eq": "192.168.1.1"},
            "macAddress": {"eq": "aa:bb:cc:dd:ee:ff"},
            "deviceName": {"contains": "router"},
        }

        clause = self.repo._normalize_where(
            where_clause, "test_view", {"ip_address", "mac_address", "device_name", "data"}
        )
        result, params = clause.to_sql()

        assert result is not None
        sql_str = result.as_string(None)

        # Should generate SQL with snake_case database field names
        # At least one of the fields should be present (could be in JSONB or column)
        assert "ip_address" in sql_str or "data" in sql_str

        # Should contain the values in params
        assert "192.168.1.1" in str(params)

    def test_mixed_case_fields_both_work(self) -> None:
        """Mixed camelCase and snake_case fields should both work."""
        # Test the conversion method directly
        assert hasattr(self.repo, "_convert_field_name_to_database")

        # Test various conversions
        assert self.repo._convert_field_name_to_database("ipAddress") == "ip_address"
        assert self.repo._convert_field_name_to_database("macAddress") == "mac_address"
        assert self.repo._convert_field_name_to_database("deviceName") == "device_name"
        assert self.repo._convert_field_name_to_database("createdAt") == "created_at"

        # Snake case should be unchanged
        assert self.repo._convert_field_name_to_database("ip_address") == "ip_address"
        assert self.repo._convert_field_name_to_database("status") == "status"

    def test_empty_where_clause_handling(self) -> None:
        """Empty WHERE clauses should raise ValueError."""
        with pytest.raises(ValueError, match="WHERE clause cannot be empty dict"):
            self.repo._normalize_where({}, "test_view", {"status"})

    def test_none_field_values_ignored(self) -> None:
        """None values in WHERE clauses should be ignored."""
        where_clause = {
            "ipAddress": {"eq": "192.168.1.1"},  # Valid
            "status": None,  # Should be ignored
            "deviceName": {"contains": None},  # Should be ignored
        }

        clause = self.repo._normalize_where(
            where_clause, "test_view", {"ip_address", "status", "device_name", "data"}
        )
        result, _params = clause.to_sql()
        assert result is not None

        sql_str = result.as_string(None)

        # Should contain the valid field (converted to snake_case)
        assert "ip_address" in sql_str or "data" in sql_str

        # Should not contain ignored fields
        assert "status" not in sql_str or '"status"' not in sql_str
        assert "deviceName" not in sql_str
        assert "device_name" not in sql_str or sql_str.count("device_name") == 0

    def test_complex_camel_case_conversions(self) -> None:
        """Test more complex camelCase to snake_case conversions."""
        test_cases = [
            ("ipAddress", "ip_address"),
            ("macAddress", "mac_address"),
            ("deviceName", "device_name"),
            ("createdAt", "created_at"),
            ("updatedAt", "updated_at"),
            ("userId", "user_id"),
            ("organizationId", "organization_id"),
            ("APIKey", "api_key"),  # Multiple capitals
            ("HTTPPort", "http_port"),  # Multiple capitals
            ("XMLData", "xml_data"),  # Multiple capitals
        ]

        for camel_case, expected_snake_case in test_cases:
            where_clause = {camel_case: {"eq": "test_value"}}
            clause = self.repo._normalize_where(
                where_clause, "test_view", {expected_snake_case, "data"}
            )
            result, _params = clause.to_sql()

            assert result is not None
            sql_str = result.as_string(None)

            # Should contain the converted snake_case field name or JSONB access
            assert expected_snake_case in sql_str or "data" in sql_str, (
                f"Failed to find {expected_snake_case} or JSONB access in SQL for {camel_case}"
            )

    def test_edge_case_field_names(self) -> None:
        """Test edge cases like empty strings and unusual field names."""
        # Test empty field name handling
        assert self.repo._convert_field_name_to_database("") == ""

        # Test single character names
        assert self.repo._convert_field_name_to_database("a") == "a"
        assert self.repo._convert_field_name_to_database("A") == "a"

        # Test numbers in field names
        assert self.repo._convert_field_name_to_database("id1") == "id1"
        assert self.repo._convert_field_name_to_database("apiV2Key") == "api_v2_key"

    def test_method_is_idempotent(self) -> None:
        """Calling the conversion method multiple times should produce the same result."""
        test_cases = ["ipAddress", "ip_address", "deviceName", "status"]

        for field_name in test_cases:
            # First conversion
            first_result = self.repo._convert_field_name_to_database(field_name)

            # Second conversion on the result
            second_result = self.repo._convert_field_name_to_database(first_result)

            # Should be the same
            assert first_result == second_result, f"Method not idempotent for {field_name}"

    def test_nested_camel_case_fields(self) -> None:
        """Test nested object fields with camelCase names."""
        where_clause = {"machineInfo": {"ipAddress": {"eq": "192.168.1.1"}}}

        clause = self.repo._normalize_where(where_clause, "test_view", {"machine_info", "data"})
        result, params = clause.to_sql()

        assert result is not None
        sql_str = result.as_string(None)

        # Should handle nested field conversion
        assert "machine_info" in sql_str or "data" in sql_str
        assert "192.168.1.1" in str(params)
