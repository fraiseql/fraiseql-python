"""Test for dict WHERE filter bug with mixed nested and direct filters.

This test reproduces Issue #117: When using dict-based WHERE filters (not GraphQL
where types) with a mix of nested object filters (e.g., {machine: {id: {eq: value}}})
and direct field filters (e.g., {is_current: {eq: true}}), the second filter is
incorrectly skipped due to variable scoping bug in _convert_dict_where_to_sql().

Root cause: is_nested_object flag is declared outside the field iteration loop,
causing it to carry state between iterations.
"""

import json
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.database

from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.db import register_type_for_view


# Test types
@fraiseql.type
class Machine:
    id: UUID
    name: str


@fraiseql.type
class RouterConfig:
    id: UUID
    machine_id: UUID
    config_name: str
    is_current: bool
    created_at: datetime
    machine: Optional[Machine] = None


def _parse_rust_response(result) -> list[dict[str, Any]] | dict[str, Any]:
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
            # The Rust pipeline returns a single object when there's 1 result
            # but tests expect a list
            if isinstance(data, dict):
                return [data]
            return data
        return response_json
    return result


class TestDictWhereMixedFiltersBug:
    """Test suite to reproduce and fix the dict WHERE mixed filters bug."""

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_test_tables(
        self, class_db_pool, test_schema
    ) -> AsyncGenerator[dict[str, UUID]]:
        """Create test tables for machines and router configs."""
        # Register types for views
        register_type_for_view("test_machine_view", Machine)
        register_type_for_view("test_router_config_view", RouterConfig)

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            # Create tables
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_machines (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL
                )
            """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_router_configs (
                    id UUID PRIMARY KEY,
                    machine_id UUID NOT NULL REFERENCES test_machines(id),
                    config_name TEXT NOT NULL,
                    is_current BOOLEAN NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL
                )
            """
            )

            # Create views with JSONB data column
            await conn.execute(
                """
                CREATE OR REPLACE VIEW test_machine_view AS
                SELECT
                    id, name,
                    jsonb_build_object(
                        'id', id,
                        'name', name
                    ) as data
                FROM test_machines
            """
            )

            await conn.execute(
                """
                CREATE OR REPLACE VIEW test_router_config_view AS
                SELECT
                    rc.id,
                    rc.machine_id,
                    rc.config_name,
                    rc.is_current,
                    rc.created_at,
                    jsonb_build_object(
                        'id', rc.id,
                        'machine_id', rc.machine_id,
                        'config_name', rc.config_name,
                        'is_current', rc.is_current,
                        'created_at', rc.created_at,
                        'machine', jsonb_build_object(
                            'id', m.id,
                            'name', m.name
                        )
                    ) as data
                FROM test_router_configs rc
                LEFT JOIN test_machines m ON rc.machine_id = m.id
            """
            )

            # Insert test data
            machine_1_id = uuid4()
            machine_2_id = uuid4()

            await conn.execute(
                """
                INSERT INTO test_machines (id, name)
                VALUES
                    (%s, 'router-01'),
                    (%s, 'router-02')
            """,
                (machine_1_id, machine_2_id),
            )

            # Insert router configs for machine_1
            # - 2 configs for machine_1, only 1 is current
            # - 2 configs for machine_2, only 1 is current
            await conn.execute(
                """
                INSERT INTO test_router_configs (id, machine_id, config_name, is_current, created_at)
                VALUES
                    (%s, %s, 'config-v1', false, '2024-01-01 10:00:00+00'),
                    (%s, %s, 'config-v2', true, '2024-01-02 10:00:00+00'),
                    (%s, %s, 'config-v1', false, '2024-01-01 10:00:00+00'),
                    (%s, %s, 'config-v2', true, '2024-01-02 10:00:00+00')
            """,
                (
                    uuid4(),
                    machine_1_id,
                    uuid4(),
                    machine_1_id,
                    uuid4(),
                    machine_2_id,
                    uuid4(),
                    machine_2_id,
                ),
            )

        yield {
            "machine_1_id": machine_1_id,
            "machine_2_id": machine_2_id,
        }
