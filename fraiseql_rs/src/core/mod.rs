//! Core transformation engine for zero-copy GraphQL JSON processing
//!
//! This module provides the foundation for ultra-fast JSON transformations
//! with minimal memory allocations and SIMD optimizations.

pub mod camel;
pub mod transform;

// Re-export key types for convenience
pub use camel::snake_to_camel;
pub use transform::{ByteBuf, TransformConfig, ZeroCopyTransformer};
