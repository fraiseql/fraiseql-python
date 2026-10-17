"""Comprehensive test coverage for nested filter id field handling.

This test suite validates that nested filters on related entity 'id' fields work correctly
across different scenarios: FK-based, JSONB-based, and mixed filtering.

Tests ensure that:
1. FK-based nested filters resolve to SQL FK columns (not JSONB paths)
2. JSONB-based nested filters work for non-id fields
3. Mixed filtering combines both approaches
4. WhereInput and dict-based filters produce identical results
5. Edge cases are handled correctly

Related issues: #124
"""

import json
import logging
import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from tests.fixtures.database.database_conftest import *  # noqa: F403
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.sql import UUIDFilter, create_graphql_where_input

pytestmark = pytest.mark.database


# Define test types
@fraiseql.type
class Machine:
    """Machine type with minimal fields for testing."""

    id: uuid.UUID
    name: str


@fraiseql.type
class Device:
    """Device type for JSONB table testing."""

    id: str  # String ID for JSONB scenario
    is_active: bool


@fraiseql.type(sql_source="tv_allocation")
class Allocation:
    """Allocation type representing a hybrid table.

    Hybrid table structure:
    - SQL columns: id, machine_id, status, tenant_id, data
    - JSONB column 'data' contains: machine object with nested id

    This matches the real-world printoptim_backend structure.
    """

    id: uuid.UUID
    machine: Machine | None  # Nested object from JSONB
    device: Device | None  # For JSONB testing
    status: str | None = None
    tenant_id: uuid.UUID | None = None
    created_at: datetime | None = None


@fraiseql.type(sql_source="tv_jsonb_documents")
class Document:
    """Document type for pure JSONB table testing."""

    id: str
    metadata: dict  # JSONB field that might contain 'id' key


