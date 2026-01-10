//! FFI wrapper modules for Python bindings.
//!
//! This module contains all PyO3 wrappers that connect Python code
//! to the pure Rust core library.

pub mod apq;     // Phase 6.4: APQ hasher FFI wrappers
pub mod errors;  // Phase 6.3: Error handling FFI wrappers
pub mod query;   // Phase 6.2: Query builder FFI wrappers
pub mod schema;  // Phase 6.1: Schema type FFI wrappers
