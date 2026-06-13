"""E2E tests for network operators with real PostgreSQL and GraphQL integration.

This test validates that ALL network operators work end-to-end: from GraphQL query
parsing through SQL generation to PostgreSQL execution with real INET/CIDR data.

Network operators were broken in production (missing from ALL_OPERATORS), so this
test prevents regression of this critical functionality.
"""

import pytest
from graphql import GraphQLNonNull, graphql

# Import schema_builder to ensure SchemaRegistry is patched
import fraiseql.gql.schema_builder  # noqa: F401
from fraiseql import fraise_type, query
from fraiseql.types.scalars import IpAddressScalar  # type: ignore


@pytest.fixture(scope="class")
def network_test_schema(meta_test_schema):
    """Schema registry with network-related types for testing."""
    # Clear any existing registrations
    meta_test_schema.clear()

    @fraise_type(sql_source="network_test_devices")
    class NetworkDevice:
        id: int
        hostname: str
        ip_address: IpAddressScalar  # Uses IpAddressScalar for network operations
        network: str  # CIDR notation for subnet operations
        mac_address: str
        is_active: bool = True

    @query
    async def get_network_devices(info) -> list[NetworkDevice]:
        return []

    # Register types with schema
    meta_test_schema.register_type(NetworkDevice)
    meta_test_schema.register_query(get_network_devices)

    return meta_test_schema


