"""FraiseQL Blog Simple - Complete Example Application

A small blog on PostgreSQL: posts with their author, tags and comments, read
from JSONB views and written through SQL functions. See README.md to run it.

The current user comes from the X-User-ID header (johndoe from the sample data
by default). Replace get_context with your authentication in production.
"""

import os
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from fraiseql.fastapi import create_fraiseql_app

try:
    # Running from the blog_simple directory
    from models import BLOG_MUTATIONS, BLOG_QUERIES, BLOG_TYPES
except ImportError:
    # Running from the repository root
    from examples.blog_simple.models import BLOG_MUTATIONS, BLOG_QUERIES, BLOG_TYPES

DEMO_USER_ID = "22222222-2222-2222-2222-222222222222"  # johndoe in db/seed_data.sql


def get_database_url() -> str:
    """Build the database URL from DB_* environment variables."""
    user = os.getenv("DB_USER", "fraiseql")
    password = os.getenv("DB_PASSWORD", "fraiseql")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "fraiseql_blog_simple")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


async def get_context(request: Request) -> dict:
    """Add the current user to the GraphQL context.

    fraiseql merges this into its default context, which holds the database.
    The mutations pass user_id to their SQL function (context_params).
    """
    return {"user_id": UUID(request.headers.get("X-User-ID", DEMO_USER_ID))}


def create_app() -> FastAPI:
    """Create the blog application."""
    app = create_fraiseql_app(
        database_url=get_database_url(),
        types=BLOG_TYPES,
        queries=BLOG_QUERIES,
        mutations=BLOG_MUTATIONS,
        context_getter=get_context,
        title="FraiseQL Simple Blog",
        description="Simple blog built with FraiseQL",
        production=False,  # GraphQL playground on
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # fraiseql serves GET /health itself; the service name is in this route
    @app.get("/")
    async def home():
        return {
            "message": "FraiseQL Simple Blog",
            "service": "blog_simple",
            "endpoints": {"graphql": "/graphql", "health": "/health"},
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))  # noqa: S104
