//! Pool backend trait abstraction and implementations.
//!
//! This module provides:
//! - `PoolBackend` trait for database pool abstraction
//! - Error types for pool operations
//! - Support for swapping pool implementations

pub mod traits;

pub use traits::{PoolBackend, PoolError, PoolResult};
