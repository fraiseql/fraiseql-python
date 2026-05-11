"""Test to reproduce JSONB+INET network filtering issue.

This test reproduces a critical bug in FraiseQL v0.5.7:
"""

from __future__ import annotations

"""
- IP addresses stored as INET in PostgreSQL command tables
- Exposed as JSONB text in query views (CQRS pattern)
- Network equality operators (eq, neq, in, notin) return empty results
- Subnet operators (inSubnet) work correctly

This test follows FraiseQL repository testing patterns:
- Uses unified container approach with session-scoped PostgreSQL container
- Creates proper CQRS-style schema with command tables and query views
- Tests actual GraphQL queries with realistic data seeding
- Uses FraiseQL's transaction-based test isolation
"""

import uuid
from typing import get_type_hints

import pytest
from fastapi.testclient import TestClient
from psycopg.sql import SQL

import fraiseql
from fraiseql.sql.graphql_where_generator import create_graphql_where_input
from fraiseql.types import UUID, IpAddress

pytestmark = pytest.mark.integration


@fraiseql.type(sql_source="v_dns_server")
class DnsServer:
    """DNS Server type for CQRS pattern testing.

    This matches common CQRS patterns:
    - id: UUID (mapped from pk_dns_server)
    - identifier: Human-readable name
    - ip_address: IP address (stored as INET in DB, exposed as text in JSONB)
    """

    id: uuid.UUID
    identifier: str
    ip_address: IpAddress


# Create WHERE input type for GraphQL filtering
DnsServerWhereInput = create_graphql_where_input(DnsServer)


@fraiseql.query
async def dns_servers(
    info, where: DnsServerWhereInput | None = None, first: int = 100
) -> list[DnsServer]:
    """Query DNS servers with filtering support."""
    # In real implementation, this would use the repository
    db = info.context["db"]
    tenant_id = info.context["tenant_id"]
    return await db.find(
        "v_dns_server",
        tenant_id=tenant_id,
        where=where,
        limit=first,
    )


@fraiseql.query
async def dns_server(info, *, id: UUID) -> DnsServer | None:
    """Get single DNS server by ID."""
    db = info.context["db"]
    tenant_id = info.context["tenant_id"]
    return await db.find_one("v_dns_server", mandatory_filters={"id": id, "tenant_id": tenant_id})


