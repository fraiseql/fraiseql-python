import pytest

"""Test that scalar types are properly cached to prevent duplicate registrations."""

import datetime as dt

import fraiseql
from fraiseql.core.graphql_type import _graphql_type_cache, convert_type_to_graphql_output
from fraiseql.gql.schema_builder import SchemaRegistry, build_fraiseql_schema


@pytest.mark.unit
def test_scalar_caching_prevents_duplicates() -> None:
    """Test that scalar types are cached to prevent duplicate registrations."""
    # Clear cache to start fresh
    _graphql_type_cache.clear()

    # Convert the same scalar type multiple times
    date_gql1 = convert_type_to_graphql_output(dt.date)
    date_gql2 = convert_type_to_graphql_output(dt.date)
    date_gql3 = convert_type_to_graphql_output(dt.date)

    # All should be the exact same instance due to caching
    assert date_gql1 is date_gql2
    assert date_gql2 is date_gql3
    assert date_gql1.name == "Date"

    # Verify cache contains the scalar
    cache_keys = list(_graphql_type_cache.keys())
    assert ("scalar_date", "datetime") in cache_keys

    # Verify cached instance is the same as returned instances
    cached_scalar = _graphql_type_cache[("scalar_date", "datetime")]
    assert cached_scalar is date_gql1


def test_different_scalars_cached_separately() -> None:
    """Test that different scalar types are cached separately."""
    _graphql_type_cache.clear()

    # Convert different scalar types
    date_gql = convert_type_to_graphql_output(dt.date)
    datetime_gql = convert_type_to_graphql_output(dt.datetime)
    int_gql = convert_type_to_graphql_output(int)

    # Should have separate cache entries
    cache_keys = list(_graphql_type_cache.keys())
    assert ("scalar_date", "datetime") in cache_keys
    assert ("scalar_datetime", "datetime") in cache_keys
    assert ("scalar_int", "builtins") in cache_keys

    # Each should be different instances
    assert date_gql is not datetime_gql
    assert date_gql is not int_gql
    assert datetime_gql is not int_gql


def test_complex_scenario_with_caching() -> None:
    """Test a complex scenario that would previously cause duplicate registrations."""
    _graphql_type_cache.clear()
    registry = SchemaRegistry.get_instance()
    registry.clear()

    # Create multiple types that all use Date scalar
    @fraiseql.type
    class User:
        name: str
        birth_date: dt.date
        registration_date: dt.date

    @fraiseql.type
    class Event:
        title: str
        start_date: dt.date
        end_date: dt.date
        created_date: dt.date

    @fraiseql.type
    class Order:
        id: int
        order_date: dt.date
        delivery_date: dt.date | None

    # Input types with dates
    @fraiseql.input
    class CreateEventInput:
        title: str
        start_date: dt.date
        end_date: dt.date

    # Queries and mutations
    @fraiseql.query
    async def get_users(info) -> list[User]:
        today = dt.date.today()
        return [User(name="Test", birth_date=today, registration_date=today)]

    @fraiseql.query
    async def get_events(info) -> list[Event]:
        today = dt.date.today()
        return [Event(title="Test", start_date=today, end_date=today, created_date=today)]

    @fraiseql.mutation
    async def create_event(info, input: CreateEventInput) -> Event:
        return Event(
            title=input.title,
            start_date=input.start_date,
            end_date=input.end_date,
            created_date=dt.date.today(),
        )

    # Build schema - this should not fail with duplicate Date registrations
    schema = build_fraiseql_schema(
        query_types=[User, Event, Order, get_users, get_events], mutation_resolvers=[create_event]
    )

    # Verify Date scalar is present and unique
    assert "Date" in schema.type_map
    date_type = schema.type_map["Date"]
    assert date_type.name == "Date"

    # Count Date scalars (should be exactly 1)
    date_count = sum(1 for name in schema.type_map if name == "Date")
    assert date_count == 1, f"Found {date_count} Date scalars, expected exactly 1"

    # Verify all date fields reference the same scalar instance
    user_type = schema.type_map["User"]
    event_type = schema.type_map["Event"]
    order_type = schema.type_map["Order"]

    # Extract Date types from various fields
    birth_date_type = user_type.fields["birthDate"].type
    start_date_type = event_type.fields["startDate"].type
    order_date_type = order_type.fields["orderDate"].type

    # Unwrap NonNull if necessary
    if hasattr(birth_date_type, "of_type"):
        birth_date_type = birth_date_type.of_type
    if hasattr(start_date_type, "of_type"):
        start_date_type = start_date_type.of_type
    if hasattr(order_date_type, "of_type"):
        order_date_type = order_date_type.of_type

    # All should reference the same Date scalar instance
    assert birth_date_type is start_date_type
    assert start_date_type is order_date_type
    assert birth_date_type is date_type


def test_cache_behavior_across_schema_builds() -> None:
    """Test caching behavior when building multiple schemas."""
    _graphql_type_cache.clear()

    # First schema
    @fraiseql.type
    class Model1:
        date_field: dt.date

    @fraiseql.query
    async def query1(info) -> Model1:
        return (Model1(date_field=dt.date.today()),)

    schema1 = build_fraiseql_schema(query_types=[Model1, query1])
    date_type1 = schema1.type_map["Date"]

    # Cache should contain Date scalar
    assert ("scalar_date", "datetime") in _graphql_type_cache
    cached_scalar = _graphql_type_cache[("scalar_date", "datetime")]
    assert cached_scalar is date_type1

    # Second schema (cache is cleared by build_fraiseql_schema)
    @fraiseql.type
    class Model2:
        another_date: dt.date

    @fraiseql.query
    async def query2(info) -> Model2:
        return (Model2(another_date=dt.date.today()),)

    schema2 = build_fraiseql_schema(query_types=[Model2, query2])
    date_type2 = schema2.type_map["Date"]

    # Both schemas should have Date scalar
    assert date_type1.name == "Date"
    assert date_type2.name == "Date"

    # No duplicate registration error should occur
    assert "Date" in schema1.type_map
    assert "Date" in schema2.type_map
