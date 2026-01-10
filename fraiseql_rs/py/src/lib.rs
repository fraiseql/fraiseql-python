//! `FraiseQL` Python Bindings (Phase 6.1 + Phase 6.2)
//!
//! This crate provides Python bindings for the `FraiseQL` core library.
//! It wraps pure Rust types with `PyO3` decorators.
//!
//! Architecture:
//! - fraiseql_core/: Pure Rust (no PyO3 dependencies)
//! - fraiseql_py/: FFI layer (PyO3 wrappers for core)
//! - Python API: Old imports for backward compat, new organized imports

mod ffi;

use ffi::query::{
    build_sql_query, build_sql_query_cached, clear_cache, get_cache_stats, PyCacheStats,
    PyGeneratedQuery, PyQueryBuilder,
};
use ffi::schema::{PySchemaMetadata, PyTableSchema};
use pyo3::prelude::*;

/// Module version.
const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Get the library version.
#[pyfunction]
fn version() -> &'static str {
    VERSION
}

/// Python module definition (Phase 6.1 + Phase 6.2).
#[pymodule]
fn _fraiseql_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;

    // Phase 6.1: Schema types (from FFI layer)
    m.add_class::<PyTableSchema>()?;
    m.add_class::<PySchemaMetadata>()?;

    // Phase 6.2: Query building (from FFI layer)
    m.add_class::<PyQueryBuilder>()?;
    m.add_class::<PyGeneratedQuery>()?;
    m.add_class::<PyCacheStats>()?;

    // Backward compatibility functions
    m.add_function(wrap_pyfunction!(build_sql_query, m)?)?;
    m.add_function(wrap_pyfunction!(build_sql_query_cached, m)?)?;
    m.add_function(wrap_pyfunction!(get_cache_stats, m)?)?;
    m.add_function(wrap_pyfunction!(clear_cache, m)?)?;

    // Classes will be added here as we migrate:
    // Phase 6.3: Error handling
    // Phase 6.4: APQ hasher
    // Phase 6.5: Full FFI bridge

    Ok(())
}
