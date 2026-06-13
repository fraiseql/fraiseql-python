"""Regression test for JSONB nested field camelCase conversion.

Validates that nested objects within JSONB columns have their field names
correctly converted from snake_case to camelCase in GraphQL responses.

Test patterns:
- Single nested objects (e.g., smtpServer)
- Numbered fields (e.g., dns1, dns2)
- Arrays of nested objects (e.g., printServers)
"""

import uuid
from typing import TYPE_CHECKING, AsyncGenerator

import pytest
import pytest_asyncio

from fraiseql import query
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import fraise_type

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.integration


@fraise_type
class DnsServer:
    """DNS server nested object."""

    id: uuid.UUID
    identifier: str
    ip_address: str


@fraise_type
class SmtpServer:
    """SMTP server nested object."""

    id: uuid.UUID
    identifier: str
    ip_address: str
    port: int


@fraise_type
class PrintServer:
    """Print server nested object."""

    id: uuid.UUID
    identifier: str
    hostname: str


@fraise_type
class Gateway:
    """Gateway nested object (single word - control case)."""

    id: uuid.UUID
    identifier: str
    ip_address: str


@fraise_type(sql_source="tv_network_configuration", jsonb_column="data")
class NetworkConfiguration:
    """Network configuration with nested JSONB objects."""

    id: uuid.UUID
    identifier: str

    # Single-word nested objects (control case - should work)
    gateway: Gateway | None = None

    # Underscore nested objects
    smtp_server: SmtpServer | None = None

    # Underscore+number nested objects
    dns_1: DnsServer | None = None
    dns_2: DnsServer | None = None

    # Array of nested objects
    print_servers: list[PrintServer] | None = None


@query
async def network_configuration(info, id: uuid.UUID) -> NetworkConfiguration | None:
    """Get a network configuration by ID."""
    repo = info.context["db"]
    return await repo.find_one("tv_network_configuration", mandatory_filters={"id": str(id)})


@query
async def network_configurations(info, limit: int = 10) -> list[NetworkConfiguration]:
    """List network configurations."""
    repo = info.context["db"]
    return await repo.find("tv_network_configuration", limit=limit)


