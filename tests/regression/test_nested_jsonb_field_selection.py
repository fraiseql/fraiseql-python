"""Regression test for nested JSONB field selection with composed views.

Tests that field selection works correctly when using the recommended FraiseQL
architecture: composed JSONB views where nested objects come from joining
other table views' `data` columns.

Example SQL pattern being tested:
    CREATE VIEW v_allocation AS
    SELECT jsonb_build_object(
        'id', ta_allocation.id,
        'name', ta_allocation.name,
        'network_configuration', tv_network_configuration.data  -- ← Nested JSONB!
    ) as data
    FROM ta_allocation
    LEFT JOIN tv_network_configuration ...

This is THE CRITICAL test for the 7.5x bandwidth issue reported.
"""

import uuid
from typing import TYPE_CHECKING, Optional

import pytest
import pytest_asyncio

from fraiseql import query
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import fraise_type

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.integration


# Define test types matching the JSONB view pattern
@fraise_type
class NetworkConfig:
    """Network configuration with many fields."""

    id: uuid.UUID
    ip_address: str
    subnet_mask: str
    gateway: str
    dns_primary: str
    dns_secondary: str
    hostname: str
    domain_name: str


@fraise_type
class Allocation:
    """Allocation with nested JSONB object from composed view."""

    id: uuid.UUID
    name: str
    network_config: Optional[NetworkConfig] = None


