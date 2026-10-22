"""SaaS Starter Data Models.

Multi-tenant SaaS models with organization, user, subscription, and billing support.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import fraiseql
from fraiseql import fraise_field
from fraiseql.types import ID


@fraiseql.type(sql_source="v_organization", jsonb_column="data")
class Organization:
    """Organization/tenant entity."""

    id: ID = fraise_field(description="Organization unique identifier")
    name: str = fraise_field(description="Organization name")
    slug: str = fraise_field(description="URL-friendly slug")
    plan: str = fraise_field(description="Subscription plan")
    subscription_status: str = fraise_field(description="Subscription status")
    member_count: int = fraise_field(description="Number of team members")
    settings: dict = fraise_field(description="Organization settings (JSONB)")
    created_at: datetime = fraise_field(description="Organization creation date")
    updated_at: datetime = fraise_field(description="Last update timestamp")


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    """User entity - belongs to an organization."""

    id: ID = fraise_field(description="User unique identifier")
    fk_organization: int = fraise_field(description="Parent organization")
    email: str = fraise_field(description="User email address")
    name: str = fraise_field(description="User full name")
    role: str = fraise_field(description="User role in organization")
    status: str = fraise_field(description="User status")
    avatar_url: str | None = fraise_field(description="Avatar URL")
    last_active: datetime | None = fraise_field(description="Last activity timestamp")
    created_at: datetime = fraise_field(description="Account creation date")


@fraiseql.type
class Subscription:
    """Subscription/billing information."""

    id: ID = fraise_field(description="Subscription unique identifier")
    fk_organization: int = fraise_field(description="Organization ID")
    plan: str = fraise_field(description="Plan name")
    status: str = fraise_field(description="Subscription status")
    amount: Decimal = fraise_field(description="Amount charged")
    currency: str = fraise_field(description="Currency code")
    interval: str = fraise_field(description="Billing interval")
    current_period_start: datetime = fraise_field(description="Current period start")
    current_period_end: datetime = fraise_field(description="Current period end")
    cancel_at_period_end: bool = fraise_field(description="Whether subscription will cancel")
    stripe_subscription_id: str | None = fraise_field(description="Stripe subscription ID")
    features: dict = fraise_field(description="Plan features (JSONB)")


@fraiseql.type
class UsageMetrics:
    """Organization usage metrics."""

    fk_organization: int = fraise_field(description="Organization ID")
    period_start: datetime = fraise_field(description="Period start date")
    period_end: datetime = fraise_field(description="Period end date")
    projects: int = fraise_field(description="Number of projects")
    storage: int = fraise_field(description="Storage used in bytes")
    api_calls: int = fraise_field(description="API calls made")
    seats: int = fraise_field(description="Active user seats")


@fraiseql.type
class UsageLimits:
    """Organization usage limits based on plan."""

    projects: int = fraise_field(description="Maximum projects")
    storage: int = fraise_field(description="Storage limit in bytes")
    api_calls: int = fraise_field(description="API calls per month")
    seats: int = fraise_field(description="Team member seats")


@fraiseql.type
class TeamInvitation:
    """Team member invitation."""

    id: ID = fraise_field(description="Invitation unique identifier")
    fk_organization: int = fraise_field(description="Organization ID")
    email: str = fraise_field(description="Invitee email")
    role: str = fraise_field(description="Invited role")
    token: str = fraise_field(description="Invitation token")
    fk_invited_by: int = fraise_field(description="User who sent invitation")
    status: str = fraise_field(description="Invitation status")
    expires_at: datetime = fraise_field(description="Expiration timestamp")
    created_at: datetime = fraise_field(description="Invitation sent date")


@fraiseql.type
class ActivityLogEntry:
    """Activity log entry for audit trail."""

    id: ID = fraise_field(description="Log entry unique identifier")
    fk_organization: int = fraise_field(description="Organization ID")
    fk_user: int = fraise_field(description="User who performed action")
    action: str = fraise_field(description="Action type")
    resource: str = fraise_field(description="Resource type")
    resource_id: ID | None = fraise_field(description="Resource ID")
    details: dict = fraise_field(description="Action details (JSONB)")
    ip_address: str | None = fraise_field(description="User IP address")
    user_agent: str | None = fraise_field(description="User agent string")
    created_at: datetime = fraise_field(description="Action timestamp")


@fraiseql.type(sql_source="v_project", jsonb_column="data")
class Project:
    """Example resource - tenant-aware project."""

    id: ID = fraise_field(description="Project unique identifier")
    fk_organization: int = fraise_field(description="Parent organization")
    name: str = fraise_field(description="Project name")
    description: str | None = fraise_field(description="Project description")
    fk_owner: int = fraise_field(description="Project owner")
    status: str = fraise_field(description="Project status")
    settings: dict = fraise_field(description="Project settings (JSONB)")
    created_at: datetime = fraise_field(description="Creation date")
    updated_at: datetime = fraise_field(description="Last update timestamp")


# Input types for mutations
@fraiseql.input
class RegisterInput:
    """Input for new user registration."""

    email: str = fraise_field(description="User email")
    password: str = fraise_field(description="User password")
    name: str = fraise_field(description="User full name")
    organization_name: str = fraise_field(description="Organization name")


@fraiseql.input
class LoginInput:
    """Input for user login."""

    email: str = fraise_field(description="User email")
    password: str = fraise_field(description="User password")


@fraiseql.input
class OrganizationUpdateInput:
    """Input for updating organization."""

    name: str | None = fraise_field(default=None, description="New organization name")
    settings: dict | None = fraise_field(default=None, description="Updated settings")


@fraiseql.input
class InviteTeamMemberInput:
    """Input for team member invitation."""

    email: str = fraise_field(description="Invitee email")
    role: str = fraise_field(description="Role to assign")


@fraiseql.input
class AcceptInvitationInput:
    """Input for accepting invitation."""

    token: str = fraise_field(description="Invitation token")
    password: str = fraise_field(description="New user password")
    name: str = fraise_field(description="User full name")


@fraiseql.input
class ProjectCreateInput:
    """Input for creating project."""

    name: str = fraise_field(description="Project name")
    description: str | None = fraise_field(default=None, description="Project description")


@fraiseql.input
class ProjectUpdateInput:
    """Input for updating project."""

    id: ID = fraise_field(description="Project to update")
    name: str | None = fraise_field(default=None, description="Updated name")
    description: str | None = fraise_field(default=None, description="Updated description")
    status: str | None = fraise_field(default=None, description="Updated status")


# Result types for mutations
@fraiseql.type
class AuthSuccess:
    """Successful authentication result."""

    token: str = fraise_field(description="JWT access token")
    user: User = fraise_field(description="Authenticated user")
    organization: Organization = fraise_field(description="User's organization")


@fraiseql.type
class AuthError:
    """Authentication error result."""

    message: str = fraise_field(description="Error message")
    code: str = fraise_field(description="Error code")


@fraiseql.type
class InviteSuccess:
    """Successful invitation result."""

    invitation: TeamInvitation = fraise_field(description="Created invitation")
    invite_url: str = fraise_field(description="Invitation URL")


@fraiseql.type
class InviteError:
    """Invitation error result."""

    message: str = fraise_field(description="Error message")
    code: str = fraise_field(description="Error code")


# Union types for mutation results
AuthResult = AuthSuccess | AuthError
InviteResult = InviteSuccess | InviteError
