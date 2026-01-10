//! `FraiseQL` Python Bindings (Phase 6.1+)
//!
//! This crate provides Python bindings for the `FraiseQL` core library.
//! It wraps pure Rust types with `PyO3` decorators.
//!
//! Architecture:
//! - fraiseql_core/: Pure Rust (no PyO3 dependencies)
//! - fraiseql_py/: FFI layer (PyO3 wrappers for core)
//! - Python API: Old imports for backward compat, new organized imports

mod ffi;

use ffi::schema::{PySchemaMetadata, PyTableSchema};
use pyo3::prelude::*;

/// Module version.
const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Get the library version.
#[pyfunction]
fn version() -> &'static str {
    VERSION
}

/// Python module definition (Phase 6.1: Schema extraction).
#[pymodule]
fn _fraiseql_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;

    // Phase 6.1: Schema types (from FFI layer)
    m.add_class::<PyTableSchema>()?;
    m.add_class::<PySchemaMetadata>()?;

    // Classes will be added here as we migrate:
    // Phase 6.2: QueryBuilder
    // Phase 6.3: Error handling
    // Phase 6.4: APQ hasher
    // Phase 6.5: Full FFI bridge

    Ok(())
}
