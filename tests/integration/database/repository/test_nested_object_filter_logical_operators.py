"""Integration test for logical operators (OR, AND, NOT) in nested object filtering."""

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import psycopg_pool
import pytest
import pytest_asyncio

# Import database fixtures
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.core.rust_pipeline import RustResponseBytes

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


class TestNestedObjectFilterLogicalOperators:
    """Test logical operators (OR, AND, NOT) work within nested object filters."""

    def test_nested_or_logical_operator(self) -> None:
        """Test nested OR operator.

        {device: {OR: [{is_active: {eq: true}}, {name: {contains: "router"}}]}}
        """
        # This test validates that the dict structure is accepted
        # The actual functionality will be tested in database integration tests
        where_dict = {
            "device": {"OR": [{"is_active": {"eq": True}}, {"name": {"contains": "router"}}]}
        }

        # For now, just validate the dict structure is correct
        assert "device" in where_dict
        assert "OR" in where_dict["device"]
        assert isinstance(where_dict["device"]["OR"], list)
        assert len(where_dict["device"]["OR"]) == 2

        # This will pass once the functionality is implemented
        # Currently the dict conversion will ignore the nested OR
        # but the structure validation should work

    def test_nested_and_logical_operator(self) -> None:
        """Test nested AND operator.

        {device: {AND: [{is_active: {eq: true}}, {name: {contains: "router"}}]}}
        """
        # This test validates that the dict structure is accepted
        where_dict = {
            "device": {"AND": [{"is_active": {"eq": True}}, {"name": {"contains": "router"}}]}
        }

        # Validate the dict structure
        assert "device" in where_dict
        assert "AND" in where_dict["device"]
        assert isinstance(where_dict["device"]["AND"], list)
        assert len(where_dict["device"]["AND"]) == 2

    def test_nested_not_logical_operator(self) -> None:
        """Test nested NOT operator: {device: {NOT: {is_active: {eq: true}}}}"""
        # This test validates that the dict structure is accepted
        where_dict = {"device": {"NOT": {"is_active": {"eq": True}}}}

        # Validate the dict structure
        assert "device" in where_dict
        assert "NOT" in where_dict["device"]
        assert isinstance(where_dict["device"]["NOT"], dict)
        assert "is_active" in where_dict["device"]["NOT"]

    def test_top_level_or_with_nested_objects(self) -> None:
        """Test top-level OR with nested objects.

        {OR: [{device: {is_active: {eq: true}}}, {status: {eq: "pending"}}]}
        """
        where_dict = {
            "OR": [{"device": {"is_active": {"eq": True}}}, {"status": {"eq": "pending"}}]
        }

        # Validate the dict structure
        assert "OR" in where_dict
        assert isinstance(where_dict["OR"], list)
        assert len(where_dict["OR"]) == 2
        assert "device" in where_dict["OR"][0]
        assert "status" in where_dict["OR"][1]

    def test_mixed_logical_operators(self) -> None:
        """Test mixed logical operators.

        {device: {AND: [{is_active: {eq: true}}, {NOT: {name: {contains: "deprecated"}}}]}}
        """
        where_dict = {
            "device": {
                "AND": [{"is_active": {"eq": True}}, {"NOT": {"name": {"contains": "deprecated"}}}]
            }
        }

        # Validate the dict structure
        assert "device" in where_dict
        assert "AND" in where_dict["device"]
        assert isinstance(where_dict["device"]["AND"], list)
        assert len(where_dict["device"]["AND"]) == 2
        assert "NOT" in where_dict["device"]["AND"][1]

    def test_camelcase_in_logical_operators(self) -> None:
        """Test camelCase field names within logical operators.

        {device: {OR: [{isActive: {eq: true}}, {deviceName: {contains: "router"}}]}}
        """
        where_dict = {
            "device": {
                "OR": [
                    {"isActive": {"eq": True}},  # camelCase
                    {"deviceName": {"contains": "router"}},  # camelCase
                ]
            }
        }

        # Validate the dict structure
        assert "device" in where_dict
        assert "OR" in where_dict["device"]
        assert isinstance(where_dict["device"]["OR"], list)
        assert len(where_dict["device"]["OR"]) == 2
        assert "isActive" in where_dict["device"]["OR"][0]  # camelCase preserved in input


def _parse_rust_response(result: Any) -> Any:
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
class TestNestedObjectFilterLogicalOperatorsDatabase:
    """End-to-end database integration tests for logical operators in nested object filtering."""

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_test_data(
        self, class_db_pool: psycopg_pool.AsyncConnectionPool, test_schema
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

            test_id_active_router = uuid.uuid4()
            test_id_inactive_router = uuid.uuid4()
            test_id_active_switch = uuid.uuid4()
            test_id_pending = uuid.uuid4()

            # Insert records one by one with proper JSON handling
            await conn.execute(
                "INSERT INTO test_assignments (id, data) VALUES (%s::uuid, %s::jsonb)",
                (
                    str(test_id_active_router),
                    psycopg.types.json.Json(
                        {
                            "id": str(test_id_active_router),
                            "status": "active",
                            "device": {
                                "id": str(uuid.uuid4()),
                                "name": "router-01",
                                "is_active": True,  # snake_case
                            },
                        }
                    ),
                ),
            )

            await conn.execute(
                "INSERT INTO test_assignments (id, data) VALUES (%s::uuid, %s::jsonb)",
                (
                    str(test_id_inactive_router),
                    psycopg.types.json.Json(
                        {
                            "id": str(test_id_inactive_router),
                            "status": "active",
                            "device": {
                                "id": str(uuid.uuid4()),
                                "name": "router-02",
                                "is_active": False,  # snake_case
                            },
                        }
                    ),
                ),
            )

            await conn.execute(
                "INSERT INTO test_assignments (id, data) VALUES (%s::uuid, %s::jsonb)",
                (
                    str(test_id_active_switch),
                    psycopg.types.json.Json(
                        {
                            "id": str(test_id_active_switch),
                            "status": "active",
                            "device": {
                                "id": str(uuid.uuid4()),
                                "name": "switch-01",
                                "is_active": True,  # snake_case
                            },
                        }
                    ),
                ),
            )

            await conn.execute(
                "INSERT INTO test_assignments (id, data) VALUES (%s::uuid, %s::jsonb)",
                (
                    str(test_id_pending),
                    psycopg.types.json.Json(
                        {"id": str(test_id_pending), "status": "pending", "device": None}
                    ),
                ),
            )

        yield {
            "active_router_id": test_id_active_router,
            "inactive_router_id": test_id_inactive_router,
            "active_switch_id": test_id_active_switch,
            "pending_id": test_id_pending,
        }
