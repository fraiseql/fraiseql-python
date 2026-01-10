//! `FraiseQL` Python Bindings (Phase 6.1-6.5: FFI Bridge Complete)
//!
//! This crate provides Python bindings for the `FraiseQL` core library.
//! It wraps pure Rust types with `PyO3` decorators in a clean FFI layer.
//!
//! Architecture:
//! - fraiseql_core/: Pure Rust (no PyO3 dependencies)
//! - fraiseql_py/: FFI layer (PyO3 wrappers for core, organized into submodules)
//! - Python API: Organized by submodule (schema, query, errors, apq)
//! - Backward compatible: Old top-level imports still work
//!
//! # Python API Usage
//!
//! **New organized API (recommended):**
//! ```python
//! from fraiseql_rs.schema import TableSchema, SchemaMetadata
//! from fraiseql_rs.query import QueryBuilder, build_sql_query
//! from fraiseql_rs.errors import SecurityError
//! from fraiseql_rs.apq import hash_query, verify_hash
//! ```
//!
//! **Old top-level API (still works - backward compatible):**
//! ```python
//! from fraiseql_rs import build_sql_query, hash_query, GeneratedQuery, version
//! ```

mod ffi;

use ffi::apq::{hash_query, hash_query_with_variables, verify_hash, verify_hash_with_variables};
use ffi::errors::PySecurityError;
use ffi::query::{
    build_sql_query, build_sql_query_cached, clear_cache, get_cache_stats, PyCacheStats,
    PyGeneratedQuery, PyQueryBuilder,
};
use ffi::schema::{PySchemaMetadata, PyTableSchema};
use pyo3::prelude::*;
use pyo3::types::PyModule as PyModuleType;

/// Module version.
const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Get the library version.
#[pyfunction]
fn version() -> &'static str {
    VERSION
}

/// Python module definition (Phase 6.5: Unified FFI Bridge).
///
/// Provides both:
/// 1. Organized submodule structure (new recommended API)
/// 2. Top-level backward compatibility (old API)
#[pymodule]
fn _fraiseql_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;

    // ==================================================================
    // PHASE 6.5: Organized submodule structure (NEW API)
    // ==================================================================

    // Schema submodule: Types for GraphQL schema handling
    let schema_module = PyModuleType::new(m.py(), "schema")?;
    schema_module.add_class::<PyTableSchema>()?;
    schema_module.add_class::<PySchemaMetadata>()?;
    m.add_submodule(&schema_module)?;

    // Query submodule: Query building and execution
    let query_module = PyModuleType::new(m.py(), "query")?;
    query_module.add_class::<PyQueryBuilder>()?;
    query_module.add_class::<PyGeneratedQuery>()?;
    query_module.add_class::<PyCacheStats>()?;
    query_module.add_function(wrap_pyfunction!(build_sql_query, &query_module)?)?;
    query_module.add_function(wrap_pyfunction!(build_sql_query_cached, &query_module)?)?;
    query_module.add_function(wrap_pyfunction!(get_cache_stats, &query_module)?)?;
    query_module.add_function(wrap_pyfunction!(clear_cache, &query_module)?)?;
    m.add_submodule(&query_module)?;

    // Errors submodule: Error types for security operations
    let errors_module = PyModuleType::new(m.py(), "errors")?;
    errors_module.add_class::<PySecurityError>()?;
    m.add_submodule(&errors_module)?;

    // APQ submodule: Automatic Persisted Queries
    let apq_module = PyModuleType::new(m.py(), "apq")?;
    apq_module.add_function(wrap_pyfunction!(hash_query, &apq_module)?)?;
    apq_module.add_function(wrap_pyfunction!(verify_hash, &apq_module)?)?;
    apq_module.add_function(wrap_pyfunction!(hash_query_with_variables, &apq_module)?)?;
    apq_module.add_function(wrap_pyfunction!(verify_hash_with_variables, &apq_module)?)?;
    m.add_submodule(&apq_module)?;

    // ==================================================================
    // BACKWARD COMPATIBILITY: Top-level exports (OLD API - STILL WORKS)
    // ==================================================================

    // Schema types at top level
    m.add_class::<PyTableSchema>()?;
    m.add_class::<PySchemaMetadata>()?;

    // Query types and functions at top level
    m.add_class::<PyQueryBuilder>()?;
    m.add_class::<PyGeneratedQuery>()?;
    m.add_class::<PyCacheStats>()?;
    m.add_function(wrap_pyfunction!(build_sql_query, m)?)?;
    m.add_function(wrap_pyfunction!(build_sql_query_cached, m)?)?;
    m.add_function(wrap_pyfunction!(get_cache_stats, m)?)?;
    m.add_function(wrap_pyfunction!(clear_cache, m)?)?;

    // Error types at top level
    m.add_class::<PySecurityError>()?;

    // APQ functions at top level
    m.add_function(wrap_pyfunction!(hash_query, m)?)?;
    m.add_function(wrap_pyfunction!(verify_hash, m)?)?;
    m.add_function(wrap_pyfunction!(hash_query_with_variables, m)?)?;
    m.add_function(wrap_pyfunction!(verify_hash_with_variables, m)?)?;

    Ok(())
}
