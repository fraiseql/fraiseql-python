//! Security-specific error types for comprehensive error handling (Phase 6.3).
//!
//! This module defines all security-related error types used throughout
//! the framework. No PyO3 decorators - all types are pure Rust.
//!
//! Note: The PyO3 FFI wrappers for Python are in `py/src/ffi/errors.rs`

use std::fmt;

/// Main security error type for all security operations.
///
/// Covers rate limiting, query validation, CORS, CSRF, audit logging,
/// and security configuration errors.
#[derive(Debug, Clone)]
pub enum SecurityError {
    /// Rate limiting exceeded - client has made too many requests.
    ///
    /// Contains:
    /// - `retry_after`: Seconds to wait before retrying
    /// - `limit`: Maximum allowed requests
    /// - `window_secs`: Time window in seconds
    RateLimitExceeded {
        /// Seconds to wait before retrying
        retry_after: u64,
        /// Maximum allowed requests
        limit: usize,
        /// Time window in seconds
        window_secs: u64,
    },

    /// Query validation: depth exceeds maximum allowed.
    ///
    /// GraphQL queries can nest arbitrarily deep, which can cause
    /// excessive database queries or resource consumption.
    QueryTooDeep {
        /// Actual query depth
        depth: usize,
        /// Maximum allowed depth
        max_depth: usize,
    },

    /// Query validation: complexity exceeds configured limit.
    ///
    /// Complexity is calculated as a weighted sum of field costs,
    /// accounting for pagination and nested selections.
    QueryTooComplex {
        /// Actual query complexity score
        complexity: usize,
        /// Maximum allowed complexity
        max_complexity: usize,
    },

    /// Query validation: size exceeds maximum allowed bytes.
    ///
    /// Very large queries can consume memory or cause DoS.
    QueryTooLarge {
        /// Actual query size in bytes
        size: usize,
        /// Maximum allowed size in bytes
        max_size: usize,
    },

    /// CORS origin not in allowed list.
    OriginNotAllowed(String),

    /// CORS HTTP method not allowed.
    MethodNotAllowed(String),

    /// CORS header not in allowed list.
    HeaderNotAllowed(String),

    /// CSRF token validation failed.
    InvalidCSRFToken(String),

    /// CSRF token session ID mismatch.
    CSRFSessionMismatch,

    /// Audit log write failure.
    ///
    /// Audit logging to the database failed. The underlying
    /// reason is captured in the error string.
    AuditLogFailure(String),

    /// Security configuration error.
    ///
    /// The security configuration is invalid or incomplete.
    SecurityConfigError(String),
}

/// Convenience type alias for security operation results.
///
/// Use `Result<T>` in security modules for consistent error handling.
pub type Result<T> = std::result::Result<T, SecurityError>;

impl fmt::Display for SecurityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::RateLimitExceeded {
                retry_after,
                limit,
                window_secs,
            } => {
                write!(
                    f,
                    "Rate limit exceeded. Limit: {limit} per {window_secs} seconds. Retry after: {retry_after} seconds"
                )
            }
            Self::QueryTooDeep { depth, max_depth } => {
                write!(f, "Query too deep: {depth} levels (max: {max_depth})")
            }
            Self::QueryTooComplex {
                complexity,
                max_complexity,
            } => {
                write!(f, "Query too complex: {complexity} (max: {max_complexity})")
            }
            Self::QueryTooLarge { size, max_size } => {
                write!(f, "Query too large: {size} bytes (max: {max_size})")
            }
            Self::OriginNotAllowed(origin) => {
                write!(f, "CORS origin not allowed: {origin}")
            }
            Self::MethodNotAllowed(method) => {
                write!(f, "CORS method not allowed: {method}")
            }
            Self::HeaderNotAllowed(header) => {
                write!(f, "CORS header not allowed: {header}")
            }
            Self::InvalidCSRFToken(reason) => {
                write!(f, "Invalid CSRF token: {reason}")
            }
            Self::CSRFSessionMismatch => {
                write!(f, "CSRF token session mismatch")
            }
            Self::AuditLogFailure(reason) => {
                write!(f, "Audit logging failed: {reason}")
            }
            Self::SecurityConfigError(reason) => {
                write!(f, "Security configuration error: {reason}")
            }
        }
    }
}

impl std::error::Error for SecurityError {}

