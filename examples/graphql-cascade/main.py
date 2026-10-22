#!/usr/bin/env python3
"""GraphQL Cascade Example

This example demonstrates GraphQL Cascade functionality in FraiseQL.
Run with: python main.py
"""

import uuid
from typing import List, Optional

import uvicorn
from fastapi import FastAPI

import fraiseql
from fraiseql.fastapi import create_fraiseql_app


# Input/Output Types
@fraiseql.input
class CreatePostInput:
    title: str
    content: Optional[str] = None
    author_id: str


@fraiseql.type
class Post:
    id: str
    title: str
    content: Optional[str]
    author_id: str
    created_at: str


@fraiseql.type
class User:
    id: str
    name: str
    post_count: int
    created_at: str


@fraiseql.type
class PostWithAuthor:
    id: str
    title: str
    content: Optional[str]
    author: User
    created_at: str


@fraiseql.type
class CreatePostSuccess:
    id: str
    message: str


@fraiseql.type
class CreatePostError:
    code: str
    message: str
    field: Optional[str]


# Queries
@fraiseql.query
async def getPosts(info) -> List[PostWithAuthor]:
    """Get all posts with author information."""
    db = info.context["db"]
    return await db.find("v_post_with_author", "posts", info)


@fraiseql.query
async def getUser(info, id: str) -> User:
    """Get a user by ID."""
    db = info.context["db"]
    return await db.find_one("v_user", "user", info, mandatory_filters={"id": id})


# Mutations
@fraiseql.mutation(enable_cascade=True)
class CreatePost:
    input: CreatePostInput
    success: CreatePostSuccess
    error: CreatePostError


# Create FraiseQL app
app = create_fraiseql_app(
    database_url="postgresql://localhost/cascade_example",
    types=[CreatePostInput, Post, User, PostWithAuthor, CreatePostSuccess, CreatePostError],
    queries=[getPosts, getUser],
    mutations=[CreatePost],
    title="GraphQL Cascade Example",
    description="Demonstrates GraphQL Cascade functionality for automatic cache updates",
    production=False,  # Enable GraphQL playground
)


@app.get("/")
async def root():
    return {
        "message": "GraphQL Cascade Example",
        "graphql_endpoint": "/graphql",
        "graphiql": "/graphiql",
        "docs": "/docs",
    }


if __name__ == "__main__":
    print("🚀 GraphQL Cascade Example")
    print("📊 GraphQL endpoint: http://localhost:8000/graphql")
    print("🎛️  GraphiQL: http://localhost:8000/graphiql")
    print("📚 API docs: http://localhost:8000/docs")
    print()
    print("Example mutation:")
    print("""
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        id
        message
        cascade {
          updated {
            __typename
            id
            operation
            entity
          }
          invalidations {
            queryName
            strategy
            scope
          }
          metadata {
            timestamp
            affectedCount
          }
        }
      }
    }
    """)
    print('Variables: { "input": { "title": "Hello World", "author_id": "<user-id>" } }')

    uvicorn.run(app, host="0.0.0.0", port=8000)
