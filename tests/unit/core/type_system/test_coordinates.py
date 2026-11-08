# tests/types/scalars/test_coordinates.py

import pytest
from graphql import GraphQLError
from graphql.language import IntValueNode, StringValueNode

from fraiseql.types.scalars.coordinates import (
    parse_coordinate_literal,
    parse_coordinate_value,
    serialize_coordinate,
)

# The schema tests build schemas from the global SchemaRegistry, which other tests in
# the same process leave types in; start each test from an empty registry.
pytestmark = pytest.mark.usefixtures("clear_registry")


# --- Serialization Tests ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ((45.5, -122.6), "45.5,-122.6"),
        ((0, 0), "0,0"),
        ((-90, 180), "-90,180"),
        ((90, -180), "90,-180"),
    ],
)
def test_serialize_coordinate_valid(value, expected) -> None:
    assert serialize_coordinate(value) == expected


@pytest.mark.parametrize("value", [123, None, ["foo"], {"foo": "bar"}, "invalid"])
def test_serialize_coordinate_invalid(value) -> None:
    with pytest.raises(GraphQLError):
        serialize_coordinate(value)


# --- parse_value Tests ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("45.5,-122.6", (45.5, -122.6)),
        ("0,0", (0.0, 0.0)),
        ("-90,180", (-90.0, 180.0)),
        ("90,-180", (90.0, -180.0)),
        ((45.5, -122.6), (45.5, -122.6)),
        ({"lat": 45.5, "lng": -122.6}, (45.5, -122.6)),
    ],
)
def test_parse_coordinate_value_valid(value, expected) -> None:
    assert parse_coordinate_value(value) == expected


@pytest.mark.parametrize("value", [123, None, True, "invalid", "91,0", "0,181"])
def test_parse_coordinate_value_invalid(value) -> None:
    with pytest.raises(GraphQLError):
        parse_coordinate_value(value)


def test_parse_coordinate_value_latitude_bounds() -> None:
    # Should raise: (91, 0), (-91, 0)
    with pytest.raises(GraphQLError, match="Latitude must be between -90 and 90"):
        parse_coordinate_value("91,0")

    with pytest.raises(GraphQLError, match="Latitude must be between -90 and 90"):
        parse_coordinate_value("-91,0")


def test_parse_coordinate_value_longitude_bounds() -> None:
    # Should raise: (0, 181), (0, -181)
    with pytest.raises(GraphQLError, match="Longitude must be between -180 and 180"):
        parse_coordinate_value("0,181")

    with pytest.raises(GraphQLError, match="Longitude must be between -180 and 180"):
        parse_coordinate_value("0,-181")


def test_parse_coordinate_formats() -> None:
    # Support: "45.5,-122.6", (45.5, -122.6), {"lat": 45.5, "lng": -122.6}
    # PostgreSQL POINT format: "(45.5,-122.6)"
    assert parse_coordinate_value("45.5,-122.6") == (45.5, -122.6)
    assert parse_coordinate_value((45.5, -122.6)) == (45.5, -122.6)
    assert parse_coordinate_value({"lat": 45.5, "lng": -122.6}) == (45.5, -122.6)
    assert parse_coordinate_value("(45.5,-122.6)") == (45.5, -122.6)


# --- parse_literal Tests ---


def test_parse_coordinate_literal_valid() -> None:
    ast = StringValueNode(value="45.5,-122.6")
    assert parse_coordinate_literal(ast, None) == (45.5, -122.6)


def test_parse_coordinate_literal_invalid_node_type() -> None:
    ast = IntValueNode(value="123")
    with pytest.raises(GraphQLError):
        parse_coordinate_literal(ast, None)


def test_parse_coordinate_literal_invalid_value() -> None:
    class FakeNode:
        value = None

    ast = FakeNode()
    with pytest.raises(GraphQLError):
        parse_coordinate_literal(ast, None)  # type: ignore[arg-type]


# --- Type System Registration Tests ---


def test_coordinate_field_in_type_registry() -> None:
    """Test that CoordinateField is properly registered in the type system."""
    from fraiseql.types import Coordinate
    from fraiseql.types.scalars.coordinates import CoordinateField

    # Should be importable and usable in models
    assert Coordinate is not None
    assert CoordinateField is not None
    assert Coordinate is CoordinateField


def test_coordinate_field_graphql_scalar() -> None:
    """Test that Coordinate has proper GraphQL scalar."""
    from fraiseql.types.scalars.coordinates import CoordinateScalar

    # Should have proper GraphQL scalar
    assert CoordinateScalar.name == "Coordinate"
    assert CoordinateScalar.description.startswith(
        "Geographic coordinate as latitude/longitude pair"
    )
    assert "Latitude: -90.0 to 90.0 degrees" in CoordinateScalar.description
    assert "Longitude: -180.0 to 180.0 degrees" in CoordinateScalar.description
    assert CoordinateScalar.serialize is not None
    assert CoordinateScalar.parse_value is not None
    assert CoordinateScalar.parse_literal is not None


# --- GraphQL Schema Integration Tests ---


