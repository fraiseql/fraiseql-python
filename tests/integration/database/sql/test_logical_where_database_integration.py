"""Database integration tests for logical WHERE operators.

This module tests the complete end-to-end functionality of logical operators
with a real PostgreSQL database, ensuring the generated SQL actually works.
"""

import json
import uuid
from decimal import Decimal
from typing import Optional

import pytest

import fraiseql
from fraiseql.sql import (
    BooleanFilter,
    DecimalFilter,
    IntFilter,
    StringFilter,
    create_graphql_where_input,
)

pytestmark = [pytest.mark.integration, pytest.mark.database]


@fraiseql.type
class Product:
    """Product model for database integration testing."""

    id: uuid.UUID
    name: str
    price: Decimal
    stock: int
    category: str
    is_active: bool
    description: Optional[str] = None


@pytest.mark.database
class TestLogicalOperatorsDatabaseIntegration:
    """Test logical operators with real database queries."""

    @pytest.mark.asyncio
    async def test_or_operator_database_query(self, db_connection) -> None:
        """Test OR operator generates working SQL and returns correct results."""
        # Create test table and data
        conn = db_connection
        await conn.execute(
            """
            CREATE TABLE test_products (
                id UUID PRIMARY KEY,
                data JSONB NOT NULL
            )
        """
        )

        # Insert test data
        test_products = [
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Widget A",
                    "price": 50,
                    "category": "electronics",
                    "is_active": True,
                },
            },
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Widget B",
                    "price": 75,
                    "category": "electronics",
                    "is_active": True,
                },
            },
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Gadget C",
                    "price": 100,
                    "category": "toys",
                    "is_active": True,
                },
            },
        ]

        for product in test_products:
            await conn.execute(
                "INSERT INTO test_products (id, data) VALUES (%s, %s::jsonb)",
                (product["id"], json.dumps(product["data"])),
            )

        # Create GraphQL where input with OR condition
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(
            OR=[
                ProductWhereInput(name=StringFilter(eq="Widget A")),
                ProductWhereInput(name=StringFilter(eq="Widget B")),
            ]
        )

        # Convert to SQL where type and generate SQL
        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        # Execute the query using psycopg's SQL composition
        from psycopg.sql import SQL, Composed

        query = Composed([SQL("SELECT id, data FROM test_products WHERE "), sql])
        cursor = await conn.execute(query)
        results = await cursor.fetchall()

        # Should return both Widget A and Widget B
        assert len(results) == 2

        result_names = [row[1]["name"] for row in results]
        assert "Widget A" in result_names
        assert "Widget B" in result_names
        assert "Gadget C" not in result_names

    @pytest.mark.asyncio
    async def test_and_operator_database_query(self, db_connection) -> None:
        """Test AND operator generates working SQL and returns correct results."""
        # Use existing table from previous test or create new one
        conn = db_connection
        await conn.execute(
            """
            CREATE TABLE test_products_and (
                id UUID PRIMARY KEY,
                data JSONB NOT NULL
            )
        """
        )

        # Insert test data with different categories and active states
        test_products = [
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Active Electronics",
                    "category": "electronics",
                    "is_active": True,
                    "price": 50,
                },
            },
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Inactive Electronics",
                    "category": "electronics",
                    "is_active": False,
                    "price": 60,
                },
            },
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Active Toys",
                    "category": "toys",
                    "is_active": True,
                    "price": 40,
                },
            },
        ]

        for product in test_products:
            await conn.execute(
                "INSERT INTO test_products_and (id, data) VALUES (%s, %s::jsonb)",
                (product["id"], json.dumps(product["data"])),
            )

        # Create GraphQL where input with AND condition
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(
            AND=[
                ProductWhereInput(category=StringFilter(eq="electronics")),
                ProductWhereInput(is_active=BooleanFilter(eq=True)),
            ]
        )

        # Convert to SQL and execute
        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        from psycopg.sql import SQL, Composed

        query = Composed([SQL("SELECT id, data FROM test_products_and WHERE "), sql])
        cursor = await conn.execute(query)
        results = await cursor.fetchall()

        # Should return only "Active Electronics"
        assert len(results) == 1
        assert results[0][1]["name"] == "Active Electronics"

    @pytest.mark.asyncio
    async def test_not_operator_database_query(self, db_connection) -> None:
        """Test NOT operator generates working SQL and returns correct results."""
        conn = db_connection
        await conn.execute(
            """
            CREATE TABLE test_products_not (
                id UUID PRIMARY KEY,
                data JSONB NOT NULL
            )
        """
        )

        # Insert test data
        test_products = [
            {
                "id": str(uuid.uuid4()),
                "data": {"name": "Active Product", "is_active": True, "price": 50},
            },
            {
                "id": str(uuid.uuid4()),
                "data": {"name": "Inactive Product 1", "is_active": False, "price": 60},
            },
            {
                "id": str(uuid.uuid4()),
                "data": {"name": "Inactive Product 2", "is_active": False, "price": 70},
            },
        ]

        for product in test_products:
            await conn.execute(
                "INSERT INTO test_products_not (id, data) VALUES (%s, %s::jsonb)",
                (product["id"], json.dumps(product["data"])),
            )

        # Create GraphQL where input with NOT condition
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(NOT=ProductWhereInput(is_active=BooleanFilter(eq=False)))

        # Convert to SQL and execute
        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        from psycopg.sql import SQL, Composed

        query = Composed([SQL("SELECT id, data FROM test_products_not WHERE "), sql])
        cursor = await conn.execute(query)
        results = await cursor.fetchall()

        # Should return only the active product
        assert len(results) == 1
        assert results[0][1]["name"] == "Active Product"

    @pytest.mark.asyncio
    async def test_complex_nested_logical_operators_database_query(self, db_connection) -> None:
        """Test complex nested logical operators with database."""
        conn = db_connection
        await conn.execute(
            """
            CREATE TABLE test_products_complex (
                id UUID PRIMARY KEY,
                data JSONB NOT NULL
            )
        """
        )

        # Insert comprehensive test data
        test_products = [
            # Should match: electronics AND (cheap OR high_stock) AND NOT inactive
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Cheap Electronics",
                    "category": "electronics",
                    "price": 25,
                    "stock": 10,
                    "is_active": True,
                },
            },
            # Should match: electronics AND (cheap OR high_stock) AND NOT inactive
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Expensive Electronics High Stock",
                    "category": "electronics",
                    "price": 150,
                    "stock": 200,
                    "is_active": True,
                },
            },
            # Should NOT match: not electronics
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Cheap Toys",
                    "category": "toys",
                    "price": 25,
                    "stock": 10,
                    "is_active": True,
                },
            },
            # Should NOT match: electronics but expensive AND low stock
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Expensive Electronics Low Stock",
                    "category": "electronics",
                    "price": 150,
                    "stock": 5,
                    "is_active": True,
                },
            },
            # Should NOT match: inactive
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Cheap Inactive Electronics",
                    "category": "electronics",
                    "price": 25,
                    "stock": 10,
                    "is_active": False,
                },
            },
        ]

        for product in test_products:
            await conn.execute(
                "INSERT INTO test_products_complex (id, data) VALUES (%s, %s::jsonb)",
                (product["id"], json.dumps(product["data"])),
            )

        # Create complex nested logical condition:
        # category = "electronics" AND (price < 50 OR stock > 100) AND NOT (is_active = false)
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(
            AND=[
                ProductWhereInput(category=StringFilter(eq="electronics")),
                ProductWhereInput(
                    OR=[
                        ProductWhereInput(price=DecimalFilter(lt=Decimal(50))),
                        ProductWhereInput(stock=IntFilter(gt=100)),
                    ]
                ),
                ProductWhereInput(NOT=ProductWhereInput(is_active=BooleanFilter(eq=False))),
            ]
        )

        # Convert to SQL and execute
        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        from psycopg.sql import SQL, Composed

        query = Composed([SQL("SELECT id, data FROM test_products_complex WHERE "), sql])
        cursor = await conn.execute(query)
        results = await cursor.fetchall()

        # Should return exactly 2 products
        assert len(results) == 2

        result_names = [row[1]["name"] for row in results]
        assert "Cheap Electronics" in result_names
        assert "Expensive Electronics High Stock" in result_names

        # Verify excluded products are not included
        assert "Cheap Toys" not in result_names
        assert "Expensive Electronics Low Stock" not in result_names
        assert "Cheap Inactive Electronics" not in result_names

    @pytest.mark.asyncio
    async def test_mixed_field_and_logical_operators_database_query(self, db_connection) -> None:
        """Test mixing direct field operators with logical operators."""
        conn = db_connection
        await conn.execute(
            """
            CREATE TABLE test_products_mixed (
                id UUID PRIMARY KEY,
                data JSONB NOT NULL
            )
        """
        )

        # Insert test data
        test_products = [
            # Should match: electronics AND is_active=true AND
            # (name contains "pro" OR price < 60)
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Pro Widget",
                    "category": "electronics",
                    "price": 100,
                    "is_active": True,
                },
            },
            # Should match: electronics AND is_active=true AND
            # (name contains "pro" OR price < 60)
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Cheap Electronics",
                    "category": "electronics",
                    "price": 50,
                    "is_active": True,
                },
            },
            # Should NOT match: not electronics
            {
                "id": str(uuid.uuid4()),
                "data": {"name": "Pro Toy", "category": "toys", "price": 40, "is_active": True},
            },
            # Should NOT match: not active
            {
                "id": str(uuid.uuid4()),
                "data": {
                    "name": "Pro Electronics Inactive",
                    "category": "electronics",
                    "price": 80,
                    "is_active": False,
                },
            },
        ]

        for product in test_products:
            await conn.execute(
                "INSERT INTO test_products_mixed (id, data) VALUES (%s, %s::jsonb)",
                (product["id"], json.dumps(product["data"])),
            )

        # Mix field operators with logical operators
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(
            # Direct field operators
            category=StringFilter(eq="electronics"),
            is_active=BooleanFilter(eq=True),
            # Logical operator
            OR=[
                ProductWhereInput(name=StringFilter(contains="Pro")),
                ProductWhereInput(price=DecimalFilter(lt=Decimal(60))),
            ],
        )

        # Convert to SQL and execute
        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        from psycopg.sql import SQL, Composed

        query = Composed([SQL("SELECT id, data FROM test_products_mixed WHERE "), sql])
        cursor = await conn.execute(query)
        results = await cursor.fetchall()

        # Should return 2 products that match all conditions
        assert len(results) == 2

        result_names = [row[1]["name"] for row in results]
        assert "Pro Widget" in result_names
        assert "Cheap Electronics" in result_names
