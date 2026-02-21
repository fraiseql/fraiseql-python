//! GraphQL query parser using graphql-parser crate.

use anyhow::{Result, anyhow};
use graphql_parser::query::{
    self, Definition, Directive as GraphQLDirective, Document, OperationDefinition, Selection,
};

use crate::graphql::types::*;

/// Parse GraphQL query string into Rust AST.
pub fn parse_query(source: &str) -> Result<ParsedQuery> {
    // Use graphql-parser to parse query string
    let doc: Document<String> =
        query::parse_query(source).map_err(|e| anyhow!("Failed to parse GraphQL query: {}", e))?;

    // Extract first operation (ignore multiple operations for now)
    let operation = doc
        .definitions
        .iter()
        .find_map(|def| match def {
            query::Definition::Operation(op) => Some(op),
            _ => None,
        })
        .ok_or_else(|| anyhow!("No query or mutation operation found"))?;

    // Extract operation details
    let (operation_type, operation_name, root_field, selections, variables) =
        extract_operation(operation)?;

    // Extract fragment definitions
    let fragments = extract_fragments(&doc)?;

    Ok(ParsedQuery {
        operation_type,
        operation_name,
        root_field,
        selections,
        variables,
        fragments,
        source: source.to_string(),
    })
}

/// Extract fragment definitions from GraphQL document.
fn extract_fragments(
    doc: &Document<String>,
) -> Result<Vec<crate::graphql::types::FragmentDefinition>> {
    let mut fragments = Vec::new();

    for def in &doc.definitions {
        if let Definition::Fragment(fragment) = def {
            let selections = parse_selection_set(&fragment.selection_set)?;

            // Extract fragment spreads from selections
            let fragment_spreads = extract_fragment_spreads(&fragment.selection_set);

            // Convert type condition to string
            let type_condition = match &fragment.type_condition {
                query::TypeCondition::On(type_name) => type_name.clone(),
            };

            fragments.push(crate::graphql::types::FragmentDefinition {
                name: fragment.name.clone(),
                type_condition,
                selections,
                fragment_spreads,
            });
        }
    }

    Ok(fragments)
}

/// Extract fragment spreads from a selection set.
fn extract_fragment_spreads(selection_set: &query::SelectionSet<String>) -> Vec<String> {
    let mut spreads = Vec::new();

    for selection in &selection_set.items {
        match selection {
            Selection::FragmentSpread(spread) => {
                spreads.push(spread.fragment_name.clone());
            },
            Selection::InlineFragment(inline) => {
                // Inline fragments can also contain spreads
                spreads.extend(extract_fragment_spreads(&inline.selection_set));
            },
            Selection::Field(field) => {
                // Fields can have nested selections with spreads
                spreads.extend(extract_fragment_spreads(&field.selection_set));
            },
        }
    }

    spreads
}

/// Extract operation details from GraphQL operation definition.
fn extract_operation(
    operation: &OperationDefinition<String>,
) -> Result<(String, Option<String>, String, Vec<FieldSelection>, Vec<VariableDefinition>)> {
    let operation_type = match operation {
        OperationDefinition::Query(_) => "query",
        OperationDefinition::Mutation(_) => "mutation",
        OperationDefinition::Subscription(_) => "subscription",
        OperationDefinition::SelectionSet(_) => "query", // Anonymous query
    }
    .to_string();

    let (name, selection_set, var_defs) = match operation {
        OperationDefinition::Query(q) => (&q.name, &q.selection_set, &q.variable_definitions),
        OperationDefinition::Mutation(m) => (&m.name, &m.selection_set, &m.variable_definitions),
        OperationDefinition::Subscription(s) => {
            (&s.name, &s.selection_set, &s.variable_definitions)
        },
        OperationDefinition::SelectionSet(sel_set) => (&None, sel_set, &Vec::new()),
    };

    // Parse selection set (recursive)
    let selections = parse_selection_set(selection_set)?;

    // Get root field name (first field in selection set)
    let root_field = selections
        .first()
        .map(|s| s.name.clone())
        .ok_or_else(|| anyhow!("No fields in selection set"))?;

    // Parse variable definitions
    let variables = var_defs
        .iter()
        .map(|var_def| VariableDefinition {
            name:          var_def.name.clone(),
            var_type:      parse_graphql_type(&var_def.var_type),
            default_value: var_def.default_value.as_ref().map(|v| serialize_value(v)),
        })
        .collect();

    Ok((operation_type, name.clone(), root_field, selections, variables))
}

