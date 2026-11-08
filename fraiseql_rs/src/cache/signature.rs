//! Query signature generation for caching.

use sha2::{Digest, Sha256};

use crate::graphql::types::{FieldSelection, ParsedQuery};

/// Generate cache key from GraphQL query.
///
/// Two queries share a key only when they would build the same SQL with the same
/// parameters: same structure, same argument values (literals are bound as
/// parameters, so they must be part of the key), same variable names.
pub fn generate_signature(parsed_query: &ParsedQuery) -> String {
    let structure = build_query_structure(parsed_query);

    // Hash the structure to get a short signature
    let mut hasher = Sha256::new();
    hasher.update(&structure);
    let hash = hasher.finalize();

    hex::encode(hash)
}

/// Build the representation that is hashed into the signature.
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

    // Argument names and values: a literal becomes an SQL parameter, so queries
    // differing only in a value need their own plan
    for arg in &selection.arguments {
        parts.push(format!("arg:{}={}:{}", arg.name, arg.value_type, arg.value_json));
    }

    // Recurse for nested fields
    for nested in &selection.nested_fields {
        parts.push(build_selection_structure(nested));
    }

    format!("({})", parts.join("|"))
}

/// Check if query is suitable for caching.
pub fn is_cacheable(parsed_query: &ParsedQuery) -> bool {
    // Cacheable if:
    // 1. No variables (fully static query)
    // 2. All arguments are literal values (not variables)

    // For now, simple heuristic: cache if no variables defined
    parsed_query.variables.is_empty()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graphql::types::{FieldSelection, GraphQLArgument, ParsedQuery};

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

    #[test]
    fn test_argument_values_are_part_of_the_signature() {
        let with_value = |value: &str| {
            let mut query = create_test_query("query { users { id } }");
            query.selections[0].arguments = vec![GraphQLArgument {
                name: "id".to_string(),
                value_type: "scalar".to_string(),
                value_json: value.to_string(),
            }];
            generate_signature(&query)
        };

        assert_eq!(with_value("1"), with_value("1"));
        assert_ne!(with_value("1"), with_value("2"));
    }

    /// A query `{ <root> { id } }`, with the root field taken from the query string.
    fn create_test_query(query_str: &str) -> ParsedQuery {
        let root = query_str
            .trim_start_matches("query {")
            .split_whitespace()
            .next()
            .unwrap()
            .to_string();
        ParsedQuery {
            operation_type: "query".to_string(),
            operation_name: None,
            root_field: root.clone(),
            selections: vec![FieldSelection {
                name: root,
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
