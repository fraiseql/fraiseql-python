"""A ``Coordinate`` field filters by distance through db.find.

``db.find(where={"location": {"distance_within": ...}})`` wrote
``data ->> 'location' distance_within %s``, a syntax error, and ``eq`` / ``in``
on a ``Coordinate`` field compared the JSONB text with a tuple. A coordinate is
stored as a ``point``, ``(longitude, latitude)``: a ``point`` column, or its text
in the view's JSONB.
"""

import pytest
import pytest_asyncio
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository
from fraiseql.fastapi import FraiseQLConfig
from fraiseql.gql.builders.registry import SchemaRegistry
from fraiseql.types import Coordinate

pytestmark = [pytest.mark.integration, pytest.mark.database]

# id: (latitude, longitude)
_PLACES = {
    1: (37.7749, -122.4194),  # San Francisco
    2: (37.8044, -122.2711),  # Oakland, 13 km away
    3: (37.3382, -121.8863),  # San Jose, 68 km away
    4: (40.7128, -74.0060),  # New York
}
_SF = "37.7749,-122.4194"
_NY = "40.7128,-74.006"

# Methods that need no PostGIS (the pgvector image has no PostGIS)
_METHODS = ["haversine", "earthdistance"]

# (radius in meters, expected ids): Oakland is 13.4 km from San Francisco
_DISTANCES = [(0, [1]), (13_300, [1]), (13_600, [1, 2]), (100_000, [1, 2, 3])]

# (GraphQL filter, Python filter, expected ids)
_POINT_FILTERS = [
    (f'{{eq: "{_SF}"}}', {"eq": _SF}, [1]),
    (f'{{neq: "{_SF}"}}', {"neq": (37.7749, -122.4194)}, [2, 3, 4]),
    (f'{{in: ["{_SF}", "{_NY}"]}}', {"in": [_SF, (40.7128, -74.006)]}, [1, 4]),
    (f'{{nin: ["{_SF}", "{_NY}"]}}', {"nin": [_SF, _NY]}, [2, 3]),
    ("{isnull: false}", {"isnull": False}, [1, 2, 3, 4]),
]

_ROOTS = {"places": "v_co_place", "flatPlaces": "v_co_flat_place"}


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def place_tables(class_db_pool, test_schema) -> None:
    values = ", ".join(f"({i}, point({lng}, {lat}))" for i, (lat, lng) in _PLACES.items())
    async with class_db_pool.connection() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS earthdistance CASCADE")
        await conn.execute(
            f"""
            CREATE TABLE {test_schema}.tb_co_place (id int PRIMARY KEY, location point);
            INSERT INTO {test_schema}.tb_co_place VALUES {values};
            CREATE VIEW {test_schema}.v_co_place AS
                SELECT id, jsonb_build_object('id', id, 'location', location) AS data
                FROM {test_schema}.tb_co_place;
            CREATE VIEW {test_schema}.v_co_flat_place AS
                SELECT id, location FROM {test_schema}.tb_co_place;
            """
        )
        await conn.commit()


@pytest.fixture
def place_types(test_schema, clear_registry):
    @fraiseql.type(sql_source=f"{test_schema}.v_co_place", jsonb_column="data")
    class CoPlace:
        id: int
        location: Coordinate | None

    @fraiseql.type(sql_source=f"{test_schema}.v_co_flat_place", jsonb_column=None)
    class CoFlatPlace:
        id: int
        location: Coordinate | None

    return CoPlace, CoFlatPlace


@pytest.fixture
def config_registry():
    registry = SchemaRegistry.get_instance()
    saved = registry.config
    yield registry
    registry.config = saved


async def _find_ids(pool, view: str, where: dict) -> list[int]:
    repo = FraiseQLRepository(pool, context={"mode": "development"})
    return sorted(
        row["id"] for row in extract_graphql_data(await repo.find(view, where=where), view)
    )


@pytest.mark.usefixtures("test_schema", "place_tables")
class TestCoordinateWhereDictFind:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", _METHODS)
    @pytest.mark.parametrize("view", _ROOTS.values())
    @pytest.mark.parametrize(("radius", "expected"), _DISTANCES)
    async def test_distance_within(
        self,
        class_db_pool,
        test_schema,
        place_types,
        config_registry,
        method,
        view,
        radius,
        expected,
    ) -> None:
        config_registry.config = FraiseQLConfig(
            database_url="postgresql://test/test", coordinate_distance_method=method
        )
        where = {"location": {"distance_within": ((37.7749, -122.4194), radius)}}

        assert await _find_ids(class_db_pool, f"{test_schema}.{view}", where) == expected

    @pytest.mark.asyncio
    async def test_distance_within_takes_center_and_radius(
        self, class_db_pool, test_schema, place_types
    ) -> None:
        where = {"location": {"distance_within": {"center": [37.7749, -122.4194], "radius": 2e4}}}

        assert await _find_ids(class_db_pool, f"{test_schema}.v_co_place", where) == [1, 2]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("view", _ROOTS.values())
    @pytest.mark.parametrize(("_gql", "location_filter", "expected"), _POINT_FILTERS)
    async def test_point_filters(
        self, class_db_pool, test_schema, place_types, view, _gql, location_filter, expected
    ) -> None:
        where = {"location": location_filter}

        assert await _find_ids(class_db_pool, f"{test_schema}.{view}", where) == expected

    @pytest.mark.asyncio
    async def test_a_malformed_distance_is_an_error(
        self, class_db_pool, test_schema, place_types
    ) -> None:
        where = {"location": {"distance_within": (37.7749, -122.4194)}}

        with pytest.raises(ValueError, match="coordinate filter 'distance_within' takes"):
            await _find_ids(class_db_pool, f"{test_schema}.v_co_place", where)
