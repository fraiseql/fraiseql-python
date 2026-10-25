"""Example FraiseQL application with native authentication.

This example demonstrates how to set up a complete FraiseQL application
with native authentication using PostgreSQL and JWT tokens.

Features demonstrated:
- User registration and login
- JWT token authentication
- GraphQL queries with auth decorators
- Password reset flow
- Session management
"""

import asyncio
import os
from datetime import datetime
from uuid import UUID

from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool

import fraiseql
from fraiseql.types import ID
from fraiseql import create_fraiseql_app
from fraiseql.auth.decorators import requires_auth, requires_role
from fraiseql.auth.native.factory import (
    add_security_middleware,
    apply_native_auth_schema,
    create_native_auth_provider,
    get_native_auth_router,
)


# Define GraphQL types
@fraiseql.type
class User:
    """User type for GraphQL API."""

    id: ID
    email: fraiseql.EmailAddress
    name: str
    roles: list[str]
    is_active: bool
    email_verified: bool
    created_at: datetime
    updated_at: datetime


@fraiseql.type
class Post:
    """Blog post type."""

    id: ID
    title: str
    content: str
    author_id: ID
    created_at: datetime
    updated_at: datetime


# Define GraphQL queries
@fraiseql.query
@requires_auth
async def me(info) -> User | None:
    """Get current user information."""
    user_context = info.context["user"]

    # Query user from database
    db = info.context["db"]
    return await db.find_one("v_user", "user", info, mandatory_filters={"id": user_context.user_id})


@fraiseql.query
@requires_auth
async def my_posts(info, limit: int = 10) -> list[Post]:
    """Get posts by current user."""
    user_context = info.context["user"]

    db = info.context["db"]
    return await db.find(
        "v_post", "posts", info, mandatory_filters={"author_id": user_context.user_id}, limit=limit
    )


@fraiseql.query
@requires_role("admin")
async def all_users(info, limit: int = 50) -> list[User]:
    """Get all users (admin only)."""
    db = info.context["db"]
    return await db.find("v_user", "users", info, limit=limit)


@fraiseql.mutation
@requires_auth
async def create_post(info, title: str, content: str) -> Post:
    """Create a new blog post."""
    user_context = info.context["user"]

    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_post",
        {
            "title": title,
            "content": content,
            "author_id": user_context.user_id,
        },
    )

    return await db.find_one("v_post", "post", info, mandatory_filters={"id": result["id"]})


async def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Database setup
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://fraiseql:fraiseql@localhost/fraiseql_dev"
    )

    # Create connection pool
    pool = AsyncConnectionPool(
        database_url,
        min_size=2,
        max_size=10,
    )
    await pool.wait()

    # Apply native auth schema (in production, use proper migrations)
    await apply_native_auth_schema(pool)

    # Create native auth provider
    auth_provider = await create_native_auth_provider(
        db_pool=pool,
        schema="public",  # Use "public" or tenant-specific schema
        access_token_ttl_minutes=15,
        refresh_token_ttl_days=30,
    )

    # Create FraiseQL app with native auth
    app = create_fraiseql_app(
        types=[User, Post],
        queries=[me, my_posts, all_users],
        mutations=[create_post],
        auth=auth_provider,  # Enable authentication
        database_url=database_url,
        production=False,  # Enable GraphQL playground
    )

    # Add native auth REST endpoints
    auth_router = get_native_auth_router(auth_provider)
    app.include_router(auth_router, prefix="/auth", tags=["authentication"])

    # Add security middleware
    jwt_secret = os.environ.get("JWT_SECRET_KEY", "development-secret-change-in-production")
    add_security_middleware(
        app,
        secret_key=jwt_secret,
        enable_rate_limiting=True,
        enable_security_headers=True,
        enable_csrf_protection=False,  # Disabled for API usage
        rate_limit_requests_per_minute=100,  # Higher limit for development
        rate_limit_auth_requests_per_minute=10,
    )

    return app


async def setup_sample_data(pool: AsyncConnectionPool):
    """Set up sample data for testing."""
    from fraiseql.auth.native.models import User as UserModel

    async with pool.connection() as conn, conn.cursor() as cursor:
        # Check if admin user exists
        admin = await UserModel.get_by_email(cursor, "public", "admin@example.com")

        if not admin:
            # Create admin user
            admin = UserModel(
                email="admin@example.com",
                password="AdminPassword123!",
                name="Admin User",
                roles=["admin", "user"],
                permissions=["users:read", "users:write", "posts:write"],
                is_active=True,
                email_verified=True,
            )
            await admin.save(cursor, "public")

            # Create regular user
            user = UserModel(
                email="user@example.com",
                password="UserPassword123!",
                name="Regular User",
                roles=["user"],
                permissions=["posts:write"],
                is_active=True,
                email_verified=True,
            )
            await user.save(cursor, "public")

            await conn.commit()
            print("✅ Sample users created:")
            print("   Admin: admin@example.com / AdminPassword123!")
            print("   User:  user@example.com / UserPassword123!")


if __name__ == "__main__":
    # For development, you can run this directly
    import uvicorn

    async def main():
        app = await create_app()

        # Set up sample data in development
        if not os.environ.get("PRODUCTION"):
            # Get the pool from app state (created during app initialization)
            # This is a simplified approach - in real apps use proper DB management
            database_url = os.environ.get(
                "DATABASE_URL", "postgresql://fraiseql:fraiseql@localhost/fraiseql_dev"
            )
            pool = AsyncConnectionPool(database_url, min_size=1, max_size=2)
            await pool.wait()
            await setup_sample_data(pool)
            await pool.close()

        # Run the server
        config = uvicorn.Config(
            "examples.native_auth_app:create_app",
            factory=True,
            host="0.0.0.0",
            port=8000,
            reload=True,
        )
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(main())
