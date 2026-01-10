//! Query signature generation for caching.

use crate::graphql::types::{FieldSelection, ParsedQuery};
use sha2::{Digest, Sha256};

/// Generate cache key from GraphQL query.
#[must_use]
pub fn generate_signature(parsed_query: &ParsedQuery) -> String {
    // Create string representation of query structure (ignoring variables and literals)
    let structure = build_query_structure(parsed_query);

    // Hash the structure to get a short signature
    let mut hasher = Sha256::new();
    hasher.update(&structure);
    let hash = hasher.finalize();

    format!("{hash:x}")
}

/// Build structural representation (variables → placeholders).
fn build_query_structure(parsed_query: &ParsedQuery) -> String {
    let mut parts = vec![];

    parts.push(format!("op:{}", parsed_query.operation_type));
    parts.push(format!("root:{}", parsed_query.root_field));

    // Include field structure (nested fields)
    for selection in &parsed_query.selections {
        parts.push(build_selection_structure(selection));
    }

    // Include variable names (not values)
    for variable in &parsed_query.variables {
        parts.push(format!("var:{}", variable.name));
    }

    parts.join("|")
}

fn build_selection_structure(selection: &FieldSelection) -> String {
    let mut parts = vec![format!("field:{}", selection.name)];

    // Include argument names (not values)
    for arg in &selection.arguments {
        parts.push(format!("arg:{}", arg.name));
    }

    // Recurse for nested fields
    for nested in &selection.nested_fields {
        parts.push(build_selection_structure(nested));
    }

    format!("({})", parts.join("|"))
}

/// Check if query is suitable for caching.
#[must_use]
pub const fn is_cacheable(parsed_query: &ParsedQuery) -> bool {
    // Cacheable if:
    // 1. No variables (fully static query)
    // 2. All arguments are literal values (not variables)

    // For now, simple heuristic: cache if no variables defined
    parsed_query.variables.is_empty()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graphql::types::{FieldSelection, ParsedQuery};

    #[test]
    fn test_signature_generation() {
        // Create two identical queries
        let query1 = create_test_query("query { users { id } }");
        let query2 = create_test_query("query { users { id } }");

        let sig1 = generate_signature(&query1);
        let sig2 = generate_signature(&query2);

        assert_eq!(sig1, sig2);
    }

    #[test]
    fn test_different_signatures() {
        let query1 = create_test_query("query { users { id } }");
        let query2 = create_test_query("query { posts { id } }");

        let sig1 = generate_signature(&query1);
        let sig2 = generate_signature(&query2);

        assert_ne!(sig1, sig2);
    }

    fn create_test_query(query_str: &str) -> ParsedQuery {
        ParsedQuery {
            operation_type: "query".to_string(),
            operation_name: None,
            root_field: "users".to_string(),
            selections: vec![FieldSelection {
                name: "users".to_string(),
                alias: None,
                arguments: vec![],
                nested_fields: vec![FieldSelection {
                    name: "id".to_string(),
                    alias: None,
                    arguments: vec![],
                    nested_fields: vec![],
                    directives: vec![],
                }],
                directives: vec![],
            }],
            variables: vec![],
            fragments: vec![],
            source: query_str.to_string(),
        }
    }
}
