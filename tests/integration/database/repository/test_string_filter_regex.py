"""Test regex operators in StringFilter.

This test suite ensures that regex matching operators work correctly
in FraiseQL WHERE filtering.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

pytestmark = pytest.mark.database

# Import database fixtures for this database test
import psycopg_pool
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.db import register_type_for_view
from fraiseql.sql.where_generator import safe_create_where_type


class TestStringFilterRegex:
    """Test suite for regex operators in StringFilter."""

    @pytest.fixture(scope="class")
    def test_types(self, clear_registry_class):
        """Create test types inside a fixture for proper isolation."""

        @fraiseql.type
        class Product:
            id: str
            name: str
            description: str

        ProductWhere = safe_create_where_type(Product)

        return {
            "Product": Product,
            "ProductWhere": ProductWhere,
        }

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_test_views(
        self, class_db_pool: psycopg_pool.AsyncConnectionPool, test_schema, test_types
    ) -> AsyncGenerator[None]:
        """Create test views with proper structure."""
        Product = test_types["Product"]
        # Register types for views (for development mode)
        register_type_for_view("test_product_view", Product)

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            # Create tables
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_products (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL
                )
            """
            )

            # Create views with JSONB data column
            await conn.execute(
                """
                CREATE OR REPLACE VIEW test_product_view AS
                SELECT
                    id, name, description,
                    jsonb_build_object(
                        'id', id,
                        'name', name,
                        'description', description
                    ) as data
                FROM test_products
            """
            )

            # Insert test data with regex-friendly patterns
            await conn.execute(
                """
                INSERT INTO test_products (id, name, description)
                VALUES
                    ('prod-001', 'Widget Alpha', 'A high-quality widget for testing'),
                    ('prod-002', 'Widget Beta', 'Another widget with different features'),
                    ('prod-003', 'Gadget Gamma', 'A gadget that starts with G'),
                    ('prod-004', 'Tool Delta', 'Tool for development work'),
                    ('prod-005', 'Widget123', 'Widget with numbers in name')
            """
            )

        yield
