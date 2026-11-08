"""Test network address filtering operations for IP addresses and CIDR ranges.

This module tests the enhanced NetworkAddressFilter functionality added in v0.3.8,
which provides network-specific filtering operations like subnet matching,
IP range queries, and private/public network detection.
"""

from dataclasses import dataclass
from typing import get_type_hints

import pytest

from fraiseql.sql.graphql_where_generator import (
    NetworkAddressFilter,
    _get_filter_type_for_field,
    create_graphql_where_input,
)
from fraiseql.types import CIDR, IpAddress

pytestmark = pytest.mark.database


@dataclass
class NetworkDevice:
    """Test network device with IP address fields."""

    id: str
    name: str
    ip_address: IpAddress
    network: CIDR
    gateway: IpAddress


class TestNetworkAddressFilter:
    """Test enhanced NetworkAddressFilter functionality."""

    def test_filter_type_assignment(self) -> None:
        """Test that IP address types get NetworkAddressFilter."""
        type_hints = get_type_hints(NetworkDevice)

        # IP address fields should get NetworkAddressFilter
        assert _get_filter_type_for_field(type_hints["ip_address"]) == NetworkAddressFilter
        assert _get_filter_type_for_field(type_hints["network"]) == NetworkAddressFilter
        assert _get_filter_type_for_field(type_hints["gateway"]) == NetworkAddressFilter

    def test_basic_operators_available(self) -> None:
        """Test that basic operators are still available."""
        operators = [
            attr
            for attr in dir(NetworkAddressFilter)
            if not attr.startswith("_") and not callable(getattr(NetworkAddressFilter, attr))
        ]

        # Basic operators should be present
        basic_ops = ["eq", "neq", "in_", "nin", "isnull"]
        for op in basic_ops:
            assert op in operators, f"Basic operator '{op}' missing from NetworkAddressFilter"

    def test_network_operators_available(self) -> None:
        """Test that network-specific operators are available."""
        operators = [
            attr
            for attr in dir(NetworkAddressFilter)
            if not attr.startswith("_") and not callable(getattr(NetworkAddressFilter, attr))
        ]

        # Network-specific operators should be present
        network_ops = ["inSubnet", "inRange", "isPrivate", "isPublic", "isIPv4", "isIPv6"]
        for op in network_ops:
            assert op in operators, f"Network operator '{op}' missing from NetworkAddressFilter"

    def test_problematic_operators_excluded(self) -> None:
        """Test that problematic string operators are not present."""
        operators = [
            attr
            for attr in dir(NetworkAddressFilter)
            if not attr.startswith("_") and not callable(getattr(NetworkAddressFilter, attr))
        ]

        # These operators should not be present
        problematic_ops = ["contains", "startswith", "endswith"]
        for op in problematic_ops:
            assert op not in operators, (
                f"Problematic operator '{op}' should not be in NetworkAddressFilter"
            )


