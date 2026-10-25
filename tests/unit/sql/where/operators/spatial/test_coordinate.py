"""Comprehensive tests for coordinate operator SQL building.

Consolidated from test_coordinate_operators_sql_building.py and test_coordinate_operators_complete.py.
"""

import pytest
from psycopg.sql import SQL

from fraiseql.sql.where.operators.coordinate import (
    build_coordinate_distance_within_sql,
    build_coordinate_distance_within_sql_earthdistance,
    build_coordinate_distance_within_sql_haversine,
    build_coordinate_eq_sql,
    build_coordinate_in_sql,
    build_coordinate_neq_sql,
    build_coordinate_notin_sql,
)


class TestCoordinateBasicOperators:
    """Test basic coordinate comparison operators."""

    def test_eq_coordinate(self):
        """Test coordinate equality."""
        path_sql = SQL("location")
        result = build_coordinate_eq_sql(path_sql, (45.5, -122.6))
        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "-122.6" in sql_str
        assert "45.5" in sql_str
        assert "::point" in sql_str
        assert "=" in sql_str

    def test_neq_coordinate(self):
        """Test coordinate inequality."""
        path_sql = SQL("location")
        result = build_coordinate_neq_sql(path_sql, (47.6, -122.3))
        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "-122.3" in sql_str
        assert "47.6" in sql_str
        assert "::point ~= POINT(" in sql_str
        assert sql_str.startswith("NOT (")

    def test_in_coordinates(self):
        """Test coordinate IN list."""
        path_sql = SQL("location")
        coords = [(45.5, -122.6), (47.6, -122.3)]
        result = build_coordinate_in_sql(path_sql, coords)
        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "-122.6" in sql_str
        assert "45.5" in sql_str
        assert "POINT(" in sql_str
        assert "-122.3" in sql_str
        assert "47.6" in sql_str
        assert "::point" in sql_str
        assert "IN" in sql_str

    def test_notin_coordinates(self):
        """Test coordinate NOT IN list."""
        path_sql = SQL("location")
        coords = [(40.7, -74.0), (34.0, -118.2)]
        result = build_coordinate_notin_sql(path_sql, coords)
        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "-74.0" in sql_str
        assert "40.7" in sql_str
        assert "POINT(" in sql_str
        assert "-118.2" in sql_str
        assert "34.0" in sql_str
        assert "::point ~= POINT(" in sql_str
        assert sql_str.startswith("NOT (")
        assert " OR " in sql_str

    def test_build_coordinate_equality_sql(self) -> None:
        """Should build proper POINT casting for coordinate equality."""
        # Red cycle - this will fail initially
        path_sql = SQL("(data ->> 'location')")
        result = build_coordinate_eq_sql(path_sql, (45.5, -122.6))

        # Should generate: ((data ->> 'location'))::point = POINT(-122.6, 45.5)
        sql_str = result.as_string(None)
        assert "::point ~= POINT(" in sql_str
        assert "data ->> 'location'" in sql_str
        assert "-122.6" in sql_str
        assert "45.5" in sql_str

    def test_build_coordinate_inequality_sql(self) -> None:
        """Should build proper POINT casting for coordinate inequality."""
        # Red cycle - this will fail initially
        path_sql = SQL("(data ->> 'coordinates')")
        result = build_coordinate_neq_sql(path_sql, (47.6097, -122.3425))

        # Should generate: (data ->> 'coordinates')::point != POINT(-122.3425, 47.6097)
        sql_str = result.as_string(None)
        assert "data ->> 'coordinates'" in sql_str
        assert sql_str.startswith("NOT (")
        assert "::point ~= POINT( -122.3425, 47.6097)" in sql_str

    def test_build_coordinate_in_list_sql(self) -> None:
        """Should build proper POINT casting for coordinate IN lists."""
        # Red cycle - this will fail initially
        path_sql = SQL("(data ->> 'position')")
        coord_list = [(45.5, -122.6), (47.6097, -122.3425), (40.7128, -74.0060)]
        result = build_coordinate_in_sql(path_sql, coord_list)

        # Should generate: (data ->> 'position')::point IN (POINT(-122.6, 45.5), POINT(-122.3425, 47.6097), POINT(-74.0060, 40.7128))
        sql_str = result.as_string(None)
        assert "data ->> 'position'" in sql_str
        assert sql_str.count(" OR ") == 2
        assert "POINT(" in sql_str
        assert "-122.6" in sql_str
        assert "45.5" in sql_str
        assert "POINT(" in sql_str
        assert "-122.3425" in sql_str
        assert "47.6097" in sql_str
        assert "POINT(" in sql_str
        assert "-74.006" in sql_str
        assert "40.7128" in sql_str

    def test_build_coordinate_not_in_list_sql(self) -> None:
        """Should build proper POINT casting for coordinate NOT IN lists."""
        # Red cycle - this will fail initially
        path_sql = SQL("(data ->> 'location')")
        coord_list = [(0.0, 0.0), (90.0, 180.0)]
        result = build_coordinate_notin_sql(path_sql, coord_list)

        # Should generate: (data ->> 'location')::point NOT IN (POINT(0, 0), POINT(180, 90))
        sql_str = result.as_string(None)
        assert "data ->> 'location'" in sql_str
        assert sql_str.startswith("NOT (")
        assert "POINT(0.0, 0.0)" in sql_str
        assert "POINT(180.0, 90.0)" in sql_str


