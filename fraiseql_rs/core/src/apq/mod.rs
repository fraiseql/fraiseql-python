//! Automatic Persisted Queries (APQ) infrastructure (Phase 5.4 + Phase 6.4).
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
//! - **hasher**: Query hashing with SHA-256 (Phase 6.4 - pure Rust, no PyO3)
//! - **storage**: APQ result storage and retrieval
//! - **metrics**: APQ performance metrics and monitoring

pub mod hasher;  // Phase 6.4: Pure Rust query hasher
pub mod metrics;
pub mod storage;

// Re-export key types for convenience
pub use hasher::{hash_query, hash_query_with_variables, verify_hash, verify_hash_with_variables};
pub use metrics::ApqMetrics;
pub use storage::{ApqError, ApqStats, ApqStorage};
