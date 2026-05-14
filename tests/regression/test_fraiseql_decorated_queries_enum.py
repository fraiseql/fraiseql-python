"""Test FraiseQL's decorator-based queries with enum arguments.

This test uses the exact pattern from printoptim_backend to see if the
enum variable bug manifests with decorated queries.
"""

from enum import Enum

import pytest
from graphql import graphql

import fraiseql

pytestmark = pytest.mark.regression


@fraiseql.enum
class Period(Enum):
    """Time period enum."""

    CURRENT = "CURRENT"
    STOCK = "STOCK"
    PAST = "PAST"
    FUTURE = "FUTURE"


@fraiseql.type
class Machine:
    """Machine with nested fields."""

    id: str
    name: str
    model: str


@fraiseql.type
class Allocation:
    """Allocation result type."""

    id: str
    location: str
    machine_id: str
    machine: Machine
    period: Period | None = None


class TestDecoratedQueriesWithEnums:
    """Test decorated @fraiseql.query with enum arguments."""

    @pytest.mark.asyncio
    async def test_decorated_query_enum_variable_tracking(self) -> None:
        """Track what type enum variables receive in decorated queries."""
        type_log = []

        async def allocations(info, period: Period | None = None) -> list[Allocation]:
            """Decorated query resolver with enum parameter."""
            # Log what type we received
            type_log.append({"type": type(period).__name__, "value": str(period), "is_enum": isinstance(period, Period)})

            # Simulate the printoptim pattern
            filters = {}
            if period:
                if isinstance(period, str):
                    try:
                        period = Period[period]
                    except KeyError:
                        period = None

                if period == Period.CURRENT:
                    filters["is_current"] = True

            # Return mock data
            if filters:
                return [
                    Allocation(
                        id="1",
                        location="Floor1",
                        machine_id="m1",
                        machine=Machine(id="m1", name="PrinterA", model="X"),
                        period=period,
                    )
                ]
            return []

        # Build schema with decorated query
        schema = fraiseql.build_fraiseql_schema(query_types=[allocations])

        # Test 1: Inline enum literal
        inline_query = """
        {
            allocations(period: CURRENT) {
                id
                location
                machine {
                    name
                }
                period
            }
        }
        """

        result = await graphql(schema, inline_query)
        print(f"\nINLINE RESULT: {result.data}, errors: {result.errors}")
        print(f"TYPE LOG: {type_log[-1]}")
        inline_type = type_log[-1]["type"]
        inline_is_enum = type_log[-1]["is_enum"]

        if result.data and result.data["allocations"]:
            alloc = result.data["allocations"][0]
            print(f"Inline nested fields: {alloc['machine']['name']}, period: {alloc['period']}")

        print(f"✅ INLINE: type={inline_type}, is_enum={inline_is_enum}")

        # Reset log
        type_log.clear()

        # Test 2: Enum variable
        variable_query = """
        query GetAllocations($period: Period) {
            allocations(period: $period) {
                id
                location
                machine {
                    name
                }
                period
            }
        }
        """

        result = await graphql(schema, variable_query, variable_values={"period": "CURRENT"})
        print(f"\nVARIABLE RESULT: {result.data}, errors: {result.errors}")
        print(f"TYPE LOG: {type_log[-1]}")
        variable_type = type_log[-1]["type"]
        variable_is_enum = type_log[-1]["is_enum"]

        if result.data and result.data["allocations"]:
            alloc = result.data["allocations"][0]
            machine_name = alloc["machine"]["name"] if alloc["machine"] else "None"
            print(f"Variable nested fields: {machine_name}, period: {alloc['period']}")
        else:
            print("⚠️  No allocations returned for variable query!")

        print(f"⚠️  VARIABLE: type={variable_type}, is_enum={variable_is_enum}")

        # Analysis
        if inline_is_enum and variable_is_enum:
            print("\n✅ BOTH are Period enums - bug appears fixed")
        elif inline_is_enum and not variable_is_enum:
            print(f"\n🐛 BUG CONFIRMED: inline={inline_type} (enum), variable={variable_type} (not enum)")
        elif not inline_is_enum and not variable_is_enum:
            print("\n⚠️  Both are strings - coercion not happening in either case")

    @pytest.mark.asyncio
    async def test_decorated_query_with_multiple_enums(self) -> None:
        """Test decorated query with multiple enum parameters."""

        @fraiseql.enum
        class Status(Enum):
            ACTIVE = "ACTIVE"
            INACTIVE = "INACTIVE"

        @fraiseql.type
        class Record:
            id: str
            period: Period
            status: Status

        async def records(
            info, period: Period | None = None, status: Status | None = None
        ) -> list[Record]:
            """Query with multiple enum parameters."""
            # Log types
            period_is_enum = isinstance(period, Period)
            status_is_enum = isinstance(status, Status)

            print(f"\nRECEIVED: period type={type(period).__name__} (enum={period_is_enum}), "
                  f"status type={type(status).__name__} (enum={status_is_enum})")

            if period_is_enum and status_is_enum:
                return [Record(id="1", period=period, status=status)]
            return []

        schema = fraiseql.build_fraiseql_schema(query_types=[records])

        query = """
        query GetRecords($period: Period, $status: Status) {
            records(period: $period, status: $status) {
                id
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

        print(f"RESULT: {result.data}, errors: {result.errors}")

        if result.data and result.data["records"]:
            record = result.data["records"][0]
            assert record["period"] == "CURRENT"
            assert record["status"] == "ACTIVE"
            print("✅ Multiple enums work correctly")
        else:
            print("⚠️  No records returned - enum coercion might have failed")
