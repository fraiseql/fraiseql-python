"""Regression test for issue #317: is_type_of rejects plain dicts from resolvers.

When a resolver returns plain dicts (e.g., from db.run()), graphql-core's
is_type_of check rejected them because dict.__class__.__name__ != 'MyType'.

Fix: Accept dicts in is_type_of — graphql-core still validates individual
fields against the schema, so this is safe.
"""

import pytest
from graphql import graphql

from fraiseql import fraise_type, query
from fraiseql.gql.schema_builder import build_fraiseql_schema

pytestmark = pytest.mark.regression


@pytest.mark.asyncio
class TestDictIsTypeOf:
    """Test that resolvers returning plain dicts are accepted by is_type_of."""

    async def test_resolver_returning_list_of_dicts(self, clear_registry) -> None:
        """A resolver returning list[dict] typed as list[MyType] should resolve."""

        @fraise_type(sql_source="sales_summary")
        class SalesSummary:
            category: str
            total_amount: float
            order_count: int

        @query
        async def get_sales_summary(info) -> list[SalesSummary]:
            # Simulates db.run() returning plain dicts
            return [
                {"category": "Electronics", "total_amount": 15000.0, "order_count": 42},
                {"category": "Books", "total_amount": 3200.0, "order_count": 128},
            ]

        schema = build_fraiseql_schema(
            query_types=[get_sales_summary],
            mutation_resolvers=[],
            camel_case_fields=True,
        )

        result = await graphql(
            schema,
            """
            query {
                getSalesSummary {
                    category
                    totalAmount
                    orderCount
                }
            }
            """,
        )

        assert result.errors is None, f"Unexpected errors: {result.errors}"
        assert result.data is not None
        data = result.data["getSalesSummary"]
        assert len(data) == 2
        assert data[0]["category"] == "Electronics"
        assert data[0]["totalAmount"] == 15000.0
        assert data[0]["orderCount"] == 42
        assert data[1]["category"] == "Books"

    async def test_resolver_returning_single_dict(self, clear_registry) -> None:
        """A resolver returning a single dict typed as MyType should resolve."""

        @fraise_type(sql_source="users")
        class UserInfo:
            id: int
            name: str
            email: str

        @query
        async def get_user(info) -> UserInfo:
            return {"id": 1, "name": "Alice", "email": "alice@example.com"}

        schema = build_fraiseql_schema(
            query_types=[get_user],
            mutation_resolvers=[],
            camel_case_fields=True,
        )

        result = await graphql(
            schema,
            """
            query {
                getUser {
                    id
                    name
                    email
                }
            }
            """,
        )

        assert result.errors is None, f"Unexpected errors: {result.errors}"
        assert result.data is not None
        user = result.data["getUser"]
        assert user["id"] == 1
        assert user["name"] == "Alice"
        assert user["email"] == "alice@example.com"

    async def test_typed_instances_still_work(self, clear_registry) -> None:
        """Existing behavior: resolvers returning typed instances still work."""

        @fraise_type(sql_source="products")
        class Product:
            id: int
            name: str

        @query
        async def get_products(info) -> list[Product]:
            return [
                Product(id=1, name="Widget"),
                Product(id=2, name="Gadget"),
            ]

        schema = build_fraiseql_schema(
            query_types=[get_products],
            mutation_resolvers=[],
            camel_case_fields=True,
        )

        result = await graphql(
            schema,
            """
            query {
                getProducts { id name }
            }
            """,
        )

        assert result.errors is None, f"Unexpected errors: {result.errors}"
        assert result.data is not None
        assert len(result.data["getProducts"]) == 2
        assert result.data["getProducts"][0]["name"] == "Widget"