class TestIPAddressValidation:
    """Test IP address validation and parsing utilities."""

    def test_valid_ipv4_addresses(self) -> None:
        """Test validation of valid IPv4 addresses."""
        from fraiseql.sql.network_utils import is_ipv4, validate_ip_address

        valid_ipv4 = [
            "192.168.1.1",
            "10.0.0.1",
            "172.16.0.1",
            "8.8.8.8",
            "127.0.0.1",
            "0.0.0.0",
            "255.255.255.255",
        ]

        for ip in valid_ipv4:
            assert validate_ip_address(ip), f"Valid IPv4 address {ip} failed validation"
            assert is_ipv4(ip), f"IPv4 address {ip} not detected as IPv4"

    def test_valid_ipv6_addresses(self) -> None:
        """Test validation of valid IPv6 addresses."""
        from fraiseql.sql.network_utils import is_ipv6, validate_ip_address

        valid_ipv6 = [
            "2001:db8::1",
            "::1",
            "2001:0db8:85a3:0000:0000:8a2e:0370:7334",
            "2001:db8:85a3::8a2e:370:7334",
            "::ffff:192.0.2.1",  # IPv4-mapped IPv6
            "fe80::1%lo0",  # Link-local with zone
        ]

        for ip in valid_ipv6:
            assert validate_ip_address(ip), f"Valid IPv6 address {ip} failed validation"
            assert is_ipv6(ip), f"IPv6 address {ip} not detected as IPv6"

    def test_invalid_ip_addresses(self) -> None:
        """Test rejection of invalid IP addresses."""
        from fraiseql.sql.network_utils import validate_ip_address

        invalid_ips = [
            "256.1.1.1",  # IPv4 octet too large
            "192.168.1",  # Incomplete IPv4
            "192.168.1.1.1",  # Too many octets
            "not.an.ip.address",
            "",
            "192.168.1.-1",  # Negative octet
            "gggg::1",  # Invalid IPv6 hex
            "2001:db8::1::2",  # Multiple :: in IPv6
        ]

        for ip in invalid_ips:
            assert not validate_ip_address(ip), f"Invalid IP address {ip} passed validation"

    def test_private_network_detection(self) -> None:
        """Test detection of RFC 1918 private networks."""
        from fraiseql.sql.network_utils import is_private_ip

        private_ips = [
            "192.168.1.1",  # Class C private
            "192.168.0.1",  # Class C private
            "10.0.0.1",  # Class A private
            "10.255.255.254",  # Class A private
            "172.16.0.1",  # Class B private
            "172.31.255.254",  # Class B private
            "127.0.0.1",  # Loopback
            "169.254.1.1",  # Link-local
        ]

        for ip in private_ips:
            assert is_private_ip(ip), f"Private IP {ip} not detected as private"

        public_ips = [
            "8.8.8.8",  # Google DNS
            "1.1.1.1",  # Cloudflare DNS
            "208.67.222.222",  # OpenDNS
            "172.15.0.1",  # Just outside Class B private
            "172.32.0.1",  # Just outside Class B private
            "11.0.0.1",  # Just outside Class A private
        ]

        for ip in public_ips:
            assert not is_private_ip(ip), f"Public IP {ip} detected as private"

    def test_subnet_matching(self) -> None:
        """Test CIDR subnet matching."""
        from fraiseql.sql.network_utils import ip_in_subnet

        test_cases = [
            ("192.168.1.100", "192.168.1.0/24", True),
            ("192.168.1.255", "192.168.1.0/24", True),
            ("192.168.2.1", "192.168.1.0/24", False),
            ("10.0.0.1", "10.0.0.0/8", True),
            ("11.0.0.1", "10.0.0.0/8", False),
            ("172.16.1.1", "172.16.0.0/12", True),
            ("172.32.1.1", "172.16.0.0/12", False),
        ]

        for ip, subnet, expected in test_cases:
            result = ip_in_subnet(ip, subnet)
            assert result == expected, (
                f"ip_in_subnet({ip}, {subnet}) = {result}, expected {expected}"
            )

    def test_ip_range_matching(self) -> None:
        """Test IP range matching."""
        from fraiseql.sql.network_utils import ip_in_range

        test_cases = [
            ("192.168.1.100", "192.168.1.1", "192.168.1.200", True),
            ("192.168.1.1", "192.168.1.1", "192.168.1.200", True),  # Boundary
            ("192.168.1.200", "192.168.1.1", "192.168.1.200", True),  # Boundary
            ("192.168.1.201", "192.168.1.1", "192.168.1.200", False),
            ("192.168.0.255", "192.168.1.1", "192.168.1.200", False),
            ("10.0.0.1", "10.0.0.1", "10.0.0.255", True),
            ("10.0.1.1", "10.0.0.1", "10.0.0.255", False),
        ]

        for ip, start, end, expected in test_cases:
            result = ip_in_range(ip, start, end)
            assert result == expected, (
                f"ip_in_range({ip}, {start}, {end}) = {result}, expected {expected}"
            )


