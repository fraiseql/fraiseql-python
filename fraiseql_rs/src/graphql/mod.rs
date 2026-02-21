//! GraphQL parsing and advanced features module.

pub mod complexity;
pub mod fragments;
pub mod parser;
pub mod types;
pub mod variables;

use pyo3::prelude::*;

use crate::graphql::{parser::parse_query, types::ParsedQuery};

/// Parse GraphQL query string into structured AST.
///
/// Called from Python: result = fraiseql_rs.parse_graphql_query(query_string)
#[pyfunction]
pub fn parse_graphql_query(_py: Python, query_string: String) -> PyResult<ParsedQuery> {
    match parse_query(&query_string) {
        Ok(parsed) => Ok(parsed),
        Err(e) => Err(PyErr::new::<pyo3::exceptions::PySyntaxError, _>(e.to_string())),
    }
}
