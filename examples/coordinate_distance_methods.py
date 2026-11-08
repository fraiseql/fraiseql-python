"""Example: Coordinate Distance Calculation Methods

FraiseQL supports three distance calculation methods for geographic coordinates:

1. Haversine (default) - Pure SQL, no dependencies
2. PostGIS ST_DWithin - Most accurate, requires PostGIS extension
3. earthdistance - Moderate accuracy, requires earthdistance extension

This example shows how to configure each method.
"""

import os

from fraiseql.fastapi import FraiseQLConfig

# Example 1: Using Haversine (default - no extension needed)
# Works out of the box with standard PostgreSQL
config_haversine = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    coordinate_distance_method="haversine"  # Default
)

# Example 2: Using PostGIS (recommended for production)
# Requires: CREATE EXTENSION IF NOT EXISTS postgis;
config_postgis = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    coordinate_distance_method="postgis"
)

# Example 3: Using earthdistance (legacy systems)
# Requires: CREATE EXTENSION IF NOT EXISTS earthdistance CASCADE;  (and cube)
config_earthdistance = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    coordinate_distance_method="earthdistance"
)

# Example 4: Using environment variable
# Set FRAISEQL_COORDINATE_DISTANCE_METHOD=postgis
os.environ["FRAISEQL_COORDINATE_DISTANCE_METHOD"] = "postgis"
config_from_env = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb"
    # Will use PostGIS based on environment variable
)


# What the method changes: the SQL of the `distance_within` operator
#
# `distance_within` takes ((latitude, longitude), meters):
#     db.find("v_location", where={"coordinates": {"distance_within": ((37.77, -122.42), 5000)}})
# In GraphQL, a Coordinate field gets a CoordinateFilter:
#     locations(where: {coordinates: {distanceWithin: {center: [37.77, -122.42], radius: 5000}}})
# The coordinate is a PostgreSQL point, (longitude, latitude): a point column, or
# its text in the view's JSONB. The example below prints the SQL each method writes.
def print_distance_sql() -> None:
    from psycopg.sql import SQL

    from fraiseql.sql.operators import get_default_registry
    from fraiseql.types import Coordinate

    registry = get_default_registry()
    san_francisco = (37.7749, -122.4194)
    for method in ("haversine", "postgis", "earthdistance"):
        # Without an app config, the method is read from the environment
        os.environ["FRAISEQL_COORDINATE_DISTANCE_METHOD"] = method
        sql = registry.build_sql(
            "distance_within",
            (san_francisco, 5000),  # 5 km
            SQL("data->>'coordinates'"),
            field_type=Coordinate,
        )
        print(f"{method}: {sql.as_string(None)}")


# Accuracy Comparison
"""
Method          | Accuracy         | Dependencies | Use Case
----------------|------------------|--------------|---------------------------
Haversine       | ±0.5% (<1000km)  | None         | Development, most apps
PostGIS         | ±0.1% (any dist) | PostGIS ext  | Production, global scale
earthdistance   | ±1-2%            | earthdist ext| Legacy systems

SQL Generated Examples (p is (data ->> 'coordinates')::point: p[0] is the
longitude, p[1] the latitude):

Haversine (default, plain SQL):
WHERE (2 * 6371000 * ASIN(LEAST(1, SQRT(
  POWER(SIN(RADIANS(p[1] - lat) / 2), 2) +
  COS(RADIANS(lat)) * COS(RADIANS(p[1])) *
  POWER(SIN(RADIANS(p[0] - lng) / 2), 2)
)))) <= distance_meters

PostGIS (on geographies, so the distance is in meters):
WHERE ST_DWithin(
  ST_SetSRID(ST_MakePoint(p[0], p[1]), 4326)::geography,
  ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography,
  distance_meters
)

earthdistance:
WHERE earth_distance(ll_to_earth(lat, lng), ll_to_earth(p[1], p[0])) <= distance_meters
"""


# Installation Instructions
"""
To install PostGIS (recommended for production):

1. Install PostgreSQL extension:
   sudo apt-get install postgresql-15-postgis-3  # Ubuntu/Debian
   brew install postgis                          # macOS

2. Enable in database:
   psql -d mydb -c "CREATE EXTENSION IF NOT EXISTS postgis;"

3. Configure FraiseQL:
   config = FraiseQLConfig(
       database_url="postgresql://...",
       coordinate_distance_method="postgis"
   )

To install earthdistance:

1. Enable in database (comes with PostgreSQL):
   psql -d mydb -c "CREATE EXTENSION IF NOT EXISTS earthdistance CASCADE;"

2. Configure FraiseQL:
   config = FraiseQLConfig(
       database_url="postgresql://...",
       coordinate_distance_method="earthdistance"
   )
"""


if __name__ == "__main__":
    print_distance_sql()
