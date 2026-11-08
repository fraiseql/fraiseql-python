"""Fixtures for operator E2E tests (network, arrays, ltree, etc.)."""

import pytest

from fraiseql import fraise_type, query


@pytest.fixture(scope="class")
async def network_test_data(meta_test_pool):
    """Create test tables with network data types for operator testing."""
    async with meta_test_pool.connection() as conn:
        # Create table with network types
        await conn.execute("""
            DROP TABLE IF EXISTS test_networks CASCADE;

            CREATE TABLE test_networks (
                id SERIAL PRIMARY KEY,
                ip_address INET,
                network CIDR,
                mac_address MACADDR,
                description TEXT
            );
        """)

        # Insert test data
        await conn.execute("""
            INSERT INTO test_networks (ip_address, network, mac_address, description) VALUES
                ('192.168.1.1', '192.168.1.0/24', '08:00:2b:01:02:03', 'Private network'),
                ('10.0.0.1', '10.0.0.0/8', '08:00:2b:01:02:04', 'Corporate network'),
                ('8.8.8.8', '8.8.8.0/24', '08:00:2b:01:02:05', 'Public DNS');
        """)

        await conn.commit()

    yield  # Tests run here

    # Cleanup
    async with meta_test_pool.connection() as conn:
        await conn.execute("DROP TABLE IF EXISTS test_networks CASCADE;")
        await conn.commit()


@pytest.fixture(scope="class")
def network_schema(meta_test_schema):
    """Schema with network types for operator testing."""
    meta_test_schema.clear()

    @fraise_type(sql_source="test_networks")
    class NetworkTestType:
        id: int
        ip_address: str  # IpAddressScalar in full implementation
        network: str  # CIDRScalar
        mac_address: str  # MacAddressScalar
        description: str

    @query
    async def get_networks(info, where: dict | None = None) -> list[NetworkTestType]:
        return []

    meta_test_schema.register_type(NetworkTestType)
    meta_test_schema.register_query(get_networks)

    return meta_test_schema
