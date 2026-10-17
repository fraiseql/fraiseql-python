"""Test GraphQL field resolution for nested arrays in JSONB data.

This test reproduces the issue where nested arrays of objects return null
in GraphQL queries despite having valid data in the database JSONB column.
"""

import uuid
from typing import Optional

import pytest

import fraiseql

pytestmark = [pytest.mark.integration, pytest.mark.database]


@fraiseql.type
class PrintServer:
    """A print server device."""

    id: uuid.UUID
    identifier: str
    hostname: str
    operating_system: Optional[str] = None


@fraiseql.type
class DnsServer:
    """A DNS server configuration."""

    id: uuid.UUID
    identifier: str
    ip_address: str


@fraiseql.type
class NetworkConfiguration:
    """Network configuration with nested objects and arrays."""

    id: uuid.UUID
    identifier: str

    # Single nested object - should work
    dns1: Optional[DnsServer] = None

    # Array of nested objects - currently broken
    print_servers: Optional[list[PrintServer]] = None


@pytest.mark.unit
class TestNestedArrayFieldResolution:
    """Test GraphQL field resolution for nested arrays."""

    def test_single_nested_object_works(self) -> None:
        """Verify that single nested objects work as expected."""
        # Sample data that would come from JSONB
        data = {
            "id": "01436121-0000-0000-0000-000000000010",
            "identifier": "network-config-001",
            "dns1": {
                "id": "01431121-0000-0000-0000-000000000001",
                "identifier": "primary-dns-server",
                "ipAddress": "120.0.0.1",
            },
            "printServers": [
                {
                    "id": "01433121-0000-0000-0000-000000000002",
                    "identifier": "PrintServer-002",
                    "hostname": "printserver02.local",
                    "operatingSystem": "Windows Server 2016",
                },
                {
                    "id": "01433121-0000-0000-0000-000000000003",
                    "identifier": "PrintServer-003",
                    "hostname": "printserver03.local",
                    "operatingSystem": "Windows Server 2019",
                },
            ],
        }

        # Create instance using from_dict (this should work)
        config = NetworkConfiguration.from_dict(data)

        # Single nested object should work
        assert config.dns1 is not None
        assert isinstance(config.dns1, DnsServer)
        assert config.dns1.identifier == "primary-dns-server"

        # Nested array should work too
        assert config.print_servers is not None
        assert len(config.print_servers) == 2
        assert all(isinstance(server, PrintServer) for server in config.print_servers)
        assert config.print_servers[0].hostname == "printserver02.local"

    def test_field_resolver_handles_nested_arrays(self) -> None:
        """Test that GraphQL field resolvers handle nested arrays correctly.

        This reproduces the exact bug: when objects have raw dict arrays,
        the field resolver fails to convert them to typed objects if the
        field_type doesn't have __args__ properly accessible.
        """

        # Create a mock object that simulates what comes from database
        # with raw dictionaries in the array (not converted yet)
        class MockNetworkConfig:
            def __init__(self) -> None:
                self.id = uuid.UUID("01436121-0000-0000-0000-000000000010")
                self.identifier = "network-config-001"
                self.dns1 = DnsServer(
                    id=uuid.UUID("01431121-0000-0000-0000-000000000001"),
                    identifier="primary-dns-server",
                    ip_address="120.0.0.1",
                )
                # This is the key issue: raw dict array from JSONB
                self.print_servers = [
                    {
                        "id": "01433121-0000-0000-0000-000000000002",
                        "identifier": "PrintServer-002",
                        "hostname": "printserver02.local",
                        "operatingSystem": "Windows Server 2016",
                    }
                ]

        config = MockNetworkConfig()

        # Now simulate what happens during GraphQL field resolution
        from fraiseql.core.graphql_type import convert_type_to_graphql_output

        # Get the GraphQL type
        gql_type = convert_type_to_graphql_output(NetworkConfiguration)

        # Extract field resolver for printServers
        print_servers_field = gql_type.fields["printServers"]
        resolver = print_servers_field.resolve

        # Call the resolver (this is what GraphQL does)
        class MockInfo:
            pass

        mock_info = MockInfo()

        # Test nested array resolution with raw dicts
        result = resolver(config, mock_info)

        # The issue: field resolver should convert dict items to PrintServer objects
        assert result is not None, "Field resolver should return nested array, not None"
        assert len(result) == 1

        # This is the critical assertion that will FAIL:
        # The result[0] should be a PrintServer object, not a dict
        assert isinstance(result[0], PrintServer), f"Expected PrintServer, got {type(result[0])}"
        assert result[0].hostname == "printserver02.local"

    def test_empty_nested_array_handling(self) -> None:
        """Test that empty arrays are handled correctly."""
        data = {
            "id": "01436121-0000-0000-0000-000000000010",
            "identifier": "network-config-002",
            "printServers": [],  # Empty array
        }

        config = NetworkConfiguration.from_dict(data)

        # from_dict should handle empty arrays
        assert config.print_servers == []

        # Field resolver should also handle empty arrays
        from fraiseql.core.graphql_type import convert_type_to_graphql_output

        gql_type = convert_type_to_graphql_output(NetworkConfiguration)
        print_servers_field = gql_type.fields["printServers"]
        resolver = print_servers_field.resolve

        class MockInfo:
            pass

        result = resolver(config, MockInfo())
        assert result == []  # Should return empty array, not None

    def test_null_nested_array_handling(self) -> None:
        """Test that null arrays are handled correctly."""
        data = {
            "id": "01436121-0000-0000-0000-000000000010",
            "identifier": "network-config-003",
            "printServers": None,  # Null array
        }

        config = NetworkConfiguration.from_dict(data)

        # from_dict should handle None
        assert config.print_servers is None

        # Field resolver should also handle None
        from fraiseql.core.graphql_type import convert_type_to_graphql_output

        gql_type = convert_type_to_graphql_output(NetworkConfiguration)
        print_servers_field = gql_type.fields["printServers"]
        resolver = print_servers_field.resolve

        class MockInfo:
            pass

        result = resolver(config, MockInfo())
        assert result is None  # Should return None

    def test_deeply_nested_arrays(self) -> None:
        """Test arrays within nested objects."""

        @fraiseql.type
        class Printer:
            id: uuid.UUID
            name: str

        @fraiseql.type
        class Department:
            id: uuid.UUID
            name: str
            printers: list[Printer]

        @fraiseql.type
        class Organization:
            id: uuid.UUID
            name: str
            departments: list[Department]

        data = {
            "id": "01436121-0000-0000-0000-000000000010",
            "name": "Tech Corp",
            "departments": [
                {
                    "id": "01436121-0000-0000-0000-000000000011",
                    "name": "Engineering",
                    "printers": [
                        {"id": "01436121-0000-0000-0000-000000000012", "name": "Printer 1"},
                        {"id": "01436121-0000-0000-0000-000000000013", "name": "Printer 2"},
                    ],
                }
            ],
        }

        Organization.from_dict(data)

        # Test field resolution for deeply nested arrays
        from fraiseql.core.graphql_type import convert_type_to_graphql_output

        gql_type = convert_type_to_graphql_output(Organization)

        departments_field = gql_type.fields["departments"]
        departments_resolver = departments_field.resolve

        class MockOrg:
            def __init__(self) -> None:
                self.id = uuid.UUID("01436121-0000-0000-0000-000000000010")
                self.name = "Tech Corp"
                self.departments = [
                    {
                        "id": "01436121-0000-0000-0000-000000000011",
                        "name": "Engineering",
                        "printers": [
                            {"id": "01436121-0000-0000-0000-000000000012", "name": "Printer 1"},
                            {"id": "01436121-0000-0000-0000-000000000013", "name": "Printer 2"},
                        ],
                    }
                ]

        mock_org = MockOrg()

        class MockInfo:
            pass

        result = departments_resolver(mock_org, MockInfo())

        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], Department)
        assert result[0].name == "Engineering"

        # The nested printers array should also be converted
        assert isinstance(result[0].printers, list)
        assert len(result[0].printers) == 2
        assert all(isinstance(p, Printer) for p in result[0].printers)
        assert result[0].printers[0].name == "Printer 1"

    def test_mixed_array_content(self) -> None:
        """Test arrays with mixed content (some dicts, some already converted)."""

        @fraiseql.type
        class Device:
            id: uuid.UUID
            name: str

        @fraiseql.type
        class Container:
            id: uuid.UUID
            devices: list[Device]

        # Create a container with mixed content
        class MockContainer:
            def __init__(self) -> None:
                self.id = uuid.UUID("01436121-0000-0000-0000-000000000010")
                self.devices = [
                    # Already converted object
                    Device(id=uuid.UUID("01436121-0000-0000-0000-000000000011"), name="Device 1"),
                    # Raw dict that needs conversion
                    {"id": "01436121-0000-0000-0000-000000000012", "name": "Device 2"},
                    # Another raw dict
                    {"id": "01436121-0000-0000-0000-000000000013", "name": "Device 3"},
                ]

        mock_container = MockContainer()

        from fraiseql.core.graphql_type import convert_type_to_graphql_output

        gql_type = convert_type_to_graphql_output(Container)

        devices_field = gql_type.fields["devices"]
        devices_resolver = devices_field.resolve

        class MockInfo:
            pass

        result = devices_resolver(mock_container, MockInfo())

        assert result is not None
        assert len(result) == 3

        # All items should be Device objects now
        assert all(isinstance(device, Device) for device in result)
        assert result[0].name == "Device 1"  # Was already converted
        assert result[1].name == "Device 2"  # Was dict, now converted
        assert result[2].name == "Device 3"  # Was dict, now converted

    def test_non_fraiseql_array_items(self) -> None:
        """Test arrays with non-FraiseQL items (should remain unchanged)."""

        @fraiseql.type
        class SimpleContainer:
            id: uuid.UUID
            strings: list[str]
            numbers: list[int]
            raw_data: list[dict]  # Not typed to FraiseQL objects

        class MockContainer:
            def __init__(self) -> None:
                self.id = uuid.UUID("01436121-0000-0000-0000-000000000010")
                self.strings = ["hello", "world"]
                self.numbers = [1, 2, 3]
                self.raw_data = [{"key": "value"}, {"another": "dict"}]

        mock_container = MockContainer()

        from fraiseql.core.graphql_type import convert_type_to_graphql_output

        gql_type = convert_type_to_graphql_output(SimpleContainer)

        # Test strings (should remain unchanged)
        strings_field = gql_type.fields["strings"]
        strings_resolver = strings_field.resolve
        strings_result = strings_resolver(mock_container, type("MockInfo", (), {})())

        assert strings_result == ["hello", "world"]
        assert all(isinstance(s, str) for s in strings_result)

        # Test numbers (should remain unchanged)
        numbers_field = gql_type.fields["numbers"]
        numbers_resolver = numbers_field.resolve
        numbers_result = numbers_resolver(mock_container, type("MockInfo", (), {})())

        assert numbers_result == [1, 2, 3]
        assert all(isinstance(n, int) for n in numbers_result)

        # Test raw dicts (should remain as dicts since not FraiseQL types)
        raw_data_field = gql_type.fields["rawData"]
        raw_data_resolver = raw_data_field.resolve
        raw_data_result = raw_data_resolver(mock_container, type("MockInfo", (), {})())

        assert raw_data_result == [{"key": "value"}, {"another": "dict"}]
        assert all(isinstance(d, dict) for d in raw_data_result)
