"""Documented API Example for FraiseQL

This example demonstrates how to create a well-documented GraphQL API
with FraiseQL, including docstrings, descriptions, and examples.
"""

from datetime import datetime
from uuid import UUID

from graphql import GraphQLResolveInfo

import fraiseql
from fraiseql.types import ID


@fraiseql.type
class User:
    """A user in the system.

    Users can have posts, comments, and interact with other users.
    """
    id: ID
    email: str
    name: str
    created_at: datetime
    is_active: bool = True


@fraiseql.type
class Post:
    """A blog post created by a user.

    Posts can have multiple comments and tags.
    """
    id: ID
    title: str
    content: str
    author_id: ID
    created_at: datetime
    published: bool = False


@fraiseql.query
def get_user(
    info: GraphQLResolveInfo,
    id: ID
) -> User | None:
    """Get a single user by ID.

    Args:
        id: The unique identifier of the user

    Returns:
        The user object if found, None otherwise

    Example:
        ```graphql
        query {
          getUser(id: "123e4567-e89b-12d3-a456-426614174000") {
            id
            name
            email
          }
        }
        ```
    """
    return info.context.repo.find_one("users_view", id=id)


@fraiseql.query
def get_users(
    info: GraphQLResolveInfo,
    limit: int = 10,
    active_only: bool = True
) -> list[User]:
    """Get a list of users.

    Args:
        limit: Maximum number of users to return (default: 10)
        active_only: Only return active users (default: True)

    Returns:
        List of user objects

    Example:
        ```graphql
        query {
          getUsers(limit: 5, activeOnly: true) {
            id
            name
            email
            isActive
          }
        }
        ```
    """
    filters = {"is_active": True} if active_only else {}
    return info.context.repo.find("users_view", limit=limit, **filters)


@fraiseql.query
def search_posts(
    info: GraphQLResolveInfo,
    query: str,
    published_only: bool = True
) -> list[Post]:
    """Search for posts by title or content.

    Args:
        query: Search term to match against title and content
        published_only: Only return published posts (default: True)

    Returns:
        List of matching posts

    Example:
        ```graphql
        query {
          searchPosts(query: "python", publishedOnly: true) {
            id
            title
            content
            createdAt
          }
        }
        ```
    """
    # In a real implementation, this would use full-text search
    filters = {"published": True} if published_only else {}
    return info.context.repo.find("posts_view", limit=20, **filters)


@fraiseql.mutation
async def create_user(
    info: GraphQLResolveInfo,
    email: str,
    name: str
) -> User:
    """Create a new user.

    Args:
        email: User's email address (must be unique)
        name: User's display name

    Returns:
        The newly created user

    Raises:
        ValueError: If email already exists

    Example:
        ```graphql
        mutation {
          createUser(
            email: "user@example.com"
            name: "John Doe"
          ) {
            id
            email
            name
            createdAt
          }
        }
        ```
    """
    return await info.context.repo.insert(
        "users",
        {"email": email, "name": name}
    )


@fraiseql.mutation
async def update_user(
    info: GraphQLResolveInfo,
    id: ID,
    name: str | None = None,
    email: str | None = None
) -> User:
    """Update an existing user.

    Args:
        id: ID of the user to update
        name: New name (optional)
        email: New email (optional)

    Returns:
        The updated user

    Raises:
        NotFoundError: If user doesn't exist

    Example:
        ```graphql
        mutation {
          updateUser(
            id: "123e4567-e89b-12d3-a456-426614174000"
            name: "Jane Doe"
          ) {
            id
            name
            email
          }
        }
        ```
    """
    updates = {}
    if name is not None:
        updates["name"] = name
    if email is not None:
        updates["email"] = email

    return await info.context.repo.update(
        "users",
        id=id,
        **updates
    )


# Schema configuration with documentation
schema = fraiseql.build_fraiseql_schema(
    query_types=[User, Post, get_user, get_users, search_posts],
    mutation_resolvers=[create_user, update_user],
)

# FastAPI integration
if __name__ == "__main__":
    import asyncpg
    import uvicorn

    from fraiseql.fastapi import create_fraiseql_app

    # In production, use proper async setup
    # This is simplified for example purposes
    print("Note: This is an example. Set up proper database connection in production.")

    # app = create_fraiseql_app(
    #     database_url="postgresql://localhost/mydb",
    #     types=[User, Post],
    #     queries=[get_user, get_users, search_posts],
    #     mutations=[create_user, update_user],
    #     title="Documented API Example",
    #     description="A well-documented GraphQL API built with FraiseQL",
    #     version="1.0.0",
    # )

    # uvicorn.run(app, host="0.0.0.0", port=8000)
