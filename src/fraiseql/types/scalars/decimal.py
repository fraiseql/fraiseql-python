"""Decimal scalar type for exact decimal numbers, such as money."""

from decimal import Decimal, InvalidOperation
from typing import Any

from graphql import GraphQLError, GraphQLScalarType
from graphql.language import FloatValueNode, IntValueNode, StringValueNode, ValueNode


def _to_decimal(value: Any) -> Decimal:
    """Convert a value to a finite Decimal, or raise GraphQLError."""
    if isinstance(value, bool):
        raise GraphQLError(f"Decimal cannot represent a boolean: {value!r}")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        # str() gives the shortest repr that round-trips: 0.1 -> "0.1", not
        # 0.1000000000000000055511151231257827.
        result = Decimal(str(value))
    elif isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except InvalidOperation:
            raise GraphQLError(f"Decimal cannot represent {value!r}") from None
    else:
        raise GraphQLError(f"Decimal cannot represent {value!r}")
    if not result.is_finite():
        raise GraphQLError(f"Decimal cannot represent a non-finite value: {value!r}")
    return result


def serialize_decimal(value: Any) -> str:
    """Serialize a decimal number to a string, keeping every digit."""
    return str(_to_decimal(value))


def parse_decimal_value(value: Any) -> Decimal:
    """Parse a variable value (a string, or a JSON number) to a Decimal."""
    return _to_decimal(value)


def parse_decimal_literal(ast: ValueNode, _variables: dict[str, Any] | None = None) -> Decimal:
    """Parse a string or number literal to a Decimal, from its source text."""
    if not isinstance(ast, StringValueNode | IntValueNode | FloatValueNode):
        raise GraphQLError("Decimal must be a string or a number literal")
    return _to_decimal(ast.value)


DecimalScalar = GraphQLScalarType(
    name="Decimal",
    description=(
        "An exact decimal number, such as a money amount. Serialized as a string "
        "('12.30') so that no digit is lost; accepts a string or a number as input."
    ),
    serialize=serialize_decimal,
    parse_value=parse_decimal_value,
    parse_literal=parse_decimal_literal,
)
