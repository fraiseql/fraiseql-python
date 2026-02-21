//! RBAC data models matching PostgreSQL schema.
//!
//! This module defines the core data structures for role-based access control:
//! - **Role**: Hierarchical roles with optional parent and tenant isolation
//! - **Permission**: Resource:action pairs with optional constraints
//! - **UserRole**: User-role assignments with expiration and audit trail
//! - **RolePermission**: Many-to-many role-permission mappings

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Role entity with hierarchical support.
///
/// Roles form a hierarchy through the `parent_role_id` field. A user with a child role
/// automatically inherits all permissions from parent roles. This enables role inheritance
/// patterns like: viewer → user → manager → admin → super_admin.
///
/// # Fields
///
/// - `id`: Unique identifier (UUID)
/// - `name`: Human-readable role name (unique per tenant)
/// - `description`: Optional role purpose/documentation
/// - `parent_role_id`: Optional parent role for inheritance
/// - `tenant_id`: Optional tenant scope (NULL = global role)
/// - `is_system`: If true, role cannot be deleted (system roles)
/// - `created_at`, `updated_at`: Audit timestamps
///
/// # Example
///
/// A typical role hierarchy:
/// - super_admin (global, no parent)
/// - admin (tenant, inherits super_admin)
/// - manager (tenant, inherits admin)
/// - user (tenant, inherits manager)
/// - viewer (tenant, inherits user)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Role {
    pub id:             Uuid,
    pub name:           String,
    pub description:    Option<String>,
    pub parent_role_id: Option<Uuid>,
    pub tenant_id:      Option<Uuid>,
    pub is_system:      bool,
    pub created_at:     DateTime<Utc>,
    pub updated_at:     DateTime<Utc>,
}

impl Role {
    /// Create Role from tokio_postgres Row
    pub fn from_row(row: tokio_postgres::Row) -> Self {
        Self {
            id:             Uuid::parse_str(&row.get::<_, String>(0)).unwrap_or_default(),
            name:           row.get(1),
            description:    row.get(2),
            parent_role_id: row.get::<_, Option<String>>(3).and_then(|s| Uuid::parse_str(&s).ok()),
            tenant_id:      row.get::<_, Option<String>>(4).and_then(|s| Uuid::parse_str(&s).ok()),
            is_system:      row.get(5),
            created_at:     chrono::DateTime::parse_from_rfc3339(&row.get::<_, String>(6))
                .map(|dt| dt.with_timezone(&chrono::Utc))
                .unwrap_or_else(|_| chrono::Utc::now()),
            updated_at:     chrono::DateTime::parse_from_rfc3339(&row.get::<_, String>(7))
                .map(|dt| dt.with_timezone(&chrono::Utc))
                .unwrap_or_else(|_| chrono::Utc::now()),
        }
    }
}

/// Permission entity for resource:action authorization.
///
/// Permissions follow a resource:action pattern (e.g., "user:read", "document:delete").
/// Supports wildcard matching for flexible permission assignment:
/// - Exact match: "user:read" matches only that permission
/// - Resource wildcard: "user:*" matches all user actions
/// - Action wildcard: "*:read" matches read on all resources
/// - Full wildcard: "*:*" grants all permissions (superuser)
///
/// # Fields
///
/// - `id`: Unique permission identifier
/// - `resource`: Resource name (e.g., "user", "document", "audit")
/// - `action`: Action type (e.g., "read", "write", "delete")
/// - `description`: Optional documentation of what this permission grants
/// - `constraints`: Optional JSON for advanced constraints (Phase 12)
///   - Examples: `{"own_data_only": true}`, `{"department_only": true}`
/// - `created_at`: Permission creation timestamp
///
/// # Example Matching
///
/// A user with permission "user:*" will match:
/// - "user:read" ✓
/// - "user:write" ✓
/// - "user:delete" ✓
/// - "document:read" ✗
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Permission {
    pub id:          Uuid,
    pub resource:    String,
    pub action:      String,
    pub description: Option<String>,
    pub constraints: Option<serde_json::Value>,
    pub created_at:  DateTime<Utc>,
}

impl Permission {
    /// Check if permission matches resource:action pattern
    pub fn matches(&self, resource: &str, action: &str) -> bool {
        // Exact match
        if self.resource == resource && self.action == action {
            return true;
        }

        // Wildcard matching: resource:* or *:action
        if self.action == "*" && self.resource == resource {
            return true;
        }
        if self.resource == "*" && self.action == action {
            return true;
        }
        if self.resource == "*" && self.action == "*" {
            return true;
        }

        false
    }

