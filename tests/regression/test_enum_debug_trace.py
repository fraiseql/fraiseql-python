"""Debug trace tests for enum variable execution paths.

This test traces the execution path of enum variables vs inline literals
to identify where nested fields are lost.
"""

import asyncio
from enum import Enum
from typing import Any
from unittest.mock import patch

import pytest
from graphql import graphql

import fraiseql


pytestmark = pytest.mark.regression


@fraiseql.enum
class Status(Enum):
    """Task status."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


@fraiseql.type
class User:
    """User type."""

    id: str
    name: str
    status: Status


# Tracing infrastructure
class ExecutionTracer:
    """Traces resolver execution and field selection."""

    def __init__(self) -> None:
        """Initialize tracer."""
        self.calls: list[dict[str, Any]] = []

    def trace_argument_coercion(self, fn_name: str, arg_name: str, raw_value: Any, coerced_value: Any) -> None:
        """Record argument coercion."""
        self.calls.append({
            "event": "argument_coercion",
            "function": fn_name,
            "argument": arg_name,
            "raw_value": raw_value,
            "coerced_value": coerced_value,
            "coerced_type": type(coerced_value).__name__,
        })

    def trace_field_selection(self, field_name: str, fields_requested: list[str]) -> None:
        """Record field selection."""
        self.calls.append({
            "event": "field_selection",
            "field": field_name,
            "fields_requested": fields_requested,
        })

    def trace_resolver_call(self, resolver_name: str, args: dict[str, Any], result: Any) -> None:
        """Record resolver call."""
        self.calls.append({
            "event": "resolver_call",
            "resolver": resolver_name,
            "args": {k: v for k, v in args.items() if k != "info"},
            "result_type": type(result).__name__,
        })

    def print_trace(self) -> str:
        """Pretty print the trace."""
        lines = []
        for i, call in enumerate(self.calls, 1):
            event = call.get("event")
            if event == "argument_coercion":
                lines.append(
                    f"{i}. COERCE {call['function']}.{call['argument']}: "
                    f"{call['raw_value']!r} -> {call['coerced_value']!r} ({call['coerced_type']})"
                )
            elif event == "field_selection":
                lines.append(f"{i}. SELECT {call['field']}: {call['fields_requested']}")
            elif event == "resolver_call":
                lines.append(
                    f"{i}. RESOLVE {call['resolver']}({call['args']}) -> {call['result_type']}"
                )
        return "\n".join(lines)


class TestEnumDebugTrace:
    """Debug trace tests for enum variables."""

    async def test_enum_inline_with_trace(self, clear_registry) -> None:
        """Trace inline enum execution."""
        # Create simple schema with resolver
        async def user_by_status(info, status: Status) -> User:
            return User(id="1", name="Alice", status=status)

        schema = fraiseql.build_fraiseql_schema(query_types=[user_by_status])

        query = """
        {
            userByStatus(status: ACTIVE) {
                id
                name
                status
            }
        }
        """

        result = await graphql(schema, query)

        assert result.errors is None or len(result.errors) == 0
        assert result.data["userByStatus"]["name"] == "Alice"

        print("\n=== INLINE ENUM LITERAL ===")
        print(f"Data: {result.data}")

    async def test_enum_variable_with_trace(self, clear_registry) -> None:
        """Trace enum variable execution."""
        # Create simple schema with resolver
        async def user_by_status(info, status: Status) -> User:
            return User(id="1", name="Alice", status=status)

        schema = fraiseql.build_fraiseql_schema(query_types=[user_by_status])

        query = """
        query GetUserByStatus($status: Status!) {
            userByStatus(status: $status) {
                id
                name
                status
            }
        }
        """

        result = await graphql(schema, query, variable_values={"status": "ACTIVE"})

        assert result.errors is None or len(result.errors) == 0
        assert result.data["userByStatus"]["name"] == "Alice"

        print("\n=== ENUM VARIABLE ===")
        print(f"Data: {result.data}")

    @pytest.mark.asyncio
    async def test_enum_argument_coercion_inline_vs_variable(self) -> None:
        """Compare argument coercion paths for inline vs variable."""
        # Import the coercion module to understand the path
        from fraiseql.types.coercion import _coerce_to_enum

        # Test direct coercion
        print("\n=== Direct Enum Coercion ===")

        # From variable (string)
        coerced_from_variable = _coerce_to_enum("ACTIVE", Status)
        print(f"From variable: 'ACTIVE' -> {coerced_from_variable!r} (type: {type(coerced_from_variable)})")
        assert coerced_from_variable == Status.ACTIVE

        # From inline literal (should also be string)
        coerced_from_inline = _coerce_to_enum("ACTIVE", Status)
        print(f"From inline: 'ACTIVE' -> {coerced_from_inline!r} (type: {type(coerced_from_inline)})")
        assert coerced_from_inline == Status.ACTIVE

        # They should be identical
        assert coerced_from_variable is coerced_from_inline
        assert type(coerced_from_variable) is type(coerced_from_inline)

    @pytest.mark.asyncio
    async def test_enum_in_resolver_argument_handling(self) -> None:
        """Test how enums are handled in resolver arguments."""
        from fraiseql.types.coercion import coerce_input_arguments

        # Define a test resolver
        async def test_resolver(info, status: Status) -> str:
            return str(status)

        # Test coercion
        raw_args_variable = {"status": "ACTIVE"}
        raw_args_inline = {"status": "ACTIVE"}

        coerced_variable = coerce_input_arguments(test_resolver, raw_args_variable)
        coerced_inline = coerce_input_arguments(test_resolver, raw_args_inline)

        print("\n=== Argument Coercion ===")
        print(f"Variable: {raw_args_variable} -> {coerced_variable}")
        print(f"Inline: {raw_args_inline} -> {coerced_inline}")

        assert coerced_variable == coerced_inline
        assert coerced_variable["status"] == Status.ACTIVE
        assert isinstance(coerced_variable["status"], Status)
