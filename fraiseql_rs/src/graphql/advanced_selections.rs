//! Advanced selection set processing for GraphQL queries.
//!
//! Orchestrates fragment resolution and directive evaluation into a unified pipeline.
//!
//! Handles:
//! - Fragment spread resolution
//! - Inline fragment handling
//! - Directive evaluation
//! - Selection set finalization

use crate::graphql::directive_evaluator::DirectiveEvaluator;
use crate::graphql::fragment_resolver::FragmentResolver;
use crate::graphql::types::{FieldSelection, FragmentDefinition, VariableDefinition};
use serde_json::Value as JsonValue;
use std::collections::HashMap;
use thiserror::Error;

/// Errors that can occur during advanced selection processing.
#[derive(Debug, Error)]
pub enum SelectionError {
    #[error("Fragment resolution error: {0}")]
    FragmentError(String),

    #[error("Directive evaluation error: {0}")]
    DirectiveError(String),

    #[error("Selection processing error: {0}")]
    ProcessingError(String),
}

/// Processed query after resolving fragments and evaluating directives.
#[derive(Debug, Clone)]
pub struct ProcessedQuery {
    /// Operation type: "query" or "mutation"
    pub operation_type: String,

    /// Optional operation name
    pub operation_name: Option<String>,

    /// First field in selection set (root field)
    pub root_field: String,

    /// Resolved and finalized field selections
    pub selections: Vec<FieldSelection>,

    /// Variable definitions
    pub variables: Vec<VariableDefinition>,

    /// Original query string (for caching key)
    pub source: String,
}

/// Processes GraphQL queries by resolving fragments and evaluating directives.
///
/// This is the orchestration layer that combines:
/// 1. FragmentResolver - Resolves fragment spreads
/// 2. DirectiveEvaluator - Evaluates directives
/// 3. Selection finalization - Deduplicates and finalizes selections
pub struct AdvancedSelectionProcessor;

impl AdvancedSelectionProcessor {
    /// Process a parsed query through the advanced selection pipeline.
    ///
    /// # Pipeline Stages
    /// 1. Fragment Resolution - Expand all fragment spreads
    /// 2. Directive Evaluation - Evaluate @skip and @include
    /// 3. Selection Finalization - Deduplicate and clean up
    ///
    /// # Errors
    /// Returns error if:
    /// - Fragment resolution fails (missing fragments, cycles)
    /// - Directive evaluation fails (undefined variables, type mismatch)
    pub fn process(
        parsed_query: &crate::graphql::types::ParsedQuery,
        variables: &HashMap<String, JsonValue>,
    ) -> Result<ProcessedQuery, SelectionError> {
        // Stage 1: Resolve all fragment spreads
        let mut processed = parsed_query.clone();
        processed.selections =
            Self::resolve_fragments(&parsed_query.selections, &parsed_query.fragments)?;

        // Stage 2: Evaluate directives recursively
        processed.selections =
            Self::evaluate_directives_recursive(&processed.selections, variables)?;

        // Stage 3: Finalize selections (deduplicate and clean)
        processed.selections = Self::finalize_selections(&processed.selections)?;

        Ok(ProcessedQuery {
            operation_type: processed.operation_type,
            operation_name: processed.operation_name,
            root_field: processed.root_field,
            selections: processed.selections,
            variables: processed.variables,
            source: processed.source,
        })
    }

    /// Stage 1: Resolve all fragment spreads in selections.
    fn resolve_fragments(
        selections: &[FieldSelection],
        fragments: &[FragmentDefinition],
    ) -> Result<Vec<FieldSelection>, SelectionError> {
        let resolver = FragmentResolver::new(fragments);
        resolver
            .resolve_spreads(selections)
            .map_err(|e| SelectionError::FragmentError(e.to_string()))
    }

    /// Stage 2: Recursively evaluate directives at all nesting levels.
    fn evaluate_directives_recursive(
        selections: &[FieldSelection],
        variables: &HashMap<String, JsonValue>,
    ) -> Result<Vec<FieldSelection>, SelectionError> {
        let mut result = Vec::new();

        for selection in selections {
            // Evaluate directives on this field
            let should_include = DirectiveEvaluator::evaluate_directives(selection, variables)
                .map_err(|e| SelectionError::DirectiveError(e.to_string()))?;

            // If directives exclude this field, skip it
            if !should_include {
                continue;
            }

            // Field should be included - process nested fields
            let mut field = selection.clone();
            if !field.nested_fields.is_empty() {
                field.nested_fields =
                    Self::evaluate_directives_recursive(&field.nested_fields, variables)?;
            }

            result.push(field);
        }

        Ok(result)
    }

