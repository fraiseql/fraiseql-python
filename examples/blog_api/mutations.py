"""Blog API mutations demonstrating FraiseQL enterprise patterns.

This example showcases enterprise-grade patterns:
- Mutation Result Pattern for standardized responses
- NOOP Handling for idempotent operations
- App/Core Function Split for clean architecture
- Comprehensive validation and error handling

For simpler patterns, see ../todo_quickstart.py
For complete enterprise example, see ../enterprise_patterns/
"""

import hashlib
from typing import TYPE_CHECKING
from uuid import UUID

from models import (
    AuditTrail,
    Comment,
    CreateCommentInput,
    CreatePostError,
    CreatePostInput,
    CreatePostNoop,
    CreatePostSuccess,
    CreateUserError,
    CreateUserInput,
    CreateUserNoop,
    CreateUserSuccess,
    Post,
    UpdatePostError,
    UpdatePostInput,
    UpdatePostNoop,
    UpdatePostSuccess,
    User,
)

import fraiseql
from fraiseql.types import ID
from fraiseql.auth import requires_auth, requires_permission

if TYPE_CHECKING:
    from db import BlogRepository


async def create_user(
    info,
    input: CreateUserInput,
) -> CreateUserSuccess | CreateUserError:
    """Create a new user account using CQRS SQL function."""
    db: BlogRepository = info.context["db"]

    # Check if email already exists
    existing_user = await db.get_user_by_email(input.email)

    if existing_user:
        return CreateUserError(
            message="Email already registered",
            code="EMAIL_EXISTS",
            field_errors={"email": "This email is already in use"},
        )

    # Hash password (in real app, use proper password hashing)
    password_hash = hashlib.sha256(input.password.encode()).hexdigest()

    # Call SQL function to create user
    result = await db.create_user(
        {
            "email": input.email,
            "name": input.name,
            "bio": input.bio,
            "avatar_url": input.avatar_url,
            "password_hash": password_hash,
        },
    )

    if not result["success"]:
        return CreateUserError(
            message=result.get("error", "Failed to create user"),
            code="CREATE_FAILED",
        )

    # Fetch the created user from the view
    user_data = await db.get_user_by_id(UUID(result["user_id"]))

    if not user_data:
        return CreateUserError(
            message="User created but could not be retrieved",
            code="RETRIEVAL_ERROR",
        )

    # Convert to User model using automatic from_dict
    user = User.from_dict(user_data)
    return CreateUserSuccess(user=user)


@requires_auth
async def create_post(
    info,
    input: CreatePostInput,
) -> CreatePostSuccess | CreatePostError:
    """Create a new blog post using CQRS SQL function."""
    db: BlogRepository = info.context["db"]
    user = info.context["user"]

    # Call SQL function to create post
    result = await db.create_post(
        {
            "author_id": user.user_id,
            "title": input.title,
            "content": input.content,
            "excerpt": input.excerpt,
            "tags": input.tags or [],
            "is_published": input.is_published,
        },
    )

    if not result["success"]:
        return CreatePostError(
            message=result.get("error", "Failed to create post"),
            code="CREATE_FAILED",
        )

    # Fetch the created post from the view
    post_data = await db.get_post_by_id(UUID(result["post_id"]))

    if not post_data:
        return CreatePostError(
            message="Post created but could not be retrieved",
            code="RETRIEVAL_ERROR",
        )

    # Convert to Post model using automatic from_dict
    post = Post.from_dict(post_data)
    return CreatePostSuccess(post=post)


@requires_auth
async def update_post(
    info,
    id: ID,
    input: UpdatePostInput,
) -> UpdatePostSuccess | UpdatePostError:
    """Update an existing blog post using CQRS SQL function."""
    db: BlogRepository = info.context["db"]
    user = info.context["user"]

    # Fetch existing post to check ownership
    post_data = await db.get_post_by_id(id)

    if not post_data:
        return UpdatePostError(message="Post not found", code="NOT_FOUND")

    # Check ownership (unless admin)
    if post_data["authorId"] != user.user_id and "admin" not in user.roles:
        return UpdatePostError(
            message="You can only edit your own posts",
            code="FORBIDDEN",
        )

    # Build update data
    update_data = {"id": str(id)}
    updated_fields = []

    if input.title is not None:
        update_data["title"] = input.title
        updated_fields.append("title")

    if input.content is not None:
        update_data["content"] = input.content
        updated_fields.append("content")

    if input.excerpt is not None:
        update_data["excerpt"] = input.excerpt
        updated_fields.append("excerpt")

    if input.tags is not None:
        update_data["tags"] = input.tags
        updated_fields.append("tags")

    if input.is_published is not None:
        update_data["is_published"] = input.is_published
        updated_fields.append("is_published")

    if not updated_fields:
        return UpdatePostError(message="No fields to update", code="NO_CHANGES")

    # Call SQL function to update post
    result = await db.update_post(update_data)

    if not result["success"]:
        return UpdatePostError(
            message=result.get("error", "Failed to update post"),
            code="UPDATE_FAILED",
        )

    # Fetch updated post from view
    updated_post_data = await db.get_post_by_id(id)

    if not updated_post_data:
        return UpdatePostError(
            message="Post updated but could not be retrieved",
            code="RETRIEVAL_ERROR",
        )

    # Convert to Post model using automatic from_dict
    post = Post.from_dict(updated_post_data)
    return UpdatePostSuccess(post=post, updated_fields=updated_fields)


