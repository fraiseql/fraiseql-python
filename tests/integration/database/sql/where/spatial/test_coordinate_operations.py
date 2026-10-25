"""Integration tests for coordinate filtering operations.

Tests the SQL generation and database execution of coordinate filters
to ensure proper PostgreSQL POINT type handling and geographic operations.
"""

import pytest
from psycopg.sql import SQL

from fraiseql.sql.operators import get_default_registry as get_operator_registry
from fraiseql.types import Coordinate

pytestmark = pytest.mark.database


@pytest.mark.integration
class TestCoordinateFilterOperations:
    """Test coordinate filtering with proper PostgreSQL POINT type handling."""

    def test_coordinate_eq_operation(self) -> None:
        """Test coordinate equality operation with POINT casting."""
        registry = get_operator_registry()
        path_sql = SQL("data->>'coordinates'")

        # Test coordinate equality
        coord = (45.5, -122.6)  # Seattle coordinates
        sql = registry.build_sql("eq", coord, path_sql, field_type=Coordinate)

        sql_str = sql.as_string(None)  # type: ignore
        assert "::point" in sql_str, "Missing point cast"
        assert " ~= " in sql_str, "Missing equality operator (point has ~=, not =)"
        # Should convert (lat, lng) to POINT(lng, lat)
        assert "POINT( -122.6, 45.5)" in sql_str, "Wrong coordinate order"

    def test_coordinate_neq_operation(self) -> None:
        """Test coordinate inequality operation."""
        registry = get_operator_registry()
        path_sql = SQL("data->>'coordinates'")

        coord = (47.6097, -122.3425)  # Pike Place Market
        sql = registry.build_sql("neq", coord, path_sql, field_type=Coordinate)

        sql_str = sql.as_string(None)  # type: ignore  # type: ignore
        assert "::point" in sql_str
        assert sql_str.startswith("NOT (")
        assert "POINT( -122.3425, 47.6097)" in sql_str

    def test_coordinate_in_operation(self) -> None:
        """Test coordinate IN operation with multiple coordinates."""
        registry = get_operator_registry()
        path_sql = SQL("data->>'coordinates'")

        coords = [
            (45.5, -122.6),  # Seattle
            (47.6097, -122.3425),  # Pike Place
            (40.7128, -74.0060),  # NYC
        ]

        sql = registry.build_sql("in", coords, path_sql, field_type=Coordinate)

        sql_str = sql.as_string(None)  # type: ignore
        assert "::point" in sql_str
        assert sql_str.count(" OR ") == 2
        # Check that all coordinates are present with correct lng,lat order
        assert "POINT( -122.6, 45.5)" in sql_str
        assert "POINT( -122.3425, 47.6097)" in sql_str
        assert "POINT( -74.006, 40.7128)" in sql_str

    def test_coordinate_notin_operation(self) -> None:
        """Test coordinate NOT IN operation."""
        registry = get_operator_registry()
        path_sql = SQL("data->>'coordinates'")

        coords = [(0, 0), (90, 180)]  # Origin and extreme coordinates

        sql = registry.build_sql("notin", coords, path_sql, field_type=Coordinate)

        sql_str = sql.as_string(None)  # type: ignore
        assert "::point" in sql_str
        assert sql_str.startswith("NOT (")
        assert "POINT(0, 0)" in sql_str
        assert "POINT(180, 90)" in sql_str

    def test_coordinate_distance_within_operation(self) -> None:
        """Test coordinate distance filtering with Haversine (default method)."""
        registry = get_operator_registry()
        path_sql = SQL("data->>'coordinates'")

        center = (45.5, -122.6)  # Seattle
        distance_meters = 1000

        sql = registry.build_sql(
            path_sql=path_sql,
            operator="distance_within",
            value=(center, distance_meters),
            field_type=Coordinate,
        )

        sql_str = sql.as_string(None)  # type: ignore
        # Default method is Haversine (no extension dependencies)
        assert "ASIN" in sql_str, "Missing Haversine formula"
        assert "::point" in sql_str, "Missing point cast"
        assert "6371000" in sql_str, "Missing Earth radius constant"
        assert "1000" in sql_str, "Wrong distance"

    def test_coordinate_edge_cases(self) -> None:
        """Test coordinate operations with edge cases."""
        registry = get_operator_registry()
        path_sql = SQL("data->>'coordinates'")

        # North pole
        north_pole = (90, 45)
        sql = registry.build_sql("eq", north_pole, path_sql, field_type=Coordinate)
        assert "POINT(45, 90)" in sql.as_string(None)  # type: ignore

        # South pole
        south_pole = (-90, 135)
        sql = registry.build_sql("eq", south_pole, path_sql, field_type=Coordinate)
        assert "POINT(135,  -90)" in sql.as_string(None)  # type: ignore

        # International date line
        date_line = (0, 180)
        sql = registry.build_sql("eq", date_line, path_sql, field_type=Coordinate)
        assert "POINT(180, 0)" in sql.as_string(None)  # type: ignore

    def test_coordinate_type_validation(self) -> None:
        """Test that coordinate operations require Coordinate field type."""
        registry = get_operator_registry()
        path_sql = SQL("data->>'coordinates'")

        # Should work with Coordinate type
        sql = registry.build_sql("eq", (45.5, -122.6), path_sql, field_type=Coordinate)
        assert "::point" in sql.as_string(None)  # type: ignore

        # Should NOT use point casting with wrong field type
        sql = registry.build_sql("eq", (45.5, -122.6), path_sql, field_type=str)
        sql_str = sql.as_string(None)  # type: ignore
        assert "::point" not in sql_str, "Should not use point casting for non-Coordinate types"

    def test_coordinate_distance_within_validation(self) -> None:
        """Test distance_within operator parameter validation."""
        registry = get_operator_registry()
        path_sql = SQL("data->>'coordinates'")

        center = (45.5, -122.6)  # Seattle
        distance_meters = 1000

        # Valid parameters
        sql = registry.build_sql(
            "distance_within", (center, distance_meters), path_sql, field_type=Coordinate
        )
        # Default method is Haversine
        assert "ASIN" in sql.as_string(None) or "ST_DWithin" in sql.as_string(None)  # type: ignore

        # Invalid: not a tuple
        with pytest.raises(TypeError, match="distance_within operator requires a tuple"):
            registry.build_sql(
                path_sql=path_sql,
                operator="distance_within",
                value="(45.5, -122.6), 1000",  # String instead of tuple
                field_type=Coordinate,
            )

        # Invalid: center not a coordinate tuple
        with pytest.raises(TypeError, match="distance_within center must be a coordinate tuple"):
            registry.build_sql(
                path_sql=path_sql,
                operator="distance_within",
                value=(45.5, -122.6),  # Center is not a tuple
                field_type=Coordinate,
            )

        # Invalid: wrong tuple length
        with pytest.raises(TypeError, match="distance_within operator requires a tuple"):
            registry.build_sql(
                path_sql=path_sql,
                operator="distance_within",
                value=((45.5, -122.6),),  # Wrong length
                field_type=Coordinate,
            )

        # Invalid: center not a coordinate tuple
        with pytest.raises(TypeError, match="distance_within center must be a coordinate tuple"):
            registry.build_sql(
                path_sql=path_sql,
                operator="distance_within",
                value=("45.5,-122.6", 1000),  # String instead of tuple
                field_type=Coordinate,
            )

        # Invalid: center not a coordinate tuple
        with pytest.raises(TypeError, match="distance_within center must be a coordinate tuple"):
            registry.build_sql(
                path_sql=path_sql,
                operator="distance_within",
                value=("45.5,-122.6", 1000),  # String instead of tuple
                field_type=Coordinate,
            )

        # Invalid: negative distance
        with pytest.raises(TypeError, match="distance_within distance must be a positive number"):
            registry.build_sql(
                path_sql=path_sql,
                operator="distance_within",
                value=((45.5, -122.6), -100),  # Negative distance
                field_type=Coordinate,
            )

    def test_coordinate_vs_other_types(self) -> None:
        """Test that coordinate operations differ from other field types."""
        registry = get_operator_registry()
        path_sql = SQL("data->>'location'")

        coord_value = (45.5, -122.6)

        # With Coordinate type - should use POINT casting
        coord_sql = registry.build_sql("eq", coord_value, path_sql, field_type=Coordinate)
        coord_sql_str = str(coord_sql)
        assert "::point" in coord_sql_str
        assert "POINT(" in coord_sql_str

        # With string type - should NOT use POINT casting
        string_sql = registry.build_sql(
            "eq",
            str(coord_value),  # Convert to string
            path_sql,
            field_type=str,
        )
        string_sql_str = str(string_sql)
        assert "::point" not in string_sql_str
        assert "POINT(" not in string_sql_str

    def test_coordinate_distance_method_selection(self) -> None:
        """Test that distance method can be configured via environment variable."""
        import os

        registry = get_operator_registry()
        path_sql = SQL("data->>'coordinates'")
        center = (45.5, -122.6)
        distance_meters = 1000

        # Test default (haversine)
        os.environ.pop("FRAISEQL_COORDINATE_DISTANCE_METHOD", None)
        sql = registry.build_sql(
            path_sql=path_sql,
            operator="distance_within",
            value=(center, distance_meters),
            field_type=Coordinate,
        )
        assert "ASIN" in sql.as_string(None)  # type: ignore, "Should use Haversine by default"

        # Test PostGIS
        os.environ["FRAISEQL_COORDINATE_DISTANCE_METHOD"] = "postgis"
        sql = registry.build_sql(
            path_sql=path_sql,
            operator="distance_within",
            value=(center, distance_meters),
            field_type=Coordinate,
        )
        assert "ST_DWithin" in sql.as_string(None)  # type: ignore, "Should use PostGIS when configured"

        # Test earthdistance
        os.environ["FRAISEQL_COORDINATE_DISTANCE_METHOD"] = "earthdistance"
        sql = registry.build_sql(
            path_sql=path_sql,
            operator="distance_within",
            value=(center, distance_meters),
            field_type=Coordinate,
        )
        assert "earth_distance" in sql.as_string(None)  # type: ignore, "Should use earthdistance when configured"

        # Cleanup
        os.environ.pop("FRAISEQL_COORDINATE_DISTANCE_METHOD", None)

    def test_coordinate_operator_availability(self) -> None:
        """Test which operators are available for coordinate fields."""
        registry = get_operator_registry()
        path_sql = SQL("data->>'coordinates'")

        # Available operators
        available_ops = ["eq", "neq", "in", "notin", "distance_within"]

        for op in available_ops:
            # Should not raise an error
            if op == "distance_within":
                val = ((45.5, -122.6), 1000)
            elif op in ("in", "notin"):
                val = [(45.5, -122.6)]
            else:
                val = (45.5, -122.6)

            sql = registry.build_sql(op, val, path_sql, field_type=Coordinate)
            assert sql is not None

        # Unavailable operators should NOT use point casting
        unavailable_ops = ["contains", "startswith", "endswith", "matches"]
        for op in unavailable_ops:
            sql = registry.build_sql(
                operator=op, value="(45.5, -122.6)", path_sql=path_sql, field_type=Coordinate
            )
            sql_str = sql.as_string(None)  # type: ignore
            assert "::point" not in sql_str, f"Operator {op} should not use point casting"
