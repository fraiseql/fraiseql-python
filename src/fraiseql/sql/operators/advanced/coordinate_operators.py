"""Coordinate operator strategies for geographic POINT data."""

import os
from typing import Any, Optional

from psycopg.sql import SQL, Composable, Composed, Literal

from fraiseql.sql.operators.base import BaseOperatorStrategy


def _distance_method() -> str:
    """The ``distance_within`` method: the app's config, else the environment, else haversine.

    ``FraiseQLConfig.coordinate_distance_method`` counts when it was set (in code or
    from ``FRAISEQL_COORDINATE_DISTANCE_METHOD`` when the config was built). Without
    such a config, the environment variable is read at query time.
    """
    from fraiseql.gql.builders.registry import SchemaRegistry

    config = SchemaRegistry.get_instance().config
    if config is not None and "coordinate_distance_method" in getattr(
        config, "model_fields_set", ()
    ):
        return str(config.coordinate_distance_method).lower()
    return os.environ.get("FRAISEQL_COORDINATE_DISTANCE_METHOD", "haversine").lower()


class CoordinateOperatorStrategy(BaseOperatorStrategy):
    """Strategy for geographic coordinate operators with PostgreSQL POINT type casting.

    Provides comprehensive coordinate filtering operations including exact equality,
    distance calculations, and PostgreSQL POINT type integration.

    Basic Operations:
        - eq: Exact coordinate equality
        - neq: Coordinate inequality
        - in: Coordinate in list of coordinates
        - notin: Coordinate not in list of coordinates

    Distance Operations:
        - distance_within: Find coordinates within distance (meters) of center point

    Note: Coordinates are provided as (latitude, longitude) tuples but are
    converted to PostgreSQL POINT(longitude, latitude) format.
    """

    SUPPORTED_OPERATORS = {"eq", "neq", "in", "notin", "nin", "distance_within"}

    def supports_operator(self, operator: str, field_type: Optional[type]) -> bool:
        """Check if this is a coordinate operator."""
        if operator not in self.SUPPORTED_OPERATORS:
            return False

        # Define coordinate-specific operators
        coordinate_specific_ops = {"distance_within"}

        # If no field type provided, only handle coordinate-specific operators
        if field_type is None:
            return operator in coordinate_specific_ops

        # Check if field_type is a Coordinate type
        type_name = field_type.__name__ if hasattr(field_type, "__name__") else str(field_type)
        return "Coordinate" in type_name or "coordinate" in type_name.lower()

    def build_sql(
        self,
        operator: str,
        value: Any,
        path_sql: Composable,
        field_type: Optional[type] = None,
        jsonb_column: Optional[str] = None,
    ) -> Optional[Composable]:
        """Build SQL for coordinate operators with proper PostgreSQL POINT type casting.

        ``point`` has no ``=`` operator: equality is ``~=`` ("same as").
        """
        if operator in ("eq", "neq", "in", "notin", "nin"):
            casted_path = _point(path_sql)

            if operator in ("eq", "neq"):
                same = SQL("{} ~= {}").format(casted_path, _point_literal(value, operator))
                return same if operator == "eq" else SQL("NOT ({})").format(same)

            if not isinstance(value, list):
                raise TypeError(f"'{operator}' operator requires a list, got {type(value)}")
            if not value:
                return SQL("FALSE") if operator == "in" else SQL("TRUE")
            any_same = SQL(" OR ").join(
                SQL("{} ~= {}").format(casted_path, _point_literal(coord, operator))
                for coord in value
            )
            if operator == "in":
                return SQL("({})").format(any_same)
            return SQL("NOT ({})").format(any_same)

        if operator == "distance_within":
            # value should be a tuple: (center_coord, distance_meters)
            if not isinstance(value, tuple) or len(value) != 2:
                raise TypeError(
                    f"distance_within operator requires a tuple "
                    f"(center_coord, distance_meters), got {value}"
                )

            center_coord, distance_meters = value
            if not isinstance(center_coord, tuple) or len(center_coord) != 2:
                raise TypeError(
                    f"distance_within center must be a coordinate tuple "
                    f"(lat, lng), got {center_coord}"
                )
            if (
                not isinstance(distance_meters, (int, float))
                or isinstance(distance_meters, bool)
                or distance_meters < 0
            ):
                raise TypeError(
                    f"distance_within distance must be a positive number, got {distance_meters}"
                )

            method = _distance_method()
            builders = {
                "postgis": build_distance_postgis,
                "earthdistance": build_distance_earthdistance,
                "haversine": build_distance_haversine,
            }
            if method not in builders:
                raise ValueError(
                    f"Invalid coordinate_distance_method: '{method}'. "
                    f"Valid options: 'postgis', 'haversine', 'earthdistance'"
                )
            return builders[method](path_sql, center_coord, distance_meters)

        return None