class TestCoordinateDistancePostGIS:
    """Test PostGIS distance calculations."""

    def test_distance_within_postgis(self):
        """Test distance within using PostGIS ST_DWithin."""
        path_sql = SQL("location")
        center = (45.5, -122.6)
        distance = 1000.0
        result = build_coordinate_distance_within_sql(path_sql, center, distance)
        sql_str = result.as_string(None)
        assert "ST_DWithin" in sql_str
        assert "ST_MakePoint(((location)::point)[0], ((location)::point)[1])" in sql_str
        assert "ST_MakePoint( -122.6::float8, 45.5::float8)" in sql_str
        assert "::geography" in sql_str
        assert "1000.0" in sql_str

    def test_distance_within_postgis_zero_distance(self):
        """Test distance within with zero distance."""
        path_sql = SQL("location")
        center = (0.0, 0.0)
        distance = 0.0
        result = build_coordinate_distance_within_sql(path_sql, center, distance)
        sql_str = result.as_string(None)
        assert "ST_DWithin" in sql_str
        assert "ST_MakePoint(0.0::float8, 0.0::float8)" in sql_str
        assert "0.0" in sql_str
        assert "0.0" in sql_str

    def test_build_coordinate_distance_within_sql_postgis(self) -> None:
        """Should build PostGIS ST_DWithin for distance calculations."""
        # Red cycle - this will fail initially
        path_sql = SQL("(data ->> 'coordinates')")
        center = (45.5, -122.6)
        meters = 1000
        result = build_coordinate_distance_within_sql(path_sql, center, meters)

        # Should generate: ST_DWithin((data ->> 'coordinates')::point, POINT(-122.6, 45.5), 1000)
        sql_str = result.as_string(None)
        assert "ST_DWithin(" in sql_str
        assert "data ->> 'coordinates'" in sql_str
        assert "::point" in sql_str
        assert "::geography" in sql_str
        assert "-122.6" in sql_str
        assert "45.5" in sql_str
        assert "1000" in sql_str


class TestCoordinateDistanceHaversine:
    """Test Haversine distance calculations."""

    def test_distance_within_haversine(self):
        """Test distance within using Haversine formula."""
        path_sql = SQL("location")
        center = (45.5, -122.6)
        distance = 5000.0
        result = build_coordinate_distance_within_sql_haversine(path_sql, center, distance)
        sql_str = result.as_string(None)
        assert "6371000" in sql_str  # Earth radius
        assert "ASIN" in sql_str
        assert "SQRT" in sql_str
        assert "RADIANS" in sql_str
        assert "ST_" not in sql_str  # PostGIS
        assert "((location)::point)[1]" in sql_str  # latitude
        assert "((location)::point)[0]" in sql_str  # longitude
        assert "5000.0" in sql_str

    def test_distance_within_haversine_equator(self):
        """Test distance within at equator."""
        path_sql = SQL("location")
        center = (0.0, 0.0)
        distance = 10000.0
        result = build_coordinate_distance_within_sql_haversine(path_sql, center, distance)
        sql_str = result.as_string(None)
        assert "RADIANS(0.0::float8)" in sql_str
        assert "10000.0" in sql_str

    def test_build_coordinate_distance_within_sql_haversine(self) -> None:
        """Should build Haversine formula for distance calculations (fallback)."""
        # Test the fallback Haversine implementation
        path_sql = SQL("(data ->> 'location')")
        center = (47.6097, -122.3425)  # Seattle coordinates
        meters = 5000
        result = build_coordinate_distance_within_sql_haversine(path_sql, center, meters)

        # Should generate complex Haversine formula
        sql_str = result.as_string(None)
        assert "data ->> 'location'" in sql_str
        assert "ASIN" in sql_str  # Haversine uses ASIN
        assert "SIN" in sql_str  # Haversine uses SIN
        assert "COS" in sql_str  # Haversine uses COS
        assert "6371000" in sql_str  # Earth radius in meters


