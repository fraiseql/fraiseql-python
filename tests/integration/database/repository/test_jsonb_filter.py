"""Tests for PostgreSQL JSONB filtering capabilities."""

from typing import AsyncGenerator

import psycopg_pool
import pytest
import pytest_asyncio

pytestmark = pytest.mark.database

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.db import register_type_for_view
from fraiseql.sql.where_generator import safe_create_where_type


class TestJSONBKeyExistence:
    """Test PostgreSQL JSONB key existence operators."""

    @pytest.fixture(scope="class")
    def test_types(self, clear_registry_class):
        """Create test types inside a fixture for proper isolation."""

        @fraiseql.type
        class Product:
            id: str
            name: str
            attributes: dict  # JSONB column

        ProductWhere = safe_create_where_type(Product)

        return {
            "Product": Product,
            "ProductWhere": ProductWhere,
        }

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_test_products(
        self, class_db_pool: psycopg_pool.AsyncConnectionPool, test_schema, test_types
    ) -> AsyncGenerator[None]:
        """Create test products with JSONB attributes."""
        # Register types for views (for development mode)
        Product = test_types["Product"]
        register_type_for_view("test_products_view", Product)

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            # Create tables
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_products (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    attributes JSONB NOT NULL
                )
            """
            )

            # Create views with JSONB data column
            await conn.execute(
                """
                CREATE OR REPLACE VIEW test_products_view AS
                SELECT
                    id, name, attributes,
                    jsonb_build_object(
                        'id', id,
                        'name', name,
                        'attributes', attributes
                    ) as data
                FROM test_products
            """
            )

            # Insert test data with JSONB attributes
            await conn.execute(
                """
                INSERT INTO test_products (id, name, attributes)
                VALUES
                    ('prod-001', 'Laptop', '{"brand": "Dell", "ram": "16GB", "ssd": "512GB"}'),
                    ('prod-002', 'Phone', '{"brand": "Apple", "storage": "128GB", "color": "black"}'),
                    ('prod-003', 'Tablet', '{"brand": "Samsung", "storage": "64GB"}')
            """
            )

        yield
