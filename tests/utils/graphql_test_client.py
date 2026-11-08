"""GraphQL test client utilities for testing RustResponseBytes integration.

This module provides utilities that mimic real GraphQL client behavior:
- TypedGraphQLResponse: Generic response type with data and errors
- GraphQLTestClient: Test client that executes queries and deserializes responses

These utilities are essential for testing the RustResponseBytes pass-through
architecture, as they simulate how actual GraphQL clients deserialize JSON
responses into typed objects.
"""

import json
from dataclasses import dataclass
from typing import Any, Generic, Type, TypeVar

from graphql import ExecutionResult, GraphQLSchema

from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.graphql.execute import execute_graphql

T = TypeVar("T")


@dataclass
class TypedGraphQLResponse(Generic[T]):
    """Generic GraphQL response with typed data.

    This class mimics the response structure of real GraphQL clients like
    Apollo, urql, or graphql-request. It provides:

    - data: The typed result of the query (T)
    - errors: Any GraphQL errors that occurred
    - ok: Boolean indicating if the response was successful

    Args:
        data: The typed data from the GraphQL response
        errors: List of GraphQL errors, if any

    Example:
        >>> response = TypedGraphQLResponse(data=product, errors=None)
        >>> if response.ok:
        ...     print(response.data.name)
    """

    data: T | None
    errors: list[dict[str, Any]] | None

    @property
    def ok(self) -> bool:
        """Check if response is successful (has data).

        Note: In GraphQL, a response can have both data and errors
        (partial success). We consider it "ok" if we have data.

        Returns:
            True if data is not None, False otherwise
        """
        return self.data is not None


class GraphQLTestClient:
    """Test client for executing GraphQL queries with type-safe responses.

    This client mimics real GraphQL client behavior by:
    1. Executing queries using execute_graphql()
    2. Handling both RustResponseBytes and ExecutionResult returns
    3. Deserializing JSON responses into typed objects
    4. Providing type-safe TypedGraphQLResponse objects

    This is essential for testing the RustResponseBytes pass-through architecture,
    as it simulates how actual GraphQL clients (like Apollo, urql, etc.) would
    deserialize responses.

    Example:
        >>> schema = GraphQLSchema(...)
        >>> client = GraphQLTestClient(schema)
        >>> response = await client.query("{ products { id name } }", result_type=list[Product])
        >>> if response.ok:
        ...     for product in response.data:
        ...         print(product.name)
    """

    def __init__(self, schema: GraphQLSchema) -> None:
        """Initialize the test client with a GraphQL schema.

        Args:
            schema: The GraphQL schema to execute queries against
        """
        self.schema = schema

    async def query(
        self,
        query: str,
        result_type: Type[T],
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> TypedGraphQLResponse[T]:
        """Execute a GraphQL query and return typed response.

        This method:
        1. Calls execute_graphql() with the query
        2. Handles both RustResponseBytes and ExecutionResult returns
        3. Deserializes the response into the specified result_type
        4. Returns a TypedGraphQLResponse with typed data

        Args:
            query: GraphQL query string
            result_type: Expected result type (e.g., list[Product], dict, etc.)
            variables: Query variables
            operation_name: Operation name for multi-operation documents
            context: Context passed to resolvers

        Returns:
            TypedGraphQLResponse with typed data and any errors
        """
        # Execute the query using execute_graphql
        result = await execute_graphql(
            schema=self.schema,
            source=query,
            variable_values=variables,
            operation_name=operation_name,
            context_value=context,
        )

        # Handle RustResponseBytes return (pass-through path)
        if isinstance(result, RustResponseBytes):
            # Deserialize the bytes into JSON
            json_data = json.loads(bytes(result))
            # Deserialize into the expected type
            typed_data = self._deserialize(json_data, result_type)
            return TypedGraphQLResponse(data=typed_data, errors=None)

        # Handle ExecutionResult return (standard GraphQL path)
        if isinstance(result, ExecutionResult):
            if result.errors:
                # Convert GraphQL errors to simple dicts
                errors = [{"message": str(err)} for err in result.errors]
                if result.data is None:
                    # Complete failure - no data
                    return TypedGraphQLResponse(data=None, errors=errors)
                # Partial success - has data and errors
                typed_data = self._deserialize(result.data, result_type)
                return TypedGraphQLResponse(data=typed_data, errors=errors)
            # Success - has data, no errors
            typed_data = self._deserialize(result.data, result_type)
            return TypedGraphQLResponse(data=typed_data, errors=None)

        # Unexpected return type
        raise TypeError(f"Unexpected result type from execute_graphql: {type(result)}")

    def _deserialize(self, data: Any, result_type: Type[T]) -> T:
        """Deserialize JSON data into typed objects.

        This method handles:
        - Primitives (str, int, float, bool, None)
        - Lists of objects
        - Dataclasses and FraiseQL types
        - Nested structures

        Args:
            data: Raw JSON data from GraphQL response
            result_type: The target type to deserialize into

        Returns:
            Deserialized typed object
        """
        # Handle None
        if data is None:
            return None

        # Handle dict (keep as-is for now, will enhance in Phase 4.3)
        if result_type is dict or result_type is Any:
            return data

        # Handle list types
        if hasattr(result_type, "__origin__") and result_type.__origin__ is list:
            # Get the item type from list[ItemType]
            item_type = result_type.__args__[0] if result_type.__args__ else Any
            if isinstance(data, list):
                return [self._deserialize(item, item_type) for item in data]
            raise TypeError(f"Expected list data for {result_type}, got {type(data)}")

        # Handle dataclasses and FraiseQL types with __fraiseql_definition__
        if isinstance(data, dict):
            # Check if result_type is a dataclass
            if hasattr(result_type, "__dataclass_fields__") or hasattr(
                result_type, "__fraiseql_definition__"
            ):
                # Create instance from dict
                return result_type(**data)

        # Return primitives as-is
        return data