def _point(path_sql: Composable) -> Composed:
    """``(path)::point``: a JSONB field's text, or a ``point`` column, as a point."""
    return Composed([SQL("("), path_sql, SQL(")::point")])


def _float(value: float) -> Composed:
    # A bare 37.7749 is numeric, which ll_to_earth() doesn't take
    return Composed([Literal(float(value)), SQL("::float8")])


def _point_literal(coord: Any, operator: str) -> Composed:
    """``POINT(lng, lat)`` for a (latitude, longitude) tuple."""
    if not isinstance(coord, tuple) or len(coord) != 2:
        raise TypeError(f"{operator} operator requires a coordinate tuple (lat, lng), got {coord}")
    lat, lng = coord
    return Composed([SQL("POINT("), Literal(lng), SQL(", "), Literal(lat), SQL(")")])


def build_distance_haversine(
    path_sql: Composable, center: tuple[float, float], distance_meters: float
) -> Composed:
    """Great-circle distance on a sphere of radius 6,371 km, in plain SQL.

    A point is ``(longitude, latitude)``: ``p[0]`` is the longitude, ``p[1]`` the
    latitude. No extension is needed (``ST_X`` / ``ST_Y`` are PostGIS's).

    d = 2R * asin(sqrt(sin^2(dlat / 2) + cos(lat1) * cos(lat2) * sin^2(dlng / 2)))
    """
    center_lat, center_lng = center
    point = _point(path_sql)
    lat = Composed([SQL("("), point, SQL(")[1]")])
    lng = Composed([SQL("("), point, SQL(")[0]")])
    return Composed(
        [
            SQL("(2 * 6371000 * ASIN(LEAST(1, SQRT(POWER(SIN(RADIANS("),
            lat,
            SQL(" - "),
            _float(center_lat),
            SQL(") / 2), 2) + COS(RADIANS("),
            _float(center_lat),
            SQL(")) * COS(RADIANS("),
            lat,
            SQL(")) * POWER(SIN(RADIANS("),
            lng,
            SQL(" - "),
            _float(center_lng),
            SQL(") / 2), 2)))) <= "),
            _float(distance_meters),
            SQL(")"),
        ]
    )


def build_distance_earthdistance(
    path_sql: Composable, center: tuple[float, float], distance_meters: float
) -> Composed:
    """``earth_distance(ll_to_earth(lat, lng), ...)``: needs ``earthdistance`` (and ``cube``)."""
    center_lat, center_lng = center
    point = _point(path_sql)
    return Composed(
        [
            SQL("(earth_distance(ll_to_earth("),
            _float(center_lat),
            SQL(", "),
            _float(center_lng),
            SQL("), ll_to_earth(("),
            point,
            SQL(")[1], ("),
            point,
            SQL(")[0])) <= "),
            _float(distance_meters),
            SQL(")"),
        ]
    )


def build_distance_postgis(
    path_sql: Composable, center: tuple[float, float], distance_meters: float
) -> Composed:
    """``ST_DWithin`` on geographies (WGS 84), so the distance is in meters: needs PostGIS.

    On a ``point`` or a ``geometry``, ST_DWithin measures in the units of the
    coordinates, degrees here.
    """
    center_lat, center_lng = center
    point = _point(path_sql)
    return Composed(
        [
            SQL("ST_DWithin(ST_SetSRID(ST_MakePoint(("),
            point,
            SQL(")[0], ("),
            point,
            SQL(")[1]), 4326)::geography, ST_SetSRID(ST_MakePoint("),
            _float(center_lng),
            SQL(", "),
            _float(center_lat),
            SQL("), 4326)::geography, "),
            _float(distance_meters),
            SQL(")"),
        ]
    )