    /// Create Permission from tokio_postgres Row
    pub fn from_row(row: tokio_postgres::Row) -> Self {
        Self {
            id:          Uuid::parse_str(&row.get::<_, String>(0)).unwrap_or_default(),
            resource:    row.get(1),
            action:      row.get(2),
            description: row.get(3),
            constraints: row
                .get::<_, Option<String>>(4)
                .and_then(|s| serde_json::from_str(&s).ok()),
            created_at:  chrono::DateTime::parse_from_rfc3339(&row.get::<_, String>(5))
                .map(|dt| dt.with_timezone(&chrono::Utc))
                .unwrap_or_else(|_| chrono::Utc::now()),
        }
    }
}

/// User-Role assignment with expiration and audit trail.
///
/// Represents the assignment of a role to a user within a specific tenant context.
/// Supports temporary role assignments through the `expires_at` field, enabling
/// time-bound access patterns for contractors, temporary staff, etc.
///
/// # Fields
///
/// - `id`: Unique assignment identifier
/// - `user_id`: User receiving the role
/// - `role_id`: Role being assigned
/// - `tenant_id`: Tenant scope for the assignment (NULL = global)
/// - `granted_by`: User ID of the admin who made this assignment (audit trail)
/// - `granted_at`: Timestamp when role was assigned
/// - `expires_at`: Optional expiration time (NULL = permanent assignment)
///
/// # Expiration Semantics
///
/// A role assignment is valid if:
/// - `expires_at` is NULL (permanent), OR
/// - `expires_at > NOW()` (not yet expired)
///
/// Expired roles are automatically filtered out by permission resolution queries.
/// This prevents the need for cleanup jobs to delete expired assignments.
///
/// # Example
///
/// ```ignore
/// // User gets temporary contractor role for 30 days
/// user_roles {
///     user_id: contractor_uuid,
///     role_id: contractor_role_uuid,
///     expires_at: now() + 30 days
/// }
/// ```
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserRole {
    pub id:         Uuid,
    pub user_id:    Uuid,
    pub role_id:    Uuid,
    pub tenant_id:  Option<Uuid>,
    pub granted_by: Option<Uuid>,
    pub granted_at: DateTime<Utc>,
    pub expires_at: Option<DateTime<Utc>>,
}

impl UserRole {
    /// Check if role assignment is still valid
    pub fn is_valid(&self) -> bool {
        if let Some(expires_at) = self.expires_at {
            Utc::now() < expires_at
        } else {
            true
        }
    }

    /// Create UserRole from tokio_postgres Row
    pub fn from_row(row: tokio_postgres::Row) -> Self {
        Self {
            id:         Uuid::parse_str(&row.get::<_, String>(0)).unwrap_or_default(),
            user_id:    Uuid::parse_str(&row.get::<_, String>(1)).unwrap_or_default(),
            role_id:    Uuid::parse_str(&row.get::<_, String>(2)).unwrap_or_default(),
            tenant_id:  row.get::<_, Option<String>>(3).and_then(|s| Uuid::parse_str(&s).ok()),
            granted_by: row.get::<_, Option<String>>(4).and_then(|s| Uuid::parse_str(&s).ok()),
            granted_at: chrono::DateTime::parse_from_rfc3339(&row.get::<_, String>(5))
                .map(|dt| dt.with_timezone(&chrono::Utc))
                .unwrap_or_else(|_| chrono::Utc::now()),
            expires_at: row
                .get::<_, Option<String>>(6)
                .and_then(|s| chrono::DateTime::parse_from_rfc3339(&s).ok())
                .map(|dt| dt.with_timezone(&chrono::Utc)),
        }
    }
}

/// Role-Permission mapping for many-to-many assignments.
///
/// Links a role to a permission, establishing what capabilities users with that role have.
/// When a user is assigned a role, they inherit all permissions assigned to that role
/// (plus permissions from inherited parent roles).
///
/// # Fields
///
/// - `id`: Unique mapping identifier
/// - `role_id`: Role that has this permission
/// - `permission_id`: Permission granted to the role
/// - `granted_at`: Timestamp when permission was assigned to role
///
/// # Usage Pattern
///
/// When checking if a user can perform an action:
/// 1. Find user's roles via UserRole table
/// 2. Find all inherited roles via RoleHierarchy
/// 3. Find all permissions for those roles via RolePermission
/// 4. Match requested resource:action against permission list
///
/// This is computed efficiently by the `PermissionResolver` with caching.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RolePermission {
    pub id:            Uuid,
    pub role_id:       Uuid,
    pub permission_id: Uuid,
    pub granted_at:    DateTime<Utc>,
}
