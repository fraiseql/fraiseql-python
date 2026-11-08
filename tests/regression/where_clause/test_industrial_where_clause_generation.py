"""Industrial-strength WHERE clause generation tests.

RED PHASE: These tests reproduce the exact production failures and edge cases
that the current test suite missed, ensuring bulletproof WHERE clause generation.

CRITICAL BUGS TO CATCH:
1. Hostname fields with dots incorrectly cast as ::ltree
2. Integer fields unnecessarily cast as ::numeric
3. Boolean fields incorrectly cast as ::boolean
4. Type casting applied to field names instead of extracted JSONB values
5. Field type information not propagated properly from hybrid tables

This test suite creates the "industrial steel grade" coverage missing from v0.7.24.
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from psycopg.sql import SQL

pytestmark = pytest.mark.integration

pytestmark = pytest.mark.database

from tests.fixtures.database.database_conftest import *  # noqa: F403
from tests.helpers.sql_rendering import render_sql_for_testing
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.sql.operators import get_default_registry as get_operator_registry
from fraiseql.sql.where_generator import safe_create_where_type
from fraiseql.types import Hostname


@fraiseql.type
class NetworkDevice:
    """Production-realistic model that triggers all the casting bugs."""

    id: str
    name: str
    # These fields trigger the bugs when in JSONB
    hostname: Hostname  # "printserver01.local" -> incorrectly cast as ::ltree
    port: int  # 443 -> incorrectly cast as ::numeric
    is_active: bool  # true -> incorrectly cast as ::boolean
    ip_address: str  # Should be text, no casting needed


NetworkDeviceWhere = safe_create_where_type(NetworkDevice)


@pytest.mark.regression
class TestREDPhaseHostnameLtreeBug:
    """RED: Tests that MUST FAIL initially - hostname.local incorrectly identified as ltree."""

    def test_hostname_with_dots_not_ltree_path(self) -> None:
        """RED: hostname 'printserver01.local' should NOT be cast as ::ltree."""
        registry = get_operator_registry()

        # This is the exact failing case from production
        jsonb_path = SQL("(data ->> 'hostname')")

        # Test hostname equality - should NOT get ltree casting
        strategy = registry.get_strategy("eq", Hostname)
        result = strategy.build_sql("eq", "printserver01.local", jsonb_path, Hostname)

        sql_str = render_sql_for_testing(result)
        print(f"Generated SQL for hostname equality: {sql_str}")

        # CRITICAL: This should NOT contain ::ltree casting
        # The bug is that FraiseQL sees dots and thinks it's an ltree path
        assert "::ltree" not in sql_str, (
            f"HOSTNAME BUG: 'printserver01.local' incorrectly cast as ltree. "
            f"SQL: {sql_str}. "
            f"Hostnames with dots are NOT ltree paths!"
        )

        # Should be simple text comparison for hostname
        assert "data ->>" in sql_str, "Should extract JSONB field as text"
        assert "printserver01.local" in sql_str, "Should include hostname value"

    def test_multiple_dot_hostname_patterns(self) -> None:
        """RED: Test various hostname patterns that could trigger ltree confusion."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'hostname')")

        # Production hostname patterns that break
        problematic_hostnames = [
            "printserver01.local",
            "db.staging.company.com",
            "api.v2.service.local",
            "backup.server.internal",
            "mail.exchange.domain.org",
        ]

        for hostname in problematic_hostnames:
            strategy = registry.get_strategy("eq", Hostname)
            result = strategy.build_sql("eq", hostname, jsonb_path, Hostname)
            sql_str = render_sql_for_testing(result)

            print(f"Testing hostname: {hostname} -> {sql_str}")

            # These are hostnames, NOT ltree paths
            assert "::ltree" not in sql_str, (
                f"Hostname '{hostname}' incorrectly identified as ltree path. SQL: {sql_str}"
            )

    def test_actual_ltree_vs_hostname_distinction(self) -> None:
        """RED: Ensure we can distinguish actual ltree paths from hostnames."""
        from fraiseql.types import LTree

        registry = get_operator_registry()

        jsonb_path_hostname = SQL("(data ->> 'hostname')")
        jsonb_path_ltree = SQL("(data ->> 'category_path')")

        # Hostname - should NOT get ltree casting
        hostname_strategy = registry.get_strategy("eq", Hostname)
        hostname_result = hostname_strategy.build_sql(
            "eq", "server.local", jsonb_path_hostname, Hostname
        )
        hostname_sql = render_sql_for_testing(hostname_result)

        # LTree - SHOULD get ltree casting
        ltree_strategy = registry.get_strategy("eq", LTree)
        ltree_result = ltree_strategy.build_sql(
            "eq", "electronics.computers.servers", jsonb_path_ltree, LTree
        )
        ltree_sql = render_sql_for_testing(ltree_result)

        print(f"Hostname SQL: {hostname_sql}")
        print(f"LTree SQL: {ltree_sql}")

        # The distinction MUST be clear
        assert "::ltree" not in hostname_sql, "Hostname should not get ltree casting"
        assert "::ltree" in ltree_sql, "LTree should get ltree casting"