class TestJSONBNetworkFilteringBug:
    """Reproduce the JSONB+INET network filtering bug."""

    @pytest.mark.database
    @pytest.mark.asyncio
    async def test_cqrs_schema_setup(self, db_connection) -> None:
        """Set up the CQRS schema pattern that reproduces the bug."""
        # 1. Create command-side table (INET storage)
        command_table_schema = """
            CREATE TABLE tenant_tb_dns_server (
                pk_dns_server UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                pk_organization UUID NOT NULL DEFAULT '22222222-2222-2222-2222-222222222222',
                identifier TEXT NOT NULL,
                ip_address INET NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """
        await db_connection.execute(command_table_schema)

        # 2. Create query-side view (JSONB transformation)
        query_view_sql = """
            SELECT
                pk_dns_server::text as id,
                jsonb_build_object(
                    'identifier', identifier,
                    'ip_address', ip_address::text  -- KEY ISSUE: INET → TEXT in JSONB
                ) AS data
            FROM tenant_tb_dns_server
        """
        await db_connection.execute(f"CREATE VIEW v_dns_server AS {query_view_sql}")

        # 3. Seed with test data
        await db_connection.execute(
            """
            INSERT INTO tenant_tb_dns_server (pk_dns_server, identifier, ip_address) VALUES
            ('646e7300-1111-1111-1111-000000000001', 'Primary DNS Google', '8.8.8.8'),
            ('646e7300-1111-1111-1111-000000000002', 'Secondary DNS Google', '8.8.4.4'),
            ('646e7300-1111-1111-1111-000000000003', 'Primary DNS Cloudflare', '1.1.1.1'),
            ('646e7300-1111-1111-1111-000000000004', 'Secondary DNS Cloudflare', '1.0.0.1'),
            ('646e7300-1111-1111-1111-000000000007', 'Internal DNS 192', '192.168.1.1'),
            ('646e7300-1111-1111-1111-000000000008', 'Internal DNS 10', '10.0.0.1'),
            ('646e7300-1111-1111-1111-000000000009', 'Test Network 21.43', '21.43.60.1'),
            ('646e7300-1111-1111-1111-000000000010', 'Test Network 21.43 #2', '21.43.65.100')
        """
        )

        # Verify data seeded correctly in command table
        cursor = await db_connection.execute(
            "SELECT identifier, ip_address FROM tenant_tb_dns_server "
            "WHERE identifier = 'Primary DNS Google'"
        )
        result = await cursor.fetchone()
        assert result is not None, "Test data not seeded correctly"
        assert str(result[1]) == "8.8.8.8", f"IP address mismatch: {result[1]}"

        # Verify JSONB transformation in query view
        cursor = await db_connection.execute(
            "SELECT data FROM v_dns_server WHERE id = '646e7300-1111-1111-1111-000000000001'"
        )
        result = await cursor.fetchone()
        assert result is not None, "Query view not working"
        data = result[0]
        assert data["identifier"] == "Primary DNS Google"
        # PostgreSQL INET type automatically adds /32 for single IPv4 addresses
        expected_formats = ["8.8.8.8", "8.8.8.8/32"]
        assert data["ip_address"] in expected_formats, f"Unexpected IP format: {data['ip_address']}"

    @pytest.mark.database
    @pytest.mark.asyncio
    async def test_network_operator_sql_generation_with_jsonb(self, db_connection) -> None:
        """Test that network operators generate correct SQL for JSONB fields."""
        from fraiseql.sql.operators import get_default_registry as get_operator_registry

        registry = get_operator_registry()
        field_path = SQL("data->>'ip_address'")  # JSONB text extraction

        # Test inSubnet (this should work)
        subnet_sql = registry.build_sql("inSubnet", "21.43.0.0/16", field_path, IpAddress)

        from tests.helpers.sql_rendering import render_sql_for_testing

        subnet_str = render_sql_for_testing(subnet_sql)

        # Validate SQL generation includes proper INET casting

        # Should contain proper INET casting for JSONB text
        assert "::inet" in subnet_str, "Should cast JSONB text to INET type"
        assert "<<=" in subnet_str, "Should use PostgreSQL subnet operator"
        assert "21.43.0.0/16" in subnet_str, "Should include subnet parameter"

        # Test eq operator (this is the broken one)
        eq_sql = registry.build_sql("eq", "8.8.8.8", field_path, IpAddress)
        eq_str = render_sql_for_testing(eq_sql)

        # Validate equality operator generates proper SQL

        # Verify equality operator works correctly
        assert "8.8.8.8" in eq_str, "Should include IP address value"

        # Test with actual data
        await self._setup_test_schema(db_connection)

        # Test subnet query (should work) - use SQL query composition
        from psycopg.sql import Composed

        subnet_query = Composed([SQL("SELECT id, data FROM v_dns_server WHERE "), subnet_sql])
        cursor = await db_connection.execute(subnet_query)
        results = await cursor.fetchall()
        # Subnet query executed

        # Test equality query (the fixed case) - use SQL query composition
        eq_query = Composed([SQL("SELECT id, data FROM v_dns_server WHERE "), eq_sql])
        cursor = await db_connection.execute(eq_query)
        results = await cursor.fetchall()
        # Equality query executed

        # Verify the bug is fixed: should return exactly 1 record
        assert len(results) == 1, f"Expected 1 record for Google DNS, got {len(results)}"

    @pytest.mark.database
    @pytest.mark.asyncio
    async def test_graphql_network_filtering_bug_reproduction(
        self, create_fraiseql_app_with_db
    ) -> None:
        """Test the complete GraphQL network filtering bug with real queries."""
        # Create FraiseQL app with our types
        app = create_fraiseql_app_with_db(
            types=[DnsServer, DnsServerWhereInput],
            queries=[dns_servers, dns_server],
            production=False,
        )

        client = TestClient(app)

        # Test 1: Control test - should work with identifier filtering
        control_query = """
            query TestControl {
                dnsServers(where: { identifier: { eq: "Primary DNS Google" } }) {
                    id
                    identifier
                    ipAddress
                }
            }
        """

        response = client.post("/graphql", json={"query": control_query})
        assert response.status_code == 200

        data = response.json()
        # Control query executed

        if "errors" not in data:
            dns_servers_data = data["data"]["dnsServers"]
            if dns_servers_data:
                target_ip = dns_servers_data[0]["ipAddress"]

                # Test 2: The broken case - IP equality filtering
                ip_eq_query = f"""
                    query TestIPEquality {{
                        dnsServers(where: {{ ipAddress: {{ eq: "{target_ip}" }} }}) {{
                            id
                            identifier
                            ipAddress
                        }}
                    }}
                """

                response = client.post("/graphql", json={"query": ip_eq_query})
                assert response.status_code == 200

                data = response.json()
                # IP equality query executed

                # Verify the equality filtering works
                if "errors" not in data:
                    ip_results = data["data"]["dnsServers"]
                    assert len(ip_results) == 1, (
                        f"IP equality filter returned {len(ip_results)} "
                        f"results instead of 1 for IP {target_ip}"
                    )

                # Test 3: Subnet filtering (should work)
                subnet_query = """
                    query TestSubnet {
                        dnsServers(where: { ipAddress: { inSubnet: "21.43.0.0/16" } }) {
                            id
                            identifier
                            ipAddress
                        }
                    }
                """

                response = client.post("/graphql", json={"query": subnet_query})
                assert response.status_code == 200

                data = response.json()
                # Subnet query executed

                if "errors" not in data:
                    subnet_results = data["data"]["dnsServers"]
                    # Should find the 21.43.x.x test servers
                    assert len(subnet_results) > 0, "Subnet filtering should work"

    @pytest.mark.database
    @pytest.mark.asyncio
    async def test_root_cause_investigation(self, db_connection) -> None:
        """Investigate the root cause of the JSONB+INET filtering issue."""
        await self._setup_test_schema(db_connection)

        # Root cause investigation

        # Test 1: Direct PostgreSQL queries on command table (should work)
        # Test 1: Direct INET column queries
        cursor = await db_connection.execute(
            """
            SELECT identifier, ip_address
            FROM tenant_tb_dns_server
            WHERE ip_address = '8.8.8.8'::inet
        """
        )
        await cursor.fetchall()
        # Direct INET equality test

        cursor = await db_connection.execute(
            """
            SELECT identifier, ip_address
            FROM tenant_tb_dns_server
            WHERE ip_address <<= '21.43.0.0/16'::inet
        """
        )
        await cursor.fetchall()
        # Direct INET subnet test

        # Test 2: JSONB text extraction queries (query view)
        # Test 2: JSONB text extraction queries
        cursor = await db_connection.execute(
            """
            SELECT id, data->>'ip_address' as ip
            FROM v_dns_server
            WHERE data->>'ip_address' = '8.8.8.8'
        """
        )
        await cursor.fetchall()
        # JSONB text equality test

        cursor = await db_connection.execute(
            """
            SELECT id, data->>'ip_address' as ip
            FROM v_dns_server
            WHERE (data->>'ip_address')::inet <<= '21.43.0.0/16'::inet
        """
        )
        await cursor.fetchall()
        # JSONB text cast to INET subnet test

        # Test 3: The exact SQL that FraiseQL might generate
        # Test 3: FraiseQL-style generated SQL

        # This is what should work for equality
        cursor = await db_connection.execute(
            """
            SELECT id, data->>'ip_address' as ip
            FROM v_dns_server
            WHERE (data->>'ip_address')::inet = '8.8.8.8'::inet
        """
        )
        await cursor.fetchall()
        # INET cast equality test

        # This is what works for subnet
        cursor = await db_connection.execute(
            """
            SELECT id, data->>'ip_address' as ip
            FROM v_dns_server
            WHERE (data->>'ip_address')::inet <<= '21.43.0.0/16'::inet
        """
        )
        await cursor.fetchall()
        # INET cast subnet test

        # Diagnosis: Check if INET cast equality works correctly

    async def _setup_test_schema(self, db_connection) -> None:
        """Helper to set up test schema and data."""
        # Drop and recreate if exists
        await db_connection.execute("DROP TABLE IF EXISTS tenant_tb_dns_server CASCADE")
        await db_connection.execute("DROP VIEW IF EXISTS v_dns_server CASCADE")

        # Create command table
        await db_connection.execute(
            """
            CREATE TABLE tenant_tb_dns_server (
                pk_dns_server UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                pk_organization UUID NOT NULL DEFAULT '22222222-2222-2222-2222-222222222222',
                identifier TEXT NOT NULL,
                ip_address INET NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """
        )

        # Create query view
        await db_connection.execute(
            """
            CREATE VIEW v_dns_server AS
            SELECT
                pk_dns_server::text as id,
                jsonb_build_object(
                    'identifier', identifier,
                    'ip_address', ip_address::text
                ) AS data
            FROM tenant_tb_dns_server
        """
        )

        # Seed data
        await db_connection.execute(
            """
            INSERT INTO tenant_tb_dns_server (pk_dns_server, identifier, ip_address) VALUES
            ('646e7300-1111-1111-1111-000000000001', 'Primary DNS Google', '8.8.8.8'),
            ('646e7300-1111-1111-1111-000000000002', 'Secondary DNS Google', '8.8.4.4'),
            ('646e7300-1111-1111-1111-000000000003', 'Primary DNS Cloudflare', '1.1.1.1'),
            ('646e7300-1111-1111-1111-000000000004', 'Secondary DNS Cloudflare', '1.0.0.1'),
            ('646e7300-1111-1111-1111-000000000007', 'Internal DNS 192', '192.168.1.1'),
            ('646e7300-1111-1111-1111-000000000008', 'Internal DNS 10', '10.0.0.1'),
            ('646e7300-1111-1111-1111-000000000009', 'Test Network 21.43', '21.43.60.1'),
            ('646e7300-1111-1111-1111-000000000010', 'Test Network 21.43 #2', '21.43.65.100')
        """
        )


