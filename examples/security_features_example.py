"""Example of using query complexity analysis and rate limiting with FraiseQL.

This example demonstrates how to protect your GraphQL API from:
1. Complex queries that could overload the database
2. Excessive requests from a single client

Note: Uses in-memory rate limiting. For distributed rate limiting,
consider PostgreSQL-based rate limiting (shared across instances).
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Request

from fraiseql import fraise_type
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.gql.complexity import ComplexityConfig, QueryComplexityAnalyzer
from fraiseql.middleware import (
    InMemoryRateLimiter,
    RateLimitConfig,
    RateLimiterMiddleware,
)


# Define types
@fraise_type
class User:
    id: str
    name: str
    email: str


@fraise_type
class Post:
    id: str
    title: str
    content: str
    author_id: str


@fraise_type
class Comment:
    id: str
    text: str
    post_id: str
    author_id: str


# Global complexity analyzer
complexity_analyzer: QueryComplexityAnalyzer | None = None


@asynccontextmanager
async def lifespan(app):
    """Application lifespan manager."""
    global complexity_analyzer

    # Initialize complexity analyzer
    complexity_config = ComplexityConfig(
        max_complexity=1000,  # Maximum complexity score
        max_depth=7,  # Maximum nesting depth
        default_list_size=20,  # Assumed size for lists without limit
        field_multipliers={
            "search": 5,  # Search is expensive
            "fullTextSearch": 10,  # Full text search is very expensive
            "aggregate": 8,  # Aggregations are expensive
        },
        enabled=True,
        include_in_response=True,  # Include complexity in response
        allow_introspection=False,  # Block introspection in production
    )
    complexity_analyzer = QueryComplexityAnalyzer(complexity_config)

    yield


def get_rate_limit_key(request: Request) -> str:
    """Get rate limit key from request.

    Uses authenticated user ID if available, otherwise IP address.
    """
    # Check if user is authenticated
    if hasattr(request.state, "user") and request.state.user:
        return f"user:{request.state.user.user_id}"

    # Fall back to IP address
    if request.client:
        return f"ip:{request.client.host}"

    return "anonymous"


# Query functions with complexity considerations
async def users(info, limit: int = 10) -> list[User]:
    """Get users with default limit to control complexity."""
    # Limit is capped to prevent excessive complexity
    limit = min(limit, 100)

    db = info.context["db"]
    return await db.find("users", limit=limit)


async def user(info, id: str) -> User | None:
    """Get single user by ID (low complexity)."""
    db = info.context["db"]
    return await db.find_one("users", mandatory_filters={"id": id})


async def user_posts(info, user_id: str, limit: int = 20) -> list[Post]:
    """Get posts by user with limit."""
    limit = min(limit, 50)  # Cap limit

    db = info.context["db"]
    return await db.find("posts", mandatory_filters={"author_id": user_id}, limit=limit)


async def search_posts(info, query: str, limit: int = 10) -> list[Post]:
    """Search posts (expensive operation with higher complexity)."""
    limit = min(limit, 20)  # Lower cap for expensive operations

    db = info.context["db"]
    # In real implementation, would use full-text search
    return await db.find("posts", limit=limit)


# Custom GraphQL executor that checks complexity
async def custom_graphql_executor(
    request: Request, query: str, variables: dict | None = None
) -> dict:
    """Custom GraphQL executor with complexity checking."""
    global complexity_analyzer

    if complexity_analyzer:
        try:
            # Analyze query complexity before execution
            complexity_info = complexity_analyzer.analyze(query, variables)

            # Log high complexity queries
            if complexity_info.total_score > 500:
                print(f"High complexity query: {complexity_info.total_score}")
                print(f"Field scores: {complexity_info.field_scores}")

            # Add complexity info to request context for response
            request.state.complexity_info = complexity_info

        except Exception as e:
            # Return GraphQL error response
            return {
                "errors": [
                    {
                        "message": str(e),
                        "extensions": {
                            "code": "COMPLEXITY_ERROR",
                            "complexity": getattr(e, "complexity", None),
                            "limit": getattr(e, "limit", None),
                        },
                    }
                ]
            }

    # Execute query normally
    # (In real implementation, would call the actual GraphQL executor)
    return {"data": {}}


# Create custom context with complexity info
async def custom_context_getter(request: Request) -> dict[str, Any]:
    """Get context with complexity and rate limit info."""
    from fraiseql.fastapi.dependencies import get_db_pool

    context = {
        "request": request,
        "db": get_db_pool(),
    }

    # Add complexity info if available
    if hasattr(request.state, "complexity_info"):
        context["complexity_info"] = request.state.complexity_info

    # Add rate limit info
    if hasattr(request.state, "rate_limit_info"):
        context["rate_limit_info"] = request.state.rate_limit_info

    return context


# Create the application
def create_app(config: FraiseQLConfig | None = None) -> Any:
    """Create FraiseQL app with security features."""
    if not config:
        config = FraiseQLConfig(
            database_url="postgresql://localhost/myapp",
            environment="production",
        )

    app = create_fraiseql_app(
        types=[User, Post, Comment],
        queries=[
            users,
            user,
            user_posts,
            search_posts,
        ],
        config=config,
        context_getter=custom_context_getter,
        lifespan=lifespan,
    )

    # In-memory rate limiter, with a custom key. Middleware must be added before
    # the app starts (Starlette refuses it in the lifespan). For the plain per-IP
    # limit, FraiseQLConfig(rate_limit_enabled=True, ...) installs the same
    # middleware. For a limit shared across instances, use PostgreSQLRateLimiter.
    rate_limiter = InMemoryRateLimiter(
        RateLimitConfig(
            requests_per_minute=30,  # 30 requests per minute
            requests_per_hour=1000,  # 1000 requests per hour
            burst_size=5,  # at least 5 requests a minute, even above requests_per_minute
            key_func=get_rate_limit_key,  # Custom key function
        )
    )
    app.add_middleware(RateLimiterMiddleware, rate_limiter=rate_limiter)

    # Add custom endpoint to check rate limit status
    @app.get("/rate-limit-status")
    async def rate_limit_status(request: Request):
        """Check current rate limit status."""
        key = get_rate_limit_key(request)

        # Get rate limiter from app (would need to store reference)
        # For demo, return mock data
        return {
            "key": key,
            "requests_remaining": 25,
            "reset_after": 45,
            "minute_limit": 30,
            "hour_limit": 1000,
        }

    # Custom GraphQL endpoint with complexity analysis
    @app.post("/graphql-analyzed")
    async def graphql_analyzed(request: Request):
        """GraphQL endpoint with complexity analysis."""
        body = await request.json()
        query = body.get("query", "")
        variables = body.get("variables")

        result = await custom_graphql_executor(request, query, variables)

        # Add complexity info to response extensions
        if hasattr(request.state, "complexity_info"):
            if "extensions" not in result:
                result["extensions"] = {}

            result["extensions"]["complexity"] = {
                "score": request.state.complexity_info.total_score,
                "depth": request.state.complexity_info.depth,
                "fieldCount": request.state.complexity_info.field_count,
                "fieldScores": request.state.complexity_info.field_scores,
            }

        return result

    return app


# Example queries showing complexity
SIMPLE_QUERY = """
query GetUser {
    user(id: "123") {
        id
        name
        email
    }
}
"""
# Complexity: ~4 (1 for user + 3 for fields)

MODERATE_QUERY = """
query GetUserWithPosts {
    user(id: "123") {
        id
        name
        posts(limit: 10) {
            id
            title
            content
        }
    }
}
"""
# Complexity: ~34 (1 for user + 2 for fields + 1 for posts + 10 * 3 for post fields)

COMPLEX_QUERY = """
query GetUsersWithDetails {
    users(limit: 50) {
        id
        name
        posts(limit: 20) {
            id
            title
            comments(limit: 10) {
                id
                text
                author {
                    id
                    name
                }
            }
        }
    }
}
"""
# Complexity: >1000 (would be rejected)

EXPENSIVE_QUERY = """
query SearchEverything {
    search(query: "test", limit: 100) {
        ... on Post {
            id
            title
            content
            author {
                id
                name
            }
        }
        ... on Comment {
            id
            text
        }
    }
}
"""
# High complexity due to search multiplier


if __name__ == "__main__":
    import uvicorn

    # Create and run the app
    app = create_app()

    print("Starting FraiseQL with security features...")
    print("- Query complexity analysis enabled (max: 1000)")
    print("- Rate limiting enabled (30 req/min, 1000 req/hour)")
    print("- Introspection disabled")
    print("\nTry the example queries to see complexity scores!")

    uvicorn.run(app, host="0.0.0.0", port=8000)
