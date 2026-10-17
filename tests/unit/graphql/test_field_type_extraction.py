"""Tests for GraphQL field type extraction functionality.

This test suite verifies that field type information is properly extracted
from GraphQL context and propagated to SQL operator strategies, particularly
for network types like IpAddress and MacAddress.
"""

from unittest.mock import Mock

import pytest

from fraiseql.graphql.field_type_extraction import (
    _camel_to_snake,
    _extract_from_field_name_heuristics,
    enhance_type_hints_with_graphql_context,
    extract_field_type_from_graphql_info,
)
from fraiseql.types import IpAddress, MacAddress
from tests.helpers.sql_rendering import render_sql_for_testing


class TestFieldTypeExtraction:
    """Test GraphQL field type extraction utilities."""

    def test_extract_ip_address_from_field_name_heuristics(self) -> None:
        """Test IP address field type detection from field names."""
        ip_field_names = [
            "ipAddress",
            "ip_address",
            "serverIp",
            "gateway_ip",
            "host",
        ]

        for field_name in ip_field_names:
            field_type = _extract_from_field_name_heuristics(field_name)
            assert field_type == IpAddress, f"Should detect IpAddress for field: {field_name}"

    def test_extract_mac_address_from_field_name_heuristics(self) -> None:
        """Test MAC address field type detection from field names."""
        mac_field_names = [
            "macAddress",
            "mac_address",
            "mac",
            "hardware_address",
        ]

        for field_name in mac_field_names:
            field_type = _extract_from_field_name_heuristics(field_name)
            assert field_type == MacAddress, f"Should detect MacAddress for field: {field_name}"

    def test_extract_no_type_for_generic_fields(self) -> None:
        """Test that generic field names don't match network types."""
        generic_field_names = [
            "id",
            "name",
            "identifier",
            "description",
            "status",
            "created_at",
        ]

        for field_name in generic_field_names:
            field_type = _extract_from_field_name_heuristics(field_name)
            assert field_type is None, f"Should not detect network type for: {field_name}"

    def test_camel_to_snake_conversion(self) -> None:
        """Test camelCase to snake_case conversion."""
        test_cases = [
            ("ipAddress", "ip_address"),
            ("macAddress", "mac_address"),
            ("serverId", "server_id"),
            ("createdAt", "created_at"),
            ("HTTPSProxy", "https_proxy"),
            ("simpleField", "simple_field"),
        ]

        for camel_case, expected_snake_case in test_cases:
            result = _camel_to_snake(camel_case)
            assert result == expected_snake_case, f"Expected {expected_snake_case}, got {result}"

    def test_extract_field_type_from_graphql_info_mock(self) -> None:
        """Test field type extraction with mock GraphQL info."""
        # Mock GraphQL info
        mock_info = Mock()
        mock_info.field_definition = None
        mock_info.parent_type = None

        # Should fall back to heuristics
        field_type = extract_field_type_from_graphql_info(mock_info, "ipAddress")
        assert field_type == IpAddress

        field_type = extract_field_type_from_graphql_info(mock_info, "macAddress")
        assert field_type == MacAddress

        field_type = extract_field_type_from_graphql_info(mock_info, "identifier")
        assert field_type is None

    def test_enhance_type_hints_with_graphql_context(self) -> None:
        """Test enhancement of type hints with GraphQL context."""
        # Initial type hints (incomplete)
        initial_hints = {
            "id": int,
            "name": str,
        }

        # Mock GraphQL info
        mock_info = Mock()
        mock_info.field_definition = None

        # Fields to extract types for
        field_names = ["id", "name", "ipAddress", "macAddress"]

        # Enhance with GraphQL context
        enhanced_hints = enhance_type_hints_with_graphql_context(
            initial_hints, mock_info, field_names
        )

        # Should preserve existing hints
        assert enhanced_hints["id"] is int
        assert enhanced_hints["name"] is str

        # Should add extracted types
        assert enhanced_hints["ipAddress"] == IpAddress
        assert enhanced_hints["macAddress"] == MacAddress

    def test_enhance_type_hints_with_none_input(self) -> None:
        """Test enhancement works with None type_hints."""
        # Mock GraphQL info
        mock_info = Mock()
        mock_info.field_definition = None

        # Fields to extract types for
        field_names = ["ipAddress", "identifier"]

        # Enhance with None input
        enhanced_hints = enhance_type_hints_with_graphql_context(None, mock_info, field_names)

        # Should create new hints dict
        assert enhanced_hints["ipAddress"] == IpAddress
        assert "identifier" not in enhanced_hints  # No type detected

    def test_enhance_type_hints_overrides_generic_types(self) -> None:
        """Test that generic types are overridden with specific GraphQL-detected types."""
        # Initial type hints with generic types that should be overridden
        initial_hints = {
            "ipAddress": str,  # Generic string type - should be upgraded to IpAddress
            "name": str,  # Generic string type - no specific detection, stays str
        }

        # Mock GraphQL info
        mock_info = Mock()
        mock_info.field_definition = None

        # Fields to extract types for
        field_names = ["ipAddress", "name", "macAddress"]

        # Enhance with GraphQL context
        enhanced_hints = enhance_type_hints_with_graphql_context(
            initial_hints, mock_info, field_names
        )

        # Should override generic str with specific IpAddress for IP address fields
        assert enhanced_hints["ipAddress"] == IpAddress  # Upgraded from str
        assert enhanced_hints["name"] is str  # No specific type detected, stays str

        # Should add new extracted type
        assert enhanced_hints["macAddress"] == MacAddress


class TestNetworkFieldTypeIntegration:
    """Test integration of field type extraction with network operators."""

    def test_field_extraction_supports_network_operator_selection(self) -> None:
        """Test that extracted field types can be used for operator selection."""
        from fraiseql.sql.operators import get_default_registry as get_operator_registry

        # Mock GraphQL info
        mock_info = Mock()

        # Extract field type
        field_type = extract_field_type_from_graphql_info(mock_info, "ipAddress")
        assert field_type == IpAddress

        # Use extracted type for operator strategy selection
        registry = get_operator_registry()

        # Without field type - should get generic strategy
        strategy_no_type = registry.get_strategy("eq", field_type=None)
        assert strategy_no_type.__class__.__name__ == "ComparisonOperatorStrategy"

        # With extracted field type - should get network strategy
        strategy_with_type = registry.get_strategy("eq", field_type=field_type)
        assert strategy_with_type.__class__.__name__ == "NetworkOperatorStrategy"

    def test_field_type_enables_proper_sql_casting(self) -> None:
        """Test that field type extraction enables proper SQL casting."""
        from psycopg.sql import SQL

        from fraiseql.sql.operators import get_default_registry as get_operator_registry

        # Mock GraphQL info and extract field type
        mock_info = Mock()
        field_type = extract_field_type_from_graphql_info(mock_info, "ipAddress")

        # Generate SQL with field type
        registry = get_operator_registry()
        strategy = registry.get_strategy("eq", field_type=field_type)

        field_path = SQL("data->>'ipAddress'")
        sql = strategy.build_sql("eq", "8.8.8.8", field_path, field_type)
        sql_str = render_sql_for_testing(sql)

        # Should use proper network casting
        assert "::inet" in sql_str, f"Expected ::inet casting in SQL: {sql_str}"
        assert "NetworkOperatorStrategy" in strategy.__class__.__name__


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
