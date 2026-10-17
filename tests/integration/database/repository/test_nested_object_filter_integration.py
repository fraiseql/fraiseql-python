"""Integration test for nested object filtering in GraphQL where inputs."""

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

import psycopg_pool
import pytest
import pytest_asyncio

# Import database fixtures
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.sql import (
    BooleanFilter,
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


class TestNestedObjectFilterIntegration:
    """Test nested object filtering works end-to-end."""

    def test_nested_filter_conversion_to_sql(self) -> None:
        """Test that nested filters are properly converted to SQL where conditions."""
        # Create where input types
        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        # Create a nested filter
        test_machine_id = uuid.uuid4()
        where_input = AllocationWhereInput(
            machine=MachineWhereInput(
                id=UUIDFilter(eq=test_machine_id),
                is_current=BooleanFilter(eq=True),
                name=StringFilter(contains="Server"),
            ),
            status=StringFilter(eq="active"),
        )

        # Convert to SQL where type
        sql_where = where_input._to_sql_where()

        # Verify the conversion worked
        assert hasattr(sql_where, "machine")
        assert hasattr(sql_where, "status")

        # The machine field should contain the nested where conditions
        assert sql_where.machine is not None
        assert sql_where.status == {"eq": "active"}

        # Generate SQL and validate its correctness
        sql = sql_where.to_sql()
        assert sql is not None

        # To properly check the generated SQL, we need to examine the SQL components
        # Check that the nested path is correctly constructed as SQL("data -> 'machine'")
        sql_str = str(sql)

        # The SQL object should contain the nested path for machine fields
        # Looking for SQL("data -> 'machine'") in the representation
        assert "SQL(\"data -> 'machine'\")" in sql_str, (
            f"Expected nested JSONB path for machine fields, but got: {sql_str}"
        )

        # Root level status filter should just use 'data'
        # Count occurrences - should have both nested and root level paths
        assert sql_str.count("SQL(\"data -> 'machine'\")") == 3, (
            f"Expected 3 nested machine paths (for id, name, is_current), but got: {sql_str}"
        )

        assert "SQL('data')" in sql_str, (
            f"Expected root-level data access for status field, but got: {sql_str}"
        )

    def test_nested_filter_with_none_values(self) -> None:
        """Test that None values in nested filters are handled correctly."""
        create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        # Test with None machine filter
        where_input = AllocationWhereInput(
            id=UUIDFilter(eq=uuid.uuid4()), machine=None, status=StringFilter(eq="pending")
        )

        sql_where = where_input._to_sql_where()
        assert sql_where.machine == {}  # No filter on machine
        assert sql_where.status == {"eq": "pending"}

    def test_deeply_nested_filtering(self) -> None:
        """Test multiple levels of nested filtering."""

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

        # Create deeply nested filter
        where_input = AllocationDeepWhereInput(
            machine=MachineWithLocationWhereInput(
                name=StringFilter(startswith="VM"),
                location=LocationWhereInput(
                    city=StringFilter(eq="Seattle"), country=StringFilter(eq="USA")
                ),
            )
        )

        # Convert and verify
        sql_where = where_input._to_sql_where()
        assert hasattr(sql_where, "machine")
        assert sql_where.machine is not None

        # Generate SQL and verify deep nesting paths
        sql = sql_where.to_sql()
        assert sql is not None
        sql_str = str(sql)

        # Check that deeply nested paths are correctly generated
        # Machine name should be at: data -> 'machine' ->> 'name'
        assert "SQL(\"data -> 'machine'\")" in sql_str, (
            f"Expected nested path for machine.name, but got: {sql_str}"
        )

        # Location city should be at: data -> 'machine' -> 'location' ->> 'city'
        assert "SQL(\"data -> 'machine' -> 'location'\")" in sql_str, (
            f"Expected deeply nested path for machine.location.city, but got: {sql_str}"
        )

    def test_mixed_scalar_and_nested_filters(self) -> None:
        """Test mixing scalar and nested object filters."""
        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        # Mix scalar and nested filters
        test_id = uuid.uuid4()
        where_input = AllocationWhereInput(
            id=UUIDFilter(eq=test_id),
            status=StringFilter(in_=["active", "pending"]),
            machine=MachineWhereInput(
                is_current=BooleanFilter(eq=True), name=StringFilter(neq="deprecated")
            ),
        )

        sql_where = where_input._to_sql_where()

        # Verify all filters are present
        assert sql_where.id == {"eq": test_id}
        assert sql_where.status == {"in": ["active", "pending"]}
        assert sql_where.machine is not None

    def test_empty_nested_filter(self) -> None:
        """Test that empty nested filters are handled correctly."""
        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        # Create filter with empty nested filter
        where_input = AllocationWhereInput(
            status=StringFilter(eq="active"),
            machine=MachineWhereInput(),  # Empty filter
        )

        sql_where = where_input._to_sql_where()

        # Empty nested filter should create a nested where object with empty fields
        assert sql_where.status == {"eq": "active"}
        assert sql_where.machine is not None
        # The nested where object should have empty operator dicts
        assert hasattr(sql_where.machine, "id")
        assert sql_where.machine.id == {}
        assert sql_where.machine.name == {}
        assert sql_where.machine.is_current == {}

    def test_nested_camelcase_to_snake_case_conversion_in_sql(self) -> None:
        """Test that camelCase field names are converted to snake_case in nested JSONB paths.

        When filtering on nested object fields, FraiseQL must convert camelCase GraphQL
        field names (e.g., 'isActive', 'isCurrent') to snake_case database field names
        (e.g., 'is_active', 'is_current') in JSONB path queries.

        Expected SQL: data->'machine'->>'is_current' = 'true'
        NOT: data->'machine'->>'isCurrent' = 'true'
        """
        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        # Create nested filter using camelCase field (as it would come from GraphQL)
        where_input = AllocationWhereInput(
            machine=MachineWhereInput(
                is_current=BooleanFilter(eq=True),  # Python uses snake_case
            )
        )

        # Convert to SQL
        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        # Get the actual SQL string by rendering it

        # Use as_string with a mock connection to render the SQL
        try:
            sql_str = sql.as_string(None)
        except (AttributeError, TypeError):
            # Fallback to string representation if as_string doesn't work
            sql_str = str(sql)

        # CRITICAL: Verify that the JSONB path uses snake_case 'is_current'
        # NOT camelCase 'isCurrent'
        assert "'is_current'" in sql_str, (
            f"BUG: Nested JSONB path is not using snake_case field name 'is_current'. "
            f"Generated SQL: {sql_str}. "
            f"This means the filter will query data->'machine'->>'isCurrent' which "
            f"returns NULL instead of data->'machine'->>'is_current' which returns the value."
        )

        # Ensure we're NOT using camelCase
        assert "'isCurrent'" not in sql_str, (
            f"BUG: Nested JSONB path is using camelCase 'isCurrent' instead of snake_case. "
            f"Generated SQL: {sql_str}"
        )

    def test_nested_multiple_camelcase_fields_conversion(self) -> None:
        """Test that multiple camelCase fields in nested objects are all converted to snake_case.

        Test camelCase conversion with multiple nested fields.
        """

        # Create a device type with multiple camelCase fields
        @fraiseql.type
        class Device:
            id: uuid.UUID
            device_name: str
            is_active: bool = False
            last_seen: datetime

        @fraiseql.type
        class Assignment:
            id: uuid.UUID
            device: Device | None
            status: str

        DeviceWhereInput = create_graphql_where_input(Device)
        AssignmentWhereInput = create_graphql_where_input(Assignment)

        # Filter on multiple nested fields with underscores
        where_input = AssignmentWhereInput(
            device=DeviceWhereInput(
                is_active=BooleanFilter(eq=True),
                device_name=StringFilter(contains="router"),
            )
        )

        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        try:
            sql_str = sql.as_string(None)
        except (AttributeError, TypeError):
            sql_str = str(sql)

        # Verify all fields use snake_case in JSONB paths
        assert "'is_active'" in sql_str, (
            f"Field 'is_active' not using snake_case in nested path. SQL: {sql_str}"
        )
        assert "'device_name'" in sql_str, (
            f"Field 'device_name' not using snake_case in nested path. SQL: {sql_str}"
        )

        # Ensure we're not using camelCase versions
        assert "'isActive'" not in sql_str
        assert "'deviceName'" not in sql_str


def _parse_rust_response(result: RustResponseBytes | list[dict] | None) -> list[dict]:
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
    # If not RustResponseBytes or unexpected format, return as list if possible
    if isinstance(result, list):
        return result
    return []


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def setup_test_data(
    class_db_pool: psycopg_pool.AsyncConnectionPool,
    test_schema,
) -> AsyncGenerator[dict[str, uuid.UUID]]:
    """Set up test tables and data for nested object filtering tests."""
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        # Clean up any existing test data

        # Create test table with JSONB data column
        await conn.execute(
            """
            CREATE TABLE test_assignments (
                id UUID PRIMARY KEY,
                data JSONB NOT NULL
            )
            """
        )

        # Create view that extracts nested data
        await conn.execute(
            """
            CREATE VIEW test_assignment_view AS
            SELECT
                id,
                data->>'id' as assignment_id,
                data->>'status' as status,
                data->'device' as device,
                data
            FROM test_assignments
            """
        )

        # Insert test data with nested device objects
        import psycopg.types.json

        test_id_active = uuid.uuid4()
        test_id_inactive = uuid.uuid4()
        test_id_no_device = uuid.uuid4()

        # Insert records one by one with proper JSON handling
        await conn.execute(
            "INSERT INTO test_assignments (id, data) VALUES (%s::uuid, %s::jsonb)",
            (
                str(test_id_active),
                psycopg.types.json.Json(
                    {
                        "id": str(test_id_active),
                        "status": "active",
                        "device": {
                            "id": str(uuid.uuid4()),
                            "name": "router-01",
                            "is_active": True,  # CRITICAL: Using snake_case in JSONB
                        },
                    }
                ),
            ),
        )

        await conn.execute(
            "INSERT INTO test_assignments (id, data) VALUES (%s::uuid, %s::jsonb)",
            (
                str(test_id_inactive),
                psycopg.types.json.Json(
                    {
                        "id": str(test_id_inactive),
                        "status": "active",
                        "device": {
                            "id": str(uuid.uuid4()),
                            "name": "router-02",
                            "is_active": False,  # CRITICAL: Using snake_case in JSONB
                        },
                    }
                ),
            ),
        )

        await conn.execute(
            "INSERT INTO test_assignments (id, data) VALUES (%s::uuid, %s::jsonb)",
            (
                str(test_id_no_device),
                psycopg.types.json.Json(
                    {"id": str(test_id_no_device), "status": "pending", "device": None}
                ),
            ),
        )

    yield {
        "active_id": test_id_active,
        "inactive_id": test_id_inactive,
        "no_device_id": test_id_no_device,
    }