class TestFraiseQLNetworkOperatorStrategy:
    """Test FraiseQL's NetworkOperatorStrategy with JSONB fields."""

    def test_network_operator_strategy_can_handle_ip_types(self) -> None:
        """Test that NetworkOperatorStrategy recognizes IP address types."""
        from fraiseql.sql.operators import NetworkOperatorStrategy

        strategy = NetworkOperatorStrategy()

        # Should handle IpAddress types
        assert strategy.supports_operator("eq", IpAddress), "Should handle eq for IpAddress"
        assert strategy.supports_operator("inSubnet", IpAddress), (
            "Should handle inSubnet for IpAddress"
        )
        assert strategy.supports_operator("isPrivate", IpAddress), (
            "Should handle isPrivate for IpAddress"
        )

        # Should not handle non-IP types
        assert not strategy.supports_operator("eq", str), "Should not handle eq for str"
        assert not strategy.supports_operator("inSubnet", int), "Should not handle inSubnet for int"

    def test_operator_registry_assigns_network_strategy_for_ip_equality(
        self,
    ) -> None:
        """Test operator registry assigns NetworkOperatorStrategy to IP equality operations."""
        from fraiseql.sql.operators import get_default_registry as get_operator_registry

        registry = get_operator_registry()

        # The key test: eq operator with IpAddress should get NetworkOperatorStrategy
        strategy = registry.get_strategy("eq", IpAddress)
        assert strategy.__class__.__name__ == "NetworkOperatorStrategy", (
            f"Expected NetworkOperatorStrategy for (eq, IpAddress), "
            f"got {strategy.__class__.__name__}"
        )

        # Other network operators should also get NetworkOperatorStrategy
        subnet_strategy = registry.get_strategy("inSubnet", IpAddress)
        assert subnet_strategy.__class__.__name__ == "NetworkOperatorStrategy"

        private_strategy = registry.get_strategy("isPrivate", IpAddress)
        assert private_strategy.__class__.__name__ == "NetworkOperatorStrategy"


