//! Query complexity analysis and cost calculation.
//!
//! This module implements GraphQL query complexity analysis with configurable
//! cost limits and field weighting to prevent resource exhaustion attacks.

use std::collections::HashMap;

use crate::graphql::types::ParsedQuery;

/// Complexity analysis result
pub struct ComplexityResult {
    /// Calculated complexity score
    pub score:    u32,
    /// Whether the query exceeds configured limits
    pub exceeded: bool,
    /// Maximum allowed complexity
    pub limit:    u32,
}

/// Complexity analyzer configuration
#[derive(Clone)]
pub struct ComplexityConfig {
    /// Maximum allowed complexity score
    pub max_complexity:   u32,
    /// Base cost for each field
    pub field_cost:       u32,
    /// Cost multiplier for nested fields
    pub depth_multiplier: f32,
    /// Special field cost overrides
    pub field_overrides:  HashMap<String, u32>,
    /// Type-specific cost multipliers
    pub type_multipliers: HashMap<String, f32>,
}

impl Default for ComplexityConfig {
    fn default() -> Self {
        Self {
            max_complexity:   1000,
            field_cost:       1,
            depth_multiplier: 1.5,
            field_overrides:  HashMap::new(),
            type_multipliers: HashMap::new(),
        }
    }
}

/// Query complexity analyzer
pub struct ComplexityAnalyzer {
    config: ComplexityConfig,
}

impl Default for ComplexityAnalyzer {
    fn default() -> Self {
        Self::new()
    }
}

impl ComplexityAnalyzer {
    /// Create a new complexity analyzer with default config
    pub fn new() -> Self {
        Self {
            config: ComplexityConfig::default(),
        }
    }

    /// Create analyzer with custom configuration
    pub fn with_config(config: ComplexityConfig) -> Self {
        Self { config }
    }

    /// Analyze query complexity
    pub fn analyze(&self, query: &ParsedQuery) -> ComplexityResult {
        let score = self.calculate_complexity(query);
        let exceeded = score > self.config.max_complexity;

        ComplexityResult {
            score,
            exceeded,
            limit: self.config.max_complexity,
        }
    }

    /// Analyze query complexity with detailed breakdown
    pub fn analyze_detailed(
        &self,
        query: &ParsedQuery,
    ) -> (ComplexityResult, std::collections::HashMap<String, u32>) {
        let result = self.analyze(query);
        let breakdown = self.get_complexity_breakdown(query);
        (result, breakdown)
    }

    /// Get complexity breakdown for debugging
    pub fn get_complexity_breakdown(&self, query: &ParsedQuery) -> HashMap<String, u32> {
        let mut breakdown = HashMap::new();

        // Count fields at different depths
        let mut field_count = 0u32;
        let mut max_depth = 0u32;

        for selection in &query.selections {
            Self::count_fields_and_depth(selection, 0, &mut field_count, &mut max_depth);
        }

        // Calculate components
        let base_complexity = field_count.saturating_mul(self.config.field_cost);
        let depth_penalty = if max_depth > 0 {
            (self.config.depth_multiplier.powi(max_depth as i32) * base_complexity as f32) as u32
                - base_complexity
        } else {
            0
        };

        let fragment_penalty = (query.fragments.len() as u32).saturating_mul(5); // Fragments add complexity when spread

        breakdown.insert("field_count".to_string(), field_count);
        breakdown.insert("max_depth".to_string(), max_depth);
        breakdown.insert("base_complexity".to_string(), base_complexity);
        breakdown.insert("depth_penalty".to_string(), depth_penalty);
        breakdown.insert("fragment_penalty".to_string(), fragment_penalty);
        breakdown.insert(
            "total".to_string(),
            base_complexity.saturating_add(depth_penalty).saturating_add(fragment_penalty),
        );

        breakdown
    }

    /// Count fields and track maximum depth (recursive helper)
    fn count_fields_and_depth(
        selection: &crate::graphql::types::FieldSelection,
        current_depth: u32,
        field_count: &mut u32,
        max_depth: &mut u32,
    ) {
        *field_count = field_count.saturating_add(1);
        *max_depth = (*max_depth).max(current_depth);

        for nested in &selection.nested_fields {
            Self::count_fields_and_depth(nested, current_depth + 1, field_count, max_depth);
        }
    }

