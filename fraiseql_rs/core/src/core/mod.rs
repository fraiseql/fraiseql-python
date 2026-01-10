//! Core transformation engine for zero-copy GraphQL JSON processing
//!
//! This module provides the foundation for ultra-fast JSON transformations
//! with minimal memory allocations and SIMD optimizations.

pub mod arena;
pub mod camel;
// transform.rs deferred to Phase 5.3 (depends on pipeline::projection)

// Re-export key types for convenience
pub use arena::Arena;
