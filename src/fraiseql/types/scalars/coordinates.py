"""Geographic coordinate types for FraiseQL GraphQL API.

This module provides comprehensive support for geographic coordinates (latitude/longitude)
with PostgreSQL POINT type integration and advanced spatial filtering capabilities.

Coordinates are validated to ensure:
- Latitude: -90.0 to +90.0 degrees
- Longitude: -180.0 to +180.0 degrees

Supported Input Formats:
- String: "45.5,-122.6" or "(45.5,-122.6)"
- Tuple: (45.5, -122.6)
- Dict: {"lat": 45.5, "lng": -122.6}

GraphQL Filtering Operators:
- eq: Exact coordinate equality
- neq: Coordinate inequality
- in/notin: Coordinate list membership
- distance_within: Distance-based filtering (meters)

Database Integration:
- PostgreSQL POINT type for efficient storage
- GiST indexes for spatial query performance
- PostGIS ST_DWithin for distance calculations

Examples:
    # GraphQL query with distance filtering
    query {
      locations(where: {
        coordinates: { distanceWithin: { center: [37.7749, -122.4194], radius: 50000 } }
      }) {
        name
        coordinates
      }
    }

Functions:
- serialize_coordinate: Converts coordinate tuple to string format
- parse_coordinate_value: Parses and validates coordinate input
- parse_coordinate_literal: Handles GraphQL AST coordinate literals

Classes:
- CoordinateField: Type marker for coordinate model fields
"""

from typing import Any

from graphql import GraphQLError, GraphQLScalarType
from graphql.language import StringValueNode, ValueNode

from fraiseql.types.definitions import ScalarMarker


def serialize_coordinate(value: Any) -> str:
    """Serialize a coordinate tuple to GraphQL string format.

    Converts a coordinate tuple (latitude, longitude) to a comma-separated string
    for GraphQL response serialization.

    Args:
        value: Coordinate tuple (lat, lng) or compatible input

    Returns:
        String in format "lat,lng" (e.g., "37.7749,-122.4194")

    Raises:
        GraphQLError: If value is not a valid coordinate tuple

    Examples:
        >>> serialize_coordinate((37.7749, -122.4194))
        '37.7749,-122.4194'
    """
    if isinstance(value, tuple) and len(value) == 2:
        lat, lng = value
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return f"{lat},{lng}"

    msg = f"Coordinate cannot represent non-coordinate value: {value!r}"
    raise GraphQLError(msg)


def _extract_lat_lng(value: Any) -> tuple[float, float]:
    """Extract latitude and longitude from various input formats.

    Internal utility function that handles multiple coordinate input formats
    and converts them to a standardized (lat, lng) tuple.

    Args:
        value: Input coordinate in supported format

    Returns:
        Tuple of (latitude, longitude) as floats

    Raises:
        GraphQLError: If input format is invalid or values are malformed

    Supported Formats:
        - String: "45.5,-122.6" or "(45.5,-122.6)"
        - Tuple: (45.5, -122.6)
        - Dict: {"lat": 45.5, "lng": -122.6}
    """
    if isinstance(value, str):
        # Handle string formats: "45.5,-122.6" or "(45.5,-122.6)"
        clean_value = value.strip()
        if clean_value.startswith("(") and clean_value.endswith(")"):
            clean_value = clean_value[1:-1]

        parts = clean_value.split(",")
        if len(parts) != 2:
            raise GraphQLError(f"Invalid coordinate format: {value!r}")

        try:
            lat = float(parts[0].strip())
            lng = float(parts[1].strip())
            return (lat, lng)
        except ValueError as e:
            raise GraphQLError(f"Invalid coordinate values: {value!r}") from e

    elif isinstance(value, tuple) and len(value) == 2:
        # Handle tuple format: (45.5, -122.6)
        lat, lng = value
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return (float(lat), float(lng))
        raise GraphQLError(f"Invalid coordinate tuple values: {value!r}")

    elif isinstance(value, dict):
        # Handle dict format: {"lat": 45.5, "lng": -122.6}
        if "lat" in value and "lng" in value:
            lat = value["lat"]
            lng = value["lng"]
            if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
                return (float(lat), float(lng))
            raise GraphQLError(f"Invalid coordinate dict values: {value!r}")
        raise GraphQLError(f"Coordinate dict must have 'lat' and 'lng' keys: {value!r}")

    else:
        raise GraphQLError(f"Invalid coordinate input type: {type(value)}")


