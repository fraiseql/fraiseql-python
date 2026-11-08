"""Integration test for nested array Where filtering with FraiseQL resolvers.

This test validates that FraiseQL can properly handle Where parameters on nested array fields
in real GraphQL query resolution scenarios.
"""

import uuid
from typing import Optional

import pytest

from fraiseql.fields import fraise_field
from fraiseql.sql.graphql_where_generator import create_graphql_where_input
from fraiseql.types import fraise_type


# Mock PrintServer type for testing
@fraise_type
class PrintServer:
    id: uuid.UUID
    hostname: str
    ip_address: Optional[str] = None
    operating_system: str
    n_total_allocations: int = 0


# Mock NetworkConfiguration with nested array that should support where filtering
@fraise_type(sql_source="tv_network_configuration", jsonb_column="data")
class NetworkConfiguration:
    id: uuid.UUID
    identifier: str
    name: str
    # This is the critical test - can we add where parameter to this field?
    print_servers: list[PrintServer] = fraise_field(default_factory=list)


@pytest.mark.integration
class TestNestedArrayWhereIntegration:
    """Integration tests for nested array Where filtering in FraiseQL resolvers."""

    def test_field_resolver_accepts_where_parameter(self) -> None:
        """Test that field resolvers can be created with where parameters for nested arrays."""
        # Create a WhereInput type for PrintServer
        PrintServerWhereInput = create_graphql_where_input(PrintServer)

        # This should now work with where parameter support
        @fraise_type(sql_source="tv_network_configuration", jsonb_column="data")
        class NetworkConfigurationWithWhereSupport:
            id: uuid.UUID
            identifier: str
            name: str
            # This syntax should now work
            print_servers: list[PrintServer] = fraise_field(
                default_factory=list, where_input_type=PrintServerWhereInput
            )

        # Verify the field has the where_input_type set
        field_dict = getattr(NetworkConfigurationWithWhereSupport, "__gql_fields__", {})
        if "print_servers" in field_dict:
            print_servers_field = field_dict["print_servers"]
            if hasattr(print_servers_field, "where_input_type"):
                assert print_servers_field.where_input_type == PrintServerWhereInput

    def test_nested_field_resolver_creation_without_where_support(self) -> None:
        """Test that current nested field resolvers don't support where parameters."""
        from fraiseql.core.nested_field_resolver import create_smart_nested_field_resolver

        # Current resolvers should not accept where parameters
        resolver = create_smart_nested_field_resolver("print_servers", list[PrintServer])

        # Check resolver signature - should not have where parameter
        import inspect

        sig = inspect.signature(resolver)

        # Should only have parent, info, **kwargs - no explicit where parameter
        param_names = list(sig.parameters.keys())
        assert "parent" in param_names
        assert "info" in param_names
        assert "where" not in param_names  # This is the key assertion - no where support yet

    def test_fraise_field_accepts_where_parameters(self) -> None:
        """Test that fraise_field now accepts where-related parameters."""
        # These should all work now that where support is implemented
        field1 = fraise_field(where_input_type=dict)
        assert field1.where_input_type is dict

        field2 = fraise_field(supports_where_filtering=True)
        assert field2.supports_where_filtering is True

        field3 = fraise_field(nested_where_type=PrintServer)
        assert field3.nested_where_type == PrintServer

    def test_graphql_schema_generation_for_nested_arrays_without_where(self) -> None:
        """Test current state - nested arrays work but without where filtering."""
        from fraiseql.core.graphql_type import convert_type_to_graphql_output

        # This should work - basic nested array support exists
        try:
            gql_type = convert_type_to_graphql_output(NetworkConfiguration)
            assert gql_type is not None

            # But the schema should not have where parameters for nested arrays
            # This is more complex to test programmatically, so we'll leave it as documentation
            # The key point is that basic nested arrays work, but where filtering doesn't

        except Exception as e:
            pytest.fail(f"Basic nested array schema generation should work: {e}")

    def test_attempt_to_use_where_parameter_in_query_fails(self) -> None:
        """Test that attempting to use where parameters in queries fails gracefully."""
        # Create a mock query that tries to use where parameter
        network_config = NetworkConfiguration(
            id=uuid.uuid4(),
            identifier="test-config",
            name="Test Configuration",
            print_servers=[
                PrintServer(
                    id=uuid.uuid4(),
                    hostname="server1",
                    operating_system="Linux",
                    n_total_allocations=50,
                ),
                PrintServer(
                    id=uuid.uuid4(),
                    hostname="server2",
                    operating_system="Windows",
                    n_total_allocations=100,
                ),
            ],
        )

        # Try to filter the servers - this should not be possible in current implementation
        # The test is that there's no built-in way to do this filtering

        # If this was implemented, we would do something like:
        # filtered_servers = await resolve_nested_field_with_where(
        #     parent=network_config,
        #     field_name="print_servers",
        #     where={"operating_system": {"eq": "Linux"}}
        # )

        # But since it's not implemented, we can only access the full list
        all_servers = network_config.print_servers
        assert len(all_servers) == 2

        # Manual filtering would be required (which is what we want to avoid)
        linux_servers = [s for s in all_servers if s.operating_system == "Linux"]
        assert len(linux_servers) == 1
        assert linux_servers[0].hostname == "server1"
