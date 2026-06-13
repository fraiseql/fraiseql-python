"""Test that demonstrates and fixes the dynamic filter construction bug.

When a GraphQL resolver dynamically modifies or adds filters to the `where` parameter,
the filters should be properly applied to the database query.

Related issue: /tmp/fraiseql_filter_not_applied_issue.md
"""

from decimal import Decimal

import pytest

pytestmark = pytest.mark.database

# Import database fixtures
from tests.fixtures.database.database_conftest import *  # noqa: F403
from tests.unit.utils.test_response_utils import extract_graphql_data

from fraiseql.db import FraiseQLRepository, register_type_for_view


@pytest.mark.asyncio
class TestDynamicFilterConstruction:
    """Test suite for dynamic filter construction in repository find() method."""

    async def test_dynamic_dict_filter_construction(self, class_db_pool, test_schema) -> None:
        """Test that dictionary where clauses are properly processed when constructed dynamically."""
        # Set up test data
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            # Create test table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_allocation (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    data JSONB NOT NULL,
                    name TEXT NOT NULL,
                    is_current BOOLEAN NOT NULL DEFAULT false,
                    tenant_id UUID NOT NULL,
                    quantity NUMERIC(10, 2) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """
            )

            # Clear existing data
            await conn.execute("DELETE FROM test_allocation")

            # Insert test data
            tenant_id = "22222222-2222-2222-2222-222222222222"
            test_data = []

            # Insert 10 current allocations and 15 past allocations
            for i in range(25):
                is_current = i < 10  # First 10 are current
                test_data.append(
                    (f"Allocation {i + 1}", is_current, tenant_id, Decimal(100 + i * 10))
                )

            async with conn.cursor() as cursor:
                await cursor.executemany(
                    """
                    INSERT INTO test_allocation (name, is_current, tenant_id, quantity, data)
                    VALUES (
                        %s, %s, %s, %s,
                        jsonb_build_object(
                            'name', %s::text,
                            'is_current', %s::boolean,
                            'tenant_id', %s::text,
                            'quantity', %s::numeric
                        )
                    )
                    """,
                    [
                        (name, is_curr, tid, qty, name, is_curr, tid, float(qty))
                        for name, is_curr, tid, qty in test_data
                    ],
                )
            await conn.commit()

        # Create repository instance in production mode (returns dicts)
        repo = FraiseQLRepository(class_db_pool, context={"mode": "production"})

        # Simulate the pattern from the bug report: dynamically building where clause
        where = None
        period = "CURRENT"  # Simulating enum value

        # Dynamic filter construction (the problematic pattern)
        if period == "CURRENT":
            if where is None:
                where = {}
            where["is_current"] = {"eq": True}

        # This should return only current allocations (10 items)
        result = await repo.find(
            "test_allocation",
            mandatory_filters={"tenant_id": tenant_id},
            where=where,
            limit=100,
        )

        # Extract data from RustResponseBytes
        results = extract_graphql_data(result, "test_allocation")

        # Verify the filter was applied
        assert len(results) == 10, f"Expected 10 current allocations, got {len(results)}"

        # Check if results are dicts (development mode)
        for r in results:
            assert r["isCurrent"] is True, f"Result has isCurrent={r['isCurrent']}, expected True"

    @pytest.mark.asyncio
    async def test_merged_dict_filters(self, class_db_pool, test_schema) -> None:
        """Test merging multiple dynamic filters into a where clause."""
        # Set up test data
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            # Create test table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_product (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    data JSONB NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    price NUMERIC(10, 2) NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT true,
                    tenant_id UUID NOT NULL
                )
            """
            )

            # Clear existing data
            await conn.execute("DELETE FROM test_product")

            # Insert test data
            tenant_id = "33333333-3333-3333-3333-333333333333"

            products = [
                ("Widget A", "electronics", Decimal("99.99"), True),
                ("Widget B", "electronics", Decimal("149.99"), True),
                ("Gadget A", "accessories", Decimal("49.99"), True),
                ("Gadget B", "accessories", Decimal("79.99"), False),
                ("Tool A", "tools", Decimal("199.99"), True),
                ("Tool B", "tools", Decimal("299.99"), False),
            ]

            async with conn.cursor() as cursor:
                for name, category, price, is_active in products:
                    await cursor.execute(
                        """
                        INSERT INTO test_product (name, category, price, is_active, tenant_id, data)
                        VALUES (
                            %s, %s, %s, %s, %s,
                            jsonb_build_object(
                                'name', %s::text,
                                'category', %s::text,
                                'price', %s::numeric,
                                'is_active', %s::boolean,
                                'tenant_id', %s::text
                            )
                        )
                        """,
                        (
                            name,
                            category,
                            price,
                            is_active,
                            tenant_id,
                            name,
                            category,
                            float(price),
                            is_active,
                            tenant_id,
                        ),
                    )
            await conn.commit()

        # Register type for development mode
        class TestProduct:
            pass

        register_type_for_view("test_product", TestProduct)

        repo = FraiseQLRepository(class_db_pool, context={"mode": "production"})

        # Build dynamic where clause with multiple conditions
        where = {}

        # Add category filter dynamically
        filter_category = "electronics"
        if filter_category:
            where["category"] = {"eq": filter_category}

        # Add price range filter dynamically
        min_price = 100
        if min_price:
            if "price" not in where:
                where["price"] = {}
            where["price"]["gte"] = min_price

        # Add active filter dynamically
        only_active = True
        if only_active:
            where["is_active"] = {"eq": True}

        # Execute query with dynamic filters
        result = await repo.find(
            "test_product",
            mandatory_filters={"tenant_id": tenant_id},
            where=where,
        )

        # Extract data from RustResponseBytes
        results = extract_graphql_data(result, "test_product")

        # Should return only Widget B (electronics, price >= 100, active)
        assert len(results) == 1, f"Expected 1 product, got {len(results)}"
        assert results[0]["name"] == "Widget B"
        assert results[0]["category"] == "electronics"
        assert float(results[0]["price"]) == 149.99
        assert results[0]["isActive"] is True

    @pytest.mark.asyncio
    async def test_empty_dict_where_to_populated(self, class_db_pool, test_schema) -> None:
        """Test that starting with empty dict and populating it works."""
        # Set up test data
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_items (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    data JSONB NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tenant_id UUID NOT NULL
                )
            """
            )

            await conn.execute("DELETE FROM test_items")

            tenant_id = "44444444-4444-4444-4444-444444444444"

            items = [
                ("Item 1", "pending"),
                ("Item 2", "active"),
                ("Item 3", "active"),
                ("Item 4", "inactive"),
                ("Item 5", "pending"),
            ]

            async with conn.cursor() as cursor:
                for name, status in items:
                    await cursor.execute(
                        """
                        INSERT INTO test_items (name, status, tenant_id, data)
                        VALUES (
                            %s, %s, %s,
                            jsonb_build_object(
                                'name', %s::text,
                                'status', %s::text,
                                'tenant_id', %s::text
                            )
                        )
                        """,
                        (name, status, tenant_id, name, status, tenant_id),
                    )
            await conn.commit()

        # Register type for development mode
        class TestItem:
            pass

        register_type_for_view("test_items", TestItem)

        repo = FraiseQLRepository(class_db_pool, context={"mode": "production"})

        # Start with empty where dict (common pattern in resolvers)
        where = {}

        # Dynamically add filter based on some condition
        filter_status = "active"
        if filter_status:
            where["status"] = {"eq": filter_status}

        result = await repo.find(
            "test_items",
            mandatory_filters={"tenant_id": tenant_id},
            where=where,
        )

        # Extract data from RustResponseBytes
        results = extract_graphql_data(result, "test_items")

        # Should return only active items
        assert len(results) == 2, f"Expected 2 active items, got {len(results)}"
        assert all(r["status"] == "active" for r in results)

    @pytest.mark.asyncio
    async def test_complex_nested_dict_filters(self, class_db_pool, test_schema) -> None:
        """Test complex dictionary filters with multiple operators."""
        # Set up test data
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_events (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    data JSONB NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    attendees INTEGER NOT NULL,
                    tenant_id UUID NOT NULL
                )
            """
            )

            await conn.execute("DELETE FROM test_events")

            tenant_id = "55555555-5555-5555-5555-555555555555"

            events = [
                ("Small Meeting", "Team sync", 5),
                ("Department Meeting", "Monthly review", 20),
                ("All Hands", "Company update", 150),
                ("Workshop", "Training session", 30),
                ("Conference", "Annual conference", 500),
            ]

            async with conn.cursor() as cursor:
                for title, desc, attendees in events:
                    await cursor.execute(
                        """
                        INSERT INTO test_events (title, description, attendees, tenant_id, data)
                        VALUES (
                            %s, %s, %s, %s,
                            jsonb_build_object(
                                'title', %s::text,
                                'description', %s::text,
                                'attendees', %s::integer,
                                'tenant_id', %s::text
                            )
                        )
                        """,
                        (title, desc, attendees, tenant_id, title, desc, attendees, tenant_id),
                    )
            await conn.commit()

        # Register type for development mode
        class TestEvent:
            pass

        register_type_for_view("test_events", TestEvent)

        repo = FraiseQLRepository(class_db_pool, context={"mode": "production"})

        # Build complex where clause dynamically
        where = {}

        # Add text search filter
        search_term = "meeting"
        if search_term:
            where["title"] = {"icontains": search_term}

        # Add range filter with multiple operators
        min_attendees = 10
        max_attendees = 100
        where["attendees"] = {"gte": min_attendees, "lte": max_attendees}

        result = await repo.find(
            "test_events",
            mandatory_filters={"tenant_id": tenant_id},
            where=where,
        )

        # Extract data from RustResponseBytes
        results = extract_graphql_data(result, "test_events")

        # Should return Department Meeting (title contains "meeting", 20 attendees in range)
        assert len(results) == 1, f"Expected 1 event, got {len(results)}"
        assert results[0]["title"] == "Department Meeting"
        assert results[0]["attendees"] == 20
