"""Blog domain models with Trinity Identifiers for FraiseQL example.

This module demonstrates FraiseQL with Trinity pattern:
- Three-tier ID system (pk_*, id, identifier)
- Type definitions with Trinity support
- SERIAL foreign keys for faster joins
- GraphQL exposes only id and identifier (not pk_*)
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from graphql import GraphQLResolveInfo

import fraiseql
from fraiseql.db import DatabaseQuery
from fraiseql.patterns import TrinityMixin, get_pk_column_name
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


# Core domain types with Trinity
@fraiseql.type(sql_source="v_users", jsonb_column=None)
class User(TrinityMixin):
    """User with profile and Trinity identifiers.

    Trinity IDs:
    - pk_user (SERIAL): Internal, fast joins (not exposed)
    - id (UUID): Public API, secure
    - identifier (TEXT): URL slug (@username)
    """

    # Public Trinity IDs (exposed in GraphQL)
    id: ID
    identifier: str | None  # @username

    # User data
    username: str
    email: str
    role: UserRole
    created_at: datetime
    updated_at: datetime
    profile_data: dict[str, Any] | None

    @fraiseql.field
    async def full_name(self, info: GraphQLResolveInfo) -> str | None:
        """Full name from profile data."""
        if self.profile_data:
            first = self.profile_data.get("first_name", "")
            last = self.profile_data.get("last_name", "")
            if first or last:
                return f"{first} {last}".strip()
        return None

    @fraiseql.field
    async def url(self, info: GraphQLResolveInfo) -> str:
        """User profile URL."""
        return f"/users/{self.identifier}" if self.identifier else f"/users/{self.id}"


@fraiseql.type(sql_source="v_posts", jsonb_column=None)
class Post(TrinityMixin):
    """Blog post with Trinity identifiers.

    Trinity IDs:
    - pk_post (SERIAL): Internal, fast joins (not exposed)
    - id (UUID): Public API, secure
    - identifier (TEXT): URL slug (post-title)

    Foreign Keys:
    - fk_author (SERIAL): Fast join to users
    """

    # Public Trinity IDs (exposed in GraphQL)
    id: ID
    identifier: str | None  # post-slug

    # Post data
    title: str
    slug: str
    content: str
    excerpt: str | None
    status: PostStatus
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    author_id: ID  # ✅ UUID relationship from view

    @fraiseql.field
    async def author(self, info: GraphQLResolveInfo) -> User:
        """Post author resolved via UUID from view."""
        db = info.context["db"]
        # ✅ View exposes author_id (UUID) - no pk_ mapping needed
        return await db.find_one("v_users", id=self.author_id)

    @fraiseql.field
    async def url(self, info: GraphQLResolveInfo) -> str:
        """Post URL."""
        return f"/posts/{self.identifier}" if self.identifier else f"/posts/{self.id}"

    @fraiseql.field
    async def comment_count(self, info: GraphQLResolveInfo) -> int:
        """Number of approved comments."""
        db = info.context["db"]

        # ✅ CORRECT: Use UUID with JOIN (no pk_ exposure)
        query = DatabaseQuery(
            """
            SELECT COUNT(*) as count FROM comments c
            JOIN posts p ON c.fk_post = p.pk_post
            WHERE p.id = %s AND c.status = %s
            """,
            [str(self.id), CommentStatus.APPROVED.value],
        )
        result = await db.run(query)
        return result[0]["count"] if result else 0


@fraiseql.type(sql_source="v_comments", jsonb_column=None)
class Comment(TrinityMixin):
    """Comment with Trinity identifiers.

    Trinity IDs:
    - pk_comment (SERIAL): Internal, fast joins (not exposed)
    - id (UUID): Public API, secure

    Foreign Keys:
    - fk_post (SERIAL): Fast join to posts
    - fk_author (SERIAL): Fast join to users
    - fk_parent (SERIAL): Fast join to parent comment
    """

    # Public Trinity IDs (exposed in GraphQL)
    id: ID

    # Comment data
    content: str
    status: CommentStatus
    created_at: datetime
    updated_at: datetime
    post_id: ID  # ✅ UUID relationship from view
    author_id: ID  # ✅ UUID relationship from view
    parent_id: ID | None  # ✅ UUID relationship from view

    @fraiseql.field
    async def author(self, info: GraphQLResolveInfo) -> User:
        """Comment author resolved via UUID from view."""
        db = info.context["db"]
        # ✅ View exposes author_id (UUID) - no pk_ mapping needed
        return await db.find_one("v_users", id=self.author_id)

    @fraiseql.field
    async def post(self, info: GraphQLResolveInfo) -> Post:
        """Comment's post resolved via UUID from view."""
        db = info.context["db"]
        # ✅ View exposes post_id (UUID) - no pk_ mapping needed
        return await db.find_one("v_posts", id=self.post_id)


@fraiseql.type(sql_source="v_tags", jsonb_column=None)
class Tag(TrinityMixin):
    """Content tag with Trinity identifiers.

    Trinity IDs:
    - pk_tag (SERIAL): Internal, fast joins (not exposed)
    - id (UUID): Public API, secure
    - identifier (TEXT): URL slug (tag-name)
    """

    # Public Trinity IDs (exposed in GraphQL)
    id: ID
    identifier: str | None  # tag-slug

    # Tag data
    name: str
    slug: str
    color: str | None
    description: str | None

    @fraiseql.field
    async def url(self, info: GraphQLResolveInfo) -> str:
        """Tag URL."""
        return f"/tags/{self.identifier}" if self.identifier else f"/tags/{self.id}"

    @fraiseql.field
    async def post_count(self, info: GraphQLResolveInfo) -> int:
        """Number of published posts with this tag."""
        db = info.context["db"]

        # ✅ CORRECT: Use UUID with JOIN (no pk_ exposure)
        query = DatabaseQuery(
            """
            SELECT COUNT(*) as count FROM posts p
            JOIN post_tags pt ON p.pk_post = pt.pk_post
            JOIN tags t ON pt.fk_tag = t.pk_tag
            WHERE t.id = %s AND p.status = %s
            """,
            [str(self.id), PostStatus.PUBLISHED.value],
        )
        result = await db.run(query)
        return result[0]["count"] if result else 0


