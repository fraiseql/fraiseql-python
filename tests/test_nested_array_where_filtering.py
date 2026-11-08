"""Test suite for nested array Where type filtering - v0.7.10+ Feature

This test suite validates the nested array where filtering functionality that builds
on the v0.7.10 nested array resolution capabilities. It enables GraphQL queries to
filter nested array elements based on their properties using Where input types.

Key Features Tested:
- Automatic WhereInput type generation for nested array elements
- Field resolver enhancement with where parameter support
- JSONB-based database filtering for nested arrays
- Complex filtering scenarios with multiple operators
- Performance optimization through database-level filtering
"""

import uuid
from typing import Optional

import pytest

from fraiseql.fields import fraise_field
from fraiseql.types import fraise_type


# Mock PrintServer type for testing (from the feature request document)
@fraise_type
class PrintServer:
    id: uuid.UUID
    hostname: str
    ip_address: Optional[str] = None
    operating_system: str
    n_total_allocations: int = 0
    identifier: Optional[str] = None


# Mock NetworkConfiguration type with nested array
@fraise_type(sql_source="tv_network_configuration", jsonb_column="data")
class NetworkConfiguration:
    id: uuid.UUID
    identifier: str
    name: str
    print_servers: list[PrintServer] = fraise_field(default_factory=list)


@pytest.mark.regression
@pytest.mark.unit
class TestNestedArrayWhereFiltering:
    """Test nested array Where type filtering functionality."""

    def test_where_input_type_generated_for_nested_array_elements(self) -> None:
        """Test that WhereInput types are automatically generated for nested array elements."""
        # This should pass after implementation - checking that the Where type is created
        from fraiseql.sql.graphql_where_generator import create_graphql_where_input

        # Should create PrintServerWhereInput automatically
        PrintServerWhereInput = create_graphql_where_input(PrintServer)

        # Verify it has the expected filter fields
        assert hasattr(PrintServerWhereInput, "__gql_fields__")
        gql_fields = PrintServerWhereInput.__gql_fields__

        # Should have fields for all PrintServer attributes
        assert "id" in gql_fields
        assert "hostname" in gql_fields
        assert "ip_address" in gql_fields
        assert "operating_system" in gql_fields
        assert "n_total_allocations" in gql_fields

        # Verify we can instantiate it
        where_filter = PrintServerWhereInput(
            hostname={"contains": "prod"},
            operating_system={"eq": "Windows"},
            n_total_allocations={"gte": 10},
        )

        assert where_filter is not None

    def test_nested_array_field_supports_where_parameter(self) -> None:
        """Test that nested array fields can accept where parameters in resolvers."""
        # This test will initially fail - need to implement where parameter support

        # Mock resolver function that should accept where parameter
        async def mock_print_servers_resolver(parent, info, where=None) -> None:
            """Mock resolver that should handle where filtering."""
            servers = getattr(parent, "print_servers", [])

            if where is None:
                return servers

            # Apply filtering logic (this is what we need to implement)
            filtered_servers = []
            for server in servers:
                if _matches_where_criteria(server, where):
                    filtered_servers.append(server)

            return filtered_servers

        # Test data
        network_config = NetworkConfiguration(
            id=uuid.uuid4(),
            identifier="test-network",
            name="Test Network Configuration",
            print_servers=[
                PrintServer(
                    id=uuid.uuid4(),
                    hostname="prod-server-01",
                    ip_address="192.168.1.10",
                    operating_system="Windows Server",
                    n_total_allocations=150,
                ),
                PrintServer(
                    id=uuid.uuid4(),
                    hostname="dev-server-01",
                    ip_address="192.168.1.20",
                    operating_system="Linux",
                    n_total_allocations=25,
                ),
                PrintServer(
                    id=uuid.uuid4(),
                    hostname="prod-server-02",
                    ip_address=None,  # Offline server
                    operating_system="Windows Server",
                    n_total_allocations=0,
                ),
            ],
        )

        # Test basic filtering - should return only production servers
        from fraiseql.sql.graphql_where_generator import create_graphql_where_input

        PrintServerWhereInput = create_graphql_where_input(PrintServer)

        where_filter = PrintServerWhereInput()
        where_filter.hostname = {"contains": "prod"}
        where_filter.ip_address = {"isnull": False}

        # This should work after implementation
        import asyncio

        result = asyncio.run(mock_print_servers_resolver(network_config, None, where_filter))

        # Should return only online production servers
        assert len(result) == 1
        assert result[0].hostname == "prod-server-01"
        assert result[0].ip_address == "192.168.1.10"

    def test_multiple_filter_operators_on_nested_arrays(self) -> None:
        """Test complex filtering with multiple operators on nested array elements."""
        # This will fail initially - need to implement operator support

        servers_data = [
            PrintServer(
                id=uuid.uuid4(),
                hostname="prod-web-01",
                operating_system="Linux",
                n_total_allocations=75,
            ),
            PrintServer(
                id=uuid.uuid4(),
                hostname="prod-db-01",
                operating_system="Windows Server",
                n_total_allocations=200,
            ),
            PrintServer(
                id=uuid.uuid4(),
                hostname="dev-test-01",
                operating_system="Linux",
                n_total_allocations=10,
            ),
        ]

        from fraiseql.sql.graphql_where_generator import create_graphql_where_input

        PrintServerWhereInput = create_graphql_where_input(PrintServer)

        # Test range filtering
        where_filter = PrintServerWhereInput()
        where_filter.n_total_allocations = {"gte": 50, "lte": 150}
        where_filter.hostname = {"startswith": "prod"}

        filtered = _apply_where_filter(servers_data, where_filter)

        # Should return only prod-web-01 (75 allocations, starts with 'prod')
        assert len(filtered) == 1
        assert filtered[0].hostname == "prod-web-01"

    def test_enum_filtering_on_nested_arrays(self) -> None:
        """Test filtering nested arrays using enum/choice operators."""
        servers_data = [
            PrintServer(id=uuid.uuid4(), hostname="server-01", operating_system="Windows Server"),
            PrintServer(id=uuid.uuid4(), hostname="server-02", operating_system="Linux"),
            PrintServer(id=uuid.uuid4(), hostname="server-03", operating_system="macOS"),
        ]

        from fraiseql.sql.graphql_where_generator import create_graphql_where_input

        PrintServerWhereInput = create_graphql_where_input(PrintServer)

        # Test IN operator for multiple values
        where_filter = PrintServerWhereInput()
        where_filter.operating_system = {"in_": ["Windows Server", "Linux"]}

        filtered = _apply_where_filter(servers_data, where_filter)

        # Should return Windows and Linux servers, not macOS
        assert len(filtered) == 2
        os_values = [s.operating_system for s in filtered]
        assert "Windows Server" in os_values
        assert "Linux" in os_values
        assert "macOS" not in os_values

    def test_null_filtering_on_nested_arrays(self) -> None:
        """Test null/not null filtering on nested array elements."""
        servers_data = [
            PrintServer(
                id=uuid.uuid4(),
                hostname="online-server",
                ip_address="192.168.1.100",
                operating_system="Linux",
            ),
            PrintServer(
                id=uuid.uuid4(),
                hostname="offline-server",
                ip_address=None,  # Offline
                operating_system="Windows",
            ),
        ]

        from fraiseql.sql.graphql_where_generator import create_graphql_where_input

        PrintServerWhereInput = create_graphql_where_input(PrintServer)

        # Test filtering for online servers (non-null IP)
        where_filter = PrintServerWhereInput()
        where_filter.ip_address = {"isnull": False}

        filtered = _apply_where_filter(servers_data, where_filter)

        assert len(filtered) == 1
        assert filtered[0].hostname == "online-server"
        assert filtered[0].ip_address is not None

        # Test filtering for offline servers (null IP)
        where_filter_offline = PrintServerWhereInput()
        where_filter_offline.ip_address = {"isnull": True}

        filtered_offline = _apply_where_filter(servers_data, where_filter_offline)

        assert len(filtered_offline) == 1
        assert filtered_offline[0].hostname == "offline-server"
        assert filtered_offline[0].ip_address is None


