"""Blog API models demonstrating audit patterns."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field

import fraiseql
from fraiseql.types import ID


@fraiseql.type
class User:
    """User type for blog application.

    Fields:
        id: Unique identifier for the user
        email: User's email address
        name: User's display name
        bio: User's biography or description
        avatar_url: URL to user's profile picture
        created_at: When the user account was created
        updated_at: When the user account was last updated
        is_active: Whether the user account is active
        roles: List of roles assigned to the user
    """

    id: ID
    identifier: str  # Human-readable username (from JSONB)
    email: str
    name: str
    bio: str | None
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime
    is_active: bool = True
    roles: list[str] = []


@fraiseql.type
class Comment:
    """Comment on a blog post.

    Fields:
        id: Unique identifier for the comment
        post_id: ID of the post this comment belongs to
        author_id: ID of the user who wrote the comment
        content: Comment text content
        created_at: When the comment was created
        updated_at: When the comment was last updated
        is_approved: Whether the comment has been approved for display
        parent_comment_id: ID of parent comment (for nested replies)
    """

    id: ID
    post_id: ID
    author_id: ID
    content: str
    created_at: datetime
    updated_at: datetime
    is_approved: bool = True
    parent_comment_id: ID | None = None  # For nested comments


@fraiseql.type
class Post:
    """Blog post type.

    Fields:
        id: Unique identifier for the post
        title: Post title
        slug: URL-friendly identifier for the post
        content: Full post content in Markdown format
        excerpt: Short description or summary of the post
        author_id: ID of the user who authored the post
        published_at: When the post was published (null for drafts)
        created_at: When the post was created
        updated_at: When the post was last updated
        tags: List of tags associated with the post
        is_published: Whether the post is published or draft
        view_count: Number of times the post has been viewed
        comments: List of comments on this post
    """

    id: ID
    title: str
    slug: str
    content: str
    excerpt: str | None
    author_id: ID
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    tags: list[str] = []
    is_published: bool = False
    view_count: int = 0
    comments: list["Comment"] = []


# Enterprise Pattern Types


@fraiseql.type
class AuditTrail:
    """Comprehensive audit information."""

    created_at: datetime
    created_by_name: str | None = None
    updated_at: datetime | None = None
    updated_by_name: str | None = None
    version: int
    change_reason: str | None = None
    updated_fields: list[str | None] = None


# Enhanced types with audit trails (enterprise pattern examples)


@fraiseql.type
class PostEnterprise:
    """Blog post with audit trail - enterprise pattern example."""

    id: ID
    title: str
    content: str
    is_published: bool

    # Enterprise features
    audit_trail: AuditTrail
    identifier: str | None = None  # Business identifier
    slug: str
    excerpt: str | None = None
    author_id: ID
    published_at: datetime | None = None
    tags: list[str] = []
    view_count: int = 0


@fraiseql.type
class UserEnterprise:
    """User with comprehensive audit trail."""

    id: ID
    email: str
    name: str
    bio: str | None = None
    avatar_url: str | None = None
    is_active: bool = True
    roles: list[str] = []

    # Enterprise audit features
    audit_trail: AuditTrail
    identifier: str | None = None  # Business identifier


# Input types for mutations


@fraiseql.input
class CreateUserInput:
    """Input for creating a new user.

    Args:
        email: User's email address (must be unique)
        name: User's display name
        password: User's password (will be hashed)
        bio: Optional biography for the user
        avatar_url: Optional URL to user's profile picture
    """

    email: str
    name: str
    password: str
    bio: str | None = None
    avatar_url: str | None = None


@fraiseql.input
class CreateUserInputEnterprise:
    """Post creation input with validation - enterprise pattern example."""

    email: Annotated[str, Field(pattern=r"^[^@]+@[^@]+\.[^@]+$")]
    name: Annotated[str, Field(min_length=2, max_length=100)]
    password: Annotated[str, Field(min_length=8)]
    bio: Annotated[str | None, Field(max_length=500)] = None
    avatar_url: str | None = None

    # Audit metadata
    _change_reason: str | None = None
    _expected_version: int | None = None


@fraiseql.input
class UpdateUserInput:
    """Input for updating user profile.

    Args:
        name: New display name for the user
        bio: New biography for the user
        avatar_url: New avatar URL for the user
        is_active: New active status for the user
    """

    name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    is_active: bool | None = None


@fraiseql.input
class CreatePostInput:
    """Input for creating a new post.

    Args:
        title: Title of the blog post
        content: Full content of the post in Markdown
        excerpt: Optional short summary of the post
        tags: Optional list of tags for the post
        is_published: Whether to publish immediately or save as draft
    """

    title: str
    content: str
    excerpt: str | None = None
    tags: list[str] | None = None
    is_published: bool = False


@fraiseql.input
class CreatePostInputEnterprise:
    """Post creation input with validation - enterprise pattern example."""

    title: Annotated[str, Field(min_length=3, max_length=200)]
    content: Annotated[str, Field(min_length=50)]
    is_published: bool = False
    excerpt: Annotated[str | None, Field(max_length=300)] = None
    tags: list[str | None] = None

    # Audit metadata
    _change_reason: str | None = None
    _expected_version: int | None = None


@fraiseql.input
class UpdatePostInput:
    """Input for updating a post.

    Args:
        title: New title for the post
        content: New content for the post
        excerpt: New excerpt for the post
        tags: New tags for the post
        is_published: New published status for the post
    """

    title: str | None = None
    content: str | None = None
    excerpt: str | None = None
    tags: list[str] | None = None
    is_published: bool | None = None


@fraiseql.input
class CreateCommentInput:
    """Input for creating a comment.

    Args:
        post_id: ID of the post to comment on
        content: Comment text content
        parent_comment_id: ID of parent comment (for replies)
    """

    post_id: ID
    content: str
    parent_comment_id: ID | None = None


@fraiseql.input
class PostFilters:
    """Filters for querying posts.

    Args:
        author_id: Filter posts by specific author
        is_published: Filter by published status (true for published, false for drafts)
        tags_contain: Filter posts that contain any of these tags
        created_after: Filter posts created after this date
        created_before: Filter posts created before this date
        search: Search in post title and content
    """

    author_id: ID | None = None
    is_published: bool | None = None
    tags_contain: list[str] | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    search: str | None = None  # Search in title and content


@fraiseql.input
class PostOrderBy:
    """Ordering options for posts.

    Args:
        field: Field to order by (created_at, updated_at, title, view_count)
        direction: Sort direction (asc or desc)
    """

    field: str  # created_at, updated_at, title, view_count
    direction: str = "desc"  # asc or desc


# Result types for mutations


@fraiseql.success
class CreateUserSuccess:
    """Successful user creation result."""

    user: User
    message: str = "User created successfully"


@fraiseql.error
class CreateUserError:
    """Failed user creation result."""

    message: str
    code: str
    field_errors: dict[str, str] | None = None


@fraiseql.success
class CreatePostSuccess:
    """Successful post creation result."""

    post: Post
    message: str = "Post created successfully"


@fraiseql.error
class CreatePostError:
    """Failed post creation result."""

    message: str
    code: str
    field_errors: dict[str, str] | None = None


@fraiseql.success
class UpdatePostSuccess:
    """Successful post update result."""

    post: Post
    message: str = "Post updated successfully"
    updated_fields: list[str]


@fraiseql.error
class UpdatePostError:
    """Failed post update result."""

    message: str
    code: str


# Enhanced Success Types with Audit Information


@fraiseql.success
class CreateUserSuccessEnterprise:
    """User created successfully with audit trail."""

    user: UserEnterprise
    message: str = "User created successfully"
    was_noop: bool = False
    audit_metadata: dict[str, Any | None] = None


@fraiseql.success
class CreatePostSuccessEnterprise:
    """Post created successfully with audit trail."""

    post: PostEnterprise
    message: str = "Post created successfully"
    was_noop: bool = False
    generated_slug: str | None = None
    audit_metadata: dict[str, Any | None] = None


@fraiseql.success
class UpdatePostSuccessEnterprise:
    """Post updated successfully with change tracking."""

    post: PostEnterprise
    message: str = "Post updated successfully"
    updated_fields: list[str]
    previous_version: int
    new_version: int
    audit_metadata: dict[str, Any | None] = None


# Enhanced Error Types with Validation Context


@fraiseql.error
class CreateUserErrorEnterprise:
    """User creation failed with detailed context."""

    message: str
    error_code: str
    field_errors: dict[str, str | None] = None
    validation_context: dict[str, Any | None] = None
    conflicting_user: User | None = None


@fraiseql.error
class CreatePostErrorEnterprise:
    """Post creation failed with detailed context."""

    message: str
    error_code: str
    field_errors: dict[str, str | None] = None
    validation_context: dict[str, Any | None] = None
    conflicting_post: Post | None = None