    /// Stage 3: Finalize selection set by deduplicating fields.
    fn finalize_selections(
        selections: &[FieldSelection],
    ) -> Result<Vec<FieldSelection>, SelectionError> {
        let mut by_key: HashMap<String, FieldSelection> = HashMap::new();

        for field in selections {
            let key = Self::response_key(field);

            if let Some(existing) = by_key.get_mut(&key) {
                // Field with same name/alias already exists - merge nested selections
                if !field.nested_fields.is_empty() {
                    existing.nested_fields.extend(field.nested_fields.clone());
                    // Deduplicate nested fields
                    existing.nested_fields = Self::deduplicate_fields(&existing.nested_fields);
                }
            } else {
                // New field - add it
                by_key.insert(key, field.clone());
            }
        }

        Ok(by_key.into_values().collect())
    }

    /// Get the response key for a field (alias if present, otherwise name).
    fn response_key(field: &FieldSelection) -> String {
        field
            .alias
            .as_ref()
            .cloned()
            .unwrap_or_else(|| field.name.clone())
    }

    /// Deduplicate fields in a selection set by response key.
    fn deduplicate_fields(fields: &[FieldSelection]) -> Vec<FieldSelection> {
        let mut seen = std::collections::HashSet::new();
        fields
            .iter()
            .filter(|f| seen.insert(Self::response_key(f)))
            .cloned()
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graphql::types::{Directive, GraphQLArgument, GraphQLType};

    fn make_field(name: &str, nested: Vec<FieldSelection>) -> FieldSelection {
        FieldSelection {
            name: name.to_string(),
            alias: None,
            arguments: vec![],
            nested_fields: nested,
            directives: vec![],
        }
    }

    fn make_field_with_directive(
        name: &str,
        directives: Vec<Directive>,
        nested: Vec<FieldSelection>,
    ) -> FieldSelection {
        FieldSelection {
            name: name.to_string(),
            alias: None,
            arguments: vec![],
            nested_fields: nested,
            directives,
        }
    }

    fn make_directive(name: &str, if_value: &str) -> Directive {
        Directive {
            name: name.to_string(),
            arguments: vec![GraphQLArgument {
                name: "if".to_string(),
                value_type: "boolean".to_string(),
                value_json: if_value.to_string(),
            }],
        }
    }

    fn make_fragment(name: &str, selections: Vec<FieldSelection>) -> FragmentDefinition {
        FragmentDefinition {
            name: name.to_string(),
            type_condition: "User".to_string(),
            selections,
            fragment_spreads: vec![],
        }
    }

    fn make_parsed_query(
        selections: Vec<FieldSelection>,
        fragments: Vec<FragmentDefinition>,
    ) -> crate::graphql::types::ParsedQuery {
        crate::graphql::types::ParsedQuery {
            operation_type: "query".to_string(),
            operation_name: None,
            root_field: "user".to_string(),
            selections,
            variables: vec![],
            fragments,
            source: "query { ... }".to_string(),
        }
    }

    #[test]
    fn test_fragment_resolution_basic() {
        let fragment = make_fragment(
            "UserFields",
            vec![make_field("id", vec![]), make_field("name", vec![])],
        );

        let query_selections = vec![FieldSelection {
            name: "...UserFields".to_string(),
            alias: None,
            arguments: vec![],
            nested_fields: vec![],
            directives: vec![],
        }];

        let query = make_parsed_query(query_selections, vec![fragment]);
        let variables = HashMap::new();

        let result = AdvancedSelectionProcessor::process(&query, &variables).unwrap();

        assert_eq!(result.selections.len(), 2);
        assert_eq!(result.selections[0].name, "id");
        assert_eq!(result.selections[1].name, "name");
    }

    #[test]
    fn test_directive_evaluation_skip() {
        let field =
            make_field_with_directive("email", vec![make_directive("skip", "true")], vec![]);

        let query = make_parsed_query(
            vec![make_field("id", vec![]), field, make_field("name", vec![])],
            vec![],
        );
        let variables = HashMap::new();

        let result = AdvancedSelectionProcessor::process(&query, &variables).unwrap();

        // Email should be skipped
        assert_eq!(result.selections.len(), 2);
        assert_eq!(result.selections[0].name, "id");
        assert_eq!(result.selections[1].name, "name");
    }

    #[test]
    fn test_directive_evaluation_include() {
        let field =
            make_field_with_directive("email", vec![make_directive("include", "false")], vec![]);

        let query = make_parsed_query(
            vec![make_field("id", vec![]), field, make_field("name", vec![])],
            vec![],
        );
        let variables = HashMap::new();

        let result = AdvancedSelectionProcessor::process(&query, &variables).unwrap();

        // Email should be excluded
        assert_eq!(result.selections.len(), 2);
        assert_eq!(result.selections[0].name, "id");
        assert_eq!(result.selections[1].name, "name");
    }

    #[test]
    fn test_fragment_and_directive_combined() {
        let fragment = make_fragment(
            "UserFields",
            vec![
                make_field("id", vec![]),
                make_field_with_directive("email", vec![make_directive("skip", "true")], vec![]),
                make_field("name", vec![]),
            ],
        );

        let query_selections = vec![FieldSelection {
            name: "...UserFields".to_string(),
            alias: None,
            arguments: vec![],
            nested_fields: vec![],
            directives: vec![],
        }];

        let query = make_parsed_query(query_selections, vec![fragment]);
        let variables = HashMap::new();

        let result = AdvancedSelectionProcessor::process(&query, &variables).unwrap();

        // Should have id and name but not email (skipped by directive)
        assert_eq!(result.selections.len(), 2);
        let names: Vec<_> = result.selections.iter().map(|f| f.name.as_str()).collect();
        assert!(names.contains(&"id"));
        assert!(names.contains(&"name"));
        assert!(!names.contains(&"email"));
    }

    #[test]
    fn test_nested_directive_evaluation() {
        let query = make_parsed_query(
            vec![make_field(
                "user",
                vec![
                    make_field("id", vec![]),
                    make_field_with_directive(
                        "email",
                        vec![make_directive("skip", "false")],
                        vec![],
                    ),
                    make_field_with_directive(
                        "profile",
                        vec![make_directive("include", "true")],
                        vec![
                            make_field("bio", vec![]),
                            make_field_with_directive(
                                "phone",
                                vec![make_directive("skip", "true")],
                                vec![],
                            ),
                        ],
                    ),
                ],
            )],
            vec![],
        );
        let variables = HashMap::new();

        let result = AdvancedSelectionProcessor::process(&query, &variables).unwrap();

        assert_eq!(result.selections.len(), 1);
        let user_field = &result.selections[0];
        assert_eq!(user_field.name, "user");

        // User should have: id, email, profile (with bio only, no phone)
        assert_eq!(user_field.nested_fields.len(), 3);

        let profile = user_field
            .nested_fields
            .iter()
            .find(|f| f.name == "profile")
            .unwrap();
        assert_eq!(profile.nested_fields.len(), 1);
        assert_eq!(profile.nested_fields[0].name, "bio");
    }

    #[test]
    fn test_deduplication_with_alias() {
        let query = make_parsed_query(
            vec![
                FieldSelection {
                    name: "user".to_string(),
                    alias: Some("primaryUser".to_string()),
                    arguments: vec![],
                    nested_fields: vec![make_field("id", vec![])],
                    directives: vec![],
                },
                FieldSelection {
                    name: "user".to_string(),
                    alias: Some("primaryUser".to_string()),
                    arguments: vec![],
                    nested_fields: vec![make_field("name", vec![])],
                    directives: vec![],
                },
            ],
            vec![],
        );
        let variables = HashMap::new();

        let result = AdvancedSelectionProcessor::process(&query, &variables).unwrap();

        // Should have one user with both id and name
        assert_eq!(result.selections.len(), 1);
        let user = &result.selections[0];
        assert_eq!(user.alias.as_ref().unwrap(), "primaryUser");
        assert_eq!(user.nested_fields.len(), 2);
    }
}
