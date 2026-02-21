//! Field-level authorization enforcement.

use std::sync::Arc;

use uuid::Uuid;

use super::{
    errors::{RbacError, Result},
    resolver::PermissionResolver,
};
use crate::pipeline::unified::UserContext;

/// Field authorization checker
pub struct FieldAuthChecker {
    resolver: Arc<PermissionResolver>,
}

impl FieldAuthChecker {
    pub fn new(resolver: Arc<PermissionResolver>) -> Self {
        Self { resolver }
    }

    /// Check field-level permissions before execution
    pub async fn check_field_access(
        &self,
        user_context: &UserContext,
        _field_name: &str,
        field_permissions: &FieldPermissions,
        tenant_id: Option<Uuid>,
    ) -> Result<()> {
        // Check required roles (from UserContext - populated by Phase 10 auth)
        if !field_permissions.required_roles.is_empty() {
            let user_roles = &user_context.roles;
            for required_role in &field_permissions.required_roles {
                if !user_roles.contains(required_role) {
                    return Err(RbacError::MissingRole {
                        required_role:   required_role.clone(),
                        available_roles: user_roles.clone(),
                    });
                }
            }
        }

        // Check required permissions
        if !field_permissions.required_permissions.is_empty() {
            let user_id_str = user_context.user_id.as_ref().ok_or_else(|| {
                RbacError::ConfigError(
                    "User context missing user_id for permission check".to_string(),
                )
            })?;

            let user_id = Uuid::parse_str(user_id_str).map_err(|e| {
                RbacError::ConfigError(format!("Invalid user ID in context: {}", e))
            })?;

            for perm in &field_permissions.required_permissions {
                let (resource, action) = parse_permission(perm)?;

                if !self.resolver.has_permission(user_id, &resource, &action, tenant_id).await? {
                    return Err(RbacError::PermissionDenied {
                        resource: resource.clone(),
                        action:   action.clone(),
                        user_id:  Some(user_id_str.clone()),
                    });
                }
            }
        }

        // TODO: Implement custom_checks in Phase 12 (advanced constraints)

        Ok(())
    }

    /// Check field access for multiple fields (bulk operation)
    pub async fn check_fields_access(
        &self,
        user_context: &UserContext,
        fields: &[(&str, &FieldPermissions)],
        tenant_id: Option<Uuid>,
    ) -> Result<()> {
        for (field_name, field_permissions) in fields {
            self.check_field_access(user_context, field_name, field_permissions, tenant_id)
                .await?;
        }
        Ok(())
    }
}

/// Field permission requirements (from GraphQL directives)
#[derive(Debug, Default, Clone)]
pub struct FieldPermissions {
    pub required_roles:       Vec<String>,
    pub required_permissions: Vec<String>,
    pub custom_checks:        Vec<String>, // For Phase 12 advanced constraints
}

impl FieldPermissions {
    /// Check if any permissions are required
    pub fn has_requirements(&self) -> bool {
        !self.required_roles.is_empty()
            || !self.required_permissions.is_empty()
            || !self.custom_checks.is_empty()
    }

    /// Merge permissions (for nested field requirements)
    pub fn merge(&mut self, other: &FieldPermissions) {
        self.required_roles.extend(other.required_roles.iter().cloned());
        self.required_permissions.extend(other.required_permissions.iter().cloned());
        self.custom_checks.extend(other.custom_checks.iter().cloned());

        // Remove duplicates
        self.required_roles.sort();
        self.required_roles.dedup();
        self.required_permissions.sort();
        self.required_permissions.dedup();
        self.custom_checks.sort();
        self.custom_checks.dedup();
    }
}

/// Parse permission string "resource:action"
fn parse_permission(perm: &str) -> Result<(String, String)> {
    let parts: Vec<&str> = perm.split(':').collect();
    if parts.len() != 2 || parts[0].is_empty() || parts[1].is_empty() {
        return Err(RbacError::InvalidPermissionFormat(perm.to_string()));
    }
    Ok((parts[0].to_string(), parts[1].to_string()))
}