/// Parse GraphQL selection set recursively.
fn parse_selection_set(selection_set: &query::SelectionSet<String>) -> Result<Vec<FieldSelection>> {
    let mut fields = Vec::new();

    for selection in &selection_set.items {
        match selection {
            Selection::Field(field) => {
                // Parse field arguments
                let arguments = field
                    .arguments
                    .iter()
                    .map(|(name, value)| GraphQLArgument {
                        name:       name.clone(),
                        value_type: value_type_string(value),
                        value_json: serialize_value(value),
                    })
                    .collect();

                // Parse nested selection set (recursive)
                let nested_fields = parse_selection_set(&field.selection_set)?;

                let directives = field
                    .directives
                    .iter()
                    .map(|d| parse_directive(d))
                    .collect::<Result<Vec<_>>>()?;

                fields.push(FieldSelection {
                    name: field.name.clone(),
                    alias: field.alias.clone(),
                    arguments,
                    nested_fields,
                    directives,
                });
            },
            Selection::InlineFragment(frag) => {
                // Inline fragments not yet supported (would need type condition evaluation)
                // TODO Phase 9: Implement proper inline fragment handling
                let type_name = frag
                    .type_condition
                    .as_ref()
                    .map(|t| format!("{}", t))
                    .unwrap_or_else(|| "(unknown)".to_string());
                return Err(anyhow!("Inline fragments not yet supported: ... on {}", type_name));
            },
            Selection::FragmentSpread(spread) => {
                // For now, treat fragment spreads as error
                // (would need fragment definitions support)
                return Err(anyhow!(
                    "Fragment spreads not yet supported: {}",
                    spread.fragment_name
                ));
            },
        }
    }

    Ok(fields)
}

/// Get type of GraphQL value for classification.
fn value_type_string(value: &query::Value<String>) -> String {
    match value {
        query::Value::String(_) => "string".to_string(),
        query::Value::Int(_) => "int".to_string(),
        query::Value::Float(_) => "float".to_string(),
        query::Value::Boolean(_) => "boolean".to_string(),
        query::Value::Null => "null".to_string(),
        query::Value::Enum(_) => "enum".to_string(),
        query::Value::List(_) => "list".to_string(),
        query::Value::Object(_) => "object".to_string(),
        query::Value::Variable(_) => "variable".to_string(),
    }
}

/// Serialize GraphQL value to JSON string.
fn serialize_value(value: &query::Value<String>) -> String {
    match value {
        query::Value::String(s) => format!("\"{}\"", s.replace("\"", "\\\"")),
        query::Value::Int(i) => {
            // SAFETY: graphql_parser::Number is a transparent wrapper around i64
            // This is safe because Number is repr(transparent) with single i64 field
            // TODO: File issue with graphql-parser to expose value or implement Display
            unsafe {
                let ptr = i as *const query::Number as *const i64;
                (*ptr).to_string()
            }
        },
        query::Value::Float(f) => format!("{}", f),
        query::Value::Boolean(b) => b.to_string(),
        query::Value::Null => "null".to_string(),
        query::Value::Enum(e) => format!("\"{}\"", e),
        query::Value::List(items) => {
            let serialized: Vec<_> = items.iter().map(serialize_value).collect();
            format!("[{}]", serialized.join(","))
        },
        query::Value::Object(obj) => {
            let pairs: Vec<_> =
                obj.iter().map(|(k, v)| format!("\"{}\":{}", k, serialize_value(v))).collect();
            format!("{{{}}}", pairs.join(","))
        },
        query::Value::Variable(v) => format!("\"${}\"", v),
    }
}