class TestNestedFilterIdField:
    """Comprehensive test suite for nested filter id field handling."""

    @pytest_asyncio.fixture
    async def setup_hybrid_table(self, class_db_pool, test_schema, clear_registry_class) -> dict:
        """Create hybrid allocation table and test data."""
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")

            # Create hybrid table with both SQL columns and JSONB data
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tv_allocation (
                    id UUID PRIMARY KEY,
                    machine_id UUID,  -- SQL FK column
                    device_id TEXT,   -- For JSONB testing
                    status TEXT,
                    tenant_id UUID DEFAULT '11111111-1111-1111-1111-111111111111'::uuid,
                    created_at TIMESTAMP DEFAULT NOW(),
                    data JSONB  -- JSONB column with nested objects
                )
                """
            )

            # Clear existing data
            await conn.execute("DELETE FROM tv_allocation")

            # Create test machines and devices
            machine1_id = uuid.UUID("01513100-0000-0000-0000-000000000066")
            machine2_id = uuid.UUID("02513100-0000-0000-0000-000000000077")
            machine3_id = uuid.UUID("03513100-0000-0000-0000-000000000088")

            # Insert test allocations
            # Machine 1: 0 allocations (for testing zero results)
            # Machine 2: 2 allocations (for testing filtering works)
            # Machine 3: 1 allocation (additional data)

            import json

            allocations = [
                # 2 allocations for machine2
                {
                    "id": uuid.uuid4(),
                    "machine_id": machine2_id,
                    "device_id": "device-001",
                    "status": "active",
                    "data": {
                        "id": str(uuid.uuid4()),
                        "machine": {"id": str(machine2_id), "name": "Printer 2"},
                        "device": {"id": "device-001", "is_active": True},
                        "status": "active",
                    },
                },
                {
                    "id": uuid.uuid4(),
                    "machine_id": machine2_id,
                    "device_id": "device-002",
                    "status": "active",
                    "data": {
                        "id": str(uuid.uuid4()),
                        "machine": {"id": str(machine2_id), "name": "Printer 2"},
                        "device": {"id": "device-002", "is_active": False},
                        "status": "active",
                    },
                },
                # 1 allocation for machine3
                {
                    "id": uuid.uuid4(),
                    "machine_id": machine3_id,
                    "device_id": "device-003",
                    "status": "pending",
                    "data": {
                        "id": str(uuid.uuid4()),
                        "machine": {"id": str(machine3_id), "name": "Printer 3"},
                        "device": {"id": "device-003", "is_active": True},
                        "status": "pending",
                    },
                },
                # 1 allocation with no machine (NULL)
                {
                    "id": uuid.uuid4(),
                    "machine_id": None,
                    "device_id": None,
                    "status": "pending",
                    "data": {
                        "id": str(uuid.uuid4()),
                        "machine": None,
                        "device": None,
                        "status": "pending",
                    },
                },
            ]

            async with conn.cursor() as cursor:
                for alloc in allocations:
                    await cursor.execute(
                        """
                        INSERT INTO tv_allocation (id, machine_id, device_id, status, data)
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            alloc["id"],
                            alloc["machine_id"],
                            alloc["device_id"],
                            alloc["status"],
                            json.dumps(alloc["data"]),
                        ),
                    )
            await conn.commit()

            # Verify data setup
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT COUNT(*) FROM tv_allocation WHERE machine_id = %s",
                    (machine1_id,),
                )
                machine1_count = (await cursor.fetchone())[0]

                await cursor.execute(
                    "SELECT COUNT(*) FROM tv_allocation WHERE machine_id = %s",
                    (machine2_id,),
                )
                machine2_count = (await cursor.fetchone())[0]

                await cursor.execute(
                    "SELECT COUNT(*) FROM tv_allocation WHERE machine_id = %s",
                    (machine3_id,),
                )
                machine3_count = (await cursor.fetchone())[0]

                await cursor.execute("SELECT COUNT(*) FROM tv_allocation")
                total_count = (await cursor.fetchone())[0]

                return {
                    "machine1_id": machine1_id,
                    "machine2_id": machine2_id,
                    "machine3_id": machine3_id,
                    "machine1_count": machine1_count,  # 0
                    "machine2_count": machine2_count,  # 2
                    "machine3_count": machine3_count,  # 1
                    "total_count": total_count,  # 4
                }

    @pytest_asyncio.fixture
    async def setup_jsonb_table(self, class_db_pool, test_schema, clear_registry_class) -> None:
        """Create pure JSONB documents table for edge case testing."""
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tv_jsonb_documents (
                    id TEXT PRIMARY KEY,
                    data JSONB
                )
                """
            )

            await conn.execute("DELETE FROM tv_jsonb_documents")

            # Insert test documents where metadata contains an 'id' field
            documents = [
                {"id": "doc-123", "data": {"metadata": {"id": "doc-123", "type": "report"}}},
                {"id": "doc-456", "data": {"metadata": {"id": "doc-456", "type": "invoice"}}},
            ]

            async with conn.cursor() as cursor:
                for doc in documents:
                    await cursor.execute(
                        "INSERT INTO tv_jsonb_documents (id, data) VALUES (%s, %s::jsonb)",
                        (doc["id"], json.dumps(doc["data"])),
                    )
            await conn.commit()

    async def test_nested_filter_on_related_id_fk_scenario(self, class_db_pool, setup_hybrid_table):
        """Test nested filter using FK column for related object ID.

        Query: allocations(where: { machine: { id: { eq: $machineId } } })
        Expected SQL: WHERE machine_id = $machineId
        """
        test_data = setup_hybrid_table

        # Register hybrid table with explicit column information
        register_type_for_view(
            "tv_allocation",
            Allocation,
            table_columns={
                "id",
                "machine_id",
                "device_id",
                "status",
                "tenant_id",
                "created_at",
                "data",
            },
            has_jsonb_data=True,
            fk_relationships={"machine": "machine_id"},
        )

        repo = FraiseQLRepository(class_db_pool, context={"tenant_id": "test"})

        # Filter for machine2 which has 2 allocations
        where = {"machine": {"id": {"eq": test_data["machine2_id"]}}}

        result = await repo.find("tv_allocation", where=where)
        results = extract_graphql_data(result, "tv_allocation")

        # Should return exactly 2 allocations
        assert len(results) == test_data["machine2_count"], (
            f"Expected {test_data['machine2_count']} allocations for machine2, "
            f"but got {len(results)}"
        )

        # Verify all returned allocations are for the correct machine
        for alloc in results:
            machine = alloc.get("machine")
            assert machine is not None, "Machine should not be None"
            assert machine["id"] == str(test_data["machine2_id"]), (
                f"Allocation machine id {machine['id']} does not match expected {test_data['machine2_id']}"
            )

    async def test_nested_filter_on_related_field_jsonb_scenario(
        self, class_db_pool, setup_hybrid_table
    ):
        """Test nested filter using JSONB path for related object fields.

        Query: allocations(where: { device: { is_active: { eq: true } } })
        Expected SQL: WHERE data->'device'->>'is_active' = 'true'
        """

        register_type_for_view(
            "tv_allocation",
            Allocation,
            table_columns={
                "id",
                "machine_id",
                "device_id",
                "status",
                "tenant_id",
                "created_at",
                "data",
            },
            has_jsonb_data=True,
        )

        repo = FraiseQLRepository(class_db_pool, context={"tenant_id": "test"})

        # Filter for allocations with active devices
        where = {"device": {"is_active": {"eq": True}}}

        result = await repo.find("tv_allocation", where=where)
        results = extract_graphql_data(result, "tv_allocation")

        # Should return allocations with active devices
        assert len(results) == 2, f"Expected 2 allocations with active devices, got {len(results)}"

        for alloc in results:
            device = alloc.get("device")
            assert device is not None, f"Device should not be None, alloc={alloc}"
            assert device["isActive"] is True, f"Device should be active, device={device}"

    async def test_nested_filter_mixed_fk_and_jsonb(self, class_db_pool, setup_hybrid_table):
        """Test nested filter combining FK and JSONB paths.

        Query: allocations(where: {
            machine: {
                id: { eq: $id },
                name: { contains: "Printer" }
            }
        })
        Expected SQL:
            WHERE machine_id = $id
            AND data->'machine'->>'name' LIKE '%Printer%'
        """
        test_data = setup_hybrid_table

        register_type_for_view(
            "tv_allocation",
            Allocation,
            table_columns={
                "id",
                "machine_id",
                "device_id",
                "status",
                "tenant_id",
                "created_at",
                "data",
            },
            has_jsonb_data=True,
        )

        repo = FraiseQLRepository(class_db_pool, context={"tenant_id": "test"})

        # Filter for machine2 AND name contains "Printer"
        where = {
            "machine": {"id": {"eq": test_data["machine2_id"]}, "name": {"contains": "Printer"}}
        }

        result = await repo.find("tv_allocation", where=where)
        results = extract_graphql_data(result, "tv_allocation")

        # Should return exactly 2 allocations (both for machine2)
        assert len(results) == 2, f"Expected 2 allocations, got {len(results)}"

        for alloc in results:
            machine = alloc.get("machine")
            assert machine is not None, "Machine should not be None"
            assert machine["id"] == str(test_data["machine2_id"]), "Should be machine2"
            assert "Printer" in machine["name"], f"Name should contain 'Printer', machine={machine}"

    async def test_whereinput_and_dict_produce_same_results(
        self, class_db_pool, setup_hybrid_table
    ):
        """Ensure WhereInput and dict-based filters return identical results."""
        test_data = setup_hybrid_table

        register_type_for_view(
            "tv_allocation",
            Allocation,
            table_columns={
                "id",
                "machine_id",
                "device_id",
                "status",
                "tenant_id",
                "created_at",
                "data",
            },
            has_jsonb_data=True,
        )

        repo = FraiseQLRepository(class_db_pool, context={"tenant_id": "test"})

        # Query using dict-based filter
        where_dict = {"machine": {"id": {"eq": test_data["machine2_id"]}}}
        result_dict = await repo.find("tv_allocation", where=where_dict)
        results_dict = extract_graphql_data(result_dict, "tv_allocation")

        # Query using WhereInput
        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        where_input = AllocationWhereInput(
            machine=MachineWhereInput(id=UUIDFilter(eq=test_data["machine2_id"]))
        )
        result_input = await repo.find("tv_allocation", where=where_input)
        results_input = extract_graphql_data(result_input, "tv_allocation")

        # Results should be identical
        dict_ids = {alloc["id"] for alloc in results_dict}
        input_ids = {alloc["id"] for alloc in results_input}

        assert dict_ids == input_ids, (
            f"Dict and WhereInput results differ: dict={dict_ids}, input={input_ids}"
        )

        assert len(results_dict) == len(results_input) == test_data["machine2_count"]

    async def test_nested_filter_on_field_literally_named_id(
        self, class_db_pool, setup_jsonb_table
    ):
        """Ensure we don't break tables with JSONB field literally called 'id'.

        Some tables might have a JSONB field called 'id' that's NOT a relationship.
        This should be filtered using JSONB path, not FK column.
        """
        register_type_for_view(
            "tv_jsonb_documents",
            Document,
            table_columns={"id", "data"},
            has_jsonb_data=True,
        )

        repo = FraiseQLRepository(class_db_pool)

        # Filter on metadata.id (JSONB field literally named 'id')
        where = {"metadata": {"id": {"eq": "doc-123"}}}

        result = await repo.find("tv_jsonb_documents", where=where)
        results = extract_graphql_data(result, "tv_jsonb_documents")

        # Should return exactly 1 document
        assert len(results) == 1, f"Expected 1 document, got {len(results)}"

        doc = results[0]
        assert doc["metadata"]["id"] == "doc-123", "Should match the filtered id"

    async def test_whereinput_nested_filter_generates_fk_sql(
        self, class_db_pool, setup_hybrid_table, caplog
    ):
        """Verify WhereInput nested filters generate FK SQL, not JSONB SQL."""
        test_data = setup_hybrid_table

        register_type_for_view(
            "tv_allocation",
            Allocation,
            table_columns={
                "id",
                "machine_id",
                "device_id",
                "status",
                "tenant_id",
                "created_at",
                "data",
            },
            has_jsonb_data=True,
        )

        repo = FraiseQLRepository(class_db_pool, context={"tenant_id": "test"})

        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        where_input = AllocationWhereInput(
            machine=MachineWhereInput(id=UUIDFilter(eq=test_data["machine2_id"]))
        )

        # Capture debug logs to verify FK detection
        with caplog.at_level(logging.DEBUG):
            result = await repo.find("tv_allocation", where=where_input)

        # Should see FK detection log
        fk_logs = [
            r
            for r in caplog.records
            if "FK nested object filter" in r.message or "FK nested filter" in r.message
        ]
        assert len(fk_logs) > 0, "Should detect FK column for machine.id filter"

        # Should NOT see operator strategy failure warning
        warnings = [r for r in caplog.records if "Operator strategy failed" in r.message]
        assert len(warnings) == 0, f"Should not fail with operator warning: {warnings}"

        # Should NOT see "Unsupported operator: id" warning
        unsupported_logs = [r for r in caplog.records if "Unsupported operator: id" in r.message]
        assert len(unsupported_logs) == 0, "Should not try to use JSONB path for id field"

        # Verify correct results
        results = extract_graphql_data(result, "tv_allocation")
        assert len(results) == test_data["machine2_count"]

    async def test_dict_and_whereinput_generate_identical_sql(
        self, class_db_pool, setup_hybrid_table
    ):
        """Verify dict and WhereInput generate identical SQL queries."""
        test_data = setup_hybrid_table

        register_type_for_view(
            "tv_allocation",
            Allocation,
            table_columns={
                "id",
                "machine_id",
                "device_id",
                "status",
                "tenant_id",
                "created_at",
                "data",
            },
            has_jsonb_data=True,
        )

        repo = FraiseQLRepository(class_db_pool, context={"tenant_id": "test"})

        # Normalize both inputs
        where_dict = {"machine": {"id": {"eq": test_data["machine2_id"]}}}

        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)
        where_input = AllocationWhereInput(
            machine=MachineWhereInput(id=UUIDFilter(eq=test_data["machine2_id"]))
        )

        # Get table columns
        table_columns = {
            "id",
            "machine_id",
            "device_id",
            "status",
            "tenant_id",
            "created_at",
            "data",
        }

        # Normalize both
        clause_dict = repo._normalize_where(where_dict, "tv_allocation", table_columns)
        clause_input = repo._normalize_where(where_input, "tv_allocation", table_columns)

        # Should produce identical WhereClause
        assert len(clause_dict.conditions) == len(clause_input.conditions)
        assert clause_dict.conditions[0].field_path == clause_input.conditions[0].field_path
        assert clause_dict.conditions[0].operator == clause_input.conditions[0].operator
        assert clause_dict.conditions[0].value == clause_input.conditions[0].value
        assert (
            clause_dict.conditions[0].lookup_strategy == clause_input.conditions[0].lookup_strategy
        )
        assert clause_dict.conditions[0].target_column == clause_input.conditions[0].target_column

        # Generate SQL from both
        sql_dict, params_dict = clause_dict.to_sql()
        sql_input, params_input = clause_input.to_sql()

        # SQL should be identical
        from psycopg.sql import Composed

        assert isinstance(sql_dict, Composed)
        assert isinstance(sql_input, Composed)
        assert sql_dict.as_string(None) == sql_input.as_string(None)  # type: ignore
        assert params_dict == params_input

        # SQL should use FK column, not JSONB path
        sql_str = sql_dict.as_string(None)  # type: ignore
        assert "machine_id" in sql_str
        assert "data->'machine'" not in sql_str
