"""Test enum variables with FraiseQL database integration.

This test reproduces the bug as it would occur with real database queries
using FraiseQL's db.find() method with enum filtering.
"""

from enum import Enum
from unittest.mock import AsyncMock, MagicMock

import pytest
from graphql import graphql

import fraiseql


pytestmark = pytest.mark.regression


@fraiseql.enum
class Period(Enum):
    """Time period for allocations."""

    CURRENT = "CURRENT"
    STOCK = "STOCK"
    PAST = "PAST"
    FUTURE = "FUTURE"


@fraiseql.type
class Machine:
    """Machine type with nested fields."""

    id: str
    name: str
    model: str


@fraiseql.type
class Allocation:
    """Allocation with nested object."""

    id: str
    machine_id: str
    location: str
    machine: Machine | None = None
    period: Period | None = None
    is_current: bool = False
    is_stock_current: bool = False


class MockDatabase:
    """Mock database that simulates FraiseQL's db behavior."""

    async def find(self, table: str, **kwargs) -> list[dict]:
        """Simulate db.find() with filtering."""
        # Extract filters from kwargs
        filters = {k: v for k, v in kwargs.items() if k not in ["info", "where", "limit", "offset", "order_by", "tenant_id"]}

        # Simulate database query results based on filters
        all_allocations = [
            {
                "id": "1",
                "machine_id": "m1",
                "location": "Floor1",
                "machine": {"id": "m1", "name": "PrinterA", "model": "ModelX"},
                "is_current": True,
                "is_stock_current": False,
                "is_past": False,
                "is_future": False,
            },
            {
                "id": "2",
                "machine_id": "m2",
                "location": "Warehouse",
                "machine": {"id": "m2", "name": "PrinterB", "model": "ModelY"},
                "is_current": False,
                "is_stock_current": True,
                "is_past": False,
                "is_future": False,
            },
            {
                "id": "3",
                "machine_id": "m3",
                "location": "Archive",
                "machine": {"id": "m3", "name": "PrinterC", "model": "ModelZ"},
                "is_current": False,
                "is_stock_current": False,
                "is_past": True,
                "is_future": False,
            },
        ]

        # Apply filters
        results = []
        for alloc in all_allocations:
            match = True
            for key, value in filters.items():
                if alloc.get(key) != value:
                    match = False
                    break
            if match:
                results.append(alloc)

        return results

    async def find_one(self, table: str, **kwargs) -> dict | None:
        """Simulate db.find_one()."""
        results = await self.find(table, **kwargs)
        return results[0] if results else None


class TestEnumVariablesWithDatabase:
    """Test enum variables with simulated database integration."""

    @pytest.mark.asyncio
    async def test_enum_variable_with_db_find(self, clear_registry) -> None:
        """Test enum variable parameter filtering with db.find()."""
        debug_info = []

        async def allocations(
            info,
            period: Period | None = None,
        ) -> list[Allocation]:
            """Query resolver that uses db.find() with enum filtering."""
            db = MockDatabase()
            tenant_id = "test-tenant"

            # Track what type we received
            debug_info.append(f"period type: {type(period).__name__}, value: {period}")

            # Build period filters (like in printoptim_backend)
            period_filters = {}
            if period:
                # Workaround for the bug: enum might come as string
                if isinstance(period, str):
                    try:
                        period = Period[period]
                    except KeyError:
                        period = None

                # Map period to column filters
                if period == Period.CURRENT:
                    period_filters["is_current"] = True
                elif period == Period.STOCK:
                    period_filters["is_stock_current"] = True
                elif period == Period.PAST:
                    period_filters["is_past"] = True
                elif period == Period.FUTURE:
                    period_filters["is_future"] = True

            # Execute db.find() with filters
            results = await db.find(
                "allocation",
                info=info,
                tenant_id=tenant_id,
                **period_filters,
            )

            # Convert dicts to Allocation objects
            return [
                Allocation(
                    id=r["id"],
                    machine_id=r["machine_id"],
                    location=r["location"],
                    machine=Machine(**r["machine"]) if r.get("machine") else None,
                    period=period,
                    is_current=r.get("is_current", False),
                    is_stock_current=r.get("is_stock_current", False),
                )
                for r in results
            ]

        schema = fraiseql.build_fraiseql_schema(query_types=[allocations])

        # Test 1: Inline literal
        inline_query = """
        {
            allocations(period: CURRENT) {
                id
                location
                machine {
                    name
                    model
                }
                period
                isCurrent
            }
        }
        """

        result = await graphql(schema, inline_query)
        print(f"\nINLINE RESULT: {result.data}, errors: {result.errors}")
        print(f"DEBUG INFO: {debug_info}")
        assert result.errors is None or len(result.errors) == 0, f"Inline errors: {result.errors}"
        allocations = result.data.get("allocations") if result.data else []
        print(f"Allocations count: {len(allocations)}")
        if allocations:
            assert allocations[0]["location"] == "Floor1"
            assert allocations[0]["machine"]["name"] == "PrinterA"
            print(f"\n✅ INLINE: {debug_info[-1]}")
        else:
            print(f"⚠️  No allocations returned for CURRENT period")

        # Reset debug info
        debug_info.clear()

        # Test 2: Variable query
        variable_query = """
        query GetAllocations($period: Period) {
            allocations(period: $period) {
                id
                location
                machine {
                    name
                    model
                }
                period
                isCurrent
            }
        }
        """

        result = await graphql(schema, variable_query, variable_values={"period": "CURRENT"})
        assert result.errors is None or len(result.errors) == 0, f"Variable errors: {result.errors}"

        # Check if nested fields are populated
        allocation = result.data["allocations"][0]
        assert allocation["location"] == "Floor1", f"Location: {allocation.get('location')}"
        assert allocation["machine"]["name"] == "PrinterA", (
            f"Machine name: {allocation.get('machine', {}).get('name')} - "
            "BUG: nested fields might be empty when enum is variable!"
        )

        print(f"⚠️  VARIABLE: {debug_info[-1]}")
        print("✅ Both inline and variable correctly filter and return nested fields!")

    @pytest.mark.asyncio
    async def test_multiple_enum_variables_in_nested_query(self, clear_registry) -> None:
        """Test multiple enum parameters with nested field selection."""

        @fraiseql.enum
        class Status(Enum):
            ACTIVE = "ACTIVE"
            INACTIVE = "INACTIVE"

        @fraiseql.type
        class AllocationDetail:
            id: str
            location: str
            period: Period
            status: Status

        async def allocations_detailed(
            info,
            period: Period | None = None,
            status: Status | None = None,
        ) -> list[AllocationDetail]:
            """Query with multiple enum parameters."""
            # Simulate filtering based on both enums
            results = []
            if period == Period.CURRENT and status == Status.ACTIVE:
                results = [AllocationDetail(id="1", location="Floor1", period=period, status=status)]
            return results

        schema = fraiseql.build_fraiseql_schema(query_types=[allocations_detailed])

        query = """
        query GetActiveCurrentAllocations($period: Period, $status: Status) {
            allocationsDetailed(period: $period, status: $status) {
                id
                location
                period
                status
            }
        }
        """

        result = await graphql(
            schema,
            query,
            variable_values={"period": "CURRENT", "status": "ACTIVE"},
        )

        assert result.errors is None or len(result.errors) == 0, f"Errors: {result.errors}"
        assert result.data["allocationsDetailed"][0]["location"] == "Floor1"
        assert result.data["allocationsDetailed"][0]["period"] == "CURRENT"
        assert result.data["allocationsDetailed"][0]["status"] == "ACTIVE"
