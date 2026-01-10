//! PyO3 FFI wrapper for schema types (Phase 6.1).
//!
//! This module provides Python bindings for the pure Rust schema types
//! defined in fraiseql_core::query::schema.
//!
//! Note: Users interact with schema via JSON strings, not Python objects.
//! These wrappers are internal FFI implementation details.

use fraiseql_core::query::schema::{
    SchemaMetadata as CoreSchemaMetadata, TableSchema as CoreTableSchema,
};
use pyo3::prelude::*;
use std::collections::HashMap;

/// Python wrapper for TableSchema (internal FFI type).
///
/// This class is not typically instantiated directly by users.
/// Schema is usually passed as JSON strings.
#[pyclass(name = "TableSchema")]
#[derive(Debug, Clone)]
pub struct PyTableSchema {
    inner: CoreTableSchema,
}

#[pymethods]
impl PyTableSchema {
    /// Get the view name.
    #[getter]
    fn view_name(&self) -> String {
        self.inner.view_name.clone()
    }

    /// Get the SQL columns.
    #[getter]
    fn sql_columns(&self) -> Vec<String> {
        self.inner.sql_columns.clone()
    }

    /// Get the JSONB column name.
    #[getter]
    fn jsonb_column(&self) -> String {
        self.inner.jsonb_column.clone()
    }

    /// Get the foreign key mappings.
    #[getter]
    fn fk_mappings(&self) -> HashMap<String, String> {
        self.inner.fk_mappings.clone()
    }

    /// Check if table has JSONB data.
    #[getter]
    fn has_jsonb_data(&self) -> bool {
        self.inner.has_jsonb_data
    }

    /// Get the pre-compiled WHERE SQL if present.
    #[getter]
    fn where_sql(&self) -> Option<String> {
        self.inner.where_sql.clone()
    }

    /// Get the ORDER BY clauses.
    #[getter]
    fn order_by(&self) -> Vec<(String, String)> {
        self.inner.order_by.clone()
    }

    /// Check if a field is a SQL column.
    ///
    /// # Arguments
    /// * `field_name` - The field name to check
    ///
    /// # Returns
    /// True if the field is a direct SQL column
    fn is_sql_column(&self, field_name: &str) -> bool {
        self.inner.is_sql_column(field_name)
    }
}

/// Convert core TableSchema to Python wrapper.
impl From<CoreTableSchema> for PyTableSchema {
    fn from(schema: CoreTableSchema) -> Self {
        PyTableSchema { inner: schema }
    }
}

/// Convert Python wrapper back to core TableSchema.
impl From<PyTableSchema> for CoreTableSchema {
    fn from(py_schema: PyTableSchema) -> Self {
        py_schema.inner
    }
}

/// Python wrapper for SchemaMetadata (internal FFI type).
///
/// This class is not typically instantiated directly by users.
/// Schema is usually passed as JSON strings.
#[pyclass(name = "SchemaMetadata")]
#[derive(Debug, Clone)]
pub struct PySchemaMetadata {
    inner: CoreSchemaMetadata,
}

#[pymethods]
impl PySchemaMetadata {
    /// Get all tables in the schema.
    #[getter]
    fn tables(&self) -> HashMap<String, PyTableSchema> {
        self.inner
            .tables
            .iter()
            .map(|(k, v)| (k.clone(), PyTableSchema::from(v.clone())))
            .collect()
    }

    /// Get a table schema by name.
    ///
    /// # Arguments
    /// * `view_name` - The view name to look up
    ///
    /// # Returns
    /// The table schema if found, None otherwise
    fn get_table(&self, view_name: &str) -> Option<PyTableSchema> {
        self.inner
            .get_table(view_name)
            .map(|t| PyTableSchema::from(t.clone()))
    }

    /// Check if a field is a SQL column.
    ///
    /// # Arguments
    /// * `view_name` - The view name
    /// * `field_name` - The field name
    ///
    /// # Returns
    /// True if the field is a direct SQL column
    fn is_sql_column(&self, view_name: &str, field_name: &str) -> bool {
        self.inner.is_sql_column(view_name, field_name)
    }

    /// Check if a field is a foreign key.
    ///
    /// # Arguments
    /// * `view_name` - The view name
    /// * `field_name` - The field name
    ///
    /// # Returns
    /// True if the field is a foreign key
    fn is_foreign_key(&self, view_name: &str, field_name: &str) -> bool {
        self.inner.is_foreign_key(view_name, field_name)
    }

    /// Get the foreign key column name.
    ///
    /// # Arguments
    /// * `view_name` - The view name
    /// * `field_name` - The field name
    ///
    /// # Returns
    /// The column name if this is a foreign key
    fn get_fk_column(&self, view_name: &str, field_name: &str) -> Option<String> {
        self.inner.get_fk_column(view_name, field_name)
    }
}

/// Convert core SchemaMetadata to Python wrapper.
impl From<CoreSchemaMetadata> for PySchemaMetadata {
    fn from(schema: CoreSchemaMetadata) -> Self {
        PySchemaMetadata { inner: schema }
    }
}

/// Convert Python wrapper back to core SchemaMetadata.
impl From<PySchemaMetadata> for CoreSchemaMetadata {
    fn from(py_schema: PySchemaMetadata) -> Self {
        py_schema.inner
    }
}

/// Convert JSON string to SchemaMetadata (Phase 6.1).
///
/// This is the primary way users pass schemas through the FFI boundary.
/// JSON is more portable and easier to debug than binary serialization.
///
/// # Arguments
/// * `schema_json` - JSON string containing the schema definition
///
/// # Returns
/// SchemaMetadata parsed from JSON
///
/// # Errors
/// Returns PyErr if JSON parsing fails
pub fn schema_from_json(schema_json: &str) -> PyResult<CoreSchemaMetadata> {
    serde_json::from_str(schema_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid schema JSON: {}", e)))
}

/// Convert SchemaMetadata to JSON string.
///
/// # Arguments
/// * `schema` - The schema metadata to serialize
///
/// # Returns
/// JSON string representation of the schema
///
/// # Errors
/// Returns PyErr if JSON serialization fails
pub fn schema_to_json(schema: &CoreSchemaMetadata) -> PyResult<String> {
    serde_json::to_string(schema).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("Schema serialization failed: {}", e))
    })
}
