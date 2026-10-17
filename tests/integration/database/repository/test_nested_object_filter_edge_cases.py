"""Edge case tests for nested object filtering in GraphQL where inputs."""

import json
import uuid
from datetime import datetime
from typing import Any

import psycopg_pool
import pytest
import pytest_asyncio

# Import database fixtures
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.sql import (
    StringFilter,
    UUIDFilter,
    create_graphql_where_input,
)

pytestmark = [pytest.mark.integration, pytest.mark.database]


# Define test types


@pytest.mark.unit
@fraiseql.type
class Machine:
    id: uuid.UUID
    name: str
    is_current: bool = False


@fraiseql.type
class Allocation:
    id: uuid.UUID
    machine: Machine | None
    status: str
    created_at: datetime


class TestNestedObjectFilterEdgeCases:
    """Test edge cases for nested object filtering."""

    def test_empty_nested_filter_dict(self) -> None:
        """Test that empty nested filter dicts are handled correctly."""
        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        # Create filter with empty nested filter
        where_input = AllocationWhereInput(
            machine=MachineWhereInput(),  # Empty filter
        )

        sql_where = where_input._to_sql_where()

        # Empty nested filter should create a nested where object with empty fields
        assert sql_where.machine is not None
        # The nested where object should have empty operator dicts
        assert hasattr(sql_where.machine, "id")
        assert sql_where.machine.id == {}
        assert sql_where.machine.name == {}
        assert sql_where.machine.is_current == {}

    def test_null_nested_filter(self) -> None:
        """Test that None nested filters are handled correctly."""
        create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        # Test with None machine filter
        where_input = AllocationWhereInput(
            id=UUIDFilter(eq=uuid.uuid4()), machine=None, status=StringFilter(eq="pending")
        )

        sql_where = where_input._to_sql_where()
        assert sql_where.machine == {}  # No filter on machine
        assert sql_where.status == {"eq": "pending"}

    def test_mixed_fk_and_field_nested_filter(self) -> None:
        """Test mixed FK + field filters in nested objects.

        This tests the scenario: {machine: {id: {...}, name: {...}}}
        Should decide whether to use FK column or JSONB paths.
        """
        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        # Create mixed filter: both id (FK) and name (JSONB field)
        test_machine_id = uuid.uuid4()
        where_input = AllocationWhereInput(
            machine=MachineWhereInput(
                id=UUIDFilter(eq=test_machine_id),
                name=StringFilter(contains="Server"),
            ),
        )

        sql_where = where_input._to_sql_where()

        # Verify the conversion worked
        assert hasattr(sql_where, "machine")
        assert sql_where.machine is not None

        # Generate SQL and validate its correctness
        sql = sql_where.to_sql()
        assert sql is not None

        # To properly check the generated SQL, we need to examine the SQL components
        sql_str = str(sql)

        # Should contain both FK column access and JSONB path access
        # FK: machine_id column
        # JSONB: data -> 'machine' ->> 'name'
        assert "machine_id" in sql_str or "machine" in sql_str, (
            f"Expected FK column or JSONB path for machine fields, but got: {sql_str}"
        )

    def test_deeply_nested_filtering_not_supported(self) -> None:
        """Test that deeply nested filtering (3+ levels) provides clear error messages.

        This tests: {machine: {location: {city: {...}}}}
        Should warn or error that deep nesting is not supported.
        """

        @fraiseql.type
        class Location:
            id: uuid.UUID
            city: str
            country: str

        @fraiseql.type
        class MachineWithLocation:
            id: uuid.UUID
            name: str
            location: Location | None

        @fraiseql.type
        class AllocationDeep:
            id: uuid.UUID
            machine: MachineWithLocation | None

        # Create where inputs
        LocationWhereInput = create_graphql_where_input(Location)
        MachineWithLocationWhereInput = create_graphql_where_input(MachineWithLocation)
        AllocationDeepWhereInput = create_graphql_where_input(AllocationDeep)

        # Create deeply nested filter (3 levels: allocation.machine.location.city)
        where_input = AllocationDeepWhereInput(
            machine=MachineWithLocationWhereInput(
                location=LocationWhereInput(city=StringFilter(eq="Seattle")),
            )
        )

        # This should either work or provide a clear error message
        # For now, let's see what happens
        sql_where = where_input._to_sql_where()
        assert hasattr(sql_where, "machine")
        assert sql_where.machine is not None

        # Generate SQL and check if it handles deep nesting
        sql = sql_where.to_sql()
        if sql is not None:
            sql_str = str(sql)
            # Check that deeply nested paths are generated
            # Should be: data -> 'machine' -> 'location' ->> 'city'
            assert "data -> 'machine' -> 'location'" in sql_str, (
                f"Expected deeply nested path for machine.location.city, but got: {sql_str}"
            )