    /// Calculate complexity score for a query
    fn calculate_complexity(&self, query: &ParsedQuery) -> u32 {
        let mut complexity = 0u32;

        // Calculate complexity from root selections
        for selection in &query.selections {
            complexity =
                complexity.saturating_add(self.calculate_selection_complexity(selection, 0));
        }

        // Add complexity from fragments (they contribute through spreads)
        // Fragment definitions themselves don't add complexity until spread
        for _fragment in &query.fragments {
            // Each fragment definition has a small base cost
            complexity = complexity.saturating_add(1);
        }

        complexity
    }

    /// Calculate complexity for a field selection recursively
    fn calculate_selection_complexity(
        &self,
        selection: &crate::graphql::types::FieldSelection,
        depth: u32,
    ) -> u32 {
        let mut complexity = 0u32;

        // Base cost for this field
        let field_cost = self
            .config
            .field_overrides
            .get(&selection.name)
            .copied()
            .unwrap_or(self.config.field_cost);

        complexity = complexity.saturating_add(field_cost);

        // Depth multiplier (exponential growth for deep queries)
        let depth_multiplier = (self.config.depth_multiplier.powi(depth as i32) * 100.0) as u32;
        complexity = complexity.saturating_mul(depth_multiplier / 100).max(field_cost);

        // Add complexity for nested fields
        let nested_count = selection.nested_fields.len() as u32;
        if nested_count > 0 {
            let nested_complexity: u32 = selection
                .nested_fields
                .iter()
                .map(|nested| self.calculate_selection_complexity(nested, depth + 1))
                .sum();

            complexity = complexity.saturating_add(nested_complexity);
        }

        // Arguments can increase complexity
        let arg_complexity = (selection.arguments.len() as u32).saturating_mul(2);
        complexity = complexity.saturating_add(arg_complexity);

        complexity
    }

    /// Calculate complexity for a field selection
    ///
    /// Reserved for future use in fine-grained complexity calculation.
    /// Currently, complexity is calculated at the selection level.
    #[allow(dead_code)]
    fn calculate_field_complexity(
        &self,
        field_name: &str,
        depth: u32,
        selection_count: u32,
    ) -> u32 {
        // Base field cost
        let base_cost = self
            .config
            .field_overrides
            .get(field_name)
            .copied()
            .unwrap_or(self.config.field_cost);

        // Depth multiplier
        let depth_factor = self.config.depth_multiplier.powi(depth as i32);

        // Selection count multiplier
        let selection_factor = selection_count as f32;

        ((base_cost as f32 * depth_factor * selection_factor) as u32).max(1)
    }

    /// Calculate complexity for a type
    ///
    /// Reserved for future use in type-based complexity multipliers.
    /// Currently, type multipliers are applied at config level.
    #[allow(dead_code)]
    fn calculate_type_complexity(&self, type_name: &str, base_complexity: u32) -> u32 {
        let multiplier = self.config.type_multipliers.get(type_name).copied().unwrap_or(1.0);

        ((base_complexity as f32 * multiplier) as u32).max(1)
    }

    /// Validate that query complexity is within limits
    pub fn validate_complexity(&self, query: &ParsedQuery) -> Result<(), String> {
        let result = self.analyze(query);
        if result.exceeded {
            Err(format!(
                "Query complexity {} exceeds maximum allowed complexity of {}",
                result.score, result.limit
            ))
        } else {
            Ok(())
        }
    }
}

/// High-complexity query detector
pub struct ComplexityDetector {
    analyzer: ComplexityAnalyzer,
}

impl Default for ComplexityDetector {
    fn default() -> Self {
        Self::new()
    }
}

impl ComplexityDetector {
    pub fn new() -> Self {
        Self {
            analyzer: ComplexityAnalyzer::new(),
        }
    }

    pub fn with_config(config: ComplexityConfig) -> Self {
        Self {
            analyzer: ComplexityAnalyzer::with_config(config),
        }
    }

