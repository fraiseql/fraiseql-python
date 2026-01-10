//! Security features (Phase 5.5a - Foundation)
//!
//! This module provides core security infrastructure:
//! - Security profiles (STANDARD, REGULATED)
//! - Security headers configuration
//! - Sensitive field masking for PII/regulated data

pub mod field_masking;
pub mod headers;
pub mod profiles;

// Deferred modules:
// Phase 5.5b will add:
//   - validators      // Query validation (depth, complexity, size)
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
//   - errors         // Security error types
// Phase 5.5e deferred:
//   - py_bindings    // Python FFI layer

// Re-export key types for convenience
pub use field_masking::{FieldMasker, FieldSensitivity};
pub use headers::SecurityHeaders;
pub use profiles::SecurityProfile;