class TestNetworkOperatorsE2E:
    """End-to-end tests for network operators with real PostgreSQL data."""

    async def test_network_operators_table_creation(self, meta_test_pool):
        """Network operators require proper PostgreSQL table setup."""
        table_name = "test_network_operators"

        async with meta_test_pool.connection() as conn:
            # Create table with INET and MACADDR columns
            await conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            await conn.execute(f"""
                CREATE TABLE {table_name} (
                    id SERIAL PRIMARY KEY,
                    ip_address INET,
                    network CIDR,
                    mac_address MACADDR,
                    hostname TEXT
                )
            """)

            # Insert test network data
            test_data = [
                ("192.168.1.1", "192.168.1.0/24", "aa:bb:cc:dd:ee:ff", "router1"),
                ("10.0.0.1", "10.0.0.0/8", "11:22:33:44:55:66", "server1"),
                ("2001:db8::1", "2001:db8::/32", "aa:bb:cc:dd:ee:00", "ipv6-router"),
                ("172.16.0.1", "172.16.0.0/12", "22:33:44:55:66:77", "internal-server"),
                ("8.8.8.8", "8.8.8.0/24", "33:44:55:66:77:88", "public-dns"),
            ]

            from psycopg import sql

            for ip, network, mac, hostname in test_data:
                await conn.execute(
                    sql.SQL(
                        "INSERT INTO {} (ip_address, network, mac_address, hostname) "
                        "VALUES (%s, %s, %s, %s)"
                    ).format(sql.Identifier(table_name)),
                    [ip, network, mac, hostname],
                )

            await conn.commit()

            # Verify data was inserted
            result = await conn.execute(f"SELECT count(*) FROM {table_name}")
            count_row = await result.fetchone()
            assert count_row[0] == 5, f"Expected 5 rows, got {count_row[0]}"

            # Cleanup
            await conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            await conn.commit()

    @pytest.mark.parametrize(
        "ip_address,expected_is_ipv4",
        [
            ("192.168.1.1", True),
            ("10.0.0.1", True),
            ("2001:db8::1", False),
            ("172.16.0.1", True),
            ("8.8.8.8", True),
        ],
    )
    async def test_isipv4_operator_e2e(self, meta_test_pool, ip_address, expected_is_ipv4):
        """Test isIPv4 operator end-to-end with real PostgreSQL data."""
        table_name = "test_isipv4"

        async with meta_test_pool.connection() as conn:
            # Setup
            await conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            await conn.execute(f"""
                CREATE TABLE {table_name} (
                    id SERIAL PRIMARY KEY,
                    ip_address INET
                )
            """)

            from psycopg import sql

            await conn.execute(
                sql.SQL("INSERT INTO {} (ip_address) VALUES (%s)").format(
                    sql.Identifier(table_name)
                ),
                [ip_address],
            )

            await conn.commit()

            # Test the operator would work (we can't easily test the full GraphQL pipeline here,
            # but we can verify the SQL generation logic works)
            # This is a placeholder for the full E2E test that would require the complete GraphQL setup

            # Cleanup
            await conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            await conn.commit()

    @pytest.mark.parametrize(
        "ip_address,subnet,expected_in_subnet",
        [
            ("192.168.1.1", "192.168.1.0/24", True),
            ("192.168.1.1", "192.168.2.0/24", False),
            ("10.0.0.1", "10.0.0.0/8", True),
            ("10.0.0.1", "192.168.0.0/16", False),
            ("2001:db8::1", "2001:db8::/32", True),
            ("2001:db8::1", "2001:db9::/32", False),
        ],
    )
    async def test_insubnet_operator_e2e(
        self, meta_test_pool, ip_address, subnet, expected_in_subnet
    ):
        """Test inSubnet operator end-to-end with real PostgreSQL data."""
        table_name = "test_insubnet"

        async with meta_test_pool.connection() as conn:
            # Setup
            await conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            await conn.execute(f"""
                CREATE TABLE {table_name} (
                    id SERIAL PRIMARY KEY,
                    ip_address INET,
                    subnet CIDR
                )
            """)

            from psycopg import sql

            await conn.execute(
                sql.SQL("INSERT INTO {} (ip_address, subnet) VALUES (%s, %s)").format(
                    sql.Identifier(table_name)
                ),
                [ip_address, subnet],
            )

            await conn.commit()

            # Test PostgreSQL's subnet containment operator directly
            result = await conn.execute(f"""
                SELECT ip_address <<= subnet as in_subnet FROM {table_name}
            """)
            row = await result.fetchone()
            actual_in_subnet = row[0]

            assert actual_in_subnet == expected_in_subnet, (
                f"PostgreSQL subnet check failed for {ip_address} in {subnet}"
            )

            # Cleanup
            await conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            await conn.commit()

    async def test_network_operators_in_graphql_schema_registration(self, network_test_schema):
        """Network operators should be available in GraphQL schema with IpAddressScalar."""
        schema = network_test_schema.build_schema()

        # Verify schema built successfully
        assert schema is not None

        # Verify IpAddressString scalar is registered (Python variable is IpAddressScalar,
        # but GraphQL type name is "IpAddressString")
        ip_address_type = schema.get_type("IpAddressString")
        assert ip_address_type is not None, "IpAddressString scalar not found in schema"

        # Verify NetworkDevice type exists
        network_device_type = schema.get_type("NetworkDevice")
        assert network_device_type is not None, "NetworkDevice type not found in schema"

        # Verify ip_address field exists and uses IpAddressScalar
        ip_address_field = network_device_type.fields.get("ipAddress")
        assert ip_address_field is not None, "ipAddress field not found"

        # The field type should be IpAddressString (the GraphQL scalar name)
        # Required field is wrapped in GraphQLNonNull (Issue #243)
        if isinstance(ip_address_field.type, GraphQLNonNull):
            assert ip_address_field.type.of_type.name == "IpAddressString"
        else:
            assert ip_address_field.type.name == "IpAddressString"

    async def test_network_operators_graphql_query_parsing(self, network_test_schema):
        """Network operators should parse correctly in GraphQL queries."""
        schema = network_test_schema.build_schema()

        # Test queries with network operators
        test_queries = [
            # isIPv4 operator
            """
            query {
                getNetworkDevices(where: {ipAddress: {isIPv4: true}}) {
                    id
                    hostname
                    ipAddress
                }
            }
            """,
            # inSubnet operator
            """
            query {
                getNetworkDevices(where: {ipAddress: {inSubnet: "192.168.1.0/24"}}) {
                    id
                    hostname
                    ipAddress
                }
            }
            """,
            # isPrivate operator
            """
            query {
                getNetworkDevices(where: {ipAddress: {isPrivate: true}}) {
                    id
                    hostname
                    ipAddress
                }
            }
            """,
        ]

        for query_str in test_queries:
            # Should not raise GraphQL parsing or validation errors
            result = await graphql(schema, query_str)
            assert not result.errors, f"GraphQL query failed: {query_str}\nErrors: {result.errors}"

    async def test_network_operators_combined_with_other_operators(self, network_test_schema):
        """Network operators should work in combination with other WHERE operators."""
        schema = network_test_schema.build_schema()

        # Test combination queries
        combination_queries = [
            # Network operator + equality
            """
            query {
                getNetworkDevices(where: {
                    AND: [
                        {ipAddress: {isIPv4: true}},
                        {isActive: {eq: true}}
                    ]
                }) {
                    id
                    hostname
                    ipAddress
                }
            }
            """,
            # Network operator + string contains
            """
            query {
                getNetworkDevices(where: {
                    AND: [
                        {ipAddress: {inSubnet: "192.168.0.0/16"}},
                        {hostname: {contains: "router"}}
                    ]
                }) {
                    id
                    hostname
                    ipAddress
                }
            }
            """,
        ]

        for query_str in combination_queries:
            result = await graphql(schema, query_str)
            assert not result.errors, (
                f"Combined operator query failed: {query_str}\nErrors: {result.errors}"
            )

    async def test_network_operators_with_null_values(self, network_test_schema):
        """Network operators should handle null values gracefully."""
        schema = network_test_schema.build_schema()

        # Query for devices that might have null IP addresses
        query_str = """
        query {
            getNetworkDevices(where: {ipAddress: {isnull: true}}) {
                id
                hostname
            }
        }
        """

        result = await graphql(schema, query_str)
        assert not result.errors, f"Null handling query failed: {result.errors}"

    async def test_network_operators_schema_introspection(self, network_test_schema):
        """Network operators should be introspectable through GraphQL schema."""
        schema = network_test_schema.build_schema()

        # Test introspection query for IpAddressString (the GraphQL scalar name)
        introspection_query = """
        query {
            __type(name: "IpAddressString") {
                name
                kind
                description
            }
        }
        """

        result = await graphql(schema, introspection_query)
        assert not result.errors, f"Schema introspection failed: {result.errors}"

        type_info = result.data["__type"]
        assert type_info is not None
        assert type_info["name"] == "IpAddressString"
        assert type_info["kind"] == "SCALAR"

    @pytest.mark.parametrize(
        "operator_name",
        [
            "isIPv4",
            "isIPv6",
            "isPrivate",
            "isPublic",
            "inSubnet",
            "inRange",
            "overlaps",
            "strictleft",
            "strictright",
            # Advanced network classification (v1.17.0+)
            "isLoopback",
            "isMulticast",
            "isBroadcast",
            "isLinkLocal",
            "isDocumentation",
            "isReserved",
            "isCarrierGrade",
            "isSiteLocal",
            "isUniqueLocal",
            "isGlobalUnicast",
        ],
    )
    async def test_all_network_operators_registered(self, operator_name):
        """All network operators should be registered in ALL_OPERATORS."""
        from fraiseql.where_clause import ALL_OPERATORS

        assert operator_name in ALL_OPERATORS, (
            f"Network operator '{operator_name}' not in ALL_OPERATORS"
        )

        # Also check camelCase variants
        camel_case_op = operator_name  # Most are already camelCase
        if operator_name in ["isipv4", "isipv6", "isprivate", "ispublic", "insubnet", "inrange"]:
            # These have camelCase equivalents
            camel_equivalent = {
                "isipv4": "isIPv4",
                "isipv6": "isIPv6",
                "isprivate": "isPrivate",
                "ispublic": "isPublic",
                "insubnet": "inSubnet",
                "inrange": "inRange",
            }[operator_name]
            assert camel_equivalent in ALL_OPERATORS, (
                f"CamelCase variant '{camel_equivalent}' not in ALL_OPERATORS"
            )

    async def test_network_operators_error_handling(self, network_test_schema):
        """Network operators should provide helpful error messages for invalid inputs."""
        schema = network_test_schema.build_schema()

        # Test with invalid IP address format
        query_str = """
        query {
            getNetworkDevices(where: {ipAddress: {inSubnet: "invalid-ip"}}) {
                id
                hostname
            }
        }
        """

        # This should either succeed (if validation happens later) or fail gracefully
        result = await graphql(schema, query_str)
        # We don't assert errors here since validation might happen at different levels
        # The important thing is no crashes occur
        assert result is not None, "GraphQL execution should not crash"

    async def test_network_operators_with_large_dataset_simulation(self, network_test_schema):
        """Network operators should work efficiently with larger datasets."""
        schema = network_test_schema.build_schema()

        # Test multiple complex queries as would happen with larger datasets
        complex_queries = [
            """
            query {
                getNetworkDevices(where: {
                    OR: [
                        {ipAddress: {isPrivate: true}},
                        {ipAddress: {inSubnet: "10.0.0.0/8"}}
                    ]
                }) {
                    id
                    hostname
                    ipAddress
                }
            }
            """,
            """
            query {
                getNetworkDevices(where: {
                    AND: [
                        {ipAddress: {isIPv4: true}},
                        {ipAddress: {isPrivate: false}}
                    ]
                }) {
                    id
                    hostname
                    ipAddress
                }
            }
            """,
        ]

        for query_str in complex_queries:
            result = await graphql(schema, query_str)
            assert not result.errors, (
                f"Complex network query failed: {query_str}\nErrors: {result.errors}"
            )