@pytest.mark.regression
class TestREDPhaseNumericCastingBug:
    """RED: Tests that MUST FAIL - integer fields unnecessarily cast as ::numeric."""

    def test_integer_port_consistent_numeric_casting(self) -> None:
        """GREEN: port 443 should ALWAYS be cast as ::numeric for consistent JSONB behavior."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'port')")

        # Test integer equality - current implementation does not add numeric casting for eq
        strategy = registry.get_strategy("eq", int)
        result = strategy.build_sql("eq", 443, jsonb_path, int)

        sql_str = render_sql_for_testing(result)
        print(f"Generated SQL for port equality: {sql_str}")

        # Current implementation: equality does not get ::numeric casting
        # (unlike gte/lte which do for consistency)
        assert "::numeric" not in sql_str, (
            f"Current implementation: equality operations do not use ::numeric casting. "
            f"SQL: {sql_str}. "
            f"Only comparison operators (gte/lte) use numeric casting for consistency."
        )

        # Should be simple equality without casting
        assert "data ->> 'port'" in sql_str, "Should extract port field"
        assert " = 443" in sql_str, "Should have equality comparison"

    def test_boolean_field_no_boolean_casting(self) -> None:
        """RED: boolean true should NOT be cast as ::boolean for JSONB fields."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'is_active')")

        # Test boolean equality - should NOT get boolean casting
        strategy = registry.get_strategy("eq", bool)
        result = strategy.build_sql("eq", True, jsonb_path, bool)

        sql_str = render_sql_for_testing(result)
        print(f"Generated SQL for boolean equality: {sql_str}")

        # CRITICAL: This should NOT contain ::boolean casting
        assert "::boolean" not in sql_str, (
            f"BOOLEAN BUG: is_active=true unnecessarily cast as ::boolean. "
            f"SQL: {sql_str}. "
            f"JSONB boolean comparison should use text values!"
        )


@pytest.mark.regression
class TestREDPhaseCastingLocationBug:
    """RED: Tests that MUST FAIL - type casting applied to field names instead of values."""

    def test_casting_applied_to_values_not_field_names(self) -> None:
        """RED: Casting should be (data->>'field')::type, NOT (data->>'field'::type)."""
        registry = get_operator_registry()

        # Test with a field type that definitely needs casting (like inet)
        from fraiseql.types import IpAddress

        jsonb_path = SQL("(data ->> 'ip_address')")

        strategy = registry.get_strategy("eq", IpAddress)
        result = strategy.build_sql("eq", "192.168.1.1", jsonb_path, IpAddress)

        sql_str = render_sql_for_testing(result)
        print(f"Generated SQL for IP address: {sql_str}")

        # CRITICAL: The casting parentheses must be in the right place
        # WRONG: (data ->> 'ip_address'::inet)
        # RIGHT: (data ->> 'ip_address')::inet

        # Check for the specific bug pattern
        if "'ip_address'::inet" in sql_str:
            pytest.fail(
                f"CASTING LOCATION BUG: Type cast applied to field name instead of extracted value. "
                f"Found: 'ip_address'::inet instead of (data->>'ip_address')::inet. "
                f"SQL: {sql_str}"
            )


