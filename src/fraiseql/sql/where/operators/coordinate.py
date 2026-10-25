"""Coordinate-specific SQL operators for PostgreSQL POINT type and geographic queries.

These functions build coordinate SQL for a path expression. They write what
``CoordinateOperatorStrategy`` writes (``fraiseql.sql.operators.advanced``), the
strategy ``db.find`` uses: coordinates are (latitude, longitude) tuples, stored as
``POINT(longitude, latitude)``, and points compare with ``~=`` (``point`` has no
``=``).
"""

from psycopg.sql import SQL, Composable, Composed

from fraiseql.sql.operators.advanced.coordinate_operators import (
    CoordinateOperatorStrategy,
    build_distance_earthdistance,
    build_distance_haversine,
    build_distance_postgis,
)

_STRATEGY = CoordinateOperatorStrategy()


def _build(operator: str, path_sql: Composable, val: object) -> Composed:
    sql = _STRATEGY.build_sql(operator, val, path_sql)
    if sql is None:  # not reached: the strategy writes every operator used here
        raise ValueError(f"coordinate operator {operator!r} is not supported")
    return Composed([sql])


def build_coordinate_eq_sql(path_sql: SQL, val: tuple[float, float]) -> Composed:
    """``(path)::point ~= POINT(lng, lat)`` for ``val`` = (latitude, longitude)."""
    return _build("eq", path_sql, val)


def build_coordinate_neq_sql(path_sql: SQL, val: tuple[float, float]) -> Composed:
    """``NOT ((path)::point ~= POINT(lng, lat))``."""
    return _build("neq", path_sql, val)


def build_coordinate_in_sql(path_sql: SQL, val: list[tuple[float, float]]) -> Composed:
    """``((path)::point ~= POINT(...) OR ...)``; FALSE for an empty list.

    Raises:
        TypeError: If ``val`` is not a list.
    """
    return _build("in", path_sql, val)


def build_coordinate_notin_sql(path_sql: SQL, val: list[tuple[float, float]]) -> Composed:
    """``NOT ((path)::point ~= POINT(...) OR ...)``; TRUE for an empty list.

    Raises:
        TypeError: If ``val`` is not a list.
    """
    return _build("notin", path_sql, val)


def build_coordinate_distance_within_sql(
    path_sql: SQL, center: tuple[float, float], distance_meters: float
) -> Composed:
    """PostGIS ``ST_DWithin`` on geographies, in meters (needs PostGIS)."""
    return build_distance_postgis(path_sql, center, distance_meters)


def build_coordinate_distance_within_sql_haversine(
    path_sql: SQL, center: tuple[float, float], distance_meters: float
) -> Composed:
    """Haversine great-circle distance in plain SQL (no extension)."""
    return build_distance_haversine(path_sql, center, distance_meters)


def build_coordinate_distance_within_sql_earthdistance(
    path_sql: SQL, center: tuple[float, float], distance_meters: float
) -> Composed:
    """``earth_distance(ll_to_earth(...), ...)`` (needs earthdistance and cube)."""
    return build_distance_earthdistance(path_sql, center, distance_meters)
