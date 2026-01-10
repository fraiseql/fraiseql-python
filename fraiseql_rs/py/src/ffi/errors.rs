//! PyO3 FFI wrapper for security errors (Phase 6.3).
//!
//! This module provides Python bindings for the pure Rust security error types
//! defined in fraiseql_core::security::errors.
//!
//! Note: The pure error types are in core/src/security/errors.rs

use fraiseql_core::security::errors::SecurityError;
use pyo3::prelude::*;
use pyo3::exceptions::{PyException, PyPermissionError, PyRuntimeError, PyValueError};

/// Python wrapper for SecurityError.
///
/// Maps Rust security errors to appropriate Python exception types.
#[pyclass(name = "SecurityError", extends = PyException)]
#[derive(Debug, Clone)]
pub struct PySecurityError {
    message: String,
}

#[pymethods]
impl PySecurityError {
    /// Create a new security error.
    #[new]
    fn new(message: String) -> Self {
        PySecurityError { message }
    }

    /// Get the error message.
    fn get_message(&self) -> String {
        self.message.clone()
    }

    /// String representation.
    fn __str__(&self) -> String {
        self.message.clone()
    }

    /// Representation.
    fn __repr__(&self) -> String {
        format!("SecurityError({})", self.message)
    }
}

/// Convert SecurityError to appropriate Python exception.
///
/// Maps different SecurityError variants to appropriate Python exception types:
/// - RateLimitExceeded → PyException
/// - Query validation → PyValueError
/// - CORS/CSRF → PyPermissionError
/// - Audit/Config → PyRuntimeError
pub fn convert_security_error_to_py(error: &SecurityError) -> PyErr {
    let message = error.to_string();

    match error {
        // Rate limiting → Custom exception
        SecurityError::RateLimitExceeded { .. } => {
            PyException::new_err(message)
        }

        // Query validation → ValueError (wrong input)
        SecurityError::QueryTooDeep { .. }
        | SecurityError::QueryTooComplex { .. }
        | SecurityError::QueryTooLarge { .. } => {
            PyValueError::new_err(message)
        }

        // CORS/CSRF → PermissionError (access denied)
        SecurityError::OriginNotAllowed(_)
        | SecurityError::MethodNotAllowed(_)
        | SecurityError::HeaderNotAllowed(_)
        | SecurityError::InvalidCSRFToken(_)
        | SecurityError::CSRFSessionMismatch => {
            PyPermissionError::new_err(message)
        }

        // Audit/Config → RuntimeError (internal issue)
        SecurityError::AuditLogFailure(_)
        | SecurityError::SecurityConfigError(_) => {
            PyRuntimeError::new_err(message)
        }
    }
}

/// Helper function to convert SecurityError to appropriate Python exception.
///
/// # Arguments
/// * `error` - The Rust SecurityError to convert
///
/// # Returns
/// A PyErr ready to be raised in Python
#[pyfunction]
pub fn security_error_to_py(error: &str) -> PyErr {
    // Generic conversion when we have just a message
    PyException::new_err(error.to_string())
}

/// Python module to expose security error handling.
///
/// This is called during module initialization in `py/src/lib.rs`
pub fn register_error_classes(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySecurityError>()?;
    m.add_function(wrap_pyfunction!(security_error_to_py, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use fraiseql_core::security::errors::SecurityError;

    #[test]
    fn test_security_error_to_py_rate_limit() {
        let err = SecurityError::RateLimitExceeded {
            retry_after: 60,
            limit: 100,
            window_secs: 60,
        };

        let _py_err = convert_security_error_to_py(&err);
        // Just verify the conversion doesn't panic
        assert_eq!(err.to_string(), "Rate limit exceeded. Limit: 100 per 60 seconds. Retry after: 60 seconds");
    }

    #[test]
    fn test_security_error_to_py_query_too_deep() {
        let err = SecurityError::QueryTooDeep {
            depth: 20,
            max_depth: 10,
        };

        let _py_err = convert_security_error_to_py(&err);
        // Just verify the conversion doesn't panic
        assert!(err.to_string().contains("too deep"));
    }

    #[test]
    fn test_security_error_to_py_cors() {
        let err = SecurityError::OriginNotAllowed("https://evil.com".to_string());
        let _py_err = convert_security_error_to_py(&err);
        // Just verify the conversion doesn't panic
        assert!(err.to_string().contains("CORS"));
    }

    #[test]
    fn test_py_security_error_creation() {
        let err = PySecurityError::new("test error".to_string());
        assert_eq!(err.message, "test error");
        assert_eq!(err.get_message(), "test error");
    }

    #[test]
    fn test_py_security_error_string() {
        let err = PySecurityError::new("test error".to_string());
        assert_eq!(err.__str__(), "test error");
        assert_eq!(err.__repr__(), "SecurityError(test error)");
    }
}
