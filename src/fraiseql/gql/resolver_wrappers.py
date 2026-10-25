"""Utility to wrap Python async resolver functions as GraphQLField instances.

Converts function signatures to GraphQL argument definitions and return types,
and provides a resolver that calls the original function with `info` and
keyword arguments.
"""

from collections.abc import Awaitable, Callable
from dataclasses import is_dataclass
from enum import Enum
from inspect import isclass, signature
from types import UnionType
from typing import Any, Union, cast, get_args, get_origin

from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLNonNull,
    GraphQLOutputType,
    GraphQLResolveInfo,
)

from fraiseql.core.graphql_type import (
    convert_type_to_graphql_input,
    convert_type_to_graphql_output,
)


def _coerce_to_enum(value: Any, enum_class: type[Enum]) -> Enum:
    """Convert a value to an enum instance.

    Args:
        value: The value to convert (typically a string or int from GraphQL)
        enum_class: The target enum class

    Returns:
        The corresponding enum instance

    Raises:
        ValueError: If the value cannot be converted to the enum
    """
    # Handle already-enum case (shouldn't happen with current check, but safe)
    if isinstance(value, enum_class):
        return value

    # Try to match by value (most common case for GraphQL enums)
    for member in enum_class:
        if member.value == value:
            return member

    # Fallback: try by name (less common but possible)
    if isinstance(value, str):
        try:
            return enum_class[value]
        except KeyError:
            pass

    # If all conversions fail, raise an error with helpful message
    valid_values = [f"{member.name}={member.value}" for member in enum_class]
    raise ValueError(
        f"Cannot convert '{value}' to {enum_class.__name__}. "
        f"Valid values are: {', '.join(valid_values)}"
    )


def wrap_resolver(fn: Callable[..., Awaitable[object]]) -> GraphQLField:
    """Wrap an async resolver function into a GraphQLField with typed arguments and input coercion.

    This function handles automatic type conversion for:
    - Dataclasses: Dict arguments are converted to dataclass instances
    - Enums: String/int values are converted to enum instances
    - Optional types: Properly extracts the underlying type for conversion

    Args:
        fn: An async resolver function to wrap

    Returns:
        A GraphQLField with proper argument definitions and type coercion
    """
    sig = signature(fn)
    args: dict[str, GraphQLArgument] = {}

    # Build GraphQL argument definitions
    for name, param in sig.parameters.items():
        if name == "info":
            continue
        gql_input_type = convert_type_to_graphql_input(param.annotation)
        args[name] = GraphQLArgument(GraphQLNonNull(cast("Any", gql_input_type)))

    gql_output_type = convert_type_to_graphql_output(sig.return_annotation)
    gql_output_type_cast = cast("GraphQLOutputType", gql_output_type)

    async def resolver(root: object, info: GraphQLResolveInfo, **kwargs: object) -> object:
        _ = root
        coerced_kwargs: dict[str, object] = {}

        for name, value in kwargs.items():
            param = sig.parameters.get(name)
            expected_type = param.annotation if param else None

            # Extract the actual type from Optional[T] or Union[T, None]
            actual_type = expected_type
            if expected_type is not None:
                origin = get_origin(expected_type)
                if origin in (Union, UnionType):
                    # Optional[T] or T | None
                    args = get_args(expected_type)
                    # Find the non-None type
                    for arg in args:
                        if arg is not type(None):
                            actual_type = arg
                            break

            if (
                isinstance(value, dict)
                and actual_type is not None
                and isclass(actual_type)
                and (is_dataclass(actual_type) or hasattr(actual_type, "__fraiseql_definition__"))
            ):
                coerced_kwargs[name] = actual_type(**value)
            elif (
                actual_type is not None
                and isclass(actual_type)
                and issubclass(actual_type, Enum)
                and value is not None
                and not isinstance(value, actual_type)
            ):
                # Convert GraphQL enum values to Python Enum instances
                # GraphQL passes enum values as strings/ints (e.g., "ACTIVE" or 1)
                # We need to convert these to the actual Python Enum instances
                # (e.g., Status.ACTIVE) for proper type safety in resolvers
                try:
                    coerced_kwargs[name] = _coerce_to_enum(value, actual_type)
                except ValueError:
                    # Pass the original value if conversion fails
                    # This allows GraphQL's type validation to handle the error
                    coerced_kwargs[name] = value
            else:
                coerced_kwargs[name] = value

        return await fn(info=info, **coerced_kwargs)

    return GraphQLField(
        type_=gql_output_type_cast,
        args=args,
        resolve=resolver,
    )
