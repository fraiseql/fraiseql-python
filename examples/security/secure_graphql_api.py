"""Example: Secure GraphQL API with FraiseQL Security

This example sets up a GraphQL API with fraiseql's security middleware:

- Rate limiting for different operation types
- CSRF protection for mutations
- Security headers for defense in depth
- Authentication from a bearer token, checked in resolvers

The posts live in memory so the example runs without a database; see
../blog_simple/ for queries and mutations backed by PostgreSQL.

Usage:
    python secure_graphql_api.py

    ENVIRONMENT=production SECRET_KEY=... DOMAIN=api.example.com \
        TRUSTED_ORIGINS=https://app.example.com python secure_graphql_api.py
"""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from graphql import GraphQLError, GraphQLResolveInfo

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.security import (
    create_security_config_for_graphql,
    setup_development_security,
    setup_production_security,
    setup_security,
)
from fraiseql.types import ID

# Environment configuration
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
DOMAIN = os.getenv("DOMAIN", "api.example.com")
TRUSTED_ORIGINS = os.getenv("TRUSTED_ORIGINS", "https://app.example.com").split(",")

# create_fraiseql_app needs a URL; nothing here queries the database
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/secure_blog")

# Redis for distributed rate limiting (optional)
REDIS_URL = os.getenv("REDIS_URL")

# The one valid token and its user, standing in for JWT validation
DEMO_TOKEN = "valid-token"
DEMO_USER_ID = UUID("123e4567-e89b-12d3-a456-426614174002")


# GraphQL Types
@fraiseql.type
class User:
    id: ID
    username: str


@fraiseql.type
class Post:
    id: ID
    title: str
    content: str
    author_id: ID
    published: bool
    created_at: datetime
    updated_at: datetime


# Input Types
@fraiseql.input
class CreatePostInput:
    title: str = fraiseql.fraise_field(description="Post title, at least 3 characters")
    content: str = fraiseql.fraise_field(description="Post content, at least 10 characters")
    published: bool = False


@fraiseql.input
class UpdatePostInput:
    id: ID
    title: str | None = None
    content: str | None = None
    published: bool | None = None


# In-memory storage, standing in for the database
POSTS: dict[UUID, Post] = {}


def _require_user(info: GraphQLResolveInfo) -> UUID:
    """Return the authenticated user's id, or refuse the operation."""
    user_id = info.context.get("user_id")
    if user_id is None:
        raise GraphQLError("Authentication required", extensions={"code": "UNAUTHENTICATED"})
    return user_id


# Queries
@fraiseql.query
async def posts(info: GraphQLResolveInfo, limit: int = 20, offset: int = 0) -> list[Post]:
    """Get published posts, newest first."""
    published = sorted(
        (p for p in POSTS.values() if p.published), key=lambda p: p.created_at, reverse=True
    )
    return published[offset : offset + limit]


@fraiseql.query
async def post(info: GraphQLResolveInfo, id: ID) -> Post | None:
    """Get a published post, or one of your own drafts."""
    found = POSTS.get(UUID(str(id)))
    if found is None or (not found.published and found.author_id != info.context.get("user_id")):
        return None
    return found


@fraiseql.query
async def me(info: GraphQLResolveInfo) -> User | None:
    """Get the authenticated user, or null."""
    user_id = info.context.get("user_id")
    return User(id=user_id, username="demo") if user_id else None


# Mutations (authentication required; CSRF protection applies to them)
@fraiseql.mutation
async def create_post(info: GraphQLResolveInfo, input: CreatePostInput) -> Post:
    """Create a post."""
    user_id = _require_user(info)

    # Validate input
    if len(input.title.strip()) < 3:
        raise GraphQLError(
            "Title must be at least 3 characters", extensions={"code": "VALIDATION_ERROR"}
        )
    if len(input.content.strip()) < 10:
        raise GraphQLError(
            "Content must be at least 10 characters", extensions={"code": "VALIDATION_ERROR"}
        )

    now = datetime.now(tz=UTC)
    new_post = Post(
        id=uuid4(),
        title=input.title.strip(),
        content=input.content.strip(),
        author_id=user_id,
        published=input.published,
        created_at=now,
        updated_at=now,
    )
    POSTS[new_post.id] = new_post
    return new_post


@fraiseql.mutation
async def update_post(info: GraphQLResolveInfo, input: UpdatePostInput) -> Post:
    """Update one of your posts."""
    user_id = _require_user(info)

    # Same answer for a missing post and someone else's: don't reveal which
    existing = POSTS.get(UUID(str(input.id)))
    if existing is None or existing.author_id != user_id:
        raise GraphQLError("Post not found or access denied", extensions={"code": "NOT_FOUND"})

    if input.title is not None:
        existing.title = input.title.strip()
    if input.content is not None:
        existing.content = input.content.strip()
    if input.published is not None:
        existing.published = input.published
    existing.updated_at = datetime.now(tz=UTC)
    return existing


# Authentication
async def auth_middleware(request: Request, call_next):
    """Set request.state.user_id from the bearer token (None without a valid one)."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ") if auth_header.startswith("Bearer ") else None

    # In a real app, validate a JWT here
    request.state.user_id = DEMO_USER_ID if token == DEMO_TOKEN else None
    return await call_next(request)


async def get_context(request: Request) -> dict:
    """Add the authenticated user to fraiseql's GraphQL context."""
    return {"user_id": getattr(request.state, "user_id", None)}


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = create_fraiseql_app(
        database_url=DATABASE_URL,
        types=[User, Post],
        queries=[posts, post, me],
        mutations=[create_post, update_post],
        context_getter=get_context,
        title="Secure GraphQL API",
        description="GraphQL API with rate limiting, CSRF protection and security headers",
        production=(ENVIRONMENT == "production"),
    )

    # Set up security based on environment
    if ENVIRONMENT == "production":
        redis_client = None
        if REDIS_URL:
            try:
                import redis.asyncio as redis

                redis_client = redis.from_url(REDIS_URL)
            except ImportError:
                pass

        setup_production_security(
            app=app,
            secret_key=SECRET_KEY,
            domain=DOMAIN,
            trusted_origins=set(TRUSTED_ORIGINS),
            redis_client=redis_client,
        )
    elif ENVIRONMENT == "development":
        # More permissive: no CSRF token required, relaxed headers
        setup_development_security(app=app, secret_key=SECRET_KEY)
    else:
        # Custom security setup for GraphQL
        config = create_security_config_for_graphql(
            secret_key=SECRET_KEY,
            environment=ENVIRONMENT,
            trusted_origins=TRUSTED_ORIGINS,
            enable_introspection=False,
        )
        setup_security(app=app, secret_key=SECRET_KEY, custom_config=config)

    # Added last, so it runs first and the security middleware sees the user
    app.middleware("http")(auth_middleware)

    @app.get("/security-info")
    async def security_info():
        """Show the security configuration (not in production)."""
        if ENVIRONMENT == "production":
            return {"error": "Not available in production"}

        return {
            "environment": ENVIRONMENT,
            "security_features": ["rate_limiting", "csrf_protection", "security_headers"],
            "trusted_origins": TRUSTED_ORIGINS,
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))  # noqa: S104
