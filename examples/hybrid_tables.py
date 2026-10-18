"""Hybrid Tables Example for FraiseQL

This example demonstrates how to use hybrid CQRS tables in FraiseQL,
where writes go to one table and reads come from an optimized view.
"""

from datetime import datetime
from uuid import UUID, uuid4

from graphql import GraphQLResolveInfo

import fraiseql
from fraiseql.types import ID
from fraiseql.db import FraiseQLRepository


@fraiseql.type
class Product:
    """Product with CQRS pattern - writes to table, reads from view."""
    id: ID
    name: str
    description: str
    price: float
    stock: int
    created_at: datetime
    updated_at: datetime


# Write table (normalized, for ACID transactions)
CREATE_PRODUCTS_TABLE = """
CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""

# Read view (denormalized, optimized for reads)
CREATE_PRODUCTS_VIEW = """
CREATE OR REPLACE VIEW products_view AS
SELECT
    id,
    name,
    description,
    price,
    stock,
    created_at,
    updated_at,
    -- Computed fields for performance
    (price * stock) as total_value,
    CASE
        WHEN stock = 0 THEN 'out_of_stock'
        WHEN stock < 10 THEN 'low_stock'
        ELSE 'in_stock'
    END as stock_status
FROM products
WHERE deleted_at IS NULL;  -- Soft delete filter

-- Add indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);
CREATE INDEX IF NOT EXISTS idx_products_stock ON products(stock);
"""


@fraiseql.query
def get_products(
    info: GraphQLResolveInfo,
    limit: int = 100,
    in_stock_only: bool = False
) -> list[Product]:
    """Get products from the read-optimized view.

    Uses the products_view which includes denormalized data
    and computed fields for optimal read performance.
    """
    filters = {}
    if in_stock_only:
        # Use computed stock_status field from view
        filters["stock_status"] = {"in": ["in_stock", "low_stock"]}

    return info.context.repo.find(
        "products_view",
        limit=limit,
        **filters
    )


@fraiseql.query
def get_product(
    info: GraphQLResolveInfo,
    id: ID
) -> Product | None:
    """Get a single product by ID from the read view."""
    return info.context.repo.find_one("products_view", id=id)


@fraiseql.mutation
async def create_product(
    info: GraphQLResolveInfo,
    name: str,
    description: str,
    price: float,
    stock: int = 0
) -> Product:
    """Create a product - writes to the table.

    The write goes to the products table, and will be
    immediately available in the products_view.
    """
    # Write to the actual table
    product_data = {
        "id": uuid4(),
        "name": name,
        "description": description,
        "price": price,
        "stock": stock
    }

    result = await info.context.repo.insert(
        "products",  # Write table
        product_data
    )

    # Read back from the view to get computed fields
    return info.context.repo.find_one(
        "products_view",  # Read view
        id=result["id"]
    )


@fraiseql.mutation
async def update_product_stock(
    info: GraphQLResolveInfo,
    id: ID,
    quantity_delta: int
) -> Product:
    """Update product stock - uses a transaction for ACID guarantees.

    Writes go to the table, ensuring data consistency.
    The view automatically reflects the changes.
    """
    async with info.context.repo.transaction() as tx:
        # Get current stock (from write table for ACID)
        current = await tx.query_one(
            "SELECT stock FROM products WHERE id = $1 FOR UPDATE",
            id
        )

        if current is None:
            raise ValueError(f"Product {id} not found")

        new_stock = current["stock"] + quantity_delta

        if new_stock < 0:
            raise ValueError("Insufficient stock")

        # Update the write table
        await tx.execute(
            "UPDATE products SET stock = $1, updated_at = NOW() WHERE id = $2",
            new_stock,
            id
        )

    # Read back from the optimized view
    return info.context.repo.find_one("products_view", id=id)


# Example usage
async def example_usage():
    """Demonstrates the hybrid table pattern.

    Benefits:
    - Writes are ACID-compliant (use table with transactions)
    - Reads are fast (use denormalized view)
    - No application-level cache synchronization needed
    - PostgreSQL handles consistency automatically
    """
    import asyncpg

    # Setup
    pool = await asyncpg.create_pool("postgresql://localhost/mydb")
    repo = FraiseQLRepository(pool)

    # Create tables (one-time setup)
    await repo.execute(CREATE_PRODUCTS_TABLE)
    await repo.execute(CREATE_PRODUCTS_VIEW)

    # Write operations use the table
    product_id = uuid4()
    await repo.insert(
        "products",  # Write table
        {
            "id": product_id,
            "name": "Widget",
            "price": 29.99,
            "stock": 100
        }
    )

    # Read operations use the view
    product = await repo.find_one(
        "products_view",  # Read view (with computed fields)
        id=product_id
    )
    print(f"Product: {product['name']}, Status: {product['stock_status']}")

    # Update with transaction (ACID)
    async with repo.transaction() as tx:
        await tx.execute(
            "UPDATE products SET stock = stock - 1 WHERE id = $1",
            product_id
        )

    # View automatically shows updated data
    updated = await repo.find_one("products_view", id=product_id)
    print(f"Updated stock: {updated['stock']}")

    await pool.close()


if __name__ == "__main__":
    import asyncio
    # asyncio.run(example_usage())
    print(__doc__)
