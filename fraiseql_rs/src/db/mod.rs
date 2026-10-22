//! Database connection and query execution layer for PostgreSQL.
//!
//! This module provides:
//! - Connection pooling with deadpool-postgres
//! - Query execution with streaming results
//! - Transaction management
//! - Connection lifecycle management
//!
//! Architecture:
//! - `pool.rs`: Connection pool management
//! - `transaction.rs`: ACID transaction support
//! - `types.rs`: Type definitions and configurations

pub mod pool;
pub mod transaction;
pub mod types;

pub use pool::DatabasePool;
pub use transaction::Transaction;
pub use types::*;