    /// Check if a query is potentially malicious based on complexity
    pub fn is_potentially_malicious(&self, query: &ParsedQuery) -> bool {
        let result = self.analyzer.analyze(query);

        // Consider malicious if:
        // - Complexity exceeds 80% of limit
        // - Or has very deep nesting (placeholder for now)
        result.score > (self.analyzer.config.max_complexity * 4) / 5
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graphql::types::FieldSelection;

    #[test]
    fn test_complexity_analysis() {
        let analyzer = ComplexityAnalyzer::new();
        let query = ParsedQuery::default();

        let result = analyzer.analyze(&query);
        assert!(!result.exceeded);
        assert_eq!(result.limit, 1000);
    }

    #[test]
    fn test_complexity_validation() {
        let analyzer = ComplexityAnalyzer::new();
        let query = ParsedQuery::default();

        let result = analyzer.validate_complexity(&query);
        assert!(result.is_ok());
    }

    #[test]
    fn test_field_complexity_calculation() {
        let analyzer = ComplexityAnalyzer::new();

        // Test basic field cost
        let cost = analyzer.calculate_field_complexity("name", 0, 1);
        assert_eq!(cost, 1);

        // Test depth multiplier
        let cost = analyzer.calculate_field_complexity("name", 2, 1);
        assert_eq!(cost, 2); // 1 * 1.5^2 = 2.25, rounded to 2
    }

    #[test]
    fn test_malicious_detection() {
        let config = ComplexityConfig {
            max_complexity: 100,
            ..Default::default()
        };
        let detector = ComplexityDetector::with_config(config);
        let query = ParsedQuery::default();

        // Should not be considered malicious with default complexity
        assert!(!detector.is_potentially_malicious(&query));
    }

    #[test]
    fn test_complexity_with_nested_fields() {
        let analyzer = ComplexityAnalyzer::new();

        // Create a query with nested fields
        let mut query = ParsedQuery::default();
        query.selections = vec![FieldSelection {
            name:          "users".to_string(),
            alias:         None,
            arguments:     vec![],
            nested_fields: vec![
                FieldSelection {
                    name:          "posts".to_string(),
                    alias:         None,
                    arguments:     vec![],
                    nested_fields: vec![FieldSelection {
                        name:          "comments".to_string(),
                        alias:         None,
                        arguments:     vec![],
                        nested_fields: vec![FieldSelection {
                            name:          "author".to_string(),
                            alias:         None,
                            arguments:     vec![],
                            nested_fields: vec![],
                            directives:    vec![],
                        }],
                        directives:    vec![],
                    }],
                    directives:    vec![],
                },
                FieldSelection {
                    name:          "profile".to_string(),
                    alias:         None,
                    arguments:     vec![],
                    nested_fields: vec![],
                    directives:    vec![],
                },
            ],
            directives:    vec![],
        }];

        let result = analyzer.analyze(&query);
        assert!(!result.exceeded);
        assert!(result.score > 1); // Should have some complexity
    }

    #[test]
    fn test_complexity_config_override() {
        let mut config = ComplexityConfig::default();
        config.field_overrides.insert("expensive_field".to_string(), 10);

        let analyzer = ComplexityAnalyzer::with_config(config);

        // Test that the override works
        let cost = analyzer.calculate_field_complexity("expensive_field", 0, 1);
        assert_eq!(cost, 10);
    }

    #[test]
    fn test_complexity_limit_exceeded() {
        let config = ComplexityConfig {
            max_complexity: 5, // Very low limit
            ..Default::default()
        };
        let analyzer = ComplexityAnalyzer::with_config(config);

        // Create a query that exceeds the limit
        let mut query = ParsedQuery::default();
        query.selections = vec![FieldSelection {
            name:          "users".to_string(),
            alias:         None,
            arguments:     vec![],
            nested_fields: vec![FieldSelection {
                name:          "posts".to_string(),
                alias:         None,
                arguments:     vec![],
                nested_fields: vec![FieldSelection {
                    name:          "comments".to_string(),
                    alias:         None,
                    arguments:     vec![],
                    nested_fields: vec![],
                    directives:    vec![],
                }],
                directives:    vec![],
            }],
            directives:    vec![],
        }];

        let result = analyzer.validate_complexity(&query);
        assert!(result.is_err());
    }

    #[test]
    fn test_complexity_breakdown_calculation() {
        let analyzer = ComplexityAnalyzer::new();
        let query = ParsedQuery::default();

        let breakdown = analyzer.get_complexity_breakdown(&query);
        assert!(breakdown.contains_key("total"));
        assert!(breakdown.contains_key("field_count"));
        assert!(breakdown.contains_key("max_depth"));
    }
}
