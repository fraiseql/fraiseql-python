"""Blog domain: types, queries and mutations.

Every type reads the data JSONB column of its view in db/setup.sql. A post's
data embeds its author, tags and approved comments, so a query such as
``posts { title author { username } tags { name } }`` is one SQL query.

The tables use the Trinity pattern (pk_* integer keys for joins, a public UUID
id, a human-readable identifier); only id and identifier reach GraphQL.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from graphql import GraphQLResolveInfo

import fraiseql
from fraiseql.types import ID


# Domain enums
@fraiseql.enum
class UserRole(str, Enum):
    """User roles in the blog system."""

    ADMIN = "admin"
    AUTHOR = "author"
    USER = "user"


@fraiseql.enum
class PostStatus(str, Enum):
    """Post publication status."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


@fraiseql.enum
class CommentStatus(str, Enum):
    """Comment moderation status."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# Types
@fraiseql.type(sql_source="v_user")
class User:
    """A user. identifier is the username."""

    id: ID
    identifier: str
    username: str
    email: str
    role: UserRole
    full_name: str | None
    profile_data: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


@fraiseql.type(sql_source="v_tag")
class Tag:
    """A content tag. identifier is the slug."""

    id: ID
    identifier: str
    name: str
    slug: str
    color: str | None
    description: str | None


@fraiseql.type(sql_source="v_comment")
class Comment:
    """A comment on a post, possibly a reply to another comment."""

    id: ID
    content: str
    status: CommentStatus
    post_id: ID
    parent_id: ID | None
    author: User
    created_at: datetime
    updated_at: datetime


@fraiseql.type(sql_source="v_post")
class Post:
    """A blog post with its author, tags and approved comments."""

    id: ID
    identifier: str
    slug: str
    title: str
    content: str
    excerpt: str | None
    status: PostStatus
    published_at: datetime | None
    author: User
    tags: list[Tag]
    comments: list[Comment]
    created_at: datetime
    updated_at: datetime


# Queries
#
# A query returning a list gets fraiseql's where, orderBy, limit and offset
# arguments. Declare them and pass them on to db.find, or they are ignored.


@fraiseql.query
async def posts(
    info: GraphQLResolveInfo,
    where=None,
    order_by=None,
    limit: int | None = 20,
    offset: int | None = None,
) -> list[Post]:
    """List posts, newest first unless orderBy says otherwise."""
    db = info.context["db"]
    return await db.find(
        "v_post",
        "posts",
        info,
        where=where,
        order_by=order_by or {"created_at": "DESC"},
        limit=limit,
        offset=offset,
    )


@fraiseql.query
async def post(
    info: GraphQLResolveInfo, id: ID | None = None, identifier: str | None = None
) -> Post | None:
    """Get a post by id or by slug."""
    if id is None and identifier is None:
        return None
    filters = {"id": id} if id is not None else {"identifier": identifier}
    return await info.context["db"].find_one("v_post", "post", info, mandatory_filters=filters)


@fraiseql.query
async def users(
    info: GraphQLResolveInfo,
    where=None,
    order_by=None,
    limit: int | None = 20,
    offset: int | None = None,
) -> list[User]:
    """List users."""
    db = info.context["db"]
    return await db.find(
        "v_user", "users", info, where=where, order_by=order_by, limit=limit, offset=offset
    )


@fraiseql.query
async def user(
    info: GraphQLResolveInfo, id: ID | None = None, identifier: str | None = None
) -> User | None:
    """Get a user by id or by username."""
    if id is None and identifier is None:
        return None
    filters = {"id": id} if id is not None else {"identifier": identifier}
    return await info.context["db"].find_one("v_user", "user", info, mandatory_filters=filters)


@fraiseql.query
async def tags(
    info: GraphQLResolveInfo,
    where=None,
    order_by=None,
    limit: int | None = 50,
    offset: int | None = None,
) -> list[Tag]:
    """List tags, by name unless orderBy says otherwise."""
    db = info.context["db"]
    return await db.find(
        "v_tag",
        "tags",
        info,
        where=where,
        order_by=order_by or {"name": "ASC"},
        limit=limit,
        offset=offset,
    )


@fraiseql.query
async def tag(
    info: GraphQLResolveInfo, id: ID | None = None, identifier: str | None = None
) -> Tag | None:
    """Get a tag by id or by slug."""
    if id is None and identifier is None:
        return None
    filters = {"id": id} if id is not None else {"identifier": identifier}
    return await info.context["db"].find_one("v_tag", "tag", info, mandatory_filters=filters)


# Mutation inputs
@fraiseql.input
class CreatePostInput:
    """Input for creating a post. New posts are drafts."""

    title: str
    content: str
    excerpt: str | None = None
    tag_ids: list[UUID] | None = None


@fraiseql.input
class UpdatePostInput:
    """Input for updating a post. Omitted fields keep their value."""

    id: ID
    title: str | None = None
    content: str | None = None
    excerpt: str | None = None
    status: PostStatus | None = None
    tag_ids: list[UUID] | None = None


@fraiseql.input
class CreateCommentInput:
    """Input for commenting on a published post."""

    post_id: ID
    content: str
    parent_id: ID | None = None


@fraiseql.input
class CreateTagInput:
    """Input for creating a tag."""

    name: str
    color: str | None = None
    description: str | None = None


# Mutation results
#
# The SQL function's mutation_response picks the result: a 'created' or
# 'updated' status returns the success type, whose field gets the entity; a
# 'validation:', 'forbidden:', 'not_found:' or 'conflict:' status returns the
# error type. fraiseql adds status, message and the other standard fields.


@fraiseql.success
class PostSuccess:
    """The created or updated post."""

    post: Post


@fraiseql.success
class CreateCommentSuccess:
    """The new comment."""

    comment: Comment


@fraiseql.success
class CreateTagSuccess:
    """The new tag."""

    tag: Tag


@fraiseql.error
class BlogError:
    """status, message and code come from the function's mutation_response."""


# Mutations
#
# Each class mutation calls the SQL function named after it in db/setup.sql
# (CreatePost calls create_post). context_params passes the caller's user id
# from the GraphQL context as the function's first argument.

_AUTHOR = {"user_id": "p_user_id"}


@fraiseql.mutation(context_params=_AUTHOR)
class CreatePost:
    """Create a draft post written by the current user."""

    input: CreatePostInput
    success: PostSuccess
    error: BlogError


@fraiseql.mutation(context_params=_AUTHOR)
class UpdatePost:
    """Update a post. Only its author can."""

    input: UpdatePostInput
    success: PostSuccess
    error: BlogError


@fraiseql.mutation(context_params=_AUTHOR)
class CreateComment:
    """Comment on a published post. New comments wait for moderation."""

    input: CreateCommentInput
    success: CreateCommentSuccess
    error: BlogError


@fraiseql.mutation
class CreateTag:
    """Create a tag."""

    input: CreateTagInput
    success: CreateTagSuccess
    error: BlogError


# Collections for create_fraiseql_app
BLOG_TYPES = [User, Post, Comment, Tag, UserRole, PostStatus, CommentStatus]
BLOG_QUERIES = [posts, post, users, user, tags, tag]
BLOG_MUTATIONS = [CreatePost, UpdatePost, CreateComment, CreateTag]
