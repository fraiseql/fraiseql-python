//! FFI wrapper modules for Python bindings.
//!
//! This module contains all PyO3 wrappers that connect Python code
//! to the pure Rust core library.

pub mod query;   // Phase 6.2: Query builder FFI wrappers
pub mod schema;  // Phase 6.1: Schema type FFI wrappers