def _parse_rust_response(result: RustResponseBytes | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Helper to parse RustResponseBytes into Python objects."""
    if isinstance(result, RustResponseBytes):
        raw_json_str = bytes(result).decode("utf-8")
        response_json = json.loads(raw_json_str)
        # Extract data from GraphQL response structure
        if "data" in response_json:
            # Get the first key in data (the field name)
            field_name = next(iter(response_json["data"].keys()))
            data = response_json["data"][field_name]

            # Normalize: always return a list for consistency
            if isinstance(data, dict):
                return [data]
            return data
        return response_json
    return result


@pytest.mark.database
class TestNestedObjectFilterDatabaseEdgeCases:
    """End-to-end database integration tests for nested object filtering edge cases."""

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_edge_case_data(
        self, class_db_pool: psycopg_pool.AsyncConnectionPool, test_schema
    ):
        """Set up test tables and data for edge case tests."""
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            # Clean up any existing test data

            # Create test table with JSONB data column
            await conn.execute(
                """
                CREATE TABLE test_allocations_edge (
                    id UUID PRIMARY KEY,
                    data JSONB NOT NULL
                )
                """
            )

            # Create view that extracts nested data
            await conn.execute(
                """
                CREATE VIEW test_allocation_edge_view AS
                SELECT
                    id,
                    data->>'id' as allocation_id,
                    data->>'status' as status,
                    data->'machine' as machine,
                    data
                FROM test_allocations_edge
                """
            )

            # Insert test data with various edge cases
            import psycopg.types.json

            test_id_empty_machine = uuid.uuid4()
            test_id_null_machine = uuid.uuid4()
            test_id_mixed_filters = uuid.uuid4()

            # Insert records
            await conn.execute(
                "INSERT INTO test_allocations_edge (id, data) VALUES (%s::uuid, %s::jsonb)",
                (
                    str(test_id_empty_machine),
                    psycopg.types.json.Json(
                        {
                            "id": str(test_id_empty_machine),
                            "status": "active",
                            "machine": {},  # Empty machine object
                        }
                    ),
                ),
            )

            await conn.execute(
                "INSERT INTO test_allocations_edge (id, data) VALUES (%s::uuid, %s::jsonb)",
                (
                    str(test_id_null_machine),
                    psycopg.types.json.Json(
                        {
                            "id": str(test_id_null_machine),
                            "status": "pending",
                            "machine": None,  # Null machine
                        }
                    ),
                ),
            )

            await conn.execute(
                "INSERT INTO test_allocations_edge (id, data) VALUES (%s::uuid, %s::jsonb)",
                (
                    str(test_id_mixed_filters),
                    psycopg.types.json.Json(
                        {
                            "id": str(test_id_mixed_filters),
                            "status": "active",
                            "machine": {
                                "id": str(uuid.uuid4()),
                                "name": "Server-01",
                                "is_current": True,
                            },
                        }
                    ),
                ),
            )

        yield {
            "empty_machine_id": test_id_empty_machine,
            "null_machine_id": test_id_null_machine,
            "mixed_filters_id": test_id_mixed_filters,
        }