def test_coordinate_scalar_in_graphql_schema() -> None:
    """Test that Coordinate scalar appears in GraphQL schema."""
    from graphql import print_schema

    import fraiseql
    from fraiseql.gql.schema_builder import build_fraiseql_schema
    from fraiseql.types import Coordinate

    @fraiseql.input
    class LocationInput:
        """Input type with Coordinate field to test scalar mapping."""

        name: str
        coordinates: Coordinate  # Should map to coordinates: Coordinate in GraphQL

    @fraiseql.success
    class CreateLocationSuccess:
        message: str = "Location created successfully"

    @fraiseql.error
    class CreateLocationError:
        message: str

    @fraiseql.mutation(
        function="create_location",
        context_params={},
        error_config=fraiseql.DEFAULT_ERROR_CONFIG,
    )
    class CreateLocation:
        """Mutation to test Coordinate scalar mapping in GraphQL schema."""

        input: LocationInput
        success: CreateLocationSuccess
        error: CreateLocationError

    @fraiseql.query
    @pytest.mark.asyncio
    async def test_query(info) -> str:
        """Required query for valid GraphQL schema."""
        return "OK"

    # Build schema with the test types
    schema = build_fraiseql_schema(
        query_types=[LocationInput, CreateLocationSuccess, CreateLocationError, test_query],
        mutation_resolvers=[CreateLocation],
        camel_case_fields=True,
    )

    # Get schema SDL
    schema_sdl = print_schema(schema)

    # Verify Coordinate scalar is present
    assert "scalar Coordinate" in schema_sdl, "Coordinate scalar missing from schema"

    # Verify LocationInput is present
    assert "input LocationInput" in schema_sdl, "LocationInput missing from schema"

    # Extract LocationInput definition
    lines = schema_sdl.split("\n")
    input_definition = []
    in_input = False

    for line in lines:
        if "input LocationInput" in line:
            in_input = True
            input_definition.append(line)
        elif in_input and line.strip() == "}":
            input_definition.append(line)
            break
        elif in_input:
            input_definition.append(line)

    input_text = "\n".join(input_definition)

    # Test field name conversion: coordinates should stay coordinates (already camelCase)
    assert "coordinates: Coordinate" in input_text, "Field not mapped to Coordinate scalar"


def test_coordinate_field_type_mapping() -> None:
    """Test that CoordinateField correctly maps to CoordinateScalar."""
    from fraiseql.types.scalars.coordinates import CoordinateField, CoordinateScalar
    from fraiseql.types.scalars.graphql_utils import convert_scalar_to_graphql

    # Test direct type mapping
    mapped_scalar = convert_scalar_to_graphql(CoordinateField)
    assert mapped_scalar == CoordinateScalar, "CoordinateField not mapped to CoordinateScalar"
    assert mapped_scalar.name == "Coordinate", "Scalar name incorrect"


def test_graphql_validation_with_coordinate_scalar() -> None:
    """Test that GraphQL validation correctly handles Coordinate variables."""
    from graphql import parse, validate

    import fraiseql
    from fraiseql.gql.schema_builder import build_fraiseql_schema
    from fraiseql.types import Coordinate

    @fraiseql.input
    class LocationInput:
        """Input type with Coordinate field."""

        name: str
        coordinates: Coordinate

    @fraiseql.success
    class CreateLocationSuccess:
        message: str = "Location created successfully"

    @fraiseql.error
    class CreateLocationError:
        message: str

    @fraiseql.mutation(
        function="create_location",
        context_params={},
        error_config=fraiseql.DEFAULT_ERROR_CONFIG,
    )
    class CreateLocation:
        """Mutation to test Coordinate scalar mapping in GraphQL schema."""

        input: LocationInput
        success: CreateLocationSuccess
        error: CreateLocationError

    @fraiseql.query
    async def health_check(info) -> str:
        """Required query for valid GraphQL schema."""
        return "OK"

    # Build schema
    schema = build_fraiseql_schema(
        query_types=[LocationInput, CreateLocationSuccess, CreateLocationError, health_check],
        mutation_resolvers=[CreateLocation],
        camel_case_fields=True,
    )

    # Query with Coordinate variable (should work)
    valid_query = """
    mutation CreateLocation($coordinates: Coordinate!) {
        createLocation(input: { name: "Test Location", coordinates: $coordinates }) {
            ... on CreateLocationSuccess {
                message
            }
            ... on CreateLocationError {
                message
            }
        }
    }
    """

    # Query with String variable (should fail)
    invalid_query = """
    mutation CreateLocation($coordinates: String!) {
        createLocation(input: { name: "Test Location", coordinates: $coordinates }) {
            ... on CreateLocationSuccess {
                message
            }
            ... on CreateLocationError {
                message
            }
        }
    }
    """

    # Validate correct query (should pass)
    valid_document = parse(valid_query)
    valid_errors = validate(schema, valid_document)
    assert not valid_errors, f"Valid query failed validation: {valid_errors}"

    # Validate incorrect query (should fail)
    invalid_document = parse(invalid_query)
    invalid_errors = validate(schema, invalid_document)
    assert invalid_errors, "Invalid query passed validation when it should have failed"

    # Check that the error message is about type mismatch
    error_message = str(invalid_errors[0])
    assert "String!" in error_message, "Error should mention String type"
    assert "Coordinate" in error_message, "Error should mention Coordinate type"
