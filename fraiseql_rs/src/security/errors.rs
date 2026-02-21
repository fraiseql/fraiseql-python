//! Security-specific error types for comprehensive error handling.

use std::fmt;

/// Main security error type
#[derive(Debug)]
pub enum SecurityError {
    /// Rate limiting errors
    RateLimitExceeded {
        retry_after: u64,
        limit:       usize,
        window_secs: u64,
    },

    /// Query validation errors
    QueryTooDeep {
        depth:     usize,
        max_depth: usize,
    },

    QueryTooComplex {
        complexity:     usize,
        max_complexity: usize,
    },

    QueryTooLarge {
        size:     usize,
        max_size: usize,
    },

    /// CORS errors
    OriginNotAllowed(String),
    MethodNotAllowed(String),
    HeaderNotAllowed(String),

    /// CSRF errors
    InvalidCSRFToken(String),
    CSRFSessionMismatch,

    /// Audit logging errors
    AuditLogFailure(String),

    /// Configuration errors
    SecurityConfigError(String),
}

pub type Result<T> = std::result::Result<T, SecurityError>;

impl fmt::Display for SecurityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SecurityError::RateLimitExceeded {
                retry_after,
                limit,
                window_secs,
            } => {
                write!(
                    f,
                    "Rate limit exceeded. Limit: {} per {} seconds. Retry after: {} seconds",
                    limit, window_secs, retry_after
                )
            },
            SecurityError::QueryTooDeep { depth, max_depth } => {
                write!(f, "Query too deep: {} levels (max: {})", depth, max_depth)
            },
            SecurityError::QueryTooComplex {
                complexity,
                max_complexity,
            } => {
                write!(f, "Query too complex: {} (max: {})", complexity, max_complexity)
            },
            SecurityError::QueryTooLarge { size, max_size } => {
                write!(f, "Query too large: {} bytes (max: {})", size, max_size)
            },
            SecurityError::OriginNotAllowed(origin) => {
                write!(f, "CORS origin not allowed: {}", origin)
            },
            SecurityError::MethodNotAllowed(method) => {
                write!(f, "CORS method not allowed: {}", method)
            },
            SecurityError::HeaderNotAllowed(header) => {
                write!(f, "CORS header not allowed: {}", header)
            },
            SecurityError::InvalidCSRFToken(reason) => {
                write!(f, "Invalid CSRF token: {}", reason)
            },
            SecurityError::CSRFSessionMismatch => {
                write!(f, "CSRF token session mismatch")
            },
            SecurityError::AuditLogFailure(reason) => {
                write!(f, "Audit logging failed: {}", reason)
            },
            SecurityError::SecurityConfigError(reason) => {
                write!(f, "Security configuration error: {}", reason)
            },
        }
    }
}

impl std::error::Error for SecurityError {}

impl From<tokio_postgres::Error> for SecurityError {
    fn from(error: tokio_postgres::Error) -> Self {
        SecurityError::AuditLogFailure(error.to_string())
    }
}

impl From<deadpool::managed::PoolError<tokio_postgres::Error>> for SecurityError {
    fn from(error: deadpool::managed::PoolError<tokio_postgres::Error>) -> Self {
        SecurityError::AuditLogFailure(error.to_string())
    }
}

#[cfg(feature = "python")]
impl From<SecurityError> for pyo3::PyErr {
    fn from(error: SecurityError) -> Self {
        use pyo3::exceptions::*;

        match error {
            SecurityError::RateLimitExceeded { .. } => PyException::new_err(error.to_string()),
            SecurityError::QueryTooDeep { .. }
            | SecurityError::QueryTooComplex { .. }
            | SecurityError::QueryTooLarge { .. } => PyValueError::new_err(error.to_string()),
            SecurityError::OriginNotAllowed(_)
            | SecurityError::MethodNotAllowed(_)
            | SecurityError::HeaderNotAllowed(_) => PyPermissionError::new_err(error.to_string()),
            _ => PyRuntimeError::new_err(error.to_string()),
        }
    }
}
