"""The SQL a coordinate ``where`` gets through db.find, per distance method.

The pgvector test image has no PostGIS, so the PostGIS SQL is checked as text
here; the other methods run against PostgreSQL in
tests/integration/graphql/test_coordinate_where_end_to_end.py.
"""

import pytest

from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.builders.registry import SchemaRegistry
from fraiseql.where_clause import FieldCondition

pytestmark = pytest.mark.unit


@pytest.fixture
def method(request, monkeypatch):
    monkeypatch.delenv("FRAISEQL_COORDINATE_DISTANCE_METHOD", raising=False)
    registry = SchemaRegistry.get_instance()
    saved = registry.config
    registry.config = FraiseQLConfig(
        database_url="postgresql://localhost/test", coordinate_distance_method=request.param
    )
    yield request.param
    registry.config = saved


def _sql(operator: str, value, *, column: bool = False, declared: bool = True) -> str:
    condition = FieldCondition(
        field_path=["location"],
        operator=operator,
        value=value,
        lookup_strategy="sql_column" if column else "jsonb_path",
        target_column="location" if column else "data",
        jsonb_path=None if column else ["location"],
        temporal_cast="point" if declared else None,
    )
    sql, params = condition.to_sql()
    assert params == []
    return sql.as_string(None)


@pytest.mark.parametrize("method", ["postgis"], indirect=True)
def test_postgis_measures_geographies_in_meters(method) -> None:
    sql = _sql("distance_within", ((37.7749, -122.4194), 5000))

    assert sql == (
        "ST_DWithin(ST_SetSRID(ST_MakePoint(((\"data\" ->> 'location')::point)[0], "
        "((\"data\" ->> 'location')::point)[1]), 4326)::geography, "
        "ST_SetSRID(ST_MakePoint( -122.4194::float8, 37.7749::float8), 4326)::geography, "
        "5000.0::float8)"
    )


@pytest.mark.parametrize("method", ["haversine", "earthdistance"], indirect=True)
def test_haversine_and_earthdistance_need_no_postgis(method) -> None:
    sql = _sql("distance_within", ((37.7749, -122.4194), 5000), column=True)

    assert "ST_" not in sql
    assert '(("location")::point)[1]' in sql  # latitude
    assert '(("location")::point)[0]' in sql  # longitude


@pytest.mark.parametrize("method", ["haversine"], indirect=True)
def test_distance_within_needs_no_declared_type(method) -> None:
    # distance_within is a coordinate filter on any field
    sql = _sql("distance_within", {"center": [1, 2], "radius": 3}, declared=False)

    assert sql.startswith("(2 * 6371000 * ASIN(")


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("eq", "37.7,-122.4", "(\"data\" ->> 'location')::point ~= POINT( -122.4, 37.7)"),
        ("neq", (37.7, -122.4), "NOT ((\"data\" ->> 'location')::point ~= POINT( -122.4, 37.7))"),
        ("in", [], "FALSE"),
        ("nin", [], "TRUE"),
    ],
)
def test_point_filters_on_a_declared_coordinate(operator, value, expected) -> None:
    assert _sql(operator, value) == expected


@pytest.mark.parametrize(
    "value", [(37.7749, -122.4194), ((37.7749, -122.4194), "far"), {"center": [1, 2]}]
)
def test_a_malformed_distance_is_an_error(value) -> None:
    with pytest.raises(ValueError, match="coordinate filter 'distance_within' takes"):
        _sql("distance_within", value)
