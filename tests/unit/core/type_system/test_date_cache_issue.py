import pytest

"""Test potential Date scalar caching issues."""

import datetime as dt

import fraiseql
from fraiseql.core.graphql_type import _graphql_type_cache, convert_type_to_graphql_output
from fraiseql.gql.schema_builder import SchemaRegistry, build_fraiseql_schema


@pytest.mark.unit
def test_date_scalar_cache_behavior() -> None:
    """Test how Date scalar interacts with type cache."""
    # Clear everything
    _graphql_type_cache.clear()
    registry = SchemaRegistry.get_instance()
    registry.clear()

    # Convert date type multiple times
    date_gql1 = convert_type_to_graphql_output(dt.date)
    date_gql2 = convert_type_to_graphql_output(dt.date)

    # They should be the same instance
    assert date_gql1 is date_gql2
    assert date_gql1.name == "Date"

    # Check if it's in the cache
    # Scalars might not be cached by type/module like classes


def test_date_scalar_with_schema_builder() -> None:
    """Test Date scalar when using build_fraiseql_schema."""

    @fraiseql.type
    class Event:
        name: str
        start_date: dt.date
        end_date: dt.date

    @fraiseql.query
    async def get_event(info) -> Event:
        today = dt.date.today()
        return Event(name="Conference", start_date=today, end_date=today)

    # Build schema using the helper function
    schema = build_fraiseql_schema(query_types=[Event, get_event], camel_case_fields=True)

    # Check that Date scalar is present and unique
    assert "Date" in schema.type_map
    date_type = schema.type_map["Date"]
    assert date_type.name == "Date"

    # Verify fields use the same Date instance
    event_type = schema.type_map["Event"]
    start_date_type = event_type.fields["startDate"].type
    end_date_type = event_type.fields["endDate"].type

    # Unwrap NonNull if needed
    if hasattr(start_date_type, "of_type"):
        start_date_type = start_date_type.of_type
    if hasattr(end_date_type, "of_type"):
        end_date_type = end_date_type.of_type

    assert start_date_type is end_date_type
    assert start_date_type is date_type


def test_multiple_schema_builds_with_date() -> None:
    """Test building multiple schemas with Date scalar."""

    # First schema
    @fraiseql.type
    class Model1:
        date1: dt.date

    @fraiseql.query
    async def query1(info) -> Model1:
        return (Model1(date1=dt.date.today()),)

    schema1 = build_fraiseql_schema(query_types=[Model1, query1])
    assert "Date" in schema1.type_map

    # Second schema - this might trigger duplicate if there's an issue
    @fraiseql.type
    class Model2:
        date2: dt.date

    @fraiseql.query
    async def query2(info) -> Model2:
        return (Model2(date2=dt.date.today()),)

    schema2 = build_fraiseql_schema(query_types=[Model2, query2])
    assert "Date" in schema2.type_map
