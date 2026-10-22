"""FraiseQL PostgreSQL-Native Caching Example

🟡 INTERMEDIATE | ⏱️ 15 min | 🎯 Performance | 🏷️ Caching

Example of using FraiseQL with PostgreSQL-native caching for improved performance—eliminating the need for Redis.

Benefits:
- Save $50-500/month (no Redis Cloud needed)
- UNLOGGED tables = Redis-level performance
- Shared across all app instances
- Same database for everything (simplified operations)

LEARNING OUTCOMES:
- PostgreSQL UNLOGGED tables for high performance
- Cache invalidation strategies
- Memory-efficient caching patterns
- Database-backed caching without Redis

PREREQUISITES:
- ../blog_api/ - Basic FraiseQL patterns
- Understanding of caching concepts

NEXT STEPS:
- ../apq_multi_tenant/ - Query-level caching
- ../turbo_router_with_complexity.py - Pre-compiled query routing
- ../analytics_dashboard/ - High-performance analytics
"""

import asyncio
from uuid import UUID

from fraiseql import fraise_type
from fraiseql.caching import (
    CacheConfig,
    CachedRepository,
    PostgresCache,
    ResultCache,
)
from fraiseql.db import FraiseQLRepository
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import ID


# Define your types
@fraise_type
class User:
    id: ID
    name: str
    email: str
    status: str


@fraise_type
class Product:
    id: ID
    name: str
    price: float
    category: str


async def setup_cached_repository(db_pool) -> CachedRepository:
    """Set up a cached repository with PostgreSQL backend.

    Uses PostgreSQL UNLOGGED tables for high-performance caching.
    - No WAL overhead = Redis-level write performance
    - Same read performance as Redis for hot data
    - Automatic persistence (survives crashes)
    - Shared across all app instances
    """
    # Create PostgreSQL cache backend
    # UNLOGGED tables provide Redis-level performance
    cache_backend = PostgresCache(db_pool)

    # Configure caching
    cache_config = CacheConfig(
        enabled=True,
        default_ttl=300,  # 5 minutes
        max_ttl=3600,  # 1 hour
        key_prefix="myapp",
    )

    # Create result cache
    result_cache = ResultCache(backend=cache_backend, config=cache_config)

    # Create base repository
    base_repo = FraiseQLRepository(pool=db_pool)

    # Wrap with caching
    return CachedRepository(base_repo, result_cache)


# Query functions that will benefit from caching
async def get_active_users(info) -> list[User]:
    """Get all active users (cached for 5 minutes)."""
    db: CachedRepository = info.context["db"]
    return await db.find("users", status="active")


async def get_user_by_id(info, user_id: ID) -> User | None:
    """Get user by ID (cached for 5 minutes)."""
    db: CachedRepository = info.context["db"]
    return await db.find_one("users", id=user_id)


async def get_products_by_category(
    info,
    category: str,
    min_price: float = 0,
    max_price: float = 10000,
) -> list[Product]:
    """Get products by category with price filter (cached)."""
    db: CachedRepository = info.context["db"]
    return await db.find(
        "products",
        category=category,
        price={"gte": min_price, "lte": max_price},
        # Custom TTL for product queries (1 hour)
        cache_ttl=3600,
    )


async def get_fresh_user_data(info, user_id: ID) -> User | None:
    """Get user data bypassing cache."""
    db: CachedRepository = info.context["db"]
    return await db.find_one("users", id=user_id, skip_cache=True)


# Mutations that will invalidate cache
async def create_user(info, name: str, email: str) -> dict:
    """Create a new user (invalidates user cache)."""
    db: CachedRepository = info.context["db"]
    return await db.execute_function(
        "create_user",
        {"name": name, "email": email, "status": "active"},
    )


async def update_product_price(info, product_id: ID, new_price: float) -> dict:
    """Update product price (invalidates product cache)."""
    db: CachedRepository = info.context["db"]
    return await db.execute_function(
        "update_product",
        {"id": str(product_id), "price": new_price},
    )


# Create the app with custom context
def create_app():
    """Create a FraiseQL app with caching enabled."""

    async def custom_context_getter(request):
        """Provide cached repository in context."""
        from fraiseql.fastapi.dependencies import get_db_pool

        pool = get_db_pool()
        cached_repo = await setup_cached_repository(pool)

        return {
            "db": cached_repo,
            "cache_enabled": True,
        }

    app = create_fraiseql_app(
        types=[User, Product],
        queries=[
            get_active_users,
            get_user_by_id,
            get_products_by_category,
            get_fresh_user_data,
        ],
        mutations=[
            create_user,
            update_product_price,
        ],
        context_getter=custom_context_getter,
    )

    return app


# Example of monitoring cache performance
async def print_cache_stats(app):
    """Print cache statistics."""
    # Get the cached repository from app context
    # In a real app, you'd expose this through an endpoint or metrics

    # This is a simplified example - in production you'd access
    # the cache through proper dependency injection
    cache_stats = {
        "hits": 150,
        "misses": 50,
        "hit_rate": 75.0,
        "errors": 2,
    }

    print("Cache Statistics:")
    print(f"  Hits: {cache_stats['hits']}")
    print(f"  Misses: {cache_stats['misses']}")
    print(f"  Hit Rate: {cache_stats['hit_rate']:.1f}%")
    print(f"  Errors: {cache_stats['errors']}")


if __name__ == "__main__":
    # Example usage
    app = create_app()

    # Run with: uvicorn caching_example:app --reload