class TestJSONBNestedCamelCase:
    """Test camelCase conversion for nested JSONB objects.

    Follows FraiseQL test architecture:
    - Class-scoped database setup
    - Schema isolation via test_<classname>_<uuid>
    - SchemaAwarePool wrapper for app connections
    """

    TEST_CONFIG_ID = "01436121-0000-0000-0000-000000000000"

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_database(self, class_db_pool, test_schema) -> AsyncGenerator[None]:
        """Set up database with JSONB nested objects."""
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")

            await conn.execute("DROP VIEW IF EXISTS tv_network_configuration CASCADE")
            await conn.execute("DROP TABLE IF EXISTS tb_network_configuration CASCADE")

            await conn.execute("""
                CREATE TABLE tb_network_configuration (
                    id UUID PRIMARY KEY,
                    identifier TEXT NOT NULL,
                    data JSONB NOT NULL
                )
            """)

            await conn.execute("""
                CREATE VIEW tv_network_configuration AS
                SELECT id, identifier, data
                FROM tb_network_configuration
            """)

            # Test data with ALL nested object patterns
            test_data = """{
                "id": "01436121-0000-0000-0000-000000000000",
                "identifier": "Network configuration 01",
                "gateway": {
                    "id": "01432121-0000-0000-0000-000000000000",
                    "identifier": "Gateway 1",
                    "ip_address": "30.0.0.1"
                },
                "smtp_server": {
                    "id": "01435121-0000-0000-0000-000000000000",
                    "identifier": "SMTP Server 1",
                    "ip_address": "13.16.1.10",
                    "port": 587
                },
                "dns_1": {
                    "id": "01431121-0000-0000-0000-000000000001",
                    "identifier": "primary-dns-server",
                    "ip_address": "120.0.0.1"
                },
                "dns_2": {
                    "id": "01431121-0000-0000-0000-000000000002",
                    "identifier": "secondary-dns-server",
                    "ip_address": "120.0.0.2"
                },
                "print_servers": [
                    {
                        "id": "01433121-0000-0000-0000-000000000001",
                        "identifier": "PrintServer-001",
                        "hostname": "printserver01.local"
                    },
                    {
                        "id": "01433121-0000-0000-0000-000000000002",
                        "identifier": "PrintServer-002",
                        "hostname": "printserver02.local"
                    }
                ]
            }"""

            await conn.execute(
                f"""
                INSERT INTO tb_network_configuration (id, identifier, data)
                VALUES (
                    '{self.TEST_CONFIG_ID}'::uuid,
                    'Network configuration 01',
                    '{test_data}'::jsonb
                )
                """
            )

            await conn.commit()

        yield

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    def graphql_app(
        self, class_db_pool, test_schema, setup_database, clear_registry_class
    ) -> "FastAPI":
        """Create GraphQL app with schema-aware pool."""
        from contextlib import asynccontextmanager

        from fraiseql.fastapi.dependencies import set_db_pool

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
            types=[NetworkConfiguration, DnsServer, SmtpServer, PrintServer, Gateway],
            queries=[network_configuration, network_configurations],
            production=False,
        )
        return app

    async def _execute_query(self, graphql_app, query_str: str, variables: dict | None = None):
        """Execute GraphQL query and return response."""
        from asgi_lifespan import LifespanManager
        from httpx import ASGITransport, AsyncClient

        async with LifespanManager(graphql_app) as manager:
            transport = ASGITransport(app=manager.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                payload = {"query": query_str}
                if variables:
                    payload["variables"] = variables
                response = await client.post("/graphql", json=payload)
        return response

    @pytest.mark.asyncio
    async def test_single_word_nested_object_converts_to_camelcase(self, graphql_app) -> None:
        """Control test: single-word nested objects should work (gateway)."""
        query_str = """
        query GetNetworkConfig {
            networkConfigurations {
                id
                identifier
                gateway {
                    id
                    identifier
                    ipAddress
                }
            }
        }
        """

        response = await self._execute_query(graphql_app, query_str)
        assert response.status_code == 200

        result = response.json()
        assert "errors" not in result, f"GraphQL errors: {result.get('errors')}"
        assert "data" in result
        assert "networkConfigurations" in result["data"]

        configs = result["data"]["networkConfigurations"]
        assert len(configs) > 0

        config = configs[0]
        assert "gateway" in config
        assert config["gateway"]["ipAddress"] == "30.0.0.1"

    @pytest.mark.asyncio
    async def test_underscore_nested_object_converts_to_camelcase(self, graphql_app) -> None:
        """Nested objects with underscore names should convert to camelCase."""
        query_str = """
        query GetNetworkConfig {
            networkConfigurations {
                id
                identifier
                smtpServer {
                    id
                    identifier
                    ipAddress
                    port
                }
            }
        }
        """

        response = await self._execute_query(graphql_app, query_str)
        assert response.status_code == 200

        result = response.json()
        assert "errors" not in result, f"GraphQL errors: {result.get('errors')}"
        assert "data" in result

        configs = result["data"]["networkConfigurations"]
        assert len(configs) > 0

        config = configs[0]
        assert "smtpServer" in config, f"Expected 'smtpServer', got keys: {list(config.keys())}"
        assert config["smtpServer"]["ipAddress"] == "13.16.1.10"
        assert config["smtpServer"]["port"] == 587

    @pytest.mark.asyncio
    async def test_underscore_number_nested_object_is_present(self, graphql_app) -> None:
        """Numbered fields like dns_1 should convert to dns1."""
        query_str = """
        query GetNetworkConfig {
            networkConfigurations {
                id
                identifier
                dns1 {
                    id
                    identifier
                    ipAddress
                }
                dns2 {
                    id
                    identifier
                    ipAddress
                }
            }
        }
        """

        response = await self._execute_query(graphql_app, query_str)
        assert response.status_code == 200

        result = response.json()
        assert "errors" not in result, f"GraphQL errors: {result.get('errors')}"
        assert "data" in result

        configs = result["data"]["networkConfigurations"]
        assert len(configs) > 0

        config = configs[0]
        assert "dns1" in config, f"Expected 'dns1', got keys: {list(config.keys())}"
        assert "dns2" in config, f"Expected 'dns2', got keys: {list(config.keys())}"
        assert config["dns1"]["ipAddress"] == "120.0.0.1"
        assert config["dns2"]["ipAddress"] == "120.0.0.2"

    @pytest.mark.asyncio
    async def test_array_nested_objects_convert_to_camelcase(self, graphql_app) -> None:
        """Array fields like print_servers should convert to printServers."""
        query_str = """
        query GetNetworkConfig {
            networkConfigurations {
                id
                identifier
                printServers {
                    id
                    identifier
                    hostname
                }
            }
        }
        """

        response = await self._execute_query(graphql_app, query_str)
        assert response.status_code == 200

        result = response.json()
        assert "errors" not in result, f"GraphQL errors: {result.get('errors')}"
        assert "data" in result

        configs = result["data"]["networkConfigurations"]
        assert len(configs) > 0

        config = configs[0]
        assert "printServers" in config, f"Expected 'printServers', got keys: {list(config.keys())}"
        assert len(config["printServers"]) == 2
        assert config["printServers"][0]["hostname"] == "printserver01.local"

    @pytest.mark.asyncio
    async def test_all_nested_fields_in_single_query(self, graphql_app) -> None:
        """Combined test: all nested field types in one query."""
        query_str = """
        query GetNetworkConfig {
            networkConfigurations {
                id
                identifier
                gateway {
                    id
                    identifier
                    ipAddress
                }
                smtpServer {
                    id
                    identifier
                    ipAddress
                }
                dns1 {
                    id
                    identifier
                    ipAddress
                }
                dns2 {
                    id
                    identifier
                    ipAddress
                }
                printServers {
                    id
                    identifier
                    hostname
                }
            }
        }
        """

        response = await self._execute_query(graphql_app, query_str)
        assert response.status_code == 200

        result = response.json()
        assert "errors" not in result, f"GraphQL errors: {result.get('errors')}"

        configs = result["data"]["networkConfigurations"]
        assert len(configs) > 0

        config = configs[0]
        expected_fields = ["gateway", "smtpServer", "dns1", "dns2", "printServers"]
        for field in expected_fields:
            assert field in config, f"Expected '{field}', got: {list(config.keys())}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
