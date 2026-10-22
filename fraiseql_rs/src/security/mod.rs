//! Security Features & Enterprise Hardening
//!
//! This module provides comprehensive security features for production deployment:
//! - Rate limiting (token bucket algorithm)
//! - Security headers enforcement
//! - Async audit logging
//! - CORS policy enforcement

pub mod audit;
pub mod cors;
pub mod errors;
pub mod headers;
pub mod rate_limit;

pub use audit::{AuditEvent, AuditEventType, AuditLogger};
pub use cors::{CORSConfig, CORSHandler};
pub use errors::{Result, SecurityError};
pub use headers::SecurityHeaders;
pub use rate_limit::{RateLimit, RateLimitStrategy, RateLimiter};
