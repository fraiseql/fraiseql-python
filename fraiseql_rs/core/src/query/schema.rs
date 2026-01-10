//! Schema metadata for query building (Pure Rust - Phase 6.1).
//!
//! This module defines the core schema types for `FraiseQL`.
//! No `PyO3` decorators - all types are pure Rust and JSON-serializable.
//!
//! Note: The `#[pyclass]` wrappers for Python binding are in `py/src/ffi/schema.rs`

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// ID policy for the schema - defines how primary keys are handled.
///
/// Determines whether the schema uses `UUID`-based or opaque identifiers.
#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "UPPERCASE")]
pub enum IDPolicy {
    /// UUID-based identifiers
    #[default]
    UUID,
    /// Opaque identifiers
    OPAQUE,
}

/// Schema metadata for all tables in `FraiseQL`.
///
/// Contains the mapping of table view names to their schemas,
/// type definitions, and the ID policy for the schema.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SchemaMetadata {
    /// Map of table view names to their schemas
    pub tables: HashMap<String, TableSchema>,
    /// Map of type names to their definitions
    pub types: HashMap<String, TypeDefinition>,
    /// ID policy for the schema (UUID or OPAQUE)
    #[serde(default)]
    pub id_policy: IDPolicy,
}

/// Schema for a single database view/table.
///
/// Contains metadata about the table including column names,
/// foreign key mappings, and optional pre-compiled WHERE/ORDER BY clauses.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TableSchema {
    /// View name (e.g., "`v_users`")
    pub view_name: String,

    /// Direct SQL columns (e.g., `["id", "email", "status"]`)
    pub sql_columns: Vec<String>,

    /// JSONB column name (e.g., "data")
    pub jsonb_column: String,

    /// Map from field name to FK column
    pub fk_mappings: HashMap<String, String>,

    /// Whether table has JSONB data column
    pub has_jsonb_data: bool,

    /// Pre-compiled WHERE SQL (Phase 7.1)
    /// Optional WHERE clause already compiled to SQL by Python
    #[serde(default)]
    pub where_sql: Option<String>,

    /// ORDER BY clauses (Phase 7.1)
    /// List of (`field_name`, `direction`) tuples
    #[serde(default)]
    pub order_by: Vec<(String, String)>,
}

/// Type definition for GraphQL types.
///
/// Defines the fields and their types for a GraphQL object type.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TypeDefinition {
    /// Type name
    pub name: String,
    /// Map from field name to field type
    pub fields: HashMap<String, FieldType>,
}

/// Field type information.
///
/// Contains information about a single field's GraphQL and SQL types.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FieldType {
    /// GraphQL type name
    pub graphql_type: String,
    /// SQL type name
    pub sql_type: String,
    /// Whether field is a scalar type
    pub is_scalar: bool,
    /// Whether field is a list type
    pub is_list: bool,
}

impl SchemaMetadata {
    /// Get table schema by view name.
    ///
    /// # Arguments
    /// * `view_name` - The name of the view to look up
    ///
    /// # Returns
    /// A reference to the table schema if found, otherwise None
    #[must_use]
    pub fn get_table(&self, view_name: &str) -> Option<&TableSchema> {
        self.tables.get(view_name)
    }

    /// Iterate over all tables in the schema.
    ///
    /// # Returns
    /// An iterator over `(view_name, TableSchema)` pairs
    pub fn iter_tables(&self) -> impl Iterator<Item = (&String, &TableSchema)> {
        self.tables.iter()
    }

    /// Check if field is a direct SQL column.
    ///
    /// # Arguments
    /// * `view_name` - The name of the view
    /// * `field_name` - The name of the field
    ///
    /// # Returns
    /// True if the field is a direct SQL column in the table
    #[must_use]
    pub fn is_sql_column(&self, view_name: &str, field_name: &str) -> bool {
        self.get_table(view_name)
            .is_some_and(|t| t.sql_columns.contains(&field_name.to_string()))
    }

    /// Check if field is a foreign key.
    ///
    /// # Arguments
    /// * `view_name` - The name of the view
    /// * `field_name` - The name of the field
    ///
    /// # Returns
    /// True if the field is a foreign key
    #[must_use]
    pub fn is_foreign_key(&self, view_name: &str, field_name: &str) -> bool {
        self.get_table(view_name)
            .is_some_and(|t| t.fk_mappings.contains_key(field_name))
    }

