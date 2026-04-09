//! GraphQL AST types for query representation.

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

/// Parsed GraphQL query in Rust.
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParsedQuery {
    #[pyo3(get)]
    pub operation_type: String, // "query" | "mutation"

    #[pyo3(get)]
    pub operation_name: Option<String>,

    #[pyo3(get)]
    pub root_field: String, // First field in selection set

    #[pyo3(get)]
    pub selections: Vec<FieldSelection>,

    #[pyo3(get)]
    pub variables: Vec<VariableDefinition>,

    #[pyo3(get)]
    pub fragments: Vec<FragmentDefinition>, // Fragment definitions

    #[pyo3(get)]
    pub source: String, // Original query string (for caching key)
}

#[pymethods]
impl ParsedQuery {
    /// Get query signature for caching (ignores variables).
    pub fn signature(&self) -> String {
        // Used by Phase 8 for query plan caching
        format!("{}::{}", self.operation_type, self.root_field)
    }

    /// Check if query is cacheable (no variables).
    pub fn is_cacheable(&self) -> bool {
        self.variables.is_empty()
    }
}

/// Field selection in GraphQL query.
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FieldSelection {
    #[pyo3(get)]
    pub name: String, // GraphQL field name (e.g., "users")

    #[pyo3(get)]
    pub alias: Option<String>, // Alias if provided (e.g., device: equipment)

    #[pyo3(get)]
    pub arguments: Vec<GraphQLArgument>, // Args like where: {...}, limit: 10

    #[pyo3(get)]
    pub nested_fields: Vec<FieldSelection>, // Recursive nested selections

    #[pyo3(get)]
    pub directives: Vec<Directive>, // @include, @skip, etc with arguments
}

/// GraphQL directive (e.g., @requiresRole(role: "admin")).
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Directive {
    #[pyo3(get)]
    pub name: String, // Directive name (e.g., "requiresRole")

    #[pyo3(get)]
    pub arguments: Vec<GraphQLArgument>, // Directive arguments
}

/// GraphQL argument (e.g., where: {...}).
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphQLArgument {
    #[pyo3(get)]
    pub name: String, // Argument name

    #[pyo3(get)]
    pub value_type: String, // "object" | "variable" | "scalar"

    #[pyo3(get)]
    pub value_json: String, // Serialized value (JSON)
}

/// GraphQL type representation
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphQLType {
    #[pyo3(get)]
    pub name: String, // Type name (e.g., "String", "User")
    #[pyo3(get)]
    pub nullable: bool, // Whether the type is nullable
    #[pyo3(get)]
    pub list: bool, // Whether it's a list type
    #[pyo3(get)]
    pub list_nullable: bool, // Whether list items are nullable
}

/// Variable definition.
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VariableDefinition {
    #[pyo3(get)]
    pub name: String, // Variable name without $

    #[pyo3(get)]
    pub var_type: GraphQLType, // Structured type information

    #[pyo3(get)]
    pub default_value: Option<String>, // Default value as JSON string
}

/// Fragment definition.
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FragmentDefinition {
    #[pyo3(get)]
    pub name: String, // Fragment name

    #[pyo3(get)]
    pub type_condition: String, // Type this fragment applies to (e.g., "User")

    #[pyo3(get)]
    pub selections: Vec<FieldSelection>, // Fields selected in fragment

    #[pyo3(get)]
    pub fragment_spreads: Vec<String>, // Names of other fragments this one spreads
}

impl Default for ParsedQuery {
    fn default() -> Self {
        Self {
            operation_type: "query".to_string(),
            operation_name: None,
            root_field: "".to_string(),
            selections: Vec::new(),
            variables: Vec::new(),
            fragments: Vec::new(),
            source: "".to_string(),
        }
    }
}

impl PartialEq for FieldSelection {
    fn eq(&self, other: &Self) -> bool {
        self.name == other.name && self.alias == other.alias && self.arguments == other.arguments
    }
}

impl PartialEq for GraphQLArgument {
    fn eq(&self, other: &Self) -> bool {
        self.name == other.name && self.value_json == other.value_json
    }
}
