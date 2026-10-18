"""Test that auto-generated types work in GraphQL schema."""

from dataclasses import dataclass
from uuid import UUID

import pytest

import fraiseql
from fraiseql.types.lazy_properties import clear_auto_generated_cache

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clear_registry")]


@pytest.mark.integration
def test_auto_generated_types_in_schema() -> None:
    """Test that auto-generated WhereInput types appear in GraphQL schema."""
    clear_auto_generated_cache()

    @fraiseql.type(sql_source="v_product_schema_test")
    @dataclass
    class ProductSchemaTest:
        id: UUID
        name: str
        price: float

    @fraiseql.query
    async def products_schema_test(
        where: ProductSchemaTest.WhereInput | None = None,
        order_by: ProductSchemaTest.OrderBy | None = None,
    ) -> list[ProductSchemaTest]:
        """Query products with auto-generated filters."""
        # Dummy implementation for schema test
        return []

    # Build schema
    schema = fraiseql.build_fraiseql_schema()

    # Check that ProductSchemaTestWhereInput exists in schema
    assert "ProductSchemaTestWhereInput" in schema.type_map
    product_where = schema.type_map["ProductSchemaTestWhereInput"]

    # Check fields exist
    assert "name" in product_where.fields
    assert "price" in product_where.fields
    assert "id" in product_where.fields

    # Check logical operators exist
    assert "OR" in product_where.fields
    assert "AND" in product_where.fields
    assert "NOT" in product_where.fields

    # Check that ProductSchemaTestOrderByInput exists in schema
    assert "ProductSchemaTestOrderByInput" in schema.type_map
    product_order = schema.type_map["ProductSchemaTestOrderByInput"]

    # OrderBy should have fields for sorting
    assert "name" in product_order.fields
    assert "price" in product_order.fields
    assert "id" in product_order.fields


@pytest.mark.integration
def test_auto_generated_nested_types_in_schema() -> None:
    """Test that nested auto-generated types work in GraphQL schema."""
    clear_auto_generated_cache()

    @fraiseql.type(sql_source="v_category_schema_test")
    @dataclass
    class CategorySchemaTest:
        id: UUID
        name: str

    @fraiseql.type(sql_source="v_item_schema_test")
    @dataclass
    class ItemSchemaTest:
        id: UUID
        name: str
        category_id: UUID
        category: CategorySchemaTest | None

    @fraiseql.query
    async def items_schema_test(
        where: ItemSchemaTest.WhereInput | None = None,
    ) -> list[ItemSchemaTest]:
        """Query items with nested category filter."""
        return []

    # Build schema
    schema = fraiseql.build_fraiseql_schema()

    # Check ItemWhereInput exists
    assert "ItemSchemaTestWhereInput" in schema.type_map
    item_where = schema.type_map["ItemSchemaTestWhereInput"]

    # Check that category field exists (nested filter)
    assert "category" in item_where.fields

    # Check CategoryWhereInput was also generated
    assert "CategorySchemaTestWhereInput" in schema.type_map
    category_where = schema.type_map["CategorySchemaTestWhereInput"]
    assert "name" in category_where.fields


@pytest.mark.integration
def test_auto_generated_types_with_multiple_queries() -> None:
    """Test that auto-generated types work with multiple queries using same type."""
    clear_auto_generated_cache()

    @fraiseql.type(sql_source="v_user_schema_test")
    @dataclass
    class UserSchemaTest:
        id: UUID
        username: str
        email: str

    @fraiseql.query
    async def users_all(
        where: UserSchemaTest.WhereInput | None = None,
    ) -> list[UserSchemaTest]:
        """Get all users."""
        return []

    @fraiseql.query
    async def users_active(
        where: UserSchemaTest.WhereInput | None = None,
    ) -> list[UserSchemaTest]:
        """Get active users."""
        return []

    # Build schema
    schema = fraiseql.build_fraiseql_schema()

    # WhereInput should be in schema only once
    assert "UserSchemaTestWhereInput" in schema.type_map

    # Both queries should use the same WhereInput type
    query_type = schema.type_map["Query"]
    assert "usersAll" in query_type.fields or "users_all" in query_type.fields
    assert "usersActive" in query_type.fields or "users_active" in query_type.fields


@pytest.mark.integration
def test_auto_generated_types_introspection() -> None:
    """Test that auto-generated types can be introspected via GraphQL."""
    clear_auto_generated_cache()

    @fraiseql.type(sql_source="v_book_schema_test")
    @dataclass
    class BookSchemaTest:
        id: UUID
        title: str
        author: str
        year: int

    @fraiseql.query
    async def books(
        where: BookSchemaTest.WhereInput | None = None,
    ) -> list[BookSchemaTest]:
        """Query books."""
        return []

    # Build schema
    schema = fraiseql.build_fraiseql_schema()

    # Run introspection query
    introspection_query = """
        query IntrospectionQuery {
            __schema {
                types {
                    name
                    kind
                    fields {
                        name
                        type {
                            name
                            kind
                        }
                    }
                }
            }
        }
    """

    from graphql import graphql_sync

    result = graphql_sync(schema, introspection_query)

    # Should not have errors
    assert result.errors is None or len(result.errors) == 0

    # Check that our auto-generated type appears in introspection
    type_names = [t["name"] for t in result.data["__schema"]["types"]]
    assert "BookSchemaTestWhereInput" in type_names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auto_generated_types_with_actual_query_execution() -> None:
    """Test that auto-generated WhereInput can be used as parameter in query signature.

    Note: This is a schema test. The actual query execution with database operations
    is tested in test_auto_generation_integration.py.
    """
    clear_auto_generated_cache()

    @fraiseql.type(sql_source="v_article_schema_test")
    @dataclass
    class ArticleSchemaTest:
        id: UUID
        title: str
        content: str

    # Verify WhereInput was auto-generated
    assert hasattr(ArticleSchemaTest, "WhereInput")
    WhereInput = ArticleSchemaTest.WhereInput
    assert WhereInput is not None

    # Verify the WhereInput has expected fields
    assert "title" in WhereInput.__annotations__
    assert "id" in WhereInput.__annotations__
    assert "content" in WhereInput.__annotations__

    # Verify it can be instantiated
    where_instance = WhereInput(title={"eq": "Test"})
    assert where_instance.title == {"eq": "Test"}