# Use class-scoped fixtures for database persistence
@pytest.mark.usefixtures("class_db_pool")
class TestNestedJSONBFieldSelection:
    """Test class for nested JSONB field selection with composed views."""

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_jsonb_views(self, class_db_pool, test_schema):
        """Create tables and composed JSONB views for testing."""
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")

            # Drop existing
            await conn.execute("DROP VIEW IF EXISTS v_allocation_nested CASCADE")
            await conn.execute("DROP VIEW IF EXISTS tv_network_config_nested CASCADE")
            await conn.execute("DROP TABLE IF EXISTS ta_network_config_nested CASCADE")
            await conn.execute("DROP TABLE IF EXISTS ta_allocation_nested CASCADE")

            # Create base tables
            await conn.execute(
                """
                CREATE TABLE ta_network_config_nested (
                    id UUID PRIMARY KEY,
                    ip_address TEXT NOT NULL,
                    subnet_mask TEXT NOT NULL,
                    gateway TEXT NOT NULL,
                    dns_primary TEXT NOT NULL,
                    dns_secondary TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    domain_name TEXT NOT NULL
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE ta_allocation_nested (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL,
                    network_config_id UUID REFERENCES ta_network_config_nested(id)
                )
                """
            )

            # Create JSONB table view for network config (all 8 fields)
            await conn.execute(
                """
                CREATE VIEW tv_network_config_nested AS
                SELECT jsonb_build_object(
                    'id', id::text,
                    'ip_address', ip_address,
                    'subnet_mask', subnet_mask,
                    'gateway', gateway,
                    'dns_primary', dns_primary,
                    'dns_secondary', dns_secondary,
                    'hostname', hostname,
                    'domain_name', domain_name
                ) as data
                FROM ta_network_config_nested
                """
            )

            # Create composed JSONB view (THE KEY PART!)
            # This embeds the FULL network config JSONB into allocation
            await conn.execute(
                """
                CREATE VIEW v_allocation_nested AS
                SELECT jsonb_build_object(
                    'id', ta_allocation_nested.id::text,
                    'name', ta_allocation_nested.name,
                    'network_config', tv_network_config_nested.data
                ) as data
                FROM ta_allocation_nested
                LEFT JOIN tv_network_config_nested
                    ON tv_network_config_nested.data->>'id' = ta_allocation_nested.network_config_id::text
                """
            )

            # Insert test data
            network_id = uuid.UUID("99999999-1111-2222-3333-444444444444")
            allocation_id = uuid.UUID("88888888-1111-2222-3333-444444444444")

            await conn.execute(
                """
                INSERT INTO ta_network_config_nested VALUES (
                    %s, '10.0.1.100', '255.255.255.0', '10.0.1.1',
                    '1.1.1.1', '8.8.8.8', 'test-server', 'test.local'
                )
                """,
                (network_id,),
            )

            await conn.execute(
                """
                INSERT INTO ta_allocation_nested VALUES (%s, 'Test Allocation', %s)
                """,
                (allocation_id, network_id),
            )

            await conn.commit()

        yield

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    def graphql_app(
        self,
        class_db_pool,
        test_schema,
        setup_jsonb_views,
        clear_registry_class,
    ) -> "FastAPI":
        """Create GraphQL app with composed JSONB views."""
        from contextlib import asynccontextmanager

        from fraiseql.fastapi.dependencies import set_db_pool

        # Define query to use the composed view
        @query
        async def allocations(info) -> list[Allocation]:
            repo = info.context["db"]

            # Register types for automatic resolution
            from fraiseql.db import register_type_for_view

            register_type_for_view(
                "v_allocation_nested", Allocation, has_jsonb_data=True, jsonb_column="data"
            )

            return await repo.find("v_allocation_nested", "allocations", info)

        # Wrap pool for schema isolation
        class SchemaAwarePool:
            def __init__(self, pool, schema):
                self._pool = pool
                self._schema = schema

            @asynccontextmanager
            async def connection(self):
                async with self._pool.connection() as conn:
                    await conn.execute(f"SET search_path TO {self._schema}, public")
                    yield conn

            def __getattr__(self, name):
                return getattr(self._pool, name)

        wrapped_pool = SchemaAwarePool(class_db_pool, test_schema)
        set_db_pool(wrapped_pool)

        app = create_fraiseql_app(
            database_url="postgresql://test/test",
            types=[NetworkConfig, Allocation],
            queries=[allocations],
            production=False,
        )
        return app

    async def _execute_query(self, graphql_app, query_str: str):
        """Execute GraphQL query."""
        from asgi_lifespan import LifespanManager
        from httpx import ASGITransport, AsyncClient

        async with LifespanManager(graphql_app) as manager:
            transport = ASGITransport(app=manager.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/graphql", json={"query": query_str})
        return response

    @pytest.mark.asyncio
    async def test_nested_jsonb_field_selection_only_requested_fields(self, graphql_app) -> None:
        """Test that only requested fields are returned from nested JSONB objects.

        This is THE CRITICAL TEST for the 7.5x bandwidth issue.

        Query requests only 2 fields (id, ipAddress) from networkConfig.
        The JSONB contains all 8 fields.
        FraiseQL should return ONLY the 2 requested fields.

        If this test FAILS, it means:
        - Extra fields are being returned
        - 7.5x bandwidth overhead
        - Rust zero-copy optimization not working
        """
        query_str = """
        query {
            allocations {
                id
                name
                networkConfig {
                    id
                    ipAddress
                }
            }
        }
        """

        response = await self._execute_query(graphql_app, query_str)
        assert response.status_code == 200

        data = response.json()
        assert "errors" not in data, f"GraphQL errors: {data.get('errors')}"

        allocations = data["data"]["allocations"]
        assert len(allocations) == 1

        allocation = allocations[0]
        network_config = allocation["networkConfig"]

        # These fields SHOULD be present
        assert "id" in network_config
        assert "ipAddress" in network_config

        # These fields should NOT be present (the bug!)
        assert "subnetMask" not in network_config, "BUG: subnetMask should not be returned"
        assert "gateway" not in network_config, "BUG: gateway should not be returned"
        assert "dnsPrimary" not in network_config, "BUG: dnsPrimary should not be returned"
        assert "dnsSecondary" not in network_config, "BUG: dnsSecondary should not be returned"
        assert "hostname" not in network_config, "BUG: hostname should not be returned"
        assert "domainName" not in network_config, "BUG: domainName should not be returned"

        # Verify only requested fields are present (__typename isn't selected)
        expected_fields = {"id", "ipAddress"}
        actual_fields = set(network_config.keys())
        assert actual_fields == expected_fields, (
            f"Expected fields {expected_fields}, got {actual_fields}. "
            f"Extra fields: {actual_fields - expected_fields}"
        )

    @pytest.mark.asyncio
    async def test_nested_jsonb_field_selection_all_fields_requested(self, graphql_app) -> None:
        """Test that all fields ARE returned when explicitly requested."""
        query_str = """
        query {
            allocations {
                id
                networkConfig {
                    __typename
                    id
                    ipAddress
                    subnetMask
                    gateway
                    dnsPrimary
                    dnsSecondary
                    hostname
                    domainName
                }
            }
        }
        """

        response = await self._execute_query(graphql_app, query_str)
        assert response.status_code == 200

        data = response.json()
        assert "errors" not in data

        allocation = data["data"]["allocations"][0]
        network_config = allocation["networkConfig"]

        # All 8 fields + __typename should be present when explicitly requested
        assert len(network_config) == 9  # 8 data fields + __typename
        assert "id" in network_config
        assert "ipAddress" in network_config
        assert "subnetMask" in network_config
        assert "gateway" in network_config
        assert "dnsPrimary" in network_config
        assert "dnsSecondary" in network_config
        assert "hostname" in network_config
        assert "domainName" in network_config
        assert "__typename" in network_config

    @pytest.mark.asyncio
    async def test_nested_jsonb_field_selection_partial_fields(self, graphql_app) -> None:
        """Test partial field selection (4 out of 8 fields)."""
        query_str = """
        query {
            allocations {
                id
                networkConfig {
                    id
                    ipAddress
                    gateway
                    hostname
                }
            }
        }
        """

        response = await self._execute_query(graphql_app, query_str)
        assert response.status_code == 200

        data = response.json()
        assert "errors" not in data

        allocation = data["data"]["allocations"][0]
        network_config = allocation["networkConfig"]

        # Exactly the 4 selected fields should be present (__typename isn't selected)
        assert len(network_config) == 4
        assert "id" in network_config
        assert "ipAddress" in network_config
        assert "gateway" in network_config
        assert "hostname" in network_config
        assert "__typename" not in network_config

        # These should NOT be present
        assert "subnetMask" not in network_config
        assert "dnsPrimary" not in network_config
        assert "dnsSecondary" not in network_config
        assert "domainName" not in network_config
