"""Test nested object filtering on hybrid tables with both SQL columns and JSONB data.

This test addresses the issue where FraiseQL fails to properly handle nested object
filters like {machine: {id: {eq: $machineId}}} on hybrid tables that have both
a SQL column (machine_id) and equivalent JSONB path (data->'machine'->>'id').

Issue: FraiseQL v0.9.4 logs "Unsupported operator: id" and returns incorrect results.
"""

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.database

from tests.fixtures.database.database_conftest import *  # noqa: F403
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.sql import UUIDFilter, create_graphql_where_input


@fraiseql.type
class Machine:
    """Machine type with just the essentials."""

    id: uuid.UUID
    name: str


@fraiseql.type
class Location:
    """Location type for testing."""

    id: uuid.UUID
    name: str


@fraiseql.type(sql_source="tv_allocation")
class Allocation:
    """Allocation type representing a hybrid table with both SQL columns and JSONB."""

    id: uuid.UUID
    machine: Machine | None  # Nested object from JSONB
    location: Location | None  # Another nested object from JSONB
    status: str | None = None
    tenant_id: uuid.UUID | None = None


class TestHybridTableNestedObjectFiltering:
    """Test that nested object filtering works correctly on hybrid tables."""

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_hybrid_allocation_table(self, class_db_pool, test_schema) -> dict:
        """Create a hybrid allocation table matching the issue description."""
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            # Create table with both SQL columns and JSONB data
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tv_allocation (
                    -- SQL columns
                    id UUID PRIMARY KEY,
                    machine_id UUID,  -- SQL column for foreign key
                    location_id UUID,  -- Another SQL column
                    status TEXT,
                    tenant_id UUID DEFAULT '11111111-1111-1111-1111-111111111111'::uuid,

                    -- JSONB column containing nested objects
                    data JSONB
                )
            """
            )

            # Clear existing data
            await conn.execute("DELETE FROM tv_allocation")

            # Test data setup
            machine1_id = uuid.UUID(
                "01513100-0000-0000-0000-000000000066"
            )  # Machine with 0 allocations
            machine2_id = uuid.UUID(
                "02513100-0000-0000-0000-000000000077"
            )  # Machine with allocations
            location1_id = uuid.uuid4()

            # Insert allocations - matching the issue where machine1 has 0 allocations
            allocations = [
                # 2 allocations for machine2
                {
                    "id": uuid.uuid4(),
                    "machine_id": machine2_id,
                    "location_id": location1_id,
                    "status": "active",
                    "data": {
                        "id": str(uuid.uuid4()),
                        "machine": {"id": str(machine2_id), "name": "Machine 2"},
                        "location": {"id": str(location1_id), "name": "Location 1"},
                        "status": "active",
                    },
                },
                {
                    "id": uuid.uuid4(),
                    "machine_id": machine2_id,
                    "location_id": location1_id,
                    "status": "active",
                    "data": {
                        "id": str(uuid.uuid4()),
                        "machine": {"id": str(machine2_id), "name": "Machine 2"},
                        "location": {"id": str(location1_id), "name": "Location 1"},
                        "status": "active",
                    },
                },
                # 1 allocation with no machine (NULL)
                {
                    "id": uuid.uuid4(),
                    "machine_id": None,
                    "location_id": location1_id,
                    "status": "pending",
                    "data": {
                        "id": str(uuid.uuid4()),
                        "machine": None,
                        "location": {"id": str(location1_id), "name": "Location 1"},
                        "status": "pending",
                    },
                },
            ]

            import json

            async with conn.cursor() as cursor:
                for alloc in allocations:
                    await cursor.execute(
                        """
                        INSERT INTO tv_allocation (id, machine_id, location_id, status, data)
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            alloc["id"],
                            alloc["machine_id"],
                            alloc["location_id"],
                            alloc["status"],
                            json.dumps(alloc["data"]),
                        ),
                    )
            await conn.commit()

            # Verify data setup
            async with conn.cursor() as cursor:
                # Machine 1 should have 0 allocations
                await cursor.execute(
                    "SELECT COUNT(*) FROM tv_allocation WHERE machine_id = %s", (machine1_id,)
                )
                machine1_count = (await cursor.fetchone())[0]

                # Machine 2 should have 2 allocations
                await cursor.execute(
                    "SELECT COUNT(*) FROM tv_allocation WHERE machine_id = %s", (machine2_id,)
                )
                machine2_count = (await cursor.fetchone())[0]

                # Total should be 3
                await cursor.execute("SELECT COUNT(*) FROM tv_allocation")
                total_count = (await cursor.fetchone())[0]

                return {
                    "machine1_id": machine1_id,
                    "machine2_id": machine2_id,
                    "machine1_allocations": machine1_count,  # Should be 0
                    "machine2_allocations": machine2_count,  # Should be 2
                    "total_allocations": total_count,  # Should be 3
                }

    @pytest.mark.asyncio
    async def test_nested_object_filter_on_hybrid_table(
        self, class_db_pool, test_schema, setup_hybrid_allocation_table
    ):
        """Test the exact scenario from the issue: nested machine.id filtering.

        This should use the SQL column machine_id for efficient filtering,
        but currently fails with "Unsupported operator: id" warning.
        """
        test_data = setup_hybrid_allocation_table

        # Register the hybrid table with explicit column information
        register_type_for_view(
            "tv_allocation",
            Allocation,
            table_columns={"id", "machine_id", "location_id", "status", "tenant_id", "data"},
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        # Create the nested filter exactly as in the issue report
        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        # Filter for machine1 which has 0 allocations
        where = AllocationWhereInput(
            machine=MachineWhereInput(id=UUIDFilter(eq=test_data["machine1_id"]))
        )

        # This should return 0 records but currently fails
        result = await repo.find("tv_allocation", where=where)

        # Extract data from RustResponseBytes
        results = extract_graphql_data(result, "tv_allocation")

        # EXPECTED: 0 allocations for machine1
        # ACTUAL (BUG): Returns incorrect number due to "Unsupported operator: id" error
        assert len(results) == test_data["machine1_allocations"], (
            f"Expected {test_data['machine1_allocations']} allocations for machine1, "
            f"but got {len(results)}. "
            "FraiseQL is failing to handle nested object filtering on hybrid tables."
        )

    @pytest.mark.asyncio
    async def test_nested_object_filter_with_results(
        self, class_db_pool, test_schema, setup_hybrid_allocation_table
    ) -> None:
        """Test nested filtering for a machine that has allocations."""
        test_data = setup_hybrid_allocation_table

        register_type_for_view(
            "tv_allocation",
            Allocation,
            table_columns={"id", "machine_id", "location_id", "status", "tenant_id", "data"},
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        # Filter for machine2 which has 2 allocations
        where = AllocationWhereInput(
            machine=MachineWhereInput(id=UUIDFilter(eq=test_data["machine2_id"]))
        )

        result = await repo.find("tv_allocation", where=where)

        # Extract data from RustResponseBytes
        results = extract_graphql_data(result, "tv_allocation")

        assert len(results) == test_data["machine2_allocations"], (
            f"Expected {test_data['machine2_allocations']} allocations for machine2, "
            f"but got {len(results)}"
        )

    @pytest.mark.asyncio
    async def test_direct_sql_comparison(
        self, class_db_pool, test_schema, setup_hybrid_allocation_table
    ) -> None:
        """Verify that direct SQL works correctly, proving the issue is in FraiseQL."""
        test_data = setup_hybrid_allocation_table

        async with class_db_pool.connection() as conn, conn.cursor() as cursor:
            # Test that SQL column filtering works
            await cursor.execute(
                "SELECT id FROM tv_allocation WHERE machine_id = %s",
                (test_data["machine1_id"],),
            )
            sql_results = await cursor.fetchall()

            assert len(sql_results) == 0, "Direct SQL confirms machine1 has 0 allocations"

            # Test JSONB path filtering (what FraiseQL might incorrectly try)
            await cursor.execute(
                """
                    SELECT id FROM tv_allocation
                    WHERE data->'machine'->>'id' = %s
                    """,
                (str(test_data["machine1_id"]),),
            )
            jsonb_results = await cursor.fetchall()

            assert len(jsonb_results) == 0, "JSONB path filtering also confirms 0 allocations"

    @pytest.mark.asyncio
    async def test_multiple_nested_object_filters(
        self, class_db_pool, test_schema, setup_hybrid_allocation_table
    ) -> None:
        """Test filtering with multiple nested object conditions."""
        test_data = setup_hybrid_allocation_table

        register_type_for_view(
            "tv_allocation",
            Allocation,
            table_columns={"id", "machine_id", "location_id", "status", "tenant_id", "data"},
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        MachineWhereInput = create_graphql_where_input(Machine)
        create_graphql_where_input(Location)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        # Complex filter with both machine and location nested filters
        where = AllocationWhereInput(
            machine=MachineWhereInput(id=UUIDFilter(eq=test_data["machine2_id"])),
            # Could also add location filter here
        )

        result = await repo.find("tv_allocation", where=where)

        # Extract data from RustResponseBytes
        results = extract_graphql_data(result, "tv_allocation")

        # Should work for complex nested filtering too
        assert len(results) == test_data["machine2_allocations"]

    @pytest.mark.asyncio
    async def test_dict_based_nested_filter(
        self, class_db_pool, test_schema, setup_hybrid_allocation_table
    ) -> None:
        """Test using dictionary-based nested filters (common in GraphQL resolvers)."""
        test_data = setup_hybrid_allocation_table

        register_type_for_view(
            "tv_allocation",
            Allocation,
            table_columns={"id", "machine_id", "location_id", "status", "tenant_id", "data"},
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        # Dictionary-based filter that might come from GraphQL
        where = {"machine": {"id": {"eq": test_data["machine1_id"]}}}

        # This pattern should also work correctly
        result = await repo.find("tv_allocation", where=where)
        results = extract_graphql_data(result, "tv_allocation")

        assert len(results) == test_data["machine1_allocations"], (
            f"Dict-based nested filter failed. Expected {test_data['machine1_allocations']}, "
            f"got {len(results)}"
        )