impl PartialEq for SecurityError {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (
                Self::RateLimitExceeded {
                    retry_after: r1,
                    limit: l1,
                    window_secs: w1,
                },
                Self::RateLimitExceeded {
                    retry_after: r2,
                    limit: l2,
                    window_secs: w2,
                },
            ) => r1 == r2 && l1 == l2 && w1 == w2,
            (
                Self::QueryTooDeep { depth: d1, max_depth: m1 },
                Self::QueryTooDeep { depth: d2, max_depth: m2 },
            ) => d1 == d2 && m1 == m2,
            (
                Self::QueryTooComplex {
                    complexity: c1,
                    max_complexity: m1,
                },
                Self::QueryTooComplex {
                    complexity: c2,
                    max_complexity: m2,
                },
            ) => c1 == c2 && m1 == m2,
            (
                Self::QueryTooLarge { size: s1, max_size: m1 },
                Self::QueryTooLarge { size: s2, max_size: m2 },
            ) => s1 == s2 && m1 == m2,
            (Self::OriginNotAllowed(o1), Self::OriginNotAllowed(o2)) => o1 == o2,
            (Self::MethodNotAllowed(m1), Self::MethodNotAllowed(m2)) => m1 == m2,
            (Self::HeaderNotAllowed(h1), Self::HeaderNotAllowed(h2)) => h1 == h2,
            (Self::InvalidCSRFToken(r1), Self::InvalidCSRFToken(r2)) => r1 == r2,
            (Self::CSRFSessionMismatch, Self::CSRFSessionMismatch) => true,
            (Self::AuditLogFailure(r1), Self::AuditLogFailure(r2)) => r1 == r2,
            (Self::SecurityConfigError(r1), Self::SecurityConfigError(r2)) => r1 == r2,
            _ => false,
        }
    }
}

impl Eq for SecurityError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rate_limit_error_display() {
        let err = SecurityError::RateLimitExceeded {
            retry_after: 60,
            limit: 100,
            window_secs: 60,
        };

        assert!(err.to_string().contains("Rate limit exceeded"));
        assert!(err.to_string().contains("100"));
        assert!(err.to_string().contains("60"));
    }

    #[test]
    fn test_query_too_deep_display() {
        let err = SecurityError::QueryTooDeep {
            depth: 20,
            max_depth: 10,
        };

        assert!(err.to_string().contains("Query too deep"));
        assert!(err.to_string().contains("20"));
        assert!(err.to_string().contains("10"));
    }

    #[test]
    fn test_query_too_complex_display() {
        let err = SecurityError::QueryTooComplex {
            complexity: 500,
            max_complexity: 100,
        };

        assert!(err.to_string().contains("Query too complex"));
        assert!(err.to_string().contains("500"));
        assert!(err.to_string().contains("100"));
    }

    #[test]
    fn test_query_too_large_display() {
        let err = SecurityError::QueryTooLarge {
            size: 100000,
            max_size: 10000,
        };

        assert!(err.to_string().contains("Query too large"));
        assert!(err.to_string().contains("100000"));
        assert!(err.to_string().contains("10000"));
    }

    #[test]
    fn test_cors_errors() {
        let origin_err = SecurityError::OriginNotAllowed("https://evil.com".to_string());
        assert!(origin_err.to_string().contains("CORS origin"));

        let method_err = SecurityError::MethodNotAllowed("DELETE".to_string());
        assert!(method_err.to_string().contains("CORS method"));

        let header_err = SecurityError::HeaderNotAllowed("X-Custom".to_string());
        assert!(header_err.to_string().contains("CORS header"));
    }

    #[test]
    fn test_csrf_errors() {
        let invalid = SecurityError::InvalidCSRFToken("expired".to_string());
        assert!(invalid.to_string().contains("Invalid CSRF token"));

        let mismatch = SecurityError::CSRFSessionMismatch;
        assert!(mismatch.to_string().contains("session mismatch"));
    }

    #[test]
    fn test_audit_error() {
        let err = SecurityError::AuditLogFailure("connection timeout".to_string());
        assert!(err.to_string().contains("Audit logging failed"));
    }

    #[test]
    fn test_config_error() {
        let err = SecurityError::SecurityConfigError("missing config key".to_string());
        assert!(err.to_string().contains("Security configuration error"));
    }

    #[test]
    fn test_error_equality() {
        let err1 = SecurityError::QueryTooDeep {
            depth: 20,
            max_depth: 10,
        };
        let err2 = SecurityError::QueryTooDeep {
            depth: 20,
            max_depth: 10,
        };
        assert_eq!(err1, err2);

        let err3 = SecurityError::QueryTooDeep {
            depth: 30,
            max_depth: 10,
        };
        assert_ne!(err1, err3);
    }

    #[test]
    fn test_rate_limit_equality() {
        let err1 = SecurityError::RateLimitExceeded {
            retry_after: 60,
            limit: 100,
            window_secs: 60,
        };
        let err2 = SecurityError::RateLimitExceeded {
            retry_after: 60,
            limit: 100,
            window_secs: 60,
        };
        assert_eq!(err1, err2);
    }
}