/// Parse GraphQL directive from graphql-parser Directive.
fn parse_directive(directive: &GraphQLDirective<String>) -> Result<Directive> {
    let arguments = directive
        .arguments
        .iter()
        .map(|(name, value)| GraphQLArgument {
            name:       name.clone(),
            value_type: value_type_string(value),
            value_json: serialize_value(value),
        })
        .collect();

    Ok(Directive {
        name: directive.name.clone(),
        arguments,
    })
}

/// Parse GraphQL type from graphql-parser Type to our GraphQLType.
fn parse_graphql_type(graphql_type: &query::Type<String>) -> GraphQLType {
    match graphql_type {
        query::Type::NamedType(name) => GraphQLType {
            name:          name.clone(),
            nullable:      true, // Named types are nullable by default
            list:          false,
            list_nullable: false,
        },
        query::Type::ListType(inner) => GraphQLType {
            name:          format!("[{}]", parse_graphql_type(inner).name),
            nullable:      true,
            list:          true,
            list_nullable: true, // List items are nullable by default
        },
        query::Type::NonNullType(inner) => {
            let mut parsed = parse_graphql_type(inner);
            parsed.nullable = false;
            if parsed.list {
                parsed.list_nullable = false;
            }
            parsed
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_simple_query() {
        let query = "query { users { id name } }";
        let parsed = parse_query(query).unwrap();

        assert_eq!(parsed.operation_type, "query");
        assert_eq!(parsed.root_field, "users");
        assert_eq!(parsed.selections.len(), 1);
        assert_eq!(parsed.selections[0].nested_fields.len(), 2);
    }

    #[test]
    fn test_parse_query_with_arguments() {
        let query = r#"
            query {
                users(where: {status: "active"}, limit: 10) {
                    id
                    name
                }
            }
        "#;
        let parsed = parse_query(query).unwrap();

        let first_field = &parsed.selections[0];
        assert_eq!(first_field.arguments.len(), 2);
        assert_eq!(first_field.arguments[0].name, "where");
        assert_eq!(first_field.arguments[1].name, "limit");
    }

    #[test]
    fn test_parse_mutation() {
        let query = "mutation { createUser(input: {}) { id } }";
        let parsed = parse_query(query).unwrap();

        assert_eq!(parsed.operation_type, "mutation");
        assert_eq!(parsed.root_field, "createUser");
    }

    #[test]
    fn test_parse_query_with_variables() {
        let query = r#"
            query GetUsers($where: UserWhere!) {
                users(where: $where) {
                    id
                }
            }
        "#;
        let parsed = parse_query(query).unwrap();

        assert_eq!(parsed.variables.len(), 1);
        assert_eq!(parsed.variables[0].name, "where");
    }

    #[test]
    fn test_parse_query_with_integer_argument() {
        // This test verifies the unsafe Number -> i64 conversion works correctly
        let query = r#"
            query {
                users(limit: 42, offset: 100) {
                    id
                }
            }
        "#;
        let parsed = parse_query(query).unwrap();

        let first_field = &parsed.selections[0];
        assert_eq!(first_field.arguments.len(), 2);

        // Verify integer serialization works (tests unsafe code block)
        assert_eq!(first_field.arguments[0].name, "limit");
        assert_eq!(first_field.arguments[0].value_type, "int");
        assert_eq!(first_field.arguments[0].value_json, "42");

        assert_eq!(first_field.arguments[1].name, "offset");
        assert_eq!(first_field.arguments[1].value_type, "int");
        assert_eq!(first_field.arguments[1].value_json, "100");
    }

    #[test]
    fn test_parse_query_with_inline_fragment_fails() {
        // Inline fragments should return error (not silently skip)
        let query = r#"
            query {
                users {
                    id
                    ... on Admin {
                        permissions
                    }
                }
            }
        "#;
        let result = parse_query(query);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Inline fragments not yet supported"));
    }

    #[test]
    fn test_parse_query_with_fragment_spread_fails() {
        // Fragment spreads should return error
        let query = r#"
            query {
                users {
                    ...UserFields
                }
            }
        "#;
        let result = parse_query(query);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Fragment spreads not yet supported"));
    }
}