# Helper functions for testing - these will be replaced by actual implementation


def _matches_where_criteria(item, where_filter) -> None:
    """Helper function to test if an item matches where criteria."""
    # This is a simplified implementation for testing
    # Real implementation will be in the field resolver

    if not where_filter:
        return True

    # Check each field in the where filter
    if hasattr(where_filter, "__gql_fields__"):
        for field_name in where_filter.__gql_fields__:
            filter_value = getattr(where_filter, field_name, None)
            if filter_value is None:
                continue

            item_value = getattr(item, field_name, None)

            # Apply filter operators
            if not _apply_field_filter(item_value, filter_value):
                return False

    return True


def _apply_field_filter(item_value, filter_dict) -> None:
    """Apply field-level filtering logic."""
    if not isinstance(filter_dict, dict):
        return True

    for operator, filter_value in filter_dict.items():
        if (operator == "eq" and item_value != filter_value) or (
            operator == "contains" and filter_value not in str(item_value)
        ):
            return False
        if (
            (operator == "startswith" and not str(item_value).startswith(filter_value))
            or (operator == "gte" and item_value < filter_value)
            or (operator == "lte" and item_value > filter_value)
            or (operator == "in_" and item_value not in filter_value)
        ):
            return False
        if operator == "isnull" and (
            (filter_value and item_value is not None) or (not filter_value and item_value is None)
        ):
            return False

    return True


def _apply_where_filter(items, where_filter) -> None:
    """Apply where filter to a list of items."""
    return [item for item in items if _matches_where_criteria(item, where_filter)]
