//! GraphQL directive enforcement (@requiresRole, @requiresPermission).

use super::{
    errors::{RbacError, Result as RbacResult},
    field_auth::FieldPermissions,
};
use crate::graphql::types::{Directive, FieldSelection, ParsedQuery};

/// Extract RBAC directives from parsed query
pub struct DirectiveExtractor;

impl DirectiveExtractor {
    /// Extract all field permissions from parsed query
    pub fn extract_field_permissions(
        query: &ParsedQuery,
    ) -> RbacResult<Vec<(String, FieldPermissions)>> {
        let mut field_permissions = Vec::new();

        for selection in &query.selections {
            Self::extract_from_selection(selection, &mut field_permissions, Vec::new())?;
        }

        Ok(field_permissions)
    }

    /// Recursively extract permissions from field selection
    fn extract_from_selection(
        selection: &FieldSelection,
        permissions: &mut Vec<(String, FieldPermissions)>,
        path: Vec<String>,
    ) -> RbacResult<()> {
        let mut current_path = path;
        current_path.push(selection.name.clone());

        // Extract directives for this field
        let field_perms = Self::extract_directives(&selection.directives)?;
        if field_perms.has_requirements() {
            let field_path = current_path.join(".");
            permissions.push((field_path, field_perms));
        }

        // Recursively process nested fields
        for nested in &selection.nested_fields {
            Self::extract_from_selection(nested, permissions, current_path.clone())?;
        }

        Ok(())
    }

    /// Parse directives into FieldPermissions
    fn extract_directives(directives: &[Directive]) -> RbacResult<FieldPermissions> {
        let mut permissions = FieldPermissions::default();

        for directive in directives {
            match directive.name.as_str() {
                "requiresRole" => {
                    Self::parse_requires_role(directive, &mut permissions)?;
                },
                "requiresPermission" => {
                    Self::parse_requires_permission(directive, &mut permissions)?;
                },
                "requiresAllRoles" => {
                    Self::parse_requires_all_roles(directive, &mut permissions)?;
                },
                "requiresAnyPermission" => {
                    Self::parse_requires_any_permission(directive, &mut permissions)?;
                },
                _ => {
                    // Ignore other directives (like @include, @skip, @deprecated)
                },
            }
        }

        Ok(permissions)
    }

    /// Parse @requiresRole directive
    fn parse_requires_role(
        directive: &Directive,
        permissions: &mut FieldPermissions,
    ) -> RbacResult<()> {
        let role_arg =
            directive.arguments.iter().find(|arg| arg.name == "role").ok_or_else(|| {
                RbacError::DirectiveError(
                    "@requiresRole directive must have a 'role' argument".to_string(),
                )
            })?;

        let role_value = serde_json::from_str::<serde_json::Value>(&role_arg.value_json)
            .map_err(|_| RbacError::DirectiveError("Invalid role argument format".to_string()))?;

        let role_str = role_value.as_str().ok_or_else(|| {
            RbacError::DirectiveError("Role argument must be a string".to_string())
        })?;

        permissions.required_roles.push(role_str.to_string());
        Ok(())
    }

    /// Parse @requiresPermission directive
    fn parse_requires_permission(
        directive: &Directive,
        permissions: &mut FieldPermissions,
    ) -> RbacResult<()> {
        let perm_arg =
            directive.arguments.iter().find(|arg| arg.name == "permission").ok_or_else(|| {
                RbacError::DirectiveError(
                    "@requiresPermission directive must have a 'permission' argument".to_string(),
                )
            })?;

        let perm_value =
            serde_json::from_str::<serde_json::Value>(&perm_arg.value_json).map_err(|_| {
                RbacError::DirectiveError("Invalid permission argument format".to_string())
            })?;

        let perm_str = perm_value.as_str().ok_or_else(|| {
            RbacError::DirectiveError("Permission argument must be a string".to_string())
        })?;

        permissions.required_permissions.push(perm_str.to_string());
        Ok(())
    }

    /// Parse @requiresAllRoles directive
    fn parse_requires_all_roles(
        directive: &Directive,
        permissions: &mut FieldPermissions,
    ) -> RbacResult<()> {
        let roles_arg =
            directive.arguments.iter().find(|arg| arg.name == "roles").ok_or_else(|| {
                RbacError::DirectiveError(
                    "@requiresAllRoles directive must have a 'roles' argument".to_string(),
                )
            })?;

        let roles_value = serde_json::from_str::<serde_json::Value>(&roles_arg.value_json)
            .map_err(|_| RbacError::DirectiveError("Invalid roles argument format".to_string()))?;

        let roles_array = roles_value.as_array().ok_or_else(|| {
            RbacError::DirectiveError("Roles argument must be an array of strings".to_string())
        })?;

        for role_value in roles_array {
            if let Some(role_str) = role_value.as_str() {
                permissions.required_roles.push(role_str.to_string());
            }
        }

        Ok(())
    }

    /// Parse @requiresAnyPermission directive
    fn parse_requires_any_permission(
        directive: &Directive,
        permissions: &mut FieldPermissions,
    ) -> RbacResult<()> {
        let perms_arg = directive
            .arguments
            .iter()
            .find(|arg| arg.name == "permissions")
            .ok_or_else(|| {
                RbacError::DirectiveError(
                    "@requiresAnyPermission directive must have a 'permissions' argument"
                        .to_string(),
                )
            })?;

        let perms_value = serde_json::from_str::<serde_json::Value>(&perms_arg.value_json)
            .map_err(|_| {
                RbacError::DirectiveError("Invalid permissions argument format".to_string())
            })?;

        let perms_array = perms_value.as_array().ok_or_else(|| {
            RbacError::DirectiveError(
                "Permissions argument must be an array of strings".to_string(),
            )
        })?;

        for perm_value in perms_array {
            if let Some(perm_str) = perm_value.as_str() {
                permissions.required_permissions.push(perm_str.to_string());
            }
        }

        Ok(())
    }
}
