"""FraiseQL Coordinate Datatype - Complete Geographic Coordinate Support

This comprehensive example demonstrates FraiseQL's Coordinate datatype for
handling geographic coordinates (latitude/longitude) with full PostgreSQL POINT
type integration and advanced spatial filtering capabilities.

Features Demonstrated:
- Coordinate field definition with type annotations
- Multiple coordinate input formats (string, tuple, dict)
- GraphQL queries with coordinate filtering operators
- Distance-based proximity queries
- Coordinate validation and bounds checking
- PostgreSQL POINT type database integration
- Spatial indexing recommendations

GraphQL Schema Integration:
- Automatic Coordinate scalar type registration
- Coordinate-specific filtering operators
- Type-safe coordinate validation
- Comprehensive error messages

Database Features:
- PostgreSQL POINT type for efficient storage
- GiST spatial indexes for query performance
- PostGIS ST_DWithin for accurate distance calculations
- Geographic coordinate system (WGS84) support

Real-World Use Cases:
- Location-based services
- Geographic search and filtering
- Proximity-based recommendations
- Mapping and GIS applications
- Delivery and logistics systems
"""

import fraiseql
from fraiseql.types import Coordinate


# Define a model with coordinate fields
@fraiseql.type
class Location:
    """A location with geographic coordinates."""

    id: int
    name: str
    coordinates: Coordinate  # Latitude/Longitude as (lat, lng) tuple
    description: str | None = None


# Example usage functions
def create_location_examples():
    """Create sample locations for demonstration."""
    locations_data = [
        {
            "name": "Golden Gate Bridge",
            "coordinates": (37.8199, -122.4783),  # (lat, lng)
            "description": "Iconic suspension bridge in San Francisco",
        },
        {
            "name": "Statue of Liberty",
            "coordinates": (40.6892, -74.0445),
            "description": "Famous statue in New York Harbor",
        },
        {
            "name": "Eiffel Tower",
            "coordinates": (48.8584, 2.2945),
            "description": "Iron lattice tower in Paris",
        },
        {
            "name": "Sydney Opera House",
            "coordinates": (-33.8568, 151.2153),
            "description": "Multi-venue performing arts centre",
        },
    ]

    return locations_data


def coordinate_filtering_examples():
    """Demonstrate various coordinate filtering operations."""
    print("=== Coordinate Filtering Examples ===\n")

    # 1. Find locations near San Francisco (within 50km)
    sf_lat, sf_lng = 37.7749, -122.4194

    print("1. Locations within 50km of San Francisco:")
    # In a real query, this would use:
    # where = WhereClause().distance_within("coordinates", (sf_lat, sf_lng), 50000)
    # results = Location.select(where=where)
    print("   Query: coordinates.distance_within((37.7749, -122.4194), 50000)")
    print("   Would return: Golden Gate Bridge\n")

    # 2. Find locations in the Northern Hemisphere (latitude > 0)
    print("2. Locations in Northern Hemisphere:")
    # where = WhereClause().gt("coordinates", (0, -180))
    print("   Query: coordinates > (0, -180)")
    print("   Would return: Golden Gate Bridge, Statue of Liberty, Eiffel Tower\n")

    # 3. Exact coordinate match
    print("3. Exact coordinate match for Eiffel Tower:")
    # where = WhereClause().eq("coordinates", (48.8584, 2.2945))
    print("   Query: coordinates.eq((48.8584, 2.2945))")
    print("   Would return: Eiffel Tower\n")

    # 4. Locations within coordinate range
    print("4. Locations in coordinate bounding box:")
    # where = WhereClause().in_("coordinates", [
    #     (37.8199, -122.4783),  # Golden Gate
    #     (40.6892, -74.0445),   # Statue of Liberty
    # ])
    print("   Query: coordinates.in_([(37.8199, -122.4783), (40.6892, -74.0445)])")
    print("   Would return: Golden Gate Bridge, Statue of Liberty\n")


