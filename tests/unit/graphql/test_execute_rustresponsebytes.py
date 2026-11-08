"""Tests for RustResponseBytes detection and pass-through in execute_graphql().

Phase 1: TDD Cycle 1.1 - Basic Detection

This test verifies that execute_graphql() can detect when a resolver returns
RustResponseBytes and passes it through directly without wrapping in ExecutionResult.
"""

import pytest
from graphql import GraphQLField, GraphQLList, GraphQLObjectType, GraphQLSchema, GraphQLString

from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.graphql.execute import execute_graphql


@pytest.mark.asyncio
async def test_execute_graphql_detects_rustresponsebytes() -> None:
    """Test that execute_graphql() returns RustResponseBytes directly when detected.

    🔴 RED Phase: This test should FAIL initially because execute_graphql()
    currently wraps RustResponseBytes in ExecutionResult instead of returning it directly.

    This test simulates the real-world scenario where:
    - Resolver declares return type as list[SomeType]
    - But actually returns RustResponseBytes (from repository)
    - GraphQL-core sees a type mismatch and creates an error
    - execute_graphql() should detect "RustResponseBytes" in error and pass through

    Expected behavior:
    - Resolver returns RustResponseBytes
    - execute_graphql() detects it via error message and returns it unwrapped
    - Return type is RustResponseBytes, not ExecutionResult
    """
    # Create a mock RustResponseBytes response
    mock_response = b'{"data":{"products":[{"id":"1","name":"Test"}]}}'
    rust_response = RustResponseBytes(mock_response)

    # Define a resolver that returns RustResponseBytes
    # This simulates repo.find() returning RustResponseBytes
    def resolve_products(root, info) -> None:
        return rust_response

    # Define a Product type
    product_type = GraphQLObjectType(
        name="Product",
        fields={
            "id": GraphQLField(GraphQLString),
            "name": GraphQLField(GraphQLString),
        },
    )

    # Create a schema where the resolver returns list[Product] but actually returns RustResponseBytes
    schema = GraphQLSchema(
        query=GraphQLObjectType(
            name="Query",
            fields={
                "products": GraphQLField(
                    GraphQLList(product_type),  # Expects list of products
                    resolve=resolve_products,  # But returns RustResponseBytes
                )
            },
        )
    )

    # Execute query
    query = "{ products { id name } }"
    result = await execute_graphql(
        schema=schema,
        source=query,
    )

    # 🎯 ASSERTION: Result should be RustResponseBytes, not ExecutionResult
    assert isinstance(result, RustResponseBytes), (
        f"Expected RustResponseBytes, got {type(result)}. "
        "execute_graphql() should return RustResponseBytes directly without wrapping."
    )

    # Verify the bytes match
    assert bytes(result) == mock_response


@pytest.mark.asyncio
async def test_execute_graphql_normal_execution_unchanged() -> None:
    """Test that normal GraphQL execution still works as before.

    This ensures backwards compatibility - resolvers that return normal values
    should still get ExecutionResult as before.
    """

    # Define a resolver that returns a normal string
    def resolve_hello(root, info) -> None:
        return "Hello, World!"

    # Create a minimal GraphQL schema
    schema = GraphQLSchema(
        query=GraphQLObjectType(
            name="Query",
            fields={
                "hello": GraphQLField(
                    GraphQLString,
                    resolve=resolve_hello,
                )
            },
        )
    )

    # Execute query
    query = "{ hello }"
    result = await execute_graphql(
        schema=schema,
        source=query,
    )

    # Should return ExecutionResult for normal resolvers
    from graphql import ExecutionResult

    assert isinstance(result, ExecutionResult), (
        f"Expected ExecutionResult for normal resolver, got {type(result)}"
    )

    # Verify data is correct
    assert result.data == {"hello": "Hello, World!"}
    assert result.errors is None


@pytest.mark.asyncio
async def test_execute_graphql_handles_resolver_errors_with_rustresponsebytes() -> None:
    """A field's error isn't lost when another root field returns RustResponseBytes.

    One field's RustResponseBytes holds that field only, so it can't be the whole
    response of an operation with two root fields: it used to be returned as is,
    and the other field and its error were dropped. The result now carries both.
    """
    # Track if resolver was called
    call_count = {"count": 0}

    # Create a mock RustResponseBytes response
    mock_response = b'{"data":{"products":[{"id":"1","name":"Test"}]}}'
    rust_response = RustResponseBytes(mock_response)

    # Define a resolver that first returns RustResponseBytes, then errors
    async def resolve_products(root, info) -> None:
        call_count["count"] += 1
        if call_count["count"] == 1:
            # First field succeeds with RustResponseBytes
            return rust_response
        # Second field raises an error
        raise ValueError("Simulated resolver error")

    # Define types
    product_type = GraphQLObjectType(
        name="Product",
        fields={
            "id": GraphQLField(GraphQLString),
            "name": GraphQLField(GraphQLString),
        },
    )

    # Create schema with two fields - one succeeds, one fails
    schema = GraphQLSchema(
        query=GraphQLObjectType(
            name="Query",
            fields={
                "products": GraphQLField(
                    GraphQLList(product_type),
                    resolve=resolve_products,
                ),
                "otherField": GraphQLField(
                    GraphQLString,
                    resolve=resolve_products,  # Will error on second call
                ),
            },
        )
    )

    # Execute query with both fields
    query = "{ products { id name } otherField }"
    result = await execute_graphql(
        schema=schema,
        source=query,
    )

    assert not isinstance(result, RustResponseBytes)
    assert result.data == {"products": [{"id": "1", "name": "Test"}], "otherField": None}
    assert [error.path for error in result.errors] == [["otherField"]]
    assert "Simulated resolver error" in result.errors[0].message
