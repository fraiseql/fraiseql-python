//! Security features (Phase 5.5a + Phase 6.3 - Foundation & Error Handling)
//!
//! This module provides core security infrastructure:
//! - Security profiles (STANDARD, REGULATED)
//! - Security headers configuration
//! - Sensitive field masking for PII/regulated data
//! - Security error types (Phase 6.3 - pure Rust, no PyO3)

pub mod errors;           // Phase 6.3: Error types (moved from src/security/errors.rs)
pub mod field_masking;    // Phase 5.5a: Field masking
pub mod headers;          // Phase 5.5a: Security headers
pub mod profiles;         // Phase 5.5a: Security profiles

// Deferred modules:
// Phase 5.5b will add:
//   - validators      // Query validation (depends on errors)
//   - rate_limit      // Token bucket rate limiting
//   - response_limits // Response size enforcement
//   - error_redactor  // Error redaction logic
// Phase 5.5c will add:
//   - constraints     // IP filtering, rate limiting constraints
//   - cors           // CORS policy enforcement
//   - csrf           // CSRF token validation
// Phase 5.5d will add:
//   - audit          // Audit logging with database backend
//   - config         // Master security configuration
// Phase 5.5e deferred:
//   - py_bindings    // Python FFI layer

// Re-export key types for convenience
pub use errors::{Result, SecurityError};
pub use field_masking::{FieldMasker, FieldSensitivity};
pub use headers::SecurityHeaders;
pub use profiles::SecurityProfile;