class TestJSONBFieldTypeMapping:
    """Test FraiseQL's handling of IP address types in JSONB fields."""

    def test_where_input_generation_for_ip_fields(self) -> None:
        """Test that IP address fields get proper NetworkAddressFilter types."""
        WhereInput = create_graphql_where_input(DnsServer)
        type_hints = get_type_hints(WhereInput)

        # IP address field should have NetworkAddressFilter
        ip_filter_type = type_hints["ip_address"]

        # Unwrap Optional type if present
        if hasattr(ip_filter_type, "__args__") and ip_filter_type.__args__:
            filter_class = ip_filter_type.__args__[0]
        else:
            filter_class = ip_filter_type

        # Create instance to test available operators
        filter_instance = filter_class()

        # Should have basic operators
        assert hasattr(filter_instance, "eq"), "Should have eq operator"
        assert hasattr(filter_instance, "neq"), "Should have neq operator"
        assert hasattr(filter_instance, "in_"), "Should have in operator"

        # Should have network operators
        assert hasattr(filter_instance, "inSubnet"), "Should have inSubnet operator"
        assert hasattr(filter_instance, "isPrivate"), "Should have isPrivate operator"
        assert hasattr(filter_instance, "isPublic"), "Should have isPublic operator"


if __name__ == "__main__":
    # Allow running this test directly
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/regression/v0_5_7/test_network_filtering_regression.py",
            "-xvs",
        ],
        check=False,
    )