# Input types
@fraiseql.input
class CreatePostInput:
    """Input for creating a blog post."""

    title: str
    content: str
    excerpt: str | None = None
    tag_ids: list[UUID] | None = None


@fraiseql.input
class UpdatePostInput:
    """Input for updating a blog post."""

    title: str | None = None
    content: str | None = None
    excerpt: str | None = None
    status: PostStatus | None = None
    tag_ids: list[UUID] | None = None


@fraiseql.input
class CreateCommentInput:
    """Input for creating a comment."""

    post_id: ID  # Public UUID (will be converted to fk_post)
    content: str
    parent_id: ID | None = None  # Public UUID (will be converted to fk_parent)


@fraiseql.input
class CreateTagInput:
    """Input for creating a tag."""

    name: str
    color: str | None = "#6366f1"
    description: str | None = None


@fraiseql.input
class CreateUserInput:
    """Input for creating a user."""

    username: str
    email: str
    password: str
    role: UserRole = UserRole.USER
    profile_data: dict[str, Any] | None = None


# Success result types
@fraiseql.success
class CreatePostSuccess:
    """Success response for post creation."""

    post: Post
    message: str = "Post created successfully"


@fraiseql.success
class UpdatePostSuccess:
    """Success response for post update."""

    post: Post
    message: str = "Post updated successfully"


@fraiseql.success
class CreateCommentSuccess:
    """Success response for comment creation."""

    comment: Comment
    message: str = "Comment created successfully"


@fraiseql.success
class CreateTagSuccess:
    """Success response for tag creation."""

    tag: Tag
    message: str = "Tag created successfully"


@fraiseql.success
class CreateUserSuccess:
    """Success response for user creation."""

    user: User
    message: str = "User created successfully"


# Error result types
@fraiseql.error
class ValidationError:
    """Validation error with details."""

    message: str
    code: str = "VALIDATION_ERROR"
    # Note: errors array is now auto-populated by FraiseQL from status strings
    # For explicit validation errors, use metadata.errors in your PostgreSQL function


@fraiseql.error
class NotFoundError:
    """Entity not found error."""

    message: str
    code: str = "NOT_FOUND"
    entity_type: str | None = None
    entity_id: ID | None = None


@fraiseql.error
class PermissionError:
    """Permission denied error."""

    message: str
    code: str = "PERMISSION_DENIED"
    required_role: str | None = None


# Mutations: fraiseql calls the SQL function create_post with the input as one
# jsonb, and turns the mutation_response it returns into CreatePostSuccess or
# ValidationError. db/setup.sql doesn't define create_post yet.
@fraiseql.mutation
class CreatePost:
    """Create a new blog post."""

    input: CreatePostInput
    success: CreatePostSuccess
    error: ValidationError


# Query resolvers
@fraiseql.query
async def posts(
    info: GraphQLResolveInfo,
    status: PostStatus | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Post]:
    """Query posts with filtering and pagination."""
    db = info.context["db"]

    # Build filters
    filters = {}
    if status:
        filters["status"] = status.value

    # Use FraiseQL repository - handles JSONB extraction and type instantiation
    return await db.find(
        "v_posts", "posts", info, limit=limit, offset=offset, order_by="created_at DESC", **filters
    )


@fraiseql.query
async def post(
    info: GraphQLResolveInfo,
    id: ID | None = None,
    identifier: str | None = None,
) -> Post | None:
    """Get a single post by UUID id or text identifier."""
    db = info.context["db"]

    if id:
        result = await db.find_one("v_posts", id=id)
    elif identifier:
        result = await db.find_one("v_posts", identifier=identifier)
    else:
        return None

    return result


@fraiseql.query
async def user(
    info: GraphQLResolveInfo,
    id: ID | None = None,
    identifier: str | None = None,
) -> User | None:
    """Get a single user by UUID id or text identifier."""
    db = info.context["db"]

    if id:
        result = await db.find_one("v_users", id=id)
    elif identifier:
        result = await db.find_one("v_users", identifier=identifier)
    else:
        return None

    return result


@fraiseql.query
async def tag(
    info: GraphQLResolveInfo,
    id: ID | None = None,
    identifier: str | None = None,
) -> Tag | None:
    """Get a single tag by UUID id or text identifier."""
    db = info.context["db"]

    if id:
        result = await db.find_one("v_tags", id=id)
    elif identifier:
        result = await db.find_one("v_tags", identifier=identifier)
    else:
        return None

    return result


@fraiseql.query
async def tags(info: GraphQLResolveInfo, limit: int = 50) -> list[Tag]:
    """Get all tags."""
    db = info.context["db"]
    result = await db.find("v_tags", limit=limit, order_by="name ASC")
    return result


@fraiseql.query
async def users(info: GraphQLResolveInfo, limit: int = 20) -> list[User]:
    """Get users (admin only)."""
    db = info.context["db"]
    result = await db.find("v_users", limit=limit, order_by="created_at DESC")
    return result


# Export collections for app registration
BLOG_TYPES = [User, Post, Comment, Tag, UserRole, PostStatus, CommentStatus]
BLOG_MUTATIONS = [CreatePost]
BLOG_QUERIES = [posts, post, user, tag, tags, users]
