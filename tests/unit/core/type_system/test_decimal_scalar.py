"""``decimal.Decimal`` maps to a ``Decimal`` scalar (issue #575).

It is serialized as a string, so no digit is lost on the way to a client, and
parsed to ``decimal.Decimal`` from a string, an int or a number literal. It
builds as an output field, an input field, an argument, and in where inputs.
"""

from decimal import Decimal

import pytest
from graphql import GraphQLError, graphql, parse_value

import fraiseql
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.mutations.sql_generator import _serialize_basic
from fraiseql.sql import create_graphql_where_input
from fraiseql.types.scalars import DecimalScalar
from fraiseql.types.scalars.graphql_utils import convert_scalar_to_graphql

pytestmark = pytest.mark.usefixtures("clear_registry")


def test_decimal_maps_to_decimal_scalar() -> None:
    assert convert_scalar_to_graphql(Decimal) is DecimalScalar
    assert DecimalScalar.name == "Decimal"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("12.345678901234567890123"), "12.345678901234567890123"),
        (Decimal("10.50"), "10.50"),
        (Decimal("-0.001"), "-0.001"),
        (7, "7"),
        ("3.14", "3.14"),
        (0.1, "0.1"),
    ],
)
def test_serialize_is_an_exact_string(value: object, expected: str) -> None:
    assert DecimalScalar.serialize(value) == expected


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), "abc", True, [1]])
def test_serialize_rejects_non_numbers(value: object) -> None:
    with pytest.raises(GraphQLError):
        DecimalScalar.serialize(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12.345678901234567890123", Decimal("12.345678901234567890123")),
        ("10.50", Decimal("10.50")),
        (42, Decimal(42)),
        (0.1, Decimal("0.1")),
    ],
)
def test_parse_value_returns_decimal(value: object, expected: Decimal) -> None:
    parsed = DecimalScalar.parse_value(value)
    assert isinstance(parsed, Decimal)
    assert parsed == expected
    assert str(parsed) == str(expected)


@pytest.mark.parametrize("value", ["abc", "NaN", "Infinity", "", True, None, [1]])
def test_parse_value_rejects_non_numbers(value: object) -> None:
    with pytest.raises(GraphQLError):
        DecimalScalar.parse_value(value)


@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        ('"12.345678901234567890123"', "12.345678901234567890123"),
        ("12.345678901234567890123", "12.345678901234567890123"),
        ("42", "42"),
    ],
)
def test_parse_literal_keeps_every_digit(literal: str, expected: str) -> None:
    parsed = DecimalScalar.parse_literal(parse_value(literal))
    assert isinstance(parsed, Decimal)
    assert str(parsed) == expected


def test_parse_literal_rejects_other_literals() -> None:
    with pytest.raises(GraphQLError):
        DecimalScalar.parse_literal(parse_value("true"))


def test_mutation_input_serializes_decimal_as_exact_string() -> None:
    assert _serialize_basic(Decimal("12.345678901234567890123")) == "12.345678901234567890123"


def test_decimal_builds_as_output_input_argument_and_where_input() -> None:
    @fraiseql.type(sql_source="v_product")
    class Product:
        id: int
        price: Decimal
        discount: Decimal | None

    @fraiseql.input
    class PriceInput:
        amount: Decimal
        fee: Decimal | None = None

    product_where = create_graphql_where_input(Product)

    @fraiseql.query
    async def products(
        info, min_price: Decimal, where: product_where | None = None
    ) -> list[Product]:
        return []

    @fraiseql.query
    async def quote(info, input: PriceInput) -> Decimal:
        return input.amount + (input.fee or Decimal(0))

    schema = build_fraiseql_schema()

    product = schema.type_map["Product"]
    assert str(product.fields["price"].type) == "Decimal!"
    assert str(product.fields["discount"].type) == "Decimal"
    assert str(schema.type_map["PriceInput"].fields["amount"].type) == "Decimal!"
    assert str(schema.query_type.fields["products"].args["minPrice"].type) == "Decimal"
    assert str(schema.type_map["DecimalFilter"].fields["gt"].type) == "Decimal"


async def test_decimal_round_trips_through_graphql_core() -> None:
    @fraiseql.type
    class Price:
        amount: Decimal

    @fraiseql.query
    async def price(info, amount: Decimal) -> Price:
        assert isinstance(amount, Decimal)
        return Price(amount=amount * 2)

    schema = build_fraiseql_schema()
    result = await graphql(schema, '{ price(amount: "1.000000000000000000001") { amount } }')

    assert result.errors is None
    assert result.data == {"price": {"amount": "2.000000000000000000002"}}
