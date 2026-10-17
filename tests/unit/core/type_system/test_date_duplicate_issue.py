"""Test to reproduce the Date duplicate registration issue."""

import datetime as dt

import pytest
from graphql import GraphQLError

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.gql.schema_builder import SchemaRegistry


@pytest.mark.unit
def test_date_scalar_in_fastapi_app() -> None:
    """Test Date scalar registration through FastAPI app creation."""
    # Clear registry
    registry = SchemaRegistry.get_instance()
    registry.clear()

    @fraiseql.type
    class Event:
        name: str
        event_date: dt.date

    @fraiseql.query
    async def get_event(info) -> Event:
        return Event(name="Test", event_date=dt.date.today())

    # This might trigger duplicate registration if there's an issue
    try:
        app = create_fraiseql_app(
            database_url="postgresql://test/test", types=[Event], queries=[get_event]
        )
        # If we get here, no duplicate registration occurred
        assert app is not None
    except GraphQLError as e:
        if "multiple types named" in str(e):
            pytest.fail(f"Duplicate Date type registration: {e}")
        else:
            raise


def test_date_scalar_multiple_registrations() -> None:
    """Test that Date scalar can be used across multiple schema builds."""
    # First schema build
    registry = SchemaRegistry.get_instance()
    registry.clear()

    @fraiseql.type
    class Model1:
        date1: dt.date

    @fraiseql.query
    async def get_model1(info) -> Model1:
        return (Model1(date1=dt.date.today()),)

    schema1 = registry.build_schema()
    assert "Date" in schema1.type_map

    # Clear and build another schema
    registry.clear()

    @fraiseql.type
    class Model2:
        date2: dt.date

    @fraiseql.query
    async def get_model2(info) -> Model2:
        return Model2(date2=dt.date.today())

    # This should not fail with duplicate Date
    schema2 = registry.build_schema()
    assert "Date" in schema2.type_map


def test_date_scalar_with_interface() -> None:
    """Test Date scalar with interface types."""
    registry = SchemaRegistry.get_instance()
    registry.clear()

    @fraiseql.interface
    class Timestamped:
        created_date: dt.date

    @fraiseql.type(implements=[Timestamped])
    class Article:
        title: str
        created_date: dt.date
        published_date: dt.date

    @fraiseql.query
    async def get_article(info) -> Article:
        today = dt.date.today()
        return Article(title="Test", created_date=today, published_date=today)

    # Should not raise duplicate Date type error
    schema = registry.build_schema()
    assert "Date" in schema.type_map
    assert "Timestamped" in schema.type_map
    assert "Article" in schema.type_map
