//! Database connectivity layer (pure Rust, no PyO3).
//!
//! This module provides pure Rust database layer with:
//! - Connection pooling (deadpool-postgres wrapper)
//! - Query execution with JSONB result handling
//! - Transaction management (ACID + savepoints)
//! - Health checks and metrics
//! - Error handling with rich context
//! - SSL/TLS support

// ============================================================================
// Core Error & Type Definitions (Leaf Nodes)
// ============================================================================

/// Error types for database operations
pub mod errors;

/// Type definitions for pool and queries
pub mod types;

/// Metrics and statistics
pub mod metrics;

/// Mutex recovery utilities
pub mod mutex_recovery;

/// Tokio runtime management
pub mod runtime;

/// Pool trait abstraction and implementations
pub mod pool;

// ============================================================================
// Configuration Modules (Phase 4.2)
// ============================================================================

/// Database pool configuration
pub mod pool_config;

/// Parameter binding and conversion
pub mod parameter_binding;

/// Query execution and caching
pub mod query;

// ============================================================================
// Production Pool Modules (Phase 4.3)
// ============================================================================

/// Production database pool implementation
pub mod pool_production;

/// Transaction management (ACID + savepoints)
pub mod transaction;

/// Health checks and pool status
pub mod health;

// ============================================================================
// Re-exports for convenient access
// ============================================================================

pub use errors::{DatabaseError, DatabaseResult};
pub use health::{HealthCheckResult, PoolHealthStats};
pub use metrics::PoolMetrics;
pub use mutex_recovery::recover_from_poisoned;
pub use pool::PoolBackend;
pub use pool_config::DatabaseConfig;
pub use pool_production::ProductionPool;
pub use transaction::Transaction;
pub use types::{PoolConfig, QueryParam};
