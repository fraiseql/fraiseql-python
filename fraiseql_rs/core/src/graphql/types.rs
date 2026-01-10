//! GraphQL AST types for query representation.

use serde::{Deserialize, Serialize};

/// Parsed GraphQL query in Rust.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParsedQuery {
    /// Operation type: "query" or "mutation"
    pub operation_type: String,

    /// Optional operation name
    pub operation_name: Option<String>,

    /// First field in selection set (root field)
    pub root_field: String,

    /// Field selections in query
    pub selections: Vec<FieldSelection>,

    /// Variable definitions
    pub variables: Vec<VariableDefinition>,

    /// Fragment definitions
    pub fragments: Vec<FragmentDefinition>,

    /// Original query string (for caching key)
    pub source: String,
}

impl ParsedQuery {
    /// Get query signature for caching (ignores variables).
    #[must_use]
    pub fn signature(&self) -> String {
        // Used by Phase 8 for query plan caching
        format!("{}::{}", self.operation_type, self.root_field)
    }

    /// Check if query is cacheable (no variables).
    #[must_use]
    pub const fn is_cacheable(&self) -> bool {
        self.variables.is_empty()
    }
}

/// Field selection in GraphQL query.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FieldSelection {
    /// GraphQL field name (e.g., "users")
    pub name: String,

    /// Alias if provided (e.g., device: equipment)
    pub alias: Option<String>,

    /// Arguments like where: {...}, limit: 10
    pub arguments: Vec<GraphQLArgument>,

    /// Recursive nested field selections
    pub nested_fields: Vec<FieldSelection>,

    /// Directives: @include, @skip, etc with arguments
    pub directives: Vec<Directive>,
}

/// GraphQL directive (e.g., @requiresRole(role: "admin")).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Directive {
    /// Directive name (e.g., "requiresRole")
    pub name: String,

    /// Directive arguments
    pub arguments: Vec<GraphQLArgument>,
}

/// GraphQL argument (e.g., where: {...}).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphQLArgument {
    /// Argument name
    pub name: String,

    /// Value type: "object", "variable", or "scalar"
    pub value_type: String,

    /// Serialized value as JSON string
    pub value_json: String,
}

/// GraphQL type representation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphQLType {
    /// Type name (e.g., "String", "User")
    pub name: String,
    /// Whether the type is nullable
    pub nullable: bool,
    /// Whether it's a list type
    pub list: bool,
    /// Whether list items are nullable
    pub list_nullable: bool,
}

/// Variable definition.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VariableDefinition {
    /// Variable name without $ prefix
    pub name: String,

    /// Structured type information
    pub var_type: GraphQLType,

    /// Default value as JSON string
    pub default_value: Option<String>,
}

/// Fragment definition.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FragmentDefinition {
    /// Fragment name
    pub name: String,

    /// Type this fragment applies to (e.g., "User")
    pub type_condition: String,

    /// Fields selected in fragment
    pub selections: Vec<FieldSelection>,

    /// Names of other fragments this one spreads
    pub fragment_spreads: Vec<String>,
}

impl Default for ParsedQuery {
    fn default() -> Self {
        Self {
            operation_type: "query".to_string(),
            operation_name: None,
            root_field: String::new(),
            selections: Vec::new(),
            variables: Vec::new(),
            fragments: Vec::new(),
            source: String::new(),
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parsed_query_signature() {
        let query = ParsedQuery {
            operation_type: "query".to_string(),
            operation_name: Some("GetUsers".to_string()),
            root_field: "users".to_string(),
            selections: vec![],
            variables: vec![],
            fragments: vec![],
            source: "{ users { id name } }".to_string(),
        };

        assert_eq!(query.signature(), "query::users");
    }

    #[test]
    fn test_parsed_query_cacheable() {
        let query = ParsedQuery {
            operation_type: "query".to_string(),
            operation_name: None,
            root_field: "users".to_string(),
            selections: vec![],
            variables: vec![], // No variables = cacheable
            fragments: vec![],
            source: "{ users { id } }".to_string(),
        };

        assert!(query.is_cacheable());
    }

    #[test]
    fn test_parsed_query_not_cacheable() {
        let query = ParsedQuery {
            operation_type: "query".to_string(),
            operation_name: None,
            root_field: "users".to_string(),
            selections: vec![],
            variables: vec![VariableDefinition {
                name: "limit".to_string(),
                var_type: GraphQLType {
                    name: "Int".to_string(),
                    nullable: false,
                    list: false,
                    list_nullable: false,
                },
                default_value: None,
            }],
            fragments: vec![],
            source: "query($limit: Int) { users(limit: $limit) { id } }".to_string(),
        };

        assert!(!query.is_cacheable());
    }

    #[test]
    fn test_graphql_argument_equality() {
        let arg1 = GraphQLArgument {
            name: "where".to_string(),
            value_type: "object".to_string(),
            value_json: r#"{"id": 1}"#.to_string(),
        };

        let arg2 = GraphQLArgument {
            name: "where".to_string(),
            value_type: "object".to_string(),
            value_json: r#"{"id": 1}"#.to_string(),
        };

        assert_eq!(arg1, arg2);
    }

    #[test]
    fn test_field_selection_default() {
        let selection = FieldSelection {
            name: "users".to_string(),
            alias: None,
            arguments: vec![],
            nested_fields: vec![],
            directives: vec![],
        };

        assert_eq!(selection.name, "users");
        assert_eq!(selection.arguments.len(), 0);
    }

    #[test]
    fn test_graphql_type_nullable() {
        let nullable_type = GraphQLType {
            name: "String".to_string(),
            nullable: true,
            list: false,
            list_nullable: false,
        };

        assert!(nullable_type.nullable);
        assert!(!nullable_type.list);
    }

    #[test]
    fn test_graphql_type_list() {
        let list_type = GraphQLType {
            name: "User".to_string(),
            nullable: false,
            list: true,
            list_nullable: false,
        };

        assert!(!list_type.nullable);
        assert!(list_type.list);
    }

    #[test]
    fn test_directive_with_arguments() {
        let directive = Directive {
            name: "requiresRole".to_string(),
            arguments: vec![GraphQLArgument {
                name: "role".to_string(),
                value_type: "scalar".to_string(),
                value_json: r#""admin""#.to_string(),
            }],
        };

        assert_eq!(directive.name, "requiresRole");
        assert_eq!(directive.arguments.len(), 1);
    }

    #[test]
    fn test_fragment_definition() {
        let fragment = FragmentDefinition {
            name: "UserFields".to_string(),
            type_condition: "User".to_string(),
            selections: vec![],
            fragment_spreads: vec![],
        };

        assert_eq!(fragment.name, "UserFields");
        assert_eq!(fragment.type_condition, "User");
    }

    #[test]
    fn test_parsed_query_default() {
        let query = ParsedQuery::default();

        assert_eq!(query.operation_type, "query");
        assert_eq!(query.root_field, "");
        assert!(query.operation_name.is_none());
        assert!(query.selections.is_empty());
        assert!(query.variables.is_empty());
        assert!(query.fragments.is_empty());
    }
}
