//! Query validation (depth, complexity, size limits).

use super::errors::{Result, SecurityError};
use crate::graphql::types::ParsedQuery;

/// Query validation limits
#[derive(Debug, Clone)]
pub struct QueryLimits {
    pub max_depth:      usize,
    pub max_complexity: usize,
    pub max_query_size: usize,
    pub max_list_size:  usize,
}

impl Default for QueryLimits {
    fn default() -> Self {
        Self {
            max_depth:      10,
            max_complexity: 1000,
            max_query_size: 100_000, // 100KB
            max_list_size:  1000,
        }
    }
}

impl QueryLimits {
    pub fn production() -> Self {
        Self {
            max_depth:      7,
            max_complexity: 500,
            max_query_size: 50_000,
            max_list_size:  500,
        }
    }

    pub fn strict() -> Self {
        Self {
            max_depth:      5,
            max_complexity: 200,
            max_query_size: 25_000,
            max_list_size:  100,
        }
    }
}

/// Query validator
pub struct QueryValidator {
    limits: QueryLimits,
}

impl QueryValidator {
    pub fn new(limits: QueryLimits) -> Self {
        Self { limits }
    }

    /// Validate query against all limits
    pub fn validate(&self, query: &str, parsed: &ParsedQuery) -> Result<()> {
        // Check query size
        if query.len() > self.limits.max_query_size {
            return Err(SecurityError::QueryTooLarge {
                size:     query.len(),
                max_size: self.limits.max_query_size,
            });
        }

        // Check depth
        let depth = self.calculate_depth(parsed);
        if depth > self.limits.max_depth {
            return Err(SecurityError::QueryTooDeep {
                depth,
                max_depth: self.limits.max_depth,
            });
        }

        // Check complexity
        let complexity = self.calculate_complexity(parsed);
        if complexity > self.limits.max_complexity {
            return Err(SecurityError::QueryTooComplex {
                complexity,
                max_complexity: self.limits.max_complexity,
            });
        }

        Ok(())
    }

    /// Calculate query depth (max nesting level)
    pub fn calculate_depth(&self, query: &ParsedQuery) -> usize {
        query.selections.iter().map(Self::calculate_selection_depth).max().unwrap_or(0)
    }

    /// Calculate depth for a single selection (recursive helper)
    fn calculate_selection_depth(selection: &crate::graphql::types::FieldSelection) -> usize {
        if selection.nested_fields.is_empty() {
            1
        } else {
            1 + selection
                .nested_fields
                .iter()
                .map(Self::calculate_selection_depth)
                .max()
                .unwrap_or(0)
        }
    }

    /// Calculate query complexity (estimated cost)
    pub fn calculate_complexity(&self, query: &ParsedQuery) -> usize {
        query
            .selections
            .iter()
            .map(|selection| self.calculate_selection_complexity(selection))
            .sum()
    }

    /// Calculate complexity for a single selection
    fn calculate_selection_complexity(
        &self,
        selection: &crate::graphql::types::FieldSelection,
    ) -> usize {
        let mut complexity = 1; // Base cost for this field

        // Add cost for arguments (indicates filtering/complexity)
        complexity += selection.arguments.len() * 2;

        // Add cost for nested fields (recursive)
        for nested in &selection.nested_fields {
            complexity += self.calculate_selection_complexity(nested);
        }

        // Add cost for list fields (pagination/multiplier)
        if self.is_list_field(selection) {
            complexity *= 10; // Assume pagination limits this
        }

        complexity
    }

    /// Check if field returns a list (affects complexity)
    fn is_list_field(&self, selection: &crate::graphql::types::FieldSelection) -> bool {
        // This would need schema introspection to determine if field returns a list
        // For now, use heuristics based on field name
        let list_indicators = ["list", "all", "many", "items", "edges", "nodes"];
        let field_name = selection.name.to_lowercase();

        list_indicators.iter().any(|&indicator| field_name.contains(indicator))
            || field_name.ends_with('s') // Plural names often indicate lists
    }

    /// Get the configured limits
    pub fn limits(&self) -> &QueryLimits {
        &self.limits
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graphql::types::{FieldSelection, GraphQLArgument, ParsedQuery, VariableDefinition};

    #[test]
    fn test_query_limits_default() {
        let limits = QueryLimits::default();
        assert_eq!(limits.max_depth, 10);
        assert_eq!(limits.max_complexity, 1000);
        assert_eq!(limits.max_query_size, 100_000);
    }

    #[test]
    fn test_query_limits_production() {
        let limits = QueryLimits::production();
        assert_eq!(limits.max_depth, 7);
        assert_eq!(limits.max_complexity, 500);
        assert_eq!(limits.max_query_size, 50_000);
    }

    #[test]
    fn test_query_validation_size() {
        let validator = QueryValidator::new(QueryLimits {
            max_query_size: 10,
            ..Default::default()
        });

        let query = ParsedQuery {
            operation_type: "query".to_string(),
            operation_name: None,
            root_field:     "test".to_string(),
            selections:     vec![],
            variables:      vec![],
            fragments:      vec![],
            source:         "query { test }".to_string(),
        };

        // Query is "query { test }" which is 13 chars, over the limit of 10
        assert!(matches!(
            validator.validate("query { test }", &query),
            Err(SecurityError::QueryTooLarge { .. })
        ));
    }

    #[test]
    fn test_query_validation_depth() {
        let validator = QueryValidator::new(QueryLimits {
            max_depth: 1,
            ..Default::default()
        });

        let query = ParsedQuery {
            operation_type: "query".to_string(),
            operation_name: None,
            root_field:     "users".to_string(),
            selections:     vec![FieldSelection {
                name:          "users".to_string(),
                alias:         None,
                arguments:     vec![],
                nested_fields: vec![FieldSelection {
                    name:          "posts".to_string(),
                    alias:         None,
                    arguments:     vec![],
                    nested_fields: vec![],
                    directives:    vec![],
                }],
                directives:    vec![],
            }],
            variables:      vec![],
            fragments:      vec![],
            source:         "query { users { posts } }".to_string(),
        };

        // Depth is 2 (users -> posts), over the limit of 1
        assert!(matches!(
            validator.validate("query { users { posts } }", &query),
            Err(SecurityError::QueryTooDeep { .. })
        ));
    }

    #[test]
    fn test_complexity_calculation() {
        let validator = QueryValidator::new(QueryLimits::default());

        let query = ParsedQuery {
            operation_type: "query".to_string(),
            operation_name: None,
            root_field:     "users".to_string(),
            selections:     vec![FieldSelection {
                name:          "users".to_string(),
                alias:         None,
                arguments:     vec![], // No args, base complexity 1
                nested_fields: vec![],
                directives:    vec![],
            }],
            variables:      vec![],
            fragments:      vec![],
            source:         "query { users }".to_string(),
        };

        assert_eq!(validator.calculate_complexity(&query), 1);
    }

    #[test]
    fn test_is_list_field() {
        let validator = QueryValidator::new(QueryLimits::default());

        let list_field = FieldSelection {
            name:          "users".to_string(),
            alias:         None,
            arguments:     vec![],
            nested_fields: vec![],
            directives:    vec![],
        };

        let non_list_field = FieldSelection {
            name:          "user".to_string(),
            alias:         None,
            arguments:     vec![],
            nested_fields: vec![],
            directives:    vec![],
        };

        assert!(validator.is_list_field(&list_field)); // ends with 's'
        assert!(!validator.is_list_field(&non_list_field));
    }
}