    /// Get foreign key column name.
    ///
    /// # Arguments
    /// * `view_name` - The name of the view
    /// * `field_name` - The name of the field
    ///
    /// # Returns
    /// The column name for the foreign key if found
    #[must_use]
    pub fn get_fk_column(&self, view_name: &str, field_name: &str) -> Option<String> {
        self.get_table(view_name)
            .and_then(|t| t.fk_mappings.get(field_name).cloned())
    }
}

impl TableSchema {
    /// Get SQL columns for this table.
    ///
    /// # Returns
    /// A slice of SQL column names
    #[must_use]
    pub fn get_sql_columns(&self) -> &[String] {
        &self.sql_columns
    }

    /// Get foreign key mappings for this table.
    ///
    /// # Returns
    /// A reference to the foreign key mappings
    #[must_use]
    pub fn get_fk_mappings(&self) -> &HashMap<String, String> {
        &self.fk_mappings
    }

    /// Check if a field is a SQL column.
    ///
    /// # Arguments
    /// * `field_name` - The name of the field
    ///
    /// # Returns
    /// True if the field is a direct SQL column
    #[must_use]
    pub fn is_sql_column(&self, field_name: &str) -> bool {
        self.sql_columns.contains(&field_name.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_schema_metadata_get_table() {
        let mut tables = HashMap::new();
        let table = TableSchema {
            view_name: "v_users".to_string(),
            sql_columns: vec!["id".to_string(), "name".to_string()],
            jsonb_column: "data".to_string(),
            fk_mappings: HashMap::new(),
            has_jsonb_data: true,
            where_sql: None,
            order_by: vec![],
        };
        tables.insert("v_users".to_string(), table);

        let schema = SchemaMetadata {
            tables,
            types: HashMap::new(),
            id_policy: IDPolicy::UUID,
        };

        assert!(schema.get_table("v_users").is_some());
        assert!(schema.get_table("v_other").is_none());
    }

    #[test]
    fn test_schema_metadata_is_sql_column() {
        let mut tables = HashMap::new();
        let table = TableSchema {
            view_name: "v_users".to_string(),
            sql_columns: vec!["id".to_string(), "email".to_string()],
            jsonb_column: "data".to_string(),
            fk_mappings: HashMap::new(),
            has_jsonb_data: false,
            where_sql: None,
            order_by: vec![],
        };
        tables.insert("v_users".to_string(), table);

        let schema = SchemaMetadata {
            tables,
            types: HashMap::new(),
            id_policy: IDPolicy::OPAQUE,
        };

        assert!(schema.is_sql_column("v_users", "id"));
        assert!(schema.is_sql_column("v_users", "email"));
        assert!(!schema.is_sql_column("v_users", "nonexistent"));
        assert!(!schema.is_sql_column("v_other", "id"));
    }

    #[test]
    fn test_table_schema_is_sql_column() {
        let table = TableSchema {
            view_name: "v_users".to_string(),
            sql_columns: vec!["id".to_string(), "name".to_string()],
            jsonb_column: "data".to_string(),
            fk_mappings: HashMap::new(),
            has_jsonb_data: true,
            where_sql: None,
            order_by: vec![],
        };

        assert!(table.is_sql_column("id"));
        assert!(table.is_sql_column("name"));
        assert!(!table.is_sql_column("nonexistent"));
    }

    #[test]
    fn test_schema_serialization() {
        let mut tables = HashMap::new();
        let table = TableSchema {
            view_name: "v_users".to_string(),
            sql_columns: vec!["id".to_string()],
            jsonb_column: "data".to_string(),
            fk_mappings: HashMap::new(),
            has_jsonb_data: true,
            where_sql: None,
            order_by: vec![],
        };
        tables.insert("v_users".to_string(), table);

        let schema = SchemaMetadata {
            tables,
            types: HashMap::new(),
            id_policy: IDPolicy::UUID,
        };

        // Serialize to JSON
        let json_str = serde_json::to_string(&schema).expect("Serialization failed");

        // Deserialize back
        let restored: SchemaMetadata =
            serde_json::from_str(&json_str).expect("Deserialization failed");

        // Verify
        assert_eq!(restored.id_policy, IDPolicy::UUID);
        assert!(restored.get_table("v_users").is_some());
    }
}
