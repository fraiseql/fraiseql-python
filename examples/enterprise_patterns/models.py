"""Enterprise patterns models demonstrating all FraiseQL enterprise patterns."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field

import fraiseql
from fraiseql.types import ID
from fraiseql import fraise_field

# Base Audit Pattern


@fraiseql.type
class AuditTrail:
    """Complete audit trail information."""

    created_at: datetime
    created_by_id: ID
    created_by_name: str
    updated_at: datetime | None = None
    updated_by_id: ID | None = None
    updated_by_name: str | None = None
    version: int
    change_reason: str | None = None
    updated_fields: list[str | None] = None
    source_system: str = "api"
    correlation_id: str | None = None


# Core Entity Types with Enterprise Features


@fraiseql.type
class Organization:
    """Organization with complete enterprise features."""

    id: ID  # Exposed as GraphQL ID
    name: str
    identifier: str  # Business identifier (ORG-2024-ACME)

    # Business fields
    legal_name: str
    tax_id: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    annual_revenue: Decimal | None = None

    # Enterprise features
    audit_trail: AuditTrail
    is_active: bool = True
    settings: dict[str, Any] = fraise_field(default_factory=dict)


@fraiseql.type
class User:
    """User with comprehensive audit and role management."""

    id: ID
    email: str
    name: str
    identifier: str  # USER-JOHN-SMITH-001

    # Profile information
    first_name: str
    last_name: str
    avatar_url: str | None = None
    bio: str | None = None
    phone: str | None = None

    # Authentication and authorization
    is_active: bool = True
    is_verified: bool = False
    roles: list[str] = fraise_field(default_factory=list)
    permissions: list[str] = fraise_field(default_factory=list)

    # Enterprise features
    audit_trail: AuditTrail
    organization_id: ID
    department: str | None = None
    job_title: str | None = None
    manager_id: ID | None = None

    # Usage tracking
    last_login_at: datetime | None = None
    login_count: int = 0
    failed_login_attempts: int = 0

    # Preferences
    timezone: str = "UTC"
    language: str = "en"
    notification_preferences: dict[str, bool] = fraise_field(default_factory=dict)


@fraiseql.type
class Project:
    """Project entity demonstrating complex business logic."""

    id: ID
    name: str
    identifier: str  # PROJ-2024-Q1-WEBSITE

    # Project details
    description: str | None = None
    status: str  # draft, active, on_hold, completed, cancelled
    priority: str = "medium"  # low, medium, high, critical

    # Relationships
    organization_id: ID
    owner_id: ID
    team_member_ids: list[UUID] = fraise_field(default_factory=list)

    # Timeline
    start_date: datetime | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None

    # Budget and tracking
    budget: Decimal | None = None
    spent: Decimal = Decimal("0.00")
    estimated_hours: int | None = None
    actual_hours: int = 0

    # Enterprise features
    audit_trail: AuditTrail
    tags: list[str] = fraise_field(default_factory=list)
    custom_fields: dict[str, Any] = fraise_field(default_factory=dict)

    # Calculated fields (populated by views)
    task_count: int | None = None
    completed_task_count: int | None = None
    progress_percentage: float | None = None


@fraiseql.type
class Task:
    """Task with nested relationships and complex validation."""

    id: ID
    title: str
    identifier: str  # TASK-PROJ-001-SETUP

    # Task details
    description: str | None = None
    status: str  # TODO, in_progress, review, done, cancelled
    priority: str = "medium"

    # Relationships
    project_id: ID
    assignee_id: ID | None = None
    reporter_id: ID
    parent_task_id: ID | None = None

    # Timeline
    due_date: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Effort tracking
    estimated_hours: float | None = None
    actual_hours: float = 0.0

    # Enterprise features
    audit_trail: AuditTrail
    labels: list[str] = fraise_field(default_factory=list)

    # Calculated fields
    subtask_count: int | None = None
    blocked_by_count: int | None = None
    is_overdue: bool | None = None


# Input Types with Enterprise Validation


@fraiseql.input
class CreateOrganizationInput:
    """Organization creation with comprehensive validation."""

    name: Annotated[str, Field(min_length=2, max_length=200)]
    legal_name: Annotated[str, Field(min_length=2, max_length=500)]
    industry: Annotated[str, Field(max_length=100) | None] = None

    # Optional business information
    tax_id: Annotated[str, Field(pattern=r"^[0-9-]+$")] | None = None
    employee_count: Annotated[int, Field(gt=0, le=1000000) | None] = None
    annual_revenue: Annotated[Decimal, Field(gt=0) | None] = None

    # Enterprise metadata
    _change_reason: str | None = None
    _source_system: str = "api"


@fraiseql.input
class CreateUserInput:
    """User creation with multi-layer validation."""

    email: Annotated[str, Field(regex=r"^[^@]+@[^@]+\.[^@]+$")]
    first_name: Annotated[str, Field(min_length=1, max_length=50)]
    last_name: Annotated[str, Field(min_length=1, max_length=50)]

    # Optional profile fields
    bio: Annotated[str, Field(max_length=1000) | None] = None
    phone: Annotated[str, Field(pattern=r"^\+?[1-9]\d{1,14}$")] | None = None

    # Organizational assignment
    organization_id: ID
    department: str | None = None
    job_title: str | None = None
    manager_id: ID | None = None

    # Initial roles and permissions
    roles: list[str] = fraise_field(default_factory=lambda: ["user"])

    # Enterprise metadata
    _change_reason: str | None = None
    _send_welcome_email: bool = True


@fraiseql.input
class CreateProjectInput:
    """Project creation with business rule validation."""

    name: Annotated[str, Field(min_length=3, max_length=200)]
    description: Annotated[str, Field(max_length=2000) | None] = None

    # Project setup
    organization_id: ID
    owner_id: ID
    status: str = "draft"
    priority: str = "medium"

    # Timeline
    start_date: datetime | None = None
    due_date: datetime | None = None

    # Budget
    budget: Annotated[Decimal, Field(gt=0) | None] = None
    estimated_hours: Annotated[int, Field(gt=0, le=10000) | None] = None

    # Team assignment
    team_member_ids: list[UUID] = fraise_field(default_factory=list)
    tags: list[str] = fraise_field(default_factory=list)

    # Enterprise metadata
    _change_reason: str | None = None
    _template_id: ID | None = None  # For project templates


@fraiseql.input
class CreateTaskInput:
    """Task creation with complex validation."""

    title: Annotated[str, Field(min_length=3, max_length=200)]
    description: Annotated[str, Field(max_length=2000) | None] = None

    # Task assignment
    project_id: ID
    assignee_id: ID | None = None
    parent_task_id: ID | None = None

    # Planning
    priority: str = "medium"
    due_date: datetime | None = None
    estimated_hours: Annotated[float, Field(gt=0, le=1000) | None] = None

    # Categorization
    labels: list[str] = fraise_field(default_factory=list)

    # Enterprise metadata
    _change_reason: str | None = None
    _copy_from_task_id: ID | None = None


# Success Types with Rich Metadata


@fraiseql.success
class CreateOrganizationSuccess:
    """Organization created successfully with audit information."""

    organization: Organization
    message: str = "Organization created successfully"

    # Enterprise metadata
    generated_identifier: str
    initial_setup_completed: bool = False
    welcome_email_sent: bool = False
    audit_metadata: dict[str, Any]


@fraiseql.success
class CreateUserSuccess:
    """User created successfully with onboarding info."""

    user: User
    message: str = "User created successfully"

    # Enterprise features
    generated_identifier: str
    initial_password_set: bool = False
    welcome_email_queued: bool = False
    role_assignments: list[dict[str, str]]
    audit_metadata: dict[str, Any]


@fraiseql.success
class CreateProjectSuccess:
    """Project created with setup information."""

    project: Project
    message: str = "Project created successfully"

    # Project setup results
    generated_identifier: str
    team_notifications_sent: int = 0
    template_applied: str | None = None
    initial_tasks_created: int = 0
    audit_metadata: dict[str, Any]


@fraiseql.success
class CreateTaskSuccess:
    """Task created with relationship validation."""

    task: Task
    message: str = "Task created successfully"

    # Task creation results
    generated_identifier: str
    assignee_notified: bool = False
    parent_task_updated: bool = False
    project_stats_updated: bool = False
    audit_metadata: dict[str, Any]


# Error Types with Detailed Context


@fraiseql.error
class CreateOrganizationError:
    """Organization creation failed with context."""

    message: str
    error_code: str
    # Note: errors array is now auto-populated by FraiseQL from status strings
    # For explicit validation errors, use metadata.errors in your PostgreSQL function

    # Enterprise error context
    validation_failures: list[dict[str, str]]
    business_rule_violations: list[str]
    system_constraints: list[str]
    suggested_fixes: list[str]


@fraiseql.error
class CreateUserError:
    """User creation failed with detailed information."""

    message: str
    error_code: str
    # Note: errors array is now auto-populated by FraiseQL from status strings
    # For explicit validation errors, use metadata.errors in your PostgreSQL function

    # User-specific error context
    email_validation_failed: bool = False
    organization_capacity_exceeded: bool = False
    role_assignment_failed: list[str] = fraise_field(default_factory=list)
    invitation_delivery_failed: bool = False

    # Compliance context
    data_privacy_violations: list[str] = fraise_field(default_factory=list)
    security_policy_violations: list[str] = fraise_field(default_factory=list)


@fraiseql.error
class CreateProjectError:
    """Project creation failed with business context."""

    message: str
    error_code: str
    # Note: errors array is now auto-populated by FraiseQL from status strings
    # For explicit validation errors, use metadata.errors in your PostgreSQL function

    # Project-specific errors
    budget_validation_failed: bool = False
    timeline_validation_failed: bool = False
    team_assignment_failed: list[UUID] = fraise_field(default_factory=list)
    template_application_failed: bool = False

    # Resource constraints
    organization_project_limit_exceeded: bool = False
    insufficient_permissions: list[str] = fraise_field(default_factory=list)


@fraiseql.error
class CreateTaskError:
    """Task creation failed with relationship context."""

    message: str
    error_code: str
    # Note: errors array is now auto-populated by FraiseQL from status strings
    # For explicit validation errors, use metadata.errors in your PostgreSQL function

    # Task-specific errors
    project_validation_failed: bool = False
    assignee_validation_failed: bool = False
    parent_task_validation_failed: bool = False
    timeline_conflict: bool = False

    # Capacity constraints
    assignee_workload_exceeded: bool = False
    project_task_limit_exceeded: bool = False


# Update Input Types (showing enterprise patterns for updates)


@fraiseql.input
class UpdateProjectInput:
    """Project update with optimistic locking."""

    name: Annotated[str, Field(min_length=3, max_length=200) | None] = None
    description: Annotated[str, Field(max_length=2000) | None] = None
    status: str | None = None
    priority: str | None = None

    # Timeline updates
    start_date: datetime | None = None
    due_date: datetime | None = None

    # Budget updates
    budget: Annotated[Decimal, Field(gt=0) | None] = None

    # Team updates
    add_team_members: list[UUID] = fraise_field(default_factory=list)
    remove_team_members: list[UUID] = fraise_field(default_factory=list)

    # Enterprise features
    _expected_version: int | None = None  # Optimistic locking
    _change_reason: str | None = None
    _notify_team: bool = True


@fraiseql.success
class UpdateProjectSuccess:
    """Project updated with change tracking."""

    project: Project
    message: str = "Project updated successfully"

    # Change tracking
    updated_fields: list[str]
    previous_version: int
    new_version: int

    # Business impact
    timeline_changed: bool = False
    budget_changed: bool = False
    team_changed: bool = False
    status_changed: bool = False

    # Notifications
    team_members_notified: int = 0
    stakeholders_notified: int = 0

    audit_metadata: dict[str, Any]


@fraiseql.error
class UpdateProjectError:
    """Project update failed with context."""

    message: str
    error_code: str
    # Note: errors array is now auto-populated by FraiseQL from status strings
    # For explicit validation errors, use metadata.errors in your PostgreSQL function

    # Update-specific errors
    version_conflict: bool = False
    concurrent_modification_detected: bool = False
    status_transition_invalid: bool = False
    timeline_validation_failed: bool = False

    # Current state context
    current_version: int | None = None
    expected_version: int | None = None
    last_modified_by: str | None = None
    last_modified_at: datetime | None = None
