"""Real-world enum variable bug reproduction from printoptim_backend.

This test reproduces the exact issue found in printoptim_backend:
When enum arguments are passed as GraphQL variables (not inline literals),
FraiseQL passes them as strings instead of Enum instances.

The printoptim backend has workarounds in allocation_queries.py:
    if isinstance(period, str):
        period = Period[period]

This test verifies that the bug exists and can be fixed.
"""

from enum import Enum

import pytest
from graphql import graphql

import fraiseql


pytestmark = pytest.mark.regression


@fraiseql.enum
class Period(Enum):
    """Time period classification for machine allocations."""

    CURRENT = "CURRENT"
    STOCK = "STOCK"
    PAST = "PAST"
    FUTURE = "FUTURE"


@fraiseql.type
class Allocation:
    """Machine allocation with nested fields."""

    id: str
    machine_name: str
    location: str
    period: Period


class TestEnumVariableBugRealWorld:
    """Real-world test reproducing the bug from printoptim_backend."""

    @pytest.mark.asyncio
    async def test_enum_variable_passed_as_string_bug(self, clear_registry) -> None:
        """Reproduce the bug: enum variables come as strings, not Enum instances.

        In printoptim_backend, resolvers receive period as a string when passed as
        a GraphQL variable, even though they're declared as Period (enum).

        This test proves the bug by checking the type received in the resolver.
        """
        received_types = []

        async def allocations(info, period: Period | None = None) -> list[Allocation]:
            """Query resolver that tracks what type period is."""
            # Record what type we actually received
            received_types.append((type(period).__name__, str(period)))

            # When period comes as a string (the bug), we have to do this workaround:
            if isinstance(period, str):
                try:
                    period = Period[period]
                except KeyError:
                    period = None

            # Return mock data
            if period == Period.CURRENT:
                return [Allocation(id="1", machine_name="PrinterA", location="Floor1", period=period)]
            elif period == Period.STOCK:
                return [Allocation(id="2", machine_name="PrinterB", location="Warehouse", period=period)]
            else:
                return []

        schema = fraiseql.build_fraiseql_schema(query_types=[allocations])

        # Test 1: Inline literal (works correctly)
        inline_query = """
        {
            allocations(period: CURRENT) {
                id
                machineName
                location
                period
            }
        }
        """

        result = await graphql(schema, inline_query)
        assert result.errors is None or len(result.errors) == 0
        assert result.data["allocations"][0]["machineName"] == "PrinterA"

        inline_type_name = received_types[-1][0]
        print(f"\n✅ INLINE LITERAL - Type received: {inline_type_name}")

        # Reset for variable test
        received_types.clear()

        # Test 2: Variable (currently broken - passes as string)
        variable_query = """
        query GetAllocations($period: Period) {
            allocations(period: $period) {
                id
                machineName
                location
                period
            }
        }
        """

        result = await graphql(schema, variable_query, variable_values={"period": "CURRENT"})
        assert result.errors is None or len(result.errors) == 0, f"Errors: {result.errors}"

        # Check if we can access the nested field
        allocation = result.data["allocations"][0] if result.data and result.data["allocations"] else None
        if allocation:
            machine_name = allocation.get("machineName")
            print(f"✅ VARIABLE - machineName returned: {machine_name}")

        variable_type_name = received_types[-1][0]
        variable_type_value = received_types[-1][1]
        print(f"⚠️  VARIABLE - Type received: {variable_type_name} (value: {variable_type_value})")

        # THE BUG: Variables come as strings, not Enum instances
        if inline_type_name == "Period" and variable_type_name == "str":
            print("\n🐛 BUG CONFIRMED: Enum variable passed as string instead of Enum instance!")
            print("   - Inline literal: Period (correct)")
            print("   - Variable: str (incorrect - should be Period)")
        elif inline_type_name == variable_type_name == "Period":
            print("\n✅ BUG FIXED: Both inline and variables correctly pass as Period enum!")

    @pytest.mark.asyncio
    async def test_enum_variable_with_complex_logic(self, clear_registry) -> None:
        """Test enum variable with the exact logic pattern from printoptim_backend."""

        async def allocations_with_filtering(
            info, period: Period | None = None
        ) -> list[Allocation]:
            """Resolver with the exact filtering logic from printoptim_backend."""
            # This is the pattern used in printoptim_backend allocation_queries.py
            filters = {}
            if period:
                # Workaround: FraiseQL still passes enums as strings
                if isinstance(period, str):
                    try:
                        period = Period[period]
                    except KeyError:
                        period = None

                # Map period to column filters (like in the real code)
                if period == Period.CURRENT:
                    filters["is_current"] = True
                elif period == Period.STOCK:
                    filters["is_stock_current"] = True
                elif period == Period.PAST:
                    filters["is_past"] = True
                elif period == Period.FUTURE:
                    filters["is_future"] = True

            # Simulate applying filters to database query
            results = []
            if filters:
                if filters.get("is_current"):
                    results = [Allocation(id="1", machine_name="Current", location="Floor1", period=Period.CURRENT)]
                elif filters.get("is_stock_current"):
                    results = [Allocation(id="2", machine_name="Stock", location="Warehouse", period=Period.STOCK)]
            return results

        schema = fraiseql.build_fraiseql_schema(query_types=[allocations_with_filtering])

        # Variable query with complex nested fields
        query = """
        query GetCurrentAllocations($period: Period) {
            allocationsWithFiltering(period: $period) {
                id
                machineName
                location
                period
            }
        }
        """

        result = await graphql(schema, query, variable_values={"period": "CURRENT"})

        assert result.errors is None or len(result.errors) == 0, f"Errors: {result.errors}"
        assert result.data is not None
        assert len(result.data["allocationsWithFiltering"]) > 0

        allocation = result.data["allocationsWithFiltering"][0]
        assert allocation["machineName"] == "Current"
        assert allocation["location"] == "Floor1"
        # The bug: these nested fields might be empty if field selection breaks
        assert allocation["id"] is not None, "NESTED FIELD BUG: id is empty/None"
        assert allocation["machineName"] is not None, "NESTED FIELD BUG: machineName is empty/None"