class TestCoordinateDistanceEarthDistance:
    """Test earthdistance module calculations."""

    def test_distance_within_earthdistance(self):
        """Test distance within using earthdistance extension."""
        path_sql = SQL("location")
        center = (40.7, -74.0)
        distance = 2000.0
        result = build_coordinate_distance_within_sql_earthdistance(path_sql, center, distance)
        sql_str = result.as_string(None)
        assert "earth_distance" in sql_str
        assert "ll_to_earth" in sql_str
        assert "40.7" in sql_str
        assert "-74.0" in sql_str
        assert "2000.0" in sql_str
        assert "ST_" not in sql_str  # PostGIS
        assert "ll_to_earth(((location)::point)[1], ((location)::point)[0])" in sql_str


class TestCoordinateEdgeCases:
    """Test coordinate operator edge cases."""

    def test_in_requires_list(self):
        """Test that IN operator requires a list."""
        path_sql = SQL("location")
        with pytest.raises(TypeError, match="'in' operator requires a list"):
            build_coordinate_in_sql(path_sql, "not-a-list")  # type: ignore

    def test_notin_requires_list(self):
        """Test that NOT IN operator requires a list."""
        path_sql = SQL("location")
        with pytest.raises(TypeError, match="'notin' operator requires a list"):
            build_coordinate_notin_sql(path_sql, "not-a-list")  # type: ignore

    def test_empty_coordinate_list(self):
        """Test empty coordinate list."""
        path_sql = SQL("location")
        result = build_coordinate_in_sql(path_sql, [])
        sql_str = result.as_string(None)
        assert sql_str == "FALSE"

    def test_single_coordinate_in_list(self):
        """Test single coordinate in list."""
        path_sql = SQL("location")
        coords = [(51.5, -0.1)]  # London
        result = build_coordinate_in_sql(path_sql, coords)
        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "-0.1" in sql_str
        assert "51.5" in sql_str
        assert "::point" in sql_str


class TestCoordinateBoundaryValues:
    """Test coordinate boundary values."""

    def test_north_pole(self):
        """Test North Pole coordinates."""
        path_sql = SQL("location")
        result = build_coordinate_eq_sql(path_sql, (90.0, 0.0))
        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "0.0" in sql_str
        assert "90.0" in sql_str

    def test_south_pole(self):
        """Test South Pole coordinates."""
        path_sql = SQL("location")
        result = build_coordinate_eq_sql(path_sql, (-90.0, 0.0))
        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "0.0" in sql_str
        assert "-90.0" in sql_str

    def test_prime_meridian(self):
        """Test Prime Meridian coordinates."""
        path_sql = SQL("location")
        result = build_coordinate_eq_sql(path_sql, (0.0, 0.0))
        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "0.0" in sql_str

    def test_international_date_line(self):
        """Test International Date Line coordinates."""
        path_sql = SQL("location")
        result = build_coordinate_eq_sql(path_sql, (0.0, 180.0))
        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "180.0" in sql_str
        assert "0.0" in sql_str

    def test_negative_longitude(self):
        """Test negative longitude (Western Hemisphere)."""
        path_sql = SQL("location")
        result = build_coordinate_eq_sql(path_sql, (40.7, -74.0))  # New York
        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "-74.0" in sql_str
        assert "40.7" in sql_str


class TestCoordinatePointOrderConversion:
    """Test coordinate point order conversion."""

    def test_coordinate_point_order_conversion(self) -> None:
        """Test that coordinates are properly converted from (lat,lng) to POINT(lng,lat)."""
        # PostgreSQL POINT uses (x,y) which maps to (longitude, latitude)
        # But users provide coordinates as (latitude, longitude)
        # So (45.5, -122.6) should become POINT(-122.6, 45.5)

        path_sql = SQL("(data ->> 'coords')")
        result = build_coordinate_eq_sql(path_sql, (45.5, -122.6))

        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "-122.6" in sql_str
        assert "45.5" in sql_str
        assert "POINT(45.5, -122.6)" not in sql_str  # NOT lat first

    def test_coordinate_edge_cases(self) -> None:
        """Test coordinate edge cases like poles and date line."""
        # North pole
        path_sql = SQL("(data ->> 'position')")
        result = build_coordinate_eq_sql(path_sql, (90, 45))  # lat=90, lng=45
        sql_str = result.as_string(None)
        assert "POINT(45, 90)" in sql_str

        # South pole
        result = build_coordinate_eq_sql(path_sql, (-90, 135))  # lat=-90, lng=135
        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "135" in sql_str
        assert "-90" in sql_str

        # International date line (lng=180)
        result = build_coordinate_eq_sql(path_sql, (0, 180))  # lat=0, lng=180
        sql_str = result.as_string(None)
        assert "POINT(180, 0)" in sql_str

        # International date line negative (lng=-180)
        result = build_coordinate_eq_sql(path_sql, (0, -180))  # lat=0, lng=-180
        sql_str = result.as_string(None)
        assert "POINT(" in sql_str
        assert "-180" in sql_str
        assert "0" in sql_str