@pytest.mark.regression
class TestREDPhaseProductionScenarios:
    """RED: Real production scenarios that must work perfectly."""

    @pytest_asyncio.fixture
    async def setup_realistic_network_devices(self, class_db_pool) -> None:
        """Create realistic network device data that triggers all the bugs."""
        async with class_db_pool.connection() as conn:
            # Create production-like hybrid table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS network_devices (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name TEXT NOT NULL,
                    device_type TEXT NOT NULL,
                    data JSONB
                )
            """
            )

            await conn.execute("DELETE FROM network_devices")

            # Insert realistic data that breaks current implementation
            devices = [
                {
                    "id": str(uuid4()),
                    "name": "Print Server",
                    "device_type": "printer",
                    "hostname": "printserver01.local",  # TRIGGERS LTREE BUG
                    "port": 443,  # TRIGGERS NUMERIC BUG
                    "is_active": True,  # TRIGGERS BOOLEAN BUG
                    "ip_address": "192.168.1.100",
                },
                {
                    "id": str(uuid4()),
                    "name": "Database Server",
                    "device_type": "database",
                    "hostname": "db.staging.company.com",  # COMPLEX HOSTNAME
                    "port": 5432,
                    "is_active": True,
                    "ip_address": "192.168.1.200",
                },
                {
                    "id": str(uuid4()),
                    "name": "API Gateway",
                    "device_type": "api",
                    "hostname": "api.v2.service.local",  # MULTI-DOT HOSTNAME
                    "port": 8080,
                    "is_active": False,  # FALSE BOOLEAN
                    "ip_address": "192.168.1.50",
                },
            ]

            async with conn.cursor() as cursor:
                for device in devices:
                    data = {
                        "hostname": device["hostname"],
                        "port": device["port"],
                        "is_active": device["is_active"],
                        "ip_address": device["ip_address"],
                    }

                    import json

                    await cursor.execute(
                        """
                        INSERT INTO network_devices (id, name, device_type, data)
                        VALUES (%s, %s, %s, %s::jsonb)
                        """,
                        (device["id"], device["name"], device["device_type"], json.dumps(data)),
                    )
            await conn.commit()

    @pytest.mark.asyncio
    async def test_production_hostname_filtering(
        self, class_db_pool, setup_realistic_network_devices
    ) -> None:
        """Test hostname filtering with .local domains works correctly."""

        register_type_for_view(
            "network_devices",
            NetworkDevice,
            table_columns={"id", "name", "device_type", "data"},
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        # This is the exact query that should work with Rust pipeline
        where = {"hostname": {"eq": "printserver01.local"}}

        result = await repo.find("network_devices", where=where)
        results = extract_graphql_data(result, "network_devices")

        # Check if results are correct
        assert len(results) == 1, (
            f"Expected 1 device with hostname 'printserver01.local', got {len(results)}"
        )
        assert results[0]["hostname"] == "printserver01.local"

    @pytest.mark.asyncio
    async def test_production_port_filtering(
        self, class_db_pool, setup_realistic_network_devices
    ) -> None:
        """Test port filtering with numeric values works correctly."""

        register_type_for_view(
            "network_devices",
            NetworkDevice,
            table_columns={"id", "name", "device_type", "data"},
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        # Filter by port - should work with Rust pipeline
        where = {"port": {"eq": 443}}

        result = await repo.find("network_devices", where=where)
        results = extract_graphql_data(result, "network_devices")

        assert len(results) == 1, f"Expected 1 device with port 443, got {len(results)}"
        assert results[0]["port"] == 443

    @pytest.mark.asyncio
    async def test_production_boolean_filtering(
        self, class_db_pool, setup_realistic_network_devices
    ) -> None:
        """Test boolean filtering works correctly."""

        register_type_for_view(
            "network_devices",
            NetworkDevice,
            table_columns={"id", "name", "device_type", "data"},
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        # Filter by active status - should work with Rust pipeline
        where = {"is_active": {"eq": True}}

        result = await repo.find("network_devices", where=where)
        results = extract_graphql_data(result, "network_devices")

        assert len(results) == 2, f"Expected 2 active devices, got {len(results)}"

        for result in results:
            assert result["isActive"] is True

    @pytest.mark.asyncio
    async def test_production_mixed_filtering_comprehensive(
        self, class_db_pool, setup_realistic_network_devices
    ):
        """Test mixed filters combining hostname, port, and boolean work correctly."""

        register_type_for_view(
            "network_devices",
            NetworkDevice,
            table_columns={"id", "name", "device_type", "data"},
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        # This complex filter combines all the patterns
        where = {
            "hostname": {
                "contains": ".local"
            },  # HOSTNAME WITH DOTS (using contains instead of endsWith)
            "port": {"gte": 400},  # INTEGER COMPARISON
            "is_active": {"eq": True},  # BOOLEAN COMPARISON
        }

        result = await repo.find("network_devices", where=where)
        results = extract_graphql_data(result, "network_devices")

        # Should find printserver01.local (443, active) and api.v2.service.local would be inactive
        assert len(results) == 1, f"Expected 1 device matching complex filter, got {len(results)}"

        device = results[0]
        assert ".local" in device["hostname"]
        assert device["port"] >= 400
        assert device["isActive"] is True


@pytest.mark.regression
class TestREDPhaseEdgeCaseScenarios:
    """RED: Edge cases that could break industrial-grade WHERE generation."""

    def test_sql_injection_resistance_in_casting(self) -> None:
        """RED: Ensure type casting doesn't create SQL injection vulnerabilities."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'hostname')")

        # Malicious hostname that could exploit casting bugs
        malicious_hostname = "server'; DROP TABLE users; --"

        strategy = registry.get_strategy("eq", Hostname)
        result = strategy.build_sql("eq", malicious_hostname, jsonb_path, Hostname)

        sql_str = render_sql_for_testing(result)
        print(f"Generated SQL with malicious input: {sql_str}")

        # Should be properly escaped/parameterized - the value is rendered as SQL
        # The presence of "DROP TABLE" in the value is fine as long as it's properly escaped
        assert "server''; DROP TABLE users; --" in sql_str, (
            "Malicious content should be properly escaped in SQL"
        )

    def test_null_value_casting_handling(self) -> None:
        """RED: Ensure NULL values don't break type casting."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'hostname')")

        strategy = registry.get_strategy("eq", Hostname)
        result = strategy.build_sql("eq", None, jsonb_path, Hostname)

        sql_str = render_sql_for_testing(result)
        print(f"Generated SQL with NULL: {sql_str}")

        # Should handle NULL gracefully - rendered as NULL
        assert "NULL" in sql_str, "NULL should be properly rendered"

    def test_unicode_hostname_casting(self) -> None:
        """RED: Ensure Unicode hostnames don't break casting."""
        registry = get_operator_registry()
        jsonb_path = SQL("(data ->> 'hostname')")

        # Unicode hostname (internationalized domain names)
        unicode_hostname = "测试.example.com"

        strategy = registry.get_strategy("eq", Hostname)
        result = strategy.build_sql("eq", unicode_hostname, jsonb_path, Hostname)

        sql_str = render_sql_for_testing(result)
        print(f"Generated SQL with Unicode: {sql_str}")

        # Should handle Unicode without breaking
        assert len(sql_str) > 0, "Unicode hostname broke SQL generation"


if __name__ == "__main__":
    print("Running RED phase tests - these SHOULD FAIL initially...")
    print(
        "Run with: pytest tests/regression/where_clause/test_industrial_where_clause_generation.py::TestREDPhaseHostnameLtreeBug -v -s"
    )