class TestNetworkFilterSQL:
    """Test SQL generation for network filtering operations."""

    def test_subnet_filter_sql(self) -> None:
        """Test SQL generation for subnet filtering."""
        from fraiseql.sql.network_utils import generate_subnet_sql

        sql, params = generate_subnet_sql("data->>'ip_address'", "192.168.1.0/24")

        # Should use PostgreSQL inet operators
        assert "<<=" in sql or "inet" in sql.lower()
        assert "192.168.1.0/24" in params

    def test_range_filter_sql(self) -> None:
        """Test SQL generation for IP range filtering."""
        from fraiseql.sql.network_utils import generate_range_sql

        sql, params = generate_range_sql("data->>'ip_address'", "192.168.1.1", "192.168.1.100")

        # Should use PostgreSQL inet comparison
        assert ">=" in sql
        assert "<=" in sql
        assert "inet" in sql.lower()
        assert "192.168.1.1" in params
        assert "192.168.1.100" in params

    def test_private_ip_filter_sql(self) -> None:
        """Test SQL generation for private IP filtering."""
        from fraiseql.sql.network_utils import generate_private_ip_sql

        sql, _params = generate_private_ip_sql("data->>'ip_address'", True)

        # Should check RFC 1918 ranges
        assert "10.0.0.0/8" in sql or "192.168.0.0/16" in sql or "172.16.0.0/12" in sql
        assert "inet" in sql.lower()

    def test_ipv4_filter_sql(self) -> None:
        """Test SQL generation for IPv4 filtering."""
        from fraiseql.sql.network_utils import generate_ipv4_sql

        sql, _params = generate_ipv4_sql("data->>'ip_address'", True)

        # Should check for IPv4 format (family = 4 or pattern matching)
        assert "family(" in sql.lower() or "inet" in sql.lower()


class TestNetworkFilterIntegration:
    """Test integration of network filtering with FraiseQL."""

    def test_where_input_generation(self) -> None:
        """Test that NetworkDevice generates proper where input with network operators."""
        WhereInput = create_graphql_where_input(NetworkDevice)

        # Verify the types
        type_hints = get_type_hints(WhereInput)

        # IP address field should use NetworkAddressFilter
        ip_filter_type = type_hints["ip_address"].__args__[0]
        assert ip_filter_type == NetworkAddressFilter

        # Should be able to create filter with network operations
        network_filter = NetworkAddressFilter()
        assert hasattr(network_filter, "eq")
        assert hasattr(network_filter, "inSubnet")
        assert hasattr(network_filter, "isPrivate")

    def test_network_filter_field_access(self) -> None:
        """Test that network filter fields are accessible."""
        filter_instance = NetworkAddressFilter()

        # Basic operators
        assert hasattr(filter_instance, "eq")
        assert hasattr(filter_instance, "neq")
        assert hasattr(filter_instance, "in_")
        assert hasattr(filter_instance, "nin")
        assert hasattr(filter_instance, "isnull")

        # Network operators
        assert hasattr(filter_instance, "inSubnet")
        assert hasattr(filter_instance, "inRange")
        assert hasattr(filter_instance, "isPrivate")
        assert hasattr(filter_instance, "isPublic")
        assert hasattr(filter_instance, "isIPv4")
        assert hasattr(filter_instance, "isIPv6")

    def test_backwards_compatibility(self) -> None:
        """Test that basic operations still work."""
        # Basic filtering should still work
        filter_instance = NetworkAddressFilter()

        # These should not raise AttributeError
        _ = filter_instance.eq
        _ = filter_instance.neq
        _ = filter_instance.in_
        _ = filter_instance.nin
        _ = filter_instance.isnull

        # New operations should also be available
        _ = filter_instance.inSubnet
        _ = filter_instance.isPrivate