def parse_coordinate_value(value: Any) -> tuple[float, float]:
    """Parse and validate coordinate input for GraphQL variable values.

    Accepts multiple input formats and validates geographic bounds.
    Used by GraphQL when coordinates are passed as query variables.

    Args:
        value: Coordinate input in supported format

    Returns:
        Validated coordinate tuple (latitude, longitude)

    Raises:
        GraphQLError: If coordinates are invalid or out of bounds

    Supported Input Formats:
        - String: "45.5,-122.6" or "(45.5,-122.6)"
        - Tuple: (45.5, -122.6)
        - Dict: {"lat": 45.5, "lng": -122.6}

    Validation Rules:
        - Latitude: -90.0 ≤ lat ≤ 90.0
        - Longitude: -180.0 ≤ lng ≤ 180.0

    Examples:
        >>> parse_coordinate_value("37.7749,-122.4194")
        (37.7749, -122.4194)

        >>> parse_coordinate_value({"lat": 37.7749, "lng": -122.4194})
        (37.7749, -122.4194)
    """
    lat, lng = _extract_lat_lng(value)

    # Validate latitude bounds
    if not (-90 <= lat <= 90):
        raise GraphQLError(f"Latitude must be between -90 and 90, got {lat}")

    # Validate longitude bounds
    if not (-180 <= lng <= 180):
        raise GraphQLError(f"Longitude must be between -180 and 180, got {lng}")

    return (lat, lng)


def parse_coordinate_literal(
    ast: ValueNode,
    variables: dict[str, Any] | None = None,
) -> tuple[float, float]:
    """Parse GraphQL AST literal into validated coordinate tuple.

    Handles coordinate literals in GraphQL queries and mutations.
    Only string literals are supported for coordinates.

    Args:
        ast: GraphQL AST node representing the coordinate literal
        variables: GraphQL variables (unused for literals)

    Returns:
        Validated coordinate tuple (latitude, longitude)

    Raises:
        GraphQLError: If AST node is not a string or coordinate format is invalid

    Examples:
        GraphQL literal: "37.7749,-122.4194"
        Parsed result: (37.7749, -122.4194)
    """
    _ = variables
    if isinstance(ast, StringValueNode):
        return parse_coordinate_value(ast.value)
    msg = f"Coordinate cannot represent non-string literal: {getattr(ast, 'value', None)!r}"
    raise GraphQLError(msg)


CoordinateScalar = GraphQLScalarType(
    name="Coordinate",
    description="""Geographic coordinate as latitude/longitude pair.

A coordinate represents a point on Earth's surface using the WGS84 coordinate system.

Input Formats (GraphQL variables):
- String: "37.7749,-122.4194" (latitude,longitude)
- Tuple: [37.7749, -122.4194]
- Object: {lat: 37.7749, lng: -122.4194}

Validation:
- Latitude: -90.0 to 90.0 degrees
- Longitude: -180.0 to 180.0 degrees

Database Storage:
- PostgreSQL POINT type: (longitude, latitude)
- Supports spatial indexes and geographic queries

Filtering Operators:
- eq: Exact coordinate match
- neq: Coordinate inequality
- in/notin: Multiple coordinate matching
- distance_within: Distance-based filtering in meters

Examples:
    # Exact coordinate query
    query { location(coordinates: "37.7749,-122.4194") { name } }

    # Distance filtering
    query {
      nearbyLocations(where: {
        coordinates: { distanceWithin: { center: [37.7749, -122.4194], radius: 5000 } }
      }) {
        name
        coordinates
      }
    }
    """,
    serialize=serialize_coordinate,
    parse_value=parse_coordinate_value,
    parse_literal=parse_coordinate_literal,
)


class CoordinateField(str, ScalarMarker):
    """Type marker for geographic coordinate fields in FraiseQL models.

    This class serves as a type annotation for model fields that should contain
    geographic coordinates. It integrates with FraiseQL's type system to provide:

    - GraphQL Coordinate scalar type mapping
    - PostgreSQL POINT type database storage
    - Coordinate-specific filtering operators
    - Automatic validation and serialization

    When used in a FraiseQL model, this field type enables:
    - Spatial filtering with distance calculations
    - Geographic proximity queries
    - Coordinate validation and bounds checking
    - Efficient spatial indexing

    Examples:
        @fraiseql.type
        class Location:
            id: int
            name: str
            coordinates: CoordinateField  # Enables spatial queries
            address: str

        # GraphQL schema automatically includes Coordinate type
        # Database creates POINT column with GiST index
    """

    __slots__ = ()

    def __repr__(self) -> str:
        """Return string representation for debugging."""
        return "Coordinate"
