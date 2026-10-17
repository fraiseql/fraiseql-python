"""Test filtering on hybrid tables with both regular SQL columns and JSONB data.

This test ensures that FraiseQL correctly handles tables that have:
1. Regular SQL columns used for filtering (id, status, is_active, etc.)
2. JSONB data column used for flexible field access

This is a critical bug fix for v0.7.23 where filtering was completely broken
for hybrid table architectures.
"""

import json
from datetime import date, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.database

from tests.fixtures.database.database_conftest import *  # noqa: F403
from tests.unit.utils.test_response_utils import extract_graphql_data

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.sql.where_generator import safe_create_where_type


@fraiseql.type
class Product:
    """Generic product type for testing hybrid tables."""

    id: str
    name: str
    status: str
    is_active: bool = True
    is_featured: bool = False
    is_available: bool = False
    category_id: str | None = None
    created_date: date | None = None
    # Fields from JSONB data
    brand: str | None = None
    color: str | None = None
    specifications: dict | None = None


# Generate WhereInput type for JSONB filtering
ProductWhere = safe_create_where_type(Product)


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def setup_hybrid_table(class_db_pool, test_schema) -> dict[str, int]:
    """Create a hybrid table with both regular SQL columns and JSONB data column."""
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        # Create hybrid table matching a common pattern
        await conn.execute(
            """
                CREATE TABLE IF NOT EXISTS products (
                    -- Regular SQL columns (used for filtering)
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID DEFAULT '11111111-1111-1111-1111-111111111111'::uuid,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    is_active BOOLEAN NOT NULL DEFAULT true,
                    is_featured BOOLEAN NOT NULL DEFAULT false,
                    is_available BOOLEAN NOT NULL DEFAULT false,
                    category_id UUID,
                    created_date DATE,

                    -- JSONB column (contains flexible data)
                    data JSONB
                )
            """
        )

        # Clear existing data
        await conn.execute("DELETE FROM products")

        # Insert test data
        today = date.today()
        yesterday = today - timedelta(days=1)

        products = [
            # Active, featured products
            {
                "id": str(uuid4()),
                "name": "Premium Widget",
                "status": "published",
                "is_active": True,
                "is_featured": True,
                "is_available": True,
                "category_id": str(uuid4()),
                "created_date": today,
                "brand": "TechCorp",
                "color": "blue",
                "specifications": {"weight": "1.2kg", "material": "aluminum"},
            },
            {
                "id": str(uuid4()),
                "name": "Standard Widget",
                "status": "published",
                "is_active": True,
                "is_featured": False,
                "is_available": True,
                "category_id": str(uuid4()),
                "created_date": today,
                "brand": "TechCorp",
                "color": "red",
                "specifications": {"weight": "0.8kg", "material": "plastic"},
            },
            # Draft product
            {
                "id": str(uuid4()),
                "name": "Beta Widget",
                "status": "draft",
                "is_active": False,
                "is_featured": False,
                "is_available": False,
                "category_id": str(uuid4()),
                "created_date": yesterday,
                "brand": "StartupCorp",
                "color": "green",
                "specifications": {"weight": "0.5kg", "material": "carbon fiber"},
            },
            # Inactive product
            {
                "id": str(uuid4()),
                "name": "Legacy Widget",
                "status": "archived",
                "is_active": False,
                "is_featured": False,
                "is_available": False,
                "category_id": str(uuid4()),
                "created_date": yesterday,
                "brand": "OldCorp",
                "color": "gray",
                "specifications": {"weight": "2.0kg", "material": "steel"},
            },
        ]

        async with conn.cursor() as cursor:
            for product in products:
                # Build JSONB data from product fields
                data = {
                    "id": product["id"],
                    "name": product["name"],
                    "status": product["status"],
                    "is_active": product["is_active"],
                    "is_featured": product["is_featured"],
                    "is_available": product["is_available"],
                    "category_id": product["category_id"],
                    "created_date": (
                        product["created_date"].isoformat() if product["created_date"] else None
                    ),
                    "brand": product["brand"],
                    "color": product["color"],
                    "specifications": product["specifications"],
                }

                import json

                await cursor.execute(
                    """
                        INSERT INTO products
                        (id, name, status, is_active, is_featured, is_available,
                         category_id, created_date, data)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                    (
                        product["id"],
                        product["name"],
                        product["status"],
                        product["is_active"],
                        product["is_featured"],
                        product["is_available"],
                        product["category_id"],
                        product["created_date"],
                        json.dumps(data),
                    ),
                )
        await conn.commit()

        # Return counts for validation
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT COUNT(*) FROM products WHERE is_active = true")
            active_count = (await cursor.fetchone())[0]

            await cursor.execute("SELECT COUNT(*) FROM products WHERE is_featured = true")
            featured_count = (await cursor.fetchone())[0]

            await cursor.execute("SELECT COUNT(*) FROM products WHERE status = 'published'")
            published_count = (await cursor.fetchone())[0]

            return {
                "total": len(products),
                "active": active_count,
                "featured": featured_count,
                "published": published_count,
            }


class TestHybridTableFiltering:
    """Test that filtering works correctly on hybrid tables with both SQL columns and JSONB data."""

    @pytest.mark.asyncio
    async def test_filter_by_regular_sql_column_is_active(
        self, class_db_pool, test_schema, setup_hybrid_table
    ) -> None:
        """Test filtering by regular SQL column 'is_active' on hybrid table.

        This is the CRITICAL BUG: FraiseQL treats all fields as JSONB paths
        even when they are regular SQL columns, causing filters to fail.
        """
        counts = setup_hybrid_table  # Already executed as fixture

        # Register with metadata for optimal performance (no runtime introspection)
        register_type_for_view(
            "products",
            Product,
            table_columns={
                "id",
                "tenant_id",
                "name",
                "status",
                "is_active",
                "is_featured",
                "is_available",
                "category_id",
                "created_date",
                "data",
            },
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        # Use dictionary filter for is_active column
        where = {"is_active": {"eq": True}}

        # This SHOULD work but was broken in the original bug
        result = await repo.find("products", where=where)

        # Extract data from RustResponseBytes
        results = extract_graphql_data(result, "products")

        # EXPECTED: Should return active products
        assert len(results) == counts["active"], (
            f"Expected {counts['active']} active products, got {len(results)}. "
            "FraiseQL is incorrectly using JSONB path (data->>'is_active') "
            "instead of direct column reference (is_active)"
        )

        # Verify the returned data
        for product in results:
            assert product["isActive"] is True

    @pytest.mark.asyncio
    async def test_dynamic_filter_construction_by_status(
        self, class_db_pool, test_schema, setup_hybrid_table
    ) -> None:
        """Test dynamic filter construction pattern used in resolvers.

        This simulates the exact pattern from the production bug report
        where status filtering is dynamically constructed.
        """
        counts = setup_hybrid_table

        register_type_for_view(
            "products",
            Product,
            table_columns={
                "id",
                "tenant_id",
                "name",
                "status",
                "is_active",
                "is_featured",
                "is_available",
                "category_id",
                "created_date",
                "data",
            },
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        # Simulate resolver logic
        filter_status = "published"  # From GraphQL enum
        where = None

        # Dynamic filter construction (exactly as in production)
        if filter_status:
            if where is None:
                where = {}
            where["status"] = {"eq": filter_status}

        # This pattern is used in production and MUST work
        result = await repo.find("products", where=where)

        # Extract data from RustResponseBytes
        results = extract_graphql_data(result, "products")

        assert len(results) == counts["published"], (
            f"Dynamic filter construction failed. Expected {counts['published']} "
            f"published products, got {len(results)}"
        )

    @pytest.mark.asyncio
    async def test_multiple_regular_column_filters(
        self, class_db_pool, test_schema, setup_hybrid_table
    ) -> None:
        """Test filtering by multiple regular SQL columns simultaneously."""

        register_type_for_view(
            "products",
            Product,
            table_columns={
                "id",
                "tenant_id",
                "name",
                "status",
                "is_active",
                "is_featured",
                "is_available",
                "category_id",
                "created_date",
                "data",
            },
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        # Filter by multiple regular columns
        where = {"is_active": {"eq": True}, "is_featured": {"eq": True}}

        # Should return active products that are also featured
        result = await repo.find("products", where=where)

        # Extract data from RustResponseBytes
        results = extract_graphql_data(result, "products")

        assert len(results) == 1  # Only Premium Widget is active AND featured
        assert results[0]["name"] == "Premium Widget"
        assert results[0]["isActive"] is True
        assert results[0]["isFeatured"] is True

    @pytest.mark.asyncio
    async def test_mixed_regular_and_jsonb_filtering(
        self, class_db_pool, test_schema, setup_hybrid_table
    ) -> None:
        """Test filtering by both regular SQL columns and JSONB fields.

        This tests the hybrid nature where some filters should use regular columns
        and others should use JSONB paths.
        """

        register_type_for_view(
            "products",
            Product,
            table_columns={
                "id",
                "tenant_id",
                "name",
                "status",
                "is_active",
                "is_featured",
                "is_available",
                "category_id",
                "created_date",
                "data",
            },
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        # Mix of regular column and JSONB field filters
        where = {
            "is_active": {"eq": True},  # Should use: WHERE is_active = true
            "brand": {"eq": "TechCorp"},  # Should use: WHERE data->>'brand' = 'TechCorp'
        }

        result = await repo.find("products", where=where)

        # Extract data from RustResponseBytes
        results = extract_graphql_data(result, "products")

        # DEBUG: Print what we actually got
        print("=== RAW RESULT ===")
        print(json.dumps(results, indent=2))
        print("=== AVAILABLE KEYS ===")
        if results:
            print(list(results[0].keys()))

        # Should return only active products from TechCorp
        assert len(results) == 2
        for product in results:
            assert product["isActive"] is True
            assert product["brand"] == "TechCorp"

    @pytest.mark.asyncio
    async def test_whereinput_type_on_hybrid_table(
        self, class_db_pool, test_schema, setup_hybrid_table
    ) -> None:
        """Test using WhereInput type (generated filter class) on hybrid table."""

        register_type_for_view(
            "products",
            Product,
            table_columns={
                "id",
                "tenant_id",
                "name",
                "status",
                "is_active",
                "is_featured",
                "is_available",
                "category_id",
                "created_date",
                "data",
            },
            has_jsonb_data=True,
        )
        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})

        # Use WhereInput type - this should intelligently handle hybrid tables
        where = ProductWhere(status={"eq": "draft"})

        result = await repo.find("products", where=where)

        # Extract data from RustResponseBytes
        results = extract_graphql_data(result, "products")

        assert len(results) == 1, (
            f"WhereInput failed on hybrid table. Expected 1 draft product, got {len(results)}"
        )
        assert results[0]["status"] == "draft"

    @pytest.mark.asyncio
    async def test_direct_sql_verification(
        self, class_db_pool, test_schema, setup_hybrid_table
    ) -> None:
        """Verify that the data and filters work correctly with direct SQL.

        This proves that the issue is with FraiseQL's filter generation,
        not with the data or database structure.
        """
        counts = setup_hybrid_table

        async with class_db_pool.connection() as conn, conn.cursor() as cursor:
            # Test direct column filtering
            await cursor.execute("SELECT id, name FROM products WHERE is_active = true")
            sql_results = await cursor.fetchall()

            assert len(sql_results) == counts["active"], (
                "Direct SQL works correctly, confirming the bug is in FraiseQL"
            )

            # Test mixed filtering
            await cursor.execute(
                """
                    SELECT id, name
                    FROM products
                    WHERE is_active = true
                      AND data->>'brand' = 'TechCorp'
                    """
            )
            mixed_results = await cursor.fetchall()

            assert len(mixed_results) == 2, "Direct SQL with mixed column/JSONB filtering works"