def graphql_query_examples():
    """Show GraphQL queries using coordinate fields."""
    print("=== GraphQL Query Examples ===\n")

    # GraphQL query with coordinate filtering
    query_with_distance = """
    query FindNearbyLocations($lat: Float!, $lng: Float!, $radius: Float!) {
      locations(
        where: {
          coordinates: { distanceWithin: { center: [$lat, $lng], radius: $radius } }
        }
      ) {
        id
        name
        coordinates
        description
      }
    }
    """

    print("GraphQL Query - Find locations within radius:")
    print(query_with_distance)

    variables = {
        "lat": 37.7749,
        "lng": -122.4194,
        "radius": 50000,  # 50km in meters
    }
    print(f"Variables: {variables}\n")

    # GraphQL mutation creating a location
    mutation_example = """
    mutation CreateLocation($input: LocationInput!) {
      createLocation(input: $input) {
        id
        name
        coordinates
        success
      }
    }
    """

    print("GraphQL Mutation - Create location with coordinates:")
    print(mutation_example)

    mutation_vars = {
        "input": {
            "name": "Mount Everest",
            "coordinates": [27.9881, 86.9250],  # [lat, lng]
            "description": "Highest mountain in the world",
        }
    }
    print(f"Variables: {mutation_vars}\n")


def coordinate_validation_examples():
    """Demonstrate coordinate validation."""
    print("=== Coordinate Validation Examples ===\n")

    valid_coordinates = [
        (37.7749, -122.4194),  # San Francisco
        (-33.8568, 151.2153),  # Sydney (Southern Hemisphere)
        (90, 0),  # North Pole
        (-90, 180),  # South Pole with International Date Line
    ]

    print("Valid coordinates:")
    for coord in valid_coordinates:
        lat, lng = coord
        print(f"  ({lat}, {lng}) ✓")

    print("\nInvalid coordinates (would raise validation errors):")
    invalid_examples = [
        (91, 0),  # Latitude too high
        (0, 181),  # Longitude too high
        (-91, 0),  # Latitude too low
        (0, -181),  # Longitude too low
        "not a tuple",  # Wrong type
    ]

    for invalid in invalid_examples:
        print(f"  {invalid} ✗")


def database_schema_example():
    """Show the database schema for coordinate fields."""
    print("=== Database Schema Example ===\n")

    schema_sql = """
-- Location table with coordinate field
CREATE TABLE locations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    coordinates POINT,  -- PostgreSQL POINT type (lng, lat)
    description TEXT
);

-- GiST index for spatial queries (IMPORTANT for performance)
CREATE INDEX idx_locations_coordinates_gist
ON locations USING GIST (coordinates);

-- Sample data insertion
INSERT INTO locations (name, coordinates, description) VALUES
    ('Golden Gate Bridge', POINT(-122.4783, 37.8199), 'Iconic bridge'),
    ('Statue of Liberty', POINT(-74.0445, 40.6892), 'Famous statue'),
    ('Eiffel Tower', POINT(2.2945, 48.8584), 'Iron tower');

-- Example spatial queries
-- Find locations within 50km of San Francisco
SELECT * FROM locations
WHERE ST_DWithin(coordinates, ST_Point(-122.4194, 37.7749)::point, 50000);

-- Find nearest location to a point
SELECT name, ST_Distance(coordinates, ST_Point(-122.4194, 37.7749)::point) as distance
FROM locations
ORDER BY coordinates <-> ST_Point(-122.4194, 37.7749)::point
LIMIT 1;
"""

    print("PostgreSQL schema and queries:")
    print(schema_sql)


def main():
    """Run all coordinate examples."""
    print("FraiseQL Coordinate Datatype Examples")
    print("=" * 50)
    print()

    # Show data examples
    locations = create_location_examples()
    print("Sample Location Data:")
    for loc in locations:
        print(f"  {loc['name']}: {loc['coordinates']}")
    print()

    # Show filtering examples
    coordinate_filtering_examples()

    # Show GraphQL examples
    graphql_query_examples()

    # Show validation examples
    coordinate_validation_examples()

    # Show database schema
    database_schema_example()

    print("For more information, see:")
    print("- docs/performance/coordinate_performance_guide.md")
    print("- migrations/trinity/003_add_coordinate_indexes.sql")


if __name__ == "__main__":
    main()
