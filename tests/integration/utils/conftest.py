"""Fixtures for utility integration tests (introspection, response utils, case conversion)."""

import pytest

from fraiseql import fraise_type, query
from fraiseql.config.schema_config import SchemaConfig


@pytest.fixture
def introspection_schema(meta_test_schema):
    """Schema configured for introspection testing."""
    meta_test_schema.clear()

    @fraise_type(sql_source="test_types")
    class TestType:
        id: int
        name: str
        description: str | None

    @query
    async def get_test_types(info) -> list[TestType]:
        return []

    meta_test_schema.register_type(TestType)
    meta_test_schema.register_query(get_test_types)

    return meta_test_schema


@pytest.fixture
def response_schema(meta_test_schema):
    """Schema for testing response formatting utilities."""
    meta_test_schema.clear()

    @fraise_type(sql_source="items")
    class Item:
        id: int
        data: dict | None  # JSONScalar
        tags: list[str] | None

    @query
    async def get_items(info) -> list[Item]:
        return []

    meta_test_schema.register_type(Item)
    meta_test_schema.register_query(get_items)

    return meta_test_schema


@pytest.fixture
def case_config():
    """Case conversion configuration for testing."""
    return {
        "input_case": "snake_case",  # Database column naming
        "output_case": "camelCase",  # GraphQL field naming
        "convert": True,
    }


@pytest.fixture
def case_conversion_schema(meta_test_schema, case_config):
    """Schema with case conversion enabled."""

    meta_test_schema.clear()

    # Configure case conversion globally
    SchemaConfig.set_config(camel_case_fields=case_config["convert"])

    @fraise_type(sql_source="snake_case_table")
    class CaseTestType:
        user_id: int  # Should become userId in GraphQL if camel_case_fields=True
        first_name: str  # Should become firstName
        last_name: str  # Should become lastName

    @query
    async def get_case_test_items(info) -> list[CaseTestType]:
        return []

    meta_test_schema.register_type(CaseTestType)
    meta_test_schema.register_query(get_case_test_items)

    return meta_test_schema