@requires_auth
async def create_comment(info, input: CreateCommentInput) -> Comment:
    """Create a comment on a post using CQRS SQL function."""
    db: BlogRepository = info.context["db"]
    user = info.context["user"]

    # Verify post exists
    post_data = await db.get_post_by_id(input.post_id)

    if not post_data:
        raise ValueError("Post not found")

    # Call SQL function to create comment
    result = await db.create_comment(
        {
            "post_id": str(input.post_id),
            "author_id": user.user_id,
            "content": input.content,
            "parent_id": str(input.parent_comment_id) if input.parent_comment_id else None,
        },
    )

    if not result["success"]:
        raise ValueError(result.get("error", "Failed to create comment"))

    # Fetch created comment from view
    comments_data = await db.get_comments_by_post(input.post_id)

    # Find the comment we just created
    comment_data = next(
        (c for c in comments_data if c["id"] == result["comment_id"]),
        None,
    )

    if not comment_data:
        raise ValueError("Comment created but could not be retrieved")

    # Convert to Comment model using automatic from_dict
    return Comment.from_dict(comment_data)


@requires_permission("admin")
async def delete_post(info, id: ID) -> bool:
    """Delete a post (admin only) using CQRS SQL function."""
    db: BlogRepository = info.context["db"]

    # Call SQL function to delete post
    result = await db.delete_post(id)

    return result["success"]


# Enterprise Pattern Examples
# These demonstrate the new FraiseQL enterprise mutation patterns


# Uses app/core split
@fraiseql.mutation(
    name="createPostEnterprise",
    function="create_post",
    schema="app",
    result_name="CreatePostEnterpriseResult",
)
class CreatePostEnterprise:
    """Create blog post with enterprise patterns.

    This shows the new mutation result pattern with:
    - Standardized success/error/noop responses
    - App/core function split architecture
    - Comprehensive audit information
    - NOOP handling for duplicate slugs
    """

    input: CreatePostInput
    success: CreatePostSuccess
    error: CreatePostError
    noop: CreatePostNoop  # For duplicate handling


@fraiseql.mutation(
    name="updatePostEnterprise",
    function="update_post",
    schema="app",
    result_name="UpdatePostEnterpriseResult",
)
class UpdatePostEnterprise:
    """Update blog post with change tracking.

    Enterprise features:
    - Field-level change detection
    - Optimistic locking with version checks
    - NOOP for no-changes scenarios
    - Complete audit trail
    """

    input: UpdatePostInput
    success: UpdatePostSuccess
    error: UpdatePostError
    noop: UpdatePostNoop  # For no-changes scenarios


@fraiseql.mutation(
    name="createUserEnterprise",
    function="create_user",
    schema="app",
    result_name="CreateUserEnterpriseResult",
)
class CreateUserEnterprise:
    """Create user with validation and NOOP handling.

    Demonstrates:
    - Multi-layer validation (GraphQL + app + core)
    - NOOP for duplicate emails
    - Structured error responses with field context
    - Audit trail creation
    """

    input: CreateUserInput
    success: CreateUserSuccess
    error: CreateUserError
    noop: CreateUserNoop  # For duplicate emails


# Legacy Pattern Examples (for comparison)
# Note: These show the old way. Use Enterprise classes above for new code.


async def create_post_legacy(
    info,
    input: CreatePostInput,
) -> CreatePostSuccess | CreatePostError:
    """Legacy pattern - for comparison only.

    This shows the old resolver-based approach.
    Compare with CreatePostEnterprise above to see the difference.

    New code should use the @fraiseql.mutation class decorators instead.
    """
    # Implementation remains the same as create_post function above
