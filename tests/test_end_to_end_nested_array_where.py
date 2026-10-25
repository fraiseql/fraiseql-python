"""End-to-end integration test for nested array where filtering.

This test validates the complete functionality from FraiseQL type definition
through GraphQL schema generation to query execution.
"""

import asyncio
import uuid
from typing import Optional

import pytest

from fraiseql.fields import fraise_field
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.types import fraise_type


@fraise_type
class Device:
    id: uuid.UUID
    hostname: str
    ip_address: Optional[str] = None
    status: str = "active"
    priority: int = 1


@fraise_type(sql_source="v_network", jsonb_column="data")
class Network:
    id: uuid.UUID
    name: str
    # This field should support where filtering
    devices: list[Device] = fraise_field(
        default_factory=list,
        supports_where_filtering=True,
        nested_where_type=Device,
        description="Network devices with optional filtering",
    )


@pytest.mark.integration
@pytest.mark.usefixtures("clear_registry")
class TestEndToEndNestedArrayWhere:
    """End-to-end tests for the complete nested array where filtering feature."""

    def test_schema_generation_with_where_parameter(self) -> None:
        """Test that GraphQL schema is generated correctly with where parameter."""
        try:
            # Create a proper query function
            from fraiseql import query

            @query
            async def network(id: uuid.UUID) -> Network:
                """Get network by id."""
                return Network(id=id, name="Test Network", devices=[])

            @query
            async def networks() -> list[Network]:
                """Get all networks."""
                return []

            schema = build_fraiseql_schema(query_types=[network, networks])
            assert schema is not None

            # Verify the schema includes the Network type
            network_type = schema.get_type("Network")
            assert network_type is not None

            # Verify the devices field exists
            devices_field = network_type.fields.get("devices")
            assert devices_field is not None

            # Verify the where argument exists on the devices field
            where_arg = devices_field.args.get("where")
            assert where_arg is not None

            # The where argument should be a DeviceWhereInput type
            where_type_name = str(where_arg.type)
            assert "DeviceWhereInput" in where_type_name

        except Exception as e:
            pytest.fail(f"Schema generation should work with where filtering: {e}")

    def test_device_where_input_type_generated(self) -> None:
        """Test that DeviceWhereInput type is properly generated."""
        try:
            # Create a proper query function
            from fraiseql import query

            @query
            async def network(id: uuid.UUID) -> Network:
                """Get network by id."""
                return Network(id=id, name="Test Network", devices=[])

            @query
            async def networks() -> list[Network]:
                """Get all networks."""
                return []

            schema = build_fraiseql_schema(query_types=[network, networks])

            # Check if DeviceWhereInput type exists in schema
            device_where_input = schema.get_type("DeviceWhereInput")
            assert device_where_input is not None

            # Verify it has the expected fields
            expected_fields = ["id", "hostname", "ipAddress", "status", "priority"]
            for field_name in expected_fields:
                field = device_where_input.fields.get(field_name)
                assert field is not None, f"DeviceWhereInput should have {field_name} field"

        except Exception as e:
            pytest.fail(f"DeviceWhereInput type generation should work: {e}")

    def test_field_resolver_integration(self) -> None:
        """Test that the enhanced field resolver is properly integrated."""
        # Create a Network instance with devices
        network = Network(
            id=uuid.uuid4(),
            name="Test Network",
            devices=[
                Device(
                    id=uuid.uuid4(),
                    hostname="server-01",
                    ip_address="192.168.1.10",
                    status="active",
                    priority=1,
                ),
                Device(
                    id=uuid.uuid4(),
                    hostname="server-02",
                    ip_address="192.168.1.20",
                    status="maintenance",
                    priority=2,
                ),
                Device(
                    id=uuid.uuid4(),
                    hostname="server-03",
                    ip_address=None,
                    status="active",
                    priority=3,
                ),
            ],
        )

        # Verify the network has all devices initially
        assert len(network.devices) == 3

        # Test that we can access the field metadata
        network_fields = getattr(Network, "__gql_fields__", {})
        devices_field = network_fields.get("devices")

        if devices_field:
            assert hasattr(devices_field, "supports_where_filtering")
            assert devices_field.supports_where_filtering is True
            assert hasattr(devices_field, "nested_where_type")
            assert devices_field.nested_where_type == Device

    def test_where_filter_creation_and_usage(self) -> None:
        """Test creating and using where filters directly."""
        from fraiseql.core.nested_field_resolver import (
            create_nested_array_field_resolver_with_where,
        )
        from fraiseql.sql.graphql_where_generator import create_graphql_where_input

        # Create DeviceWhereInput type
        DeviceWhereInput = create_graphql_where_input(Device)

        # Create where filter for active devices
        where_filter = DeviceWhereInput()
        where_filter.status = {"eq": "active"}
        where_filter.ip_address = {"isnull": False}

        # Create test data
        network = Network(
            id=uuid.uuid4(),
            name="Filtered Network",
            devices=[
                Device(
                    id=uuid.uuid4(), hostname="active-1", status="active", ip_address="192.168.1.1"
                ),
                Device(
                    id=uuid.uuid4(), hostname="active-2", status="active", ip_address=None
                ),  # No IP
                Device(
                    id=uuid.uuid4(),
                    hostname="maintenance-1",
                    status="maintenance",
                    ip_address="192.168.1.2",
                ),
            ],
        )

        # Create resolver
        resolver = create_nested_array_field_resolver_with_where("devices", list[Device])

        # Test the resolver with where filter
        import asyncio

        result = asyncio.run(resolver(network, None, where=where_filter))

        # Should return only active devices with IP addresses
        assert len(result) == 1
        assert result[0].hostname == "active-1"
        assert result[0].status == "active"
        assert result[0].ip_address is not None

    def test_automatic_where_input_generation(self) -> None:
        """Test that where input types are generated automatically from nested_where_type."""
        # Create a field with nested_where_type instead of explicit where_input_type
        test_field = fraise_field(supports_where_filtering=True, nested_where_type=Device)

        # Verify the metadata is set correctly
        assert test_field.supports_where_filtering is True
        assert test_field.nested_where_type == Device
        assert test_field.where_input_type is None  # Should be generated automatically

    def test_complex_where_filtering_scenarios(self) -> None:
        """Test complex where filtering scenarios with multiple conditions."""
        from fraiseql.core.nested_field_resolver import (
            create_nested_array_field_resolver_with_where,
        )
        from fraiseql.sql.graphql_where_generator import create_graphql_where_input

        DeviceWhereInput = create_graphql_where_input(Device)

        # Create complex test data
        devices = [
            Device(
                id=uuid.uuid4(),
                hostname="web-01",
                status="active",
                priority=1,
                ip_address="192.168.1.10",
            ),
            Device(
                id=uuid.uuid4(),
                hostname="web-02",
                status="active",
                priority=2,
                ip_address="192.168.1.11",
            ),
            Device(
                id=uuid.uuid4(),
                hostname="db-01",
                status="maintenance",
                priority=1,
                ip_address="192.168.1.20",
            ),
            Device(id=uuid.uuid4(), hostname="db-02", status="active", priority=3, ip_address=None),
        ]

        network = Network(id=uuid.uuid4(), name="Complex Network", devices=devices)

        resolver = create_nested_array_field_resolver_with_where("devices", list[Device])

        # Test 1: Active devices with priority <= 2
        where1 = DeviceWhereInput()
        where1.status = {"eq": "active"}
        where1.priority = {"lte": 2}

        result1 = asyncio.run(resolver(network, None, where=where1))
        assert len(result1) == 2  # web-01, web-02
        hostnames1 = [d.hostname for d in result1]
        assert "web-01" in hostnames1
        assert "web-02" in hostnames1

        # Test 2: Devices with hostnames starting with "web"
        where2 = DeviceWhereInput()
        where2.hostname = {"startswith": "web"}

        result2 = asyncio.run(resolver(network, None, where=where2))
        assert len(result2) == 2  # web-01, web-02

        # Test 3: High priority devices (priority >= 3)
        where3 = DeviceWhereInput()
        where3.priority = {"gte": 3}

        result3 = asyncio.run(resolver(network, None, where=where3))
        assert len(result3) == 1  # db-02
        assert result3[0].hostname == "db-02"
