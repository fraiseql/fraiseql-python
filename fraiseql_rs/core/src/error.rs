//! Error types for `FraiseQL` core.
//!
//! These errors are language-agnostic and can be converted to
//! Python exceptions, JavaScript errors, etc. by binding layers.

use thiserror::Error;

/// Result type alias for `FraiseQL` operations.
pub type Result<T> = std::result::Result<T, FraiseQLError>;

/// Main error type for `FraiseQL` operations.
#[derive(Error, Debug)]
pub enum FraiseQLError {
    /// GraphQL parsing error.
    #[error("Parse error: {0}")]
    Parse(String),

    /// GraphQL validation error.
    #[error("Validation error: {0}")]
    Validation(String),

    /// Database operation error.
    #[error("Database error: {0}")]
    Database(String),

    /// Authorization error.
    #[error("Authorization error: {0}")]
    Authorization(String),

    /// Configuration error.
    #[error("Configuration error: {0}")]
    Configuration(String),

    /// Internal error.
    #[error("Internal error: {0}")]
    Internal(String),
}
