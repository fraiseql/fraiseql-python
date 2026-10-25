"""``FraiseQLConfig.coordinate_distance_method`` picks the ``distance_within`` SQL.

Only the ``FRAISEQL_COORDINATE_DISTANCE_METHOD`` environment variable was read:
``FraiseQLConfig(coordinate_distance_method="postgis")`` still built Haversine SQL.
"""

import pytest
from psycopg.sql import SQL

from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.builders.registry import SchemaRegistry
from fraiseql.sql.operators import get_default_registry as get_operator_registry
from fraiseql.types import Coordinate

_URL = "postgresql://localhost/test"


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    monkeypatch.delenv("FRAISEQL_COORDINATE_DISTANCE_METHOD", raising=False)
    schema_registry = SchemaRegistry.get_instance()
    saved = schema_registry.config
    yield schema_registry
    schema_registry.config = saved


def _distance_sql() -> str:
    sql = get_operator_registry().build_sql(
        path_sql=SQL("data->>'coordinates'"),
        operator="distance_within",
        value=((45.5, -122.6), 1000),
        field_type=Coordinate,
    )
    return sql.as_string(None)


@pytest.mark.parametrize(
    ("method", "marker"),
    [("postgis", "ST_DWithin"), ("earthdistance", "earth_distance"), ("haversine", "ASIN")],
)
def test_the_configured_method_is_used(registry, method, marker) -> None:
    registry.config = FraiseQLConfig(database_url=_URL, coordinate_distance_method=method)
    assert marker in _distance_sql()


def test_the_configured_method_wins_over_the_environment(registry, monkeypatch) -> None:
    registry.config = FraiseQLConfig(database_url=_URL, coordinate_distance_method="postgis")
    monkeypatch.setenv("FRAISEQL_COORDINATE_DISTANCE_METHOD", "earthdistance")
    assert "ST_DWithin" in _distance_sql()


def test_without_the_setting_the_environment_still_applies(registry, monkeypatch) -> None:
    registry.config = FraiseQLConfig(database_url=_URL)
    monkeypatch.setenv("FRAISEQL_COORDINATE_DISTANCE_METHOD", "postgis")
    assert "ST_DWithin" in _distance_sql()


def test_without_a_config_the_default_is_haversine(registry) -> None:
    registry.config = None
    assert "ASIN" in _distance_sql()
