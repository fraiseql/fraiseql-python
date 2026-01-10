//! Automatic Persisted Queries (APQ) infrastructure (Phase 5.4).
//!
//! APQ is a GraphQL optimization technique that allows clients to:
//! 1. Hash queries and send only the hash on subsequent requests
//! 2. Server responds with original query if not cached
//! 3. Reduces bandwidth for frequently-used queries
//!
//! # Security Considerations
//!
//! Cache keys MUST include variables to prevent data leakage between requests
//! with different variable values.
//!
//! # Module Contents
//!
//! - **storage**: APQ result storage and retrieval
//! - **metrics**: APQ performance metrics and monitoring

pub mod metrics;
pub mod storage;

// Deferred modules:
// pub mod hasher;  // Has #[pyfunction] decorator - kept in py bindings layer

// Re-export key types for convenience
pub use metrics::ApqMetrics;
pub use storage::{ApqError, ApqStats, ApqStorage};
