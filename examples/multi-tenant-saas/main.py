"""Multi-Tenant SaaS Application with FraiseQL
============================================

Features:
- Row-Level Security (RLS) for automatic tenant isolation
- REGULATED security profile for compliance
- JWT authentication with tenant context
- Comprehensive audit trail
- GraphQL API with tenant-scoped queries

Usage:
    python main.py

Then visit: http://localhost:8000/graphql
"""

import os
from datetime import datetime
from typing import Any
from uuid import UUID

import jwt
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from fraiseql import FraiseQL, create_fraiseql_app
from fraiseql.security import SecurityProfile
from fraiseql.types import ID

# ============================================================================
# CONFIGURATION
# ============================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/multi_tenant_saas")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"

# ============================================================================
# TYPE DEFINITIONS
# ============================================================================

fraiseql = FraiseQL()


@fraiseql.type(sql_source="v_organization")
class Organization:
    """Organization (tenant) - represents a customer/company."""

    id: ID
    name: str
    slug: str
    plan: str  # free, starter, professional, enterprise
    status: str  # active, suspended, cancelled
    settings: dict | None
    created_at: datetime
    updated_at: datetime


@fraiseql.type(sql_source="v_user")
class User:
    """User within an organization."""

    id: ID
    organization_id: ID
    email: str
    name: str
    role: str  # owner, admin, member, readonly
    status: str  # active, invited, suspended
    last_active_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @fraiseql.field
    async def organization(self, info) -> Organization | None:
        """Get user's organization."""
        db = fraiseql.get_db(info.context)
        return await db.find_one("v_organization", where={"id": self.organization_id})


@fraiseql.type(sql_source="v_project")
class Project:
    """Project within an organization."""

    id: ID
    organization_id: ID
    owner_id: ID
    name: str
    description: str | None
    status: str  # active, archived, deleted
    settings: dict | None
    created_at: datetime
    updated_at: datetime

    @fraiseql.field
    async def owner(self, info) -> User | None:
        """Get project owner."""
        db = fraiseql.get_db(info.context)
        return await db.find_one("v_user", where={"id": self.owner_id})

    @fraiseql.field
    async def tasks(self, info, status: str | None = None) -> list["Task"]:
        """Get project tasks, optionally filtered by status."""
        db = fraiseql.get_db(info.context)
        where = {"project_id": self.id}
        if status:
            where["status"] = status
        return await db.find("v_task", where=where)


@fraiseql.type(sql_source="v_task")
class Task:
    """Task within a project."""

    id: ID
    organization_id: ID
    project_id: ID
    assigned_to: UUID | None
    title: str
    description: str | None
    status: str  # TODO, in_progress, done, cancelled
    priority: str  # low, medium, high, urgent
    due_date: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @fraiseql.field
    async def project(self, info) -> Project | None:
        """Get task's project."""
        db = fraiseql.get_db(info.context)
        return await db.find_one("v_project", where={"id": self.project_id})

    @fraiseql.field
    async def assigned_user(self, info) -> User | None:
        """Get assigned user."""
        if not self.assigned_to:
            return None
        db = fraiseql.get_db(info.context)
        return await db.find_one("v_user", where={"id": self.assigned_to})


@fraiseql.type(sql_source="v_audit_log")
class AuditLog:
    """Audit log entry for compliance."""

    id: ID
    organization_id: ID
    user_id: ID | None
    action: str  # created, updated, deleted, accessed
    resource_type: str  # project, task, user, etc.
    resource_id: ID | None
    changes: dict | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


@fraiseql.type(sql_source="tv_organization")
class OrganizationStats:
    """Organization statistics (computed view tv_organization)."""

    id: ID
    name: str
    slug: str
    plan: str
    status: str
    created_at: datetime
    active_users: int
    active_projects: int
    total_tasks: int
    completed_tasks: int
    api_calls_today: int


# ============================================================================
# QUERIES
# ============================================================================


