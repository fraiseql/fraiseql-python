"""Example of using TurboRouter with query complexity analysis.

This example demonstrates how to:
1. Set up EnhancedTurboRouter with complexity-based caching
2. Monitor cache performance
3. Make intelligent caching decisions
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from graphql import GraphQLSchema

import fraiseql
from fraiseql import fraise_type
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.turbo import TurboQuery
from fraiseql.fastapi.turbo_enhanced import (
    EnhancedTurboRegistry,
    EnhancedTurboRouter,
)
from fraiseql.gql.schema_builder import build_fraiseql_schema


# Define some types for the example
@fraise_type
class Author:
    id: int
    name: str
    email: str


@fraise_type
class Comment:
    id: int
    text: str
    author: Author


@fraise_type
class Post:
    id: int
    title: str
    content: str
    author: Author
    comments: list[Comment]


@fraise_type
class User:
    id: int
    name: str
    email: str
    posts: list[Post]


# Define queries
@fraiseql.query
async def get_user(info, user_id: int) -> User:
    """Simple query - good for caching."""
    # In real app, this would fetch from database
    return User(
        id=user_id,
        name=f"User {user_id}",
        email=f"user{user_id}@example.com",
        posts=[],
    )


@fraiseql.query
async def get_user_with_posts(info, user_id: int) -> User:
    """Moderate complexity query."""
    # Simulated data
    return User(
        id=user_id,
        name=f"User {user_id}",
        email=f"user{user_id}@example.com",
        posts=[
            Post(
                id=i,
                title=f"Post {i}",
                content=f"Content for post {i}",
                author=Author(id=user_id, name=f"User {user_id}", email=""),
                comments=[],
            )
            for i in range(5)
        ],
    )


@fraiseql.query
async def get_all_users_deep(info) -> list[User]:
    """Complex query - might not be cached."""
    # This would be a very expensive query
    users = []
    for user_id in range(10):
        user = User(
            id=user_id,
            name=f"User {user_id}",
            email=f"user{user_id}@example.com",
            posts=[],
        )

        # Add posts with comments
        for post_id in range(5):
            post = Post(
                id=post_id,
                title=f"Post {post_id}",
                content="Content",
                author=Author(id=user_id, name=f"User {user_id}", email=""),
                comments=[
                    Comment(
                        id=comment_id,
                        text=f"Comment {comment_id}",
                        author=Author(
                            id=100 + comment_id,
                            name=f"Commenter {comment_id}",
                            email="",
                        ),
                    )
                    for comment_id in range(10)
                ],
            )
            user.posts.append(post)

        users.append(user)

    return users


# Create the enhanced TurboRouter
def create_enhanced_app() -> FastAPI:
    """Create a FastAPI app with enhanced TurboRouter."""
    # Build schema
    schema = build_fraiseql_schema(
        query_types=[get_user, get_user_with_posts, get_all_users_deep],
    )

    # Create enhanced registry with complexity limits
    enhanced_registry = EnhancedTurboRegistry(
        max_size=100,  # Max 100 queries
        max_complexity=150,  # Reject queries with complexity > 150
        max_total_weight=200.0,  # Total cache weight limit
        schema=schema,
    )

    # Create enhanced router
    turbo_router = EnhancedTurboRouter(enhanced_registry)

    # Create the app
    # The registry analyses queries on its own; the app serves the same queries
    app = create_fraiseql_app(
        database_url=os.getenv("DATABASE_URL", "postgresql://localhost/fraiseql_example"),
        types=[Author, Comment, Post, User],
        queries=[get_user, get_user_with_posts, get_all_users_deep],
    )

    # Add monitoring endpoint
    @app.get("/cache-metrics")
    async def get_cache_metrics():
        """Get TurboRouter cache metrics."""
        return enhanced_registry.get_metrics()

    # Add endpoint to check if a query would be cached
    @app.post("/analyze-query")
    async def analyze_query(query_string: str):
        """Analyze a query's complexity and caching decision."""
        score, weight = enhanced_registry.analyze_query(query_string)
        should_cache = enhanced_registry.should_cache(score)

        return {
            "complexity_score": score.total_score,
            "field_count": score.field_count,
            "max_depth": score.max_depth,
            "array_fields": score.array_field_count,
            "cache_weight": weight,
            "should_cache": should_cache,
            "reason": (
                "Query is simple enough for caching"
                if should_cache
                else f"Query complexity ({score.total_score}) exceeds threshold"
            ),
        }

    # Pre-register common queries. (A FastAPI startup event wouldn't run: the
    # app has a lifespan.)
    def register_common_queries() -> None:
        """Pre-register common queries for turbo execution."""
        # Simple query - will be cached
        simple_query = """
        query GetUser($userId: Int!) {
            getUser(userId: $userId) {
                id
                name
                email
            }
        }
        """

        # This would normally be generated from actual execution
        simple_sql = """
        SELECT jsonb_build_object(
            'id', id,
            'name', name,
            'email', email
        ) as result
        FROM users
        WHERE id = %(userId)s
        """

        turbo_query = TurboQuery(
            graphql_query=simple_query,
            sql_template=simple_sql,
            param_mapping={"userId": "userId"},
        )

        result = enhanced_registry.register(turbo_query)
        if result:
            print(f"✓ Registered simple query (hash: {result[:8]}...)")
        else:
            print("✗ Simple query rejected by complexity analysis")

        # Complex query - might be rejected
        complex_query = """
        query GetAllUsersDeep {
            getAllUsersDeep {
                id
                name
                email
                posts {
                    id
                    title
                    content
                    author {
                        id
                        name
                    }
                    comments {
                        id
                        text
                        author {
                            id
                            name
                            email
                        }
                    }
                }
            }
        }
        """

        complex_sql = "SELECT * FROM get_all_users_deep()"  # Simplified

        complex_turbo = TurboQuery(
            graphql_query=complex_query,
            sql_template=complex_sql,
            param_mapping={},
        )

        result = enhanced_registry.register(complex_turbo)
        if result:
            print(f"✓ Registered complex query (hash: {result[:8]}...)")
        else:
            print("✗ Complex query rejected by complexity analysis")

    register_common_queries()
    return app


# Example usage
if __name__ == "__main__":
    import uvicorn

    app = create_enhanced_app()

    print("Starting FraiseQL with Enhanced TurboRouter...")
    print("Visit http://localhost:8000/graphql for GraphQL playground")
    print("Visit http://localhost:8000/cache-metrics for cache statistics")
    print()

    uvicorn.run(app, host="0.0.0.0", port=8000)
