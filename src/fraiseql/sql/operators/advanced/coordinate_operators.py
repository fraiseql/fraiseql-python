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

    SUPPORTED_OPERATORS = {"eq", "neq", "in", "notin", "distance_within"}

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
        """Build SQL for coordinate operators with proper PostgreSQL POINT type casting."""
        # Basic operations: cast to point
        if operator in ("eq", "neq", "in", "notin"):
            casted_path = SQL("({})::point").format(path_sql)

            if operator == "eq":
                if not isinstance(value, tuple) or len(value) != 2:
                    raise TypeError(
                        f"eq operator requires a coordinate tuple (lat, lng), got {value}"
                    )
                lat, lng = value
                # PostgreSQL POINT uses (x,y) = (longitude, latitude)
                return SQL("{} = POINT({}, {})").format(casted_path, Literal(lng), Literal(lat))

            if operator == "neq":
                if not isinstance(value, tuple) or len(value) != 2:
                    raise TypeError(
                        f"neq operator requires a coordinate tuple (lat, lng), got {value}"
                    )
                lat, lng = value
                return SQL("{} != POINT({}, {})").format(casted_path, Literal(lng), Literal(lat))

            if operator == "in":
                if not isinstance(value, list):
                    raise TypeError(f"'in' operator requires a list, got {type(value)}")

                point_literals = []
                for coord in value:
                    if not isinstance(coord, tuple) or len(coord) != 2:
                        raise TypeError(
                            f"in operator requires coordinate tuples (lat, lng), got {coord}"
                        )
                    lat, lng = coord
                    point_literals.append(SQL("POINT({}, {})").format(Literal(lng), Literal(lat)))
                placeholders = SQL(", ").join(point_literals)
                return SQL("{} IN ({})").format(casted_path, placeholders)

            if operator == "notin":
                if not isinstance(value, list):
                    raise TypeError(f"'notin' operator requires a list, got {type(value)}")

                point_literals = []
                for coord in value:
                    if not isinstance(coord, tuple) or len(coord) != 2:
                        raise TypeError(
                            f"notin operator requires coordinate tuples (lat, lng), got {coord}"
                        )
                    lat, lng = coord
                    point_literals.append(SQL("POINT({}, {})").format(Literal(lng), Literal(lat)))
                placeholders = SQL(", ").join(point_literals)
                return SQL("{} NOT IN ({})").format(casted_path, placeholders)

            if operator == "notin":
                if not isinstance(value, list):
                    raise TypeError(f"'notin' operator requires a list, got {type(value)}")

                sql_parts = [str(casted_path), " NOT IN ("]
                for i, coord in enumerate(value):
                    if i > 0:
                        sql_parts.append(", ")
                    if not isinstance(coord, tuple) or len(coord) != 2:
                        raise TypeError(
                            f"notin operator requires coordinate tuples (lat, lng), got {coord}"
                        )
                    lat, lng = coord
                    sql_parts.extend([f"POINT({lng}, {lat})"])
                sql_parts.append(")")
                return SQL("".join(sql_parts))

            if operator == "notin":
                if not isinstance(value, list):
                    raise TypeError(f"'notin' operator requires a list, got {type(value)}")

                parts = [casted_path, SQL(" NOT IN (")]
                for i, coord in enumerate(value):
                    if i > 0:
                        parts.append(SQL(", "))
                    if not isinstance(coord, tuple) or len(coord) != 2:
                        raise TypeError(
                            f"notin operator requires coordinate tuples (lat, lng), got {coord}"
                        )
                    lat, lng = coord
                    parts.extend([SQL("POINT("), Literal(lng), SQL(", "), Literal(lat), SQL(")")])
                parts.append(SQL(")"))
                return Composable(parts)

        # Distance operations
        elif operator == "distance_within":
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
            if not isinstance(distance_meters, (int, float)) or distance_meters < 0:
                raise TypeError(
                    f"distance_within distance must be a positive number, got {distance_meters}"
                )

            method = _distance_method()

            # Build SQL based on configured method
            if method == "postgis":
                return self._build_distance_postgis(path_sql, center_coord, distance_meters)
            if method == "earthdistance":
                return self._build_distance_earthdistance(path_sql, center_coord, distance_meters)
            if method == "haversine":
                return self._build_distance_haversine(path_sql, center_coord, distance_meters)
            raise ValueError(
                f"Invalid coordinate_distance_method: '{method}'. "
                f"Valid options: 'postgis', 'haversine', 'earthdistance'"
            )

        return None

    def _build_distance_postgis(
        self, path_sql: Composable, center: tuple[float, float], distance_meters: float
    ) -> Composable:
        """Build SQL for distance using PostGIS ST_DWithin."""
        lat, lng = center
        casted_path = SQL("({})::point").format(path_sql)

        return SQL("ST_DWithin({}, POINT({}, {}), {})").format(
            casted_path, Literal(lng), Literal(lat), Literal(distance_meters)
        )

    def _build_distance_haversine(
        self, path_sql: Composable, center: tuple[float, float], distance_meters: float
    ) -> Composable:
        """Build SQL for distance using Haversine formula."""
        center_lat, center_lng = center

        # Haversine formula: great-circle distance on spherical Earth
        # d = 2 * R * arcsin(sqrt(sin²((lat2-lat1)/2) + cos(lat1)*cos(lat2)*sin²((lng2-lng1)/2)))
        return SQL(
            "6371000 * 2 * ASIN(SQRT("
            "POWER(SIN(RADIANS({}) - RADIANS(ST_Y(({}::point)))), 2) / 2 + "
            "COS(RADIANS({})) * COS(RADIANS(ST_Y(({}::point)))) * "
            "POWER(SIN(RADIANS({}) - RADIANS(ST_X(({}::point)))), 2) / 2"
            ")) <= {}"
        ).format(
            Literal(center_lat),
            path_sql,
            Literal(center_lat),
            path_sql,
            Literal(center_lng),
            path_sql,
            Literal(distance_meters),
        )

    def _build_distance_earthdistance(
        self, path_sql: Composable, center: tuple[float, float], distance_meters: float
    ) -> Composable:
        """Build SQL for distance using earthdistance extension."""
        lat, lng = center
        casted_path = SQL("({})::point").format(path_sql)

        return Composed(
            [
                SQL("earth_distance(ll_to_earth("),
                Literal(lat),
                SQL(", "),
                Literal(lng),
                SQL("), ll_to_earth(ST_Y("),
                casted_path,
                SQL("), ST_X("),
                casted_path,
                SQL("))) <= "),
                Literal(distance_meters),
            ]
        )
