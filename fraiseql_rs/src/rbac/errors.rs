//! RBAC-specific error types for better error handling.

use std::fmt;

/// Main RBAC error type
#[derive(Debug)]
pub enum RbacError {
    /// Database connection or query errors
    Database(String),

    /// Permission denied for specific resource:action
    PermissionDenied {
        resource: String,
        action:   String,
        user_id:  Option<String>,
    },

    /// Missing required role
    MissingRole {
        required_role:   String,
        available_roles: Vec<String>,
    },

    /// User not found in RBAC system
    UserNotFound(String),

    /// Role not found
    RoleNotFound(String),

    /// Permission not found
    PermissionNotFound(String),

    /// Invalid permission format (expected "resource:action")
    InvalidPermissionFormat(String),

    /// Role hierarchy cycle detected
    HierarchyCycle(Vec<String>),

    /// Cache-related errors
    CacheError(String),

    /// Configuration errors
    ConfigError(String),

    /// GraphQL directive parsing errors
    DirectiveError(String),
}

pub type Result<T> = std::result::Result<T, RbacError>;

impl fmt::Display for RbacError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RbacError::Database(e) => write!(f, "Database error: {}", e),
            RbacError::PermissionDenied {
                resource,
                action,
                user_id,
            } => {
                if let Some(user) = user_id {
                    write!(f, "Permission denied: {}:{} for user {}", resource, action, user)
                } else {
                    write!(f, "Permission denied: {}:{}", resource, action)
                }
            },
            RbacError::MissingRole {
                required_role,
                available_roles,
            } => {
                write!(
                    f,
                    "Missing required role '{}'. Available roles: {:?}",
                    required_role, available_roles
                )
            },
            RbacError::UserNotFound(user_id) => {
                write!(f, "User not found in RBAC system: {}", user_id)
            },
            RbacError::RoleNotFound(role_name) => {
                write!(f, "Role not found: {}", role_name)
            },
            RbacError::PermissionNotFound(perm) => {
                write!(f, "Permission not found: {}", perm)
            },
            RbacError::InvalidPermissionFormat(perm) => {
                write!(f, "Invalid permission format '{}'. Expected 'resource:action'", perm)
            },
            RbacError::HierarchyCycle(roles) => {
                write!(f, "Role hierarchy cycle detected: {:?}", roles)
            },
            RbacError::CacheError(msg) => write!(f, "Cache error: {}", msg),
            RbacError::ConfigError(msg) => write!(f, "Configuration error: {}", msg),
            RbacError::DirectiveError(msg) => write!(f, "Directive parsing error: {}", msg),
        }
    }
}

impl std::error::Error for RbacError {}

impl From<uuid::Error> for RbacError {
    fn from(error: uuid::Error) -> Self {
        RbacError::ConfigError(format!("UUID parsing error: {}", error))
    }
}

impl From<tokio_postgres::Error> for RbacError {
    fn from(error: tokio_postgres::Error) -> Self {
        RbacError::Database(error.to_string())
    }
}

impl From<deadpool::managed::PoolError<tokio_postgres::Error>> for RbacError {
    fn from(error: deadpool::managed::PoolError<tokio_postgres::Error>) -> Self {
        RbacError::Database(error.to_string())
    }
}

#[cfg(feature = "python")]
impl From<RbacError> for pyo3::PyErr {
    fn from(error: RbacError) -> Self {
        use pyo3::exceptions::*;

        match error {
            RbacError::PermissionDenied { .. } => PyPermissionError::new_err(error.to_string()),
            RbacError::Database(_) => PyRuntimeError::new_err(error.to_string()),
            RbacError::UserNotFound(_) => PyValueError::new_err(error.to_string()),
            _ => PyRuntimeError::new_err(error.to_string()),
        }
    }
}
