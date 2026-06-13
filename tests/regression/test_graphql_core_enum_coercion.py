"""Test graphql-core's enum variable coercion behavior.

This test isolates whether the bug is in graphql-core's variable coercion
or in FraiseQL's resolver handling.
"""

from enum import Enum

import pytest
from graphql import (
    GraphQLArgument,
    GraphQLEnumType,
    GraphQLEnumValue,
    GraphQLField,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    execute,
    parse,
)

pytestmark = pytest.mark.regression


class Status(Enum):
    """Test enum."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


def test_graphql_core_enum_variable_coercion():
    """Test what graphql-core returns for enum variables.

    This test checks whether graphql-core properly coerces enum variables
    to enum values in the resolver arguments.
    """
    received_args = []

    # Define enum type
    status_enum = GraphQLEnumType(
        "Status",
        {
            "ACTIVE": GraphQLEnumValue("ACTIVE"),
            "INACTIVE": GraphQLEnumValue("INACTIVE"),
        },
    )

    # Define resolver that receives enum argument
    def resolve_status(root, info, status):
        received_args.append({"status": status, "type": type(status).__name__})
        return f"Status: {status}"

    # Define schema
    query_type = GraphQLObjectType(
        "Query",
        {
            "statusByValue": GraphQLField(
                GraphQLNonNull(GraphQLString),
                args={"status": GraphQLArgument(GraphQLNonNull(status_enum))},
                resolve=resolve_status,
            ),
        },
    )

    schema = GraphQLSchema(query_type)

    # Test 1: Inline literal
    print("\n=== TEST 1: Inline Literal ===")
    inline_query = """
    {
        statusByValue(status: ACTIVE)
    }
    """

    result = execute(schema, parse(inline_query))
    print(f"Result: {result.data}")
    print(f"Received args: {received_args[-1]}")
    assert result.errors is None
    assert result.data["statusByValue"] == "Status: ACTIVE"

    inline_arg_type = received_args[-1]["type"]
    inline_arg_value = received_args[-1]["status"]
    print(f"✅ INLINE: type={inline_arg_type}, value={inline_arg_value}")

    # Reset for variable test
    received_args.clear()

    # Test 2: Variable
    print("\n=== TEST 2: Variable ===")
    variable_query = """
    query GetStatus($status: Status!) {
        statusByValue(status: $status)
    }
    """

    result = execute(
        schema,
        parse(variable_query),
        variable_values={"status": "ACTIVE"},
    )
    print(f"Result: {result.data}")
    print(f"Received args: {received_args[-1]}")
    assert result.errors is None, f"Errors: {result.errors}"
    assert result.data["statusByValue"] == "Status: ACTIVE"

    variable_arg_type = received_args[-1]["type"]
    variable_arg_value = received_args[-1]["status"]
    print(f"⚠️  VARIABLE: type={variable_arg_type}, value={variable_arg_value}")

    # Analysis
    print("\n=== ANALYSIS ===")
    if inline_arg_type == variable_arg_type == "str":
        print("✅ graphql-core returns STRINGS for both inline and variables (correct)")
        print("   Enum coercion must happen in application code or middleware")
    elif inline_arg_type == "str" and variable_arg_type == "str":
        print("✅ Both are strings - consistent behavior")
    else:
        print(f"⚠️  DIFFERENT: inline={inline_arg_type}, variable={variable_arg_type}")
        if inline_arg_type != variable_arg_type:
            print("🐛 BUG: graphql-core handles inline and variables differently!")


@pytest.mark.asyncio
async def test_fraiseql_enum_coercion_in_resolver_wrapping():
    """Test FraiseQL's resolver wrapping with enum variables.

    This test checks if FraiseQL's wrap_resolver() properly coerces
    enum variables using its custom resolver logic.
    """
    import fraiseql
    from fraiseql.gql.resolver_wrappers import wrap_resolver

    @fraiseql.enum
    class Color(Enum):
        RED = "RED"
        BLUE = "BLUE"

    received_types = []

    async def get_color(info, color: Color) -> str:
        """Resolver expecting Color enum."""
        received_types.append((type(color).__name__, color))
        return f"Color: {color.value if isinstance(color, Color) else color}"

    # Wrap with FraiseQL's wrap_resolver
    field = wrap_resolver(get_color)

    class MockInfo:
        pass

    # Test 1: Pass enum instance (what wrap_resolver expects after GraphQL coercion)
    print("\n=== FRAISEQL WRAP: Enum Instance ===")
    result = await field.resolve(None, MockInfo(), color=Color.RED)
    print(f"Type: {received_types[-1][0]}, Value: {received_types[-1][1]}")

    # Test 2: Pass string (what might come from variables if graphql-core doesn't coerce)
    print("\n=== FRAISEQL WRAP: String Value ===")
    result = await field.resolve(None, MockInfo(), color="RED")
    print(f"Type: {received_types[-1][0]}, Value: {received_types[-1][1]}")

    # Check if wrap_resolver converted string to enum
    string_received_type = received_types[-1][0]
    string_received_value = received_types[-1][1]
    if string_received_type == "Color":
        print("✅ wrap_resolver converted string to Color enum")
    elif string_received_type == "str":
        print("⚠️  wrap_resolver passed string through (needs external coercion)")
