//! `FraiseQL` Python Bindings
//!
//! This crate provides Python bindings for the `FraiseQL` core library.
//! It wraps pure Rust types with `PyO3` decorators.

use pyo3::prelude::*;

/// Module version.
const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Get the library version.
#[pyfunction]
fn version() -> &'static str {
    VERSION
}

/// Python module definition.
#[pymodule]
fn _fraiseql_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;

    // Classes will be added here as we migrate:
    // m.add_class::<PyGraphQLPipeline>()?;
    // m.add_class::<PyServer>()?;

    Ok(())
}