class TestIPRangeInput:
    """Test the IPRange input type used for range filtering."""

    def test_ip_range_structure(self) -> None:
        """Test that IPRange input has correct structure."""
        from fraiseql.sql.graphql_where_generator import IPRange

        # Should be able to create with from/to fields
        ip_range = IPRange(from_="192.168.1.1", to="192.168.1.100")
        assert ip_range.from_ == "192.168.1.1"
        assert ip_range.to == "192.168.1.100"

    def test_ip_range_validation(self) -> None:
        """Test validation of IP range inputs."""
        from fraiseql.sql.network_utils import validate_ip_range

        valid_ranges = [
            ("192.168.1.1", "192.168.1.100"),
            ("10.0.0.1", "10.0.0.255"),
            ("172.16.0.1", "172.16.255.254"),
        ]

        for start, end in valid_ranges:
            assert validate_ip_range(start, end), f"Valid range {start}-{end} failed validation"

        invalid_ranges = [
            ("192.168.1.100", "192.168.1.1"),  # Start > end
            ("not.an.ip", "192.168.1.100"),  # Invalid start
            ("192.168.1.1", "not.an.ip"),  # Invalid end
            ("", "192.168.1.100"),  # Empty start
        ]

        for start, end in invalid_ranges:
            assert not validate_ip_range(start, end), (
                f"Invalid range {start}-{end} passed validation"
            )


class TestNetworkOperatorIntegration:
    """Test that network operators work correctly in the SQL generation pipeline."""

    @pytest.mark.asyncio
    async def test_subnet_operator_sql_generation(self) -> None:
        """Test that inSubnet generates correct SQL."""
        from psycopg.sql import SQL

        from fraiseql.sql.operators import get_default_registry
        from fraiseql.types import IpAddress

        registry = get_default_registry()

        # Test subnet operation
        result = registry.build_sql(
            "insubnet", "192.168.1.0/24", SQL("data->>'ip_address'"), field_type=IpAddress
        )

        # Should generate PostgreSQL inet subnet matching
        sql_str = str(result)
        assert "<<=" in sql_str or "inet" in sql_str.lower()

    @pytest.mark.asyncio
    async def test_range_operator_sql_generation(self) -> None:
        """Test that inRange generates correct SQL."""
        from psycopg.sql import SQL

        from fraiseql.sql.operators import get_default_registry
        from fraiseql.types import IpAddress

        registry = get_default_registry()

        # Test range operation
        range_value = {"from": "192.168.1.1", "to": "192.168.1.100"}
        result = registry.build_sql(
            "overlaps", range_value, SQL("data->>'ip_address'"), field_type=IpAddress
        )

        # Should generate PostgreSQL inet range comparison
        sql_str = result.as_string(None)  # type: ignore
        assert "&&" in sql_str  # inet overlaps operator

    @pytest.mark.asyncio
    async def test_private_ip_operator_sql_generation(self) -> None:
        """Test that isPrivate generates correct SQL."""
        from psycopg.sql import SQL

        from fraiseql.sql.operators import get_default_registry
        from fraiseql.types import IpAddress

        registry = get_default_registry()

        # Test private IP detection
        result = registry.build_sql(
            "isprivate", True, SQL("data->>'ip_address'"), field_type=IpAddress
        )

        # Should use CIDR range checks for private IPs (no inet_public() in PostgreSQL)
        sql_str = result.as_string(None)  # type: ignore
        assert "10.0.0.0/8" in sql_str  # RFC 1918 private range
        assert "192.168.0.0/16" in sql_str  # RFC 1918 private range
        assert "::inet" in sql_str


# Additional test data for comprehensive testing
SAMPLE_NETWORK_DATA = [
    {"id": "1", "name": "Router1", "ip_address": "192.168.1.1", "network": "192.168.1.0/24"},
    {"id": "2", "name": "Server1", "ip_address": "10.0.0.100", "network": "10.0.0.0/8"},
    {"id": "3", "name": "Gateway1", "ip_address": "172.16.0.1", "network": "172.16.0.0/12"},
    {"id": "4", "name": "DNS1", "ip_address": "8.8.8.8", "network": "8.8.8.0/24"},
    {"id": "5", "name": "WebServer", "ip_address": "203.0.113.1", "network": "203.0.113.0/24"},
]
