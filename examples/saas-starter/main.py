#!/usr/bin/env python
"""SaaS Starter Template - Main Application.

Multi-tenant SaaS application: organizations (tenants), their users and their
projects. Every query and mutation is scoped to the caller's organization.

The tenant and the user come from the X-Organization-ID and X-User-ID headers;
replace get_context with your authentication (a JWT, a session) in production.
"""

import os
from uuid import UUID

import uvicorn
from fastapi import Request
from models import (
    Organization,
    OrganizationUpdateInput,
    Project,
    ProjectCreateInput,
    ProjectUpdateInput,
    User,
)

import fraiseql
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.types import ID

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/saas_starter")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

# Demo tenant and user from schema.sql's sample data
DEMO_ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"
DEMO_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


async def get_context(request: Request) -> dict:
    """Add the caller's tenant and user to the GraphQL context.

    fraiseql merges this into its default context (which holds the database).
    In production, take both from a verified token instead of headers.
    """
    return {
        "organization_id": UUID(request.headers.get("X-Organization-ID", DEMO_ORGANIZATION_ID)),
        "user_id": UUID(request.headers.get("X-User-ID", DEMO_USER_ID)),
    }


# ============================================================================
# QUERIES
# ============================================================================


@fraiseql.query
async def current_organization(info) -> Organization | None:
    """Get current user's organization."""
    db = info.context["db"]
    return await db.find_one(
        "v_organization",
        "currentOrganization",
        info,
        mandatory_filters={"id": info.context["organization_id"]},
    )


@fraiseql.query
async def current_user(info) -> User | None:
    """Get current authenticated user."""
    db = info.context["db"]
    return await db.find_one(
        "v_user",
        "currentUser",
        info,
        mandatory_filters={
            "id": info.context["user_id"],
            "organization_id": info.context["organization_id"],
        },
    )


@fraiseql.query
async def team_members(
    info, where=None, order_by=None, limit: int | None = None, offset: int | None = None
) -> list[User]:
    """Get the team members of the current organization.

    where, order_by, limit and offset are the arguments fraiseql adds to a list
    query; the tenant filter applies whatever they are.
    """
    db = info.context["db"]
    return await db.find(
        "v_user",
        "teamMembers",
        info,
        mandatory_filters={"organization_id": info.context["organization_id"]},
        where=where,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )


@fraiseql.query
async def projects(
    info, where=None, order_by=None, limit: int = 50, offset: int | None = None
) -> list[Project]:
    """Get the projects of the current organization."""
    db = info.context["db"]
    return await db.find(
        "v_project",
        "projects",
        info,
        mandatory_filters={"organization_id": info.context["organization_id"]},
        where=where,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )


@fraiseql.query
async def project(info, id: ID) -> Project | None:
    """Get a project of the current organization by ID."""
    db = info.context["db"]
    # Scoped to the tenant: another organization's project is not found
    return await db.find_one(
        "v_project",
        "project",
        info,
        mandatory_filters={"id": id, "organization_id": info.context["organization_id"]},
    )


# ============================================================================
# MUTATIONS
# ============================================================================
#
# Each class mutation calls the SQL function named after it (CreateProject calls
# create_project) with the context params first, then the input as one jsonb.
# The functions in schema.sql check the tenant, write, track usage, log the
# activity, and return a mutation_response.

_TENANT_AND_USER = {"organization_id": "p_organization_id", "user_id": "p_user_id"}


@fraiseql.input
class DeleteProjectInput:
    id: ID


@fraiseql.success
class ProjectSuccess:
    project: Project


@fraiseql.success
class DeleteProjectSuccess:
    # Filled from the mutation_response's entity_id. @fraiseql.success adds id
    # only to a type with an entity field, and this one has none.
    id: ID | None = None


@fraiseql.success
class UpdateOrganizationSuccess:
    organization: Organization


@fraiseql.error
class SaasError:
    """status, message and code come from the function's mutation_response."""


@fraiseql.mutation(context_params=_TENANT_AND_USER)
class CreateProject:
    """Create new project in current organization."""

    input: ProjectCreateInput
    success: ProjectSuccess
    error: SaasError


@fraiseql.mutation(context_params=_TENANT_AND_USER)
class UpdateProject:
    """Update a project of the current organization."""

    input: ProjectUpdateInput
    success: ProjectSuccess
    error: SaasError


@fraiseql.mutation(context_params=_TENANT_AND_USER)
class DeleteProject:
    """Delete a project of the current organization."""

    input: DeleteProjectInput
    success: DeleteProjectSuccess
    error: SaasError


@fraiseql.mutation(context_params=_TENANT_AND_USER)
class UpdateOrganization:
    """Update the current organization's settings."""

    input: OrganizationUpdateInput
    success: UpdateOrganizationSuccess
    error: SaasError


# ============================================================================
# APP
# ============================================================================

config = FraiseQLConfig(
    database_url=DATABASE_URL,
    enable_playground=True,
    cors_origins=CORS_ORIGINS,
    database_pool_size=20,
)

app = create_fraiseql_app(
    config=config,
    types=[Organization, User, Project],
    queries=[current_organization, current_user, team_members, projects, project],
    mutations=[CreateProject, UpdateProject, DeleteProject, UpdateOrganization],
    context_getter=get_context,
    title="SaaS Starter API",
    version="1.0.0",
    description="Multi-tenant SaaS starter template with FraiseQL",
)


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy", "service": "saas-starter"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