@fraiseql.query
class Query:
    """Root query type."""

    @fraiseql.field
    async def current_user(self, info) -> User | None:
        """Get current authenticated user."""
        user_id = info.context.get("user_id")
        if not user_id:
            return None

        db = fraiseql.get_db(info.context)
        return await db.find_one("v_user", where={"id": user_id})

    @fraiseql.field
    async def current_organization(self, info) -> Organization | None:
        """Get current user's organization."""
        org_id = info.context.get("organization_id")
        if not org_id:
            return None

        db = fraiseql.get_db(info.context)
        return await db.find_one("v_organization", where={"id": org_id})

    @fraiseql.field
    async def organization_stats(self, info) -> OrganizationStats | None:
        """Get organization statistics."""
        org_id = info.context.get("organization_id")
        if not org_id:
            return None

        db = fraiseql.get_db(info.context)
        return await db.find_one("tv_organization", where={"id": org_id})

    @fraiseql.field
    async def users(
        self, info, limit: int = 50, offset: int = 0
    ) -> list[User]:
        """List users in current organization (RLS automatically filters)."""
        db = fraiseql.get_db(info.context)
        return await db.find("v_user", limit=limit, offset=offset)

    @fraiseql.field
    async def projects(
        self,
        info,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Project]:
        """List projects in current organization (RLS automatically filters)."""
        db = fraiseql.get_db(info.context)
        where = {}
        if status:
            where["status"] = status
        return await db.find("v_project", where=where, limit=limit, offset=offset)

    @fraiseql.field
    async def project(self, info, id: ID) -> Project | None:
        """Get single project by ID (RLS ensures it belongs to current org)."""
        db = fraiseql.get_db(info.context)
        return await db.find_one("v_project", where={"id": id})

    @fraiseql.field
    async def tasks(
        self,
        info,
        project_id: ID | None = None,
        assigned_to: UUID | None = None,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks in current organization (RLS automatically filters).

        Filters:
        - project_id: Filter by project
        - assigned_to: Filter by assigned user
        - status: Filter by task status (todo, in_progress, done, cancelled)
        - priority: Filter by priority (low, medium, high, urgent)
        """
        db = fraiseql.get_db(info.context)
        where = {}
        if project_id:
            where["project_id"] = project_id
        if assigned_to:
            where["assigned_to"] = assigned_to
        if status:
            where["status"] = status
        if priority:
            where["priority"] = priority
        return await db.find("v_task", where=where, limit=limit, offset=offset)

    @fraiseql.field
    async def task(self, info, id: ID) -> Task | None:
        """Get single task by ID (RLS ensures it belongs to current org)."""
        db = fraiseql.get_db(info.context)
        return await db.find_one("v_task", where={"id": id})

    @fraiseql.field
    async def audit_logs(
        self,
        info,
        resource_type: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        """List audit logs for current organization (RLS automatically filters).

        Filters:
        - resource_type: Filter by resource type (project, task, user, etc.)
        - action: Filter by action (created, updated, deleted, accessed)
        """
        db = fraiseql.get_db(info.context)
        where = {}
        if resource_type:
            where["resource_type"] = resource_type
        if action:
            where["action"] = action
        return await db.find(
            "v_audit_log",
            where=where,
            limit=limit,
            offset=offset,
            order_by=[("created_at", "DESC")],
        )


# ============================================================================
# MUTATIONS
# ============================================================================


@fraiseql.mutation(name="createProject", function="fn_create_project", enable_cascade=True)
class CreateProject:
    """Create a new project.

    CASCADE enabled: Returns updated organization statistics.
    """

    organization_id: ID
    owner_id: ID
    name: str
    description: str | None


@fraiseql.mutation(name="createTask", function="fn_create_task", enable_cascade=True)
class CreateTask:
    """Create a new task.

    CASCADE enabled: Returns updated project with new task.
    """

    organization_id: ID
    project_id: ID
    title: str
    description: str | None
    assigned_to: UUID | None
    priority: str
    due_date: datetime | None


@fraiseql.mutation(name="updateTaskStatus", function="fn_update_task_status", enable_cascade=True)
class UpdateTaskStatus:
    """Update task status.

    CASCADE enabled: Returns updated task and project statistics.
    """

    task_id: ID
    status: str


@fraiseql.mutation(name="inviteUser", function="fn_invite_user")
class InviteUser:
    """Invite a new user to the organization."""

    organization_id: ID
    email: str
    name: str
    role: str


# ============================================================================
# AUTHENTICATION & MIDDLEWARE
# ============================================================================


def decode_jwt_token(token: str) -> dict[str, Any]:
    """Decode and validate JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def auth_middleware(request: Request, call_next):
    """Authentication middleware - extracts tenant context from JWT.

    Sets request.state with:
    - user_id: Current user ID
    - organization_id: Current tenant ID
    - role: User's role in the organization
    """
    # Get Authorization header
    auth_header = request.headers.get("Authorization")

    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            payload = decode_jwt_token(token)
            request.state.user_id = payload.get("user_id")
            request.state.organization_id = payload.get("organization_id")
            request.state.role = payload.get("role")
        except HTTPException:
            # Invalid token - continue without auth context
            pass

    response = await call_next(request)
    return response


def get_context(request: Request) -> dict[str, Any]:
    """Build GraphQL context from request state.

    Includes:
    - user_id: Current user ID
    - organization_id: Current tenant ID (for RLS)
    - role: User's role
    - request: Original FastAPI request
    """
    return {
        "user_id": getattr(request.state, "user_id", None),
        "organization_id": getattr(request.state, "organization_id", None),
        "role": getattr(request.state, "role", None),
        "request": request,
    }


# ============================================================================
# DATABASE CONTEXT MANAGER
# ============================================================================


async def set_tenant_context(info) -> None:
    """Set PostgreSQL session variable for RLS.

    This ensures Row-Level Security policies use the correct tenant ID.
    """
    org_id = info.context.get("organization_id")
    if org_id:
        db = fraiseql.get_db(info.context)
        # Set session variable that RLS policies use
        await db.execute(
            f"SET LOCAL app.current_tenant_id = '{org_id}'"
        )


# ============================================================================
# APPLICATION SETUP
# ============================================================================

app = create_fraiseql_app(
    database_url=DATABASE_URL,
    schema=fraiseql.get_schema(),
    enable_rust_pipeline=True,
    enable_cascade=True,
    security_profile=SecurityProfile.REGULATED,  # Compliance-focused
    allow_introspection=True,  # Enable GraphiQL for development
    context_getter=get_context,
)

# Add authentication middleware
app.middleware("http")(auth_middleware)


# ============================================================================
# HELPER ENDPOINTS
# ============================================================================


@app.post("/auth/register")
async def register(
    organization_name: str,
    organization_slug: str,
    owner_email: str,
    owner_password: str,
    owner_name: str,
):
    """Register a new organization (tenant) and owner user.

    Returns JWT token for immediate login.
    """
    # Create organization using database function
    from asyncpg import create_pool

    pool = await create_pool(DATABASE_URL)
    try:
        org_id = await pool.fetchval(
            "SELECT fn_create_organization($1, $2, $3, $4, $5)",
            organization_name,
            organization_slug,
            owner_email,
            owner_password,
            owner_name,
        )

        # Get created user
        user = await pool.fetchrow(
            "SELECT id, email, name, role FROM tb_user WHERE organization_id = $1 AND email = $2",
            org_id,
            owner_email,
        )

        # Generate JWT token
        token = jwt.encode(
            {
                "user_id": str(user["id"]),
                "organization_id": str(org_id),
                "role": user["role"],
            },
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )

        return {
            "token": token,
            "user": {
                "id": str(user["id"]),
                "email": user["email"],
                "name": user["name"],
                "role": user["role"],
            },
            "organization": {
                "id": str(org_id),
                "name": organization_name,
                "slug": organization_slug,
            },
        }
    finally:
        await pool.close()


@app.post("/auth/login")
async def login(email: str, password: str):
    """Login with email and password.

    Returns JWT token with tenant context.
    """
    from asyncpg import create_pool

    pool = await create_pool(DATABASE_URL)
    try:
        # Verify credentials
        user = await pool.fetchrow(
            """
            SELECT id, organization_id, email, name, role, password_hash
            FROM tb_user
            WHERE email = $1 AND status = 'active'
            """,
            email,
        )

        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Check password (using pgcrypto's crypt function)
        password_valid = await pool.fetchval(
            "SELECT password_hash = crypt($1, password_hash) FROM tb_user WHERE id = $2",
            password,
            user["id"],
        )

        if not password_valid:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Get organization details
        org = await pool.fetchrow(
            "SELECT id, name, slug, plan FROM tb_organization WHERE id = $1",
            user["organization_id"],
        )

        # Generate JWT token
        token = jwt.encode(
            {
                "user_id": str(user["id"]),
                "organization_id": str(user["organization_id"]),
                "role": user["role"],
            },
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )

        return {
            "token": token,
            "user": {
                "id": str(user["id"]),
                "email": user["email"],
                "name": user["name"],
                "role": user["role"],
            },
            "organization": {
                "id": str(org["id"]),
                "name": org["name"],
                "slug": org["slug"],
                "plan": org["plan"],
            },
        }
    finally:
        await pool.close()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "security_profile": "REGULATED"}


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    print("=" * 80)
    print("Multi-Tenant SaaS Application with FraiseQL")
    print("=" * 80)
    print()
    print("Features:")
    print("  ✓ Row-Level Security (RLS) for automatic tenant isolation")
    print("  ✓ REGULATED security profile for compliance")
    print("  ✓ JWT authentication with tenant context")
    print("  ✓ Comprehensive audit trail")
    print("  ✓ GraphQL API with tenant-scoped queries")
    print()
    print("Endpoints:")
    print("  • GraphQL API: http://localhost:8000/graphql")
    print("  • GraphQL Playground: http://localhost:8000/graphql")
    print("  • Register: POST http://localhost:8000/auth/register")
    print("  • Login: POST http://localhost:8000/auth/login")
    print("  • Health: GET http://localhost:8000/health")
    print()
    print("Sample Credentials (from seed data):")
    print("  • alice@acme.com / password123 (Acme Corporation owner)")
    print("  • bob@acme.com / password123 (Acme Corporation member)")
    print("  • dave@beta.com / password123 (Beta Industries owner)")
    print()
    print("=" * 80)
    print()

    uvicorn.run(app, host="0.0.0.0", port=8000)
