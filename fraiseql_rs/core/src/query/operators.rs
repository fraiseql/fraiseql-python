//! GraphQL WHERE clause operator definitions and registry.
//!
//! This module provides a comprehensive registry of all GraphQL operators
//! supported by `FraiseQL`, including comparison, string, array, vector,
//! and full-text search operators.

use lazy_static::lazy_static;
use std::collections::HashMap;

/// Category of operator (affects SQL generation strategy)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OperatorCategory {
    /// Basic comparison: =, !=, >, <, >=, <=
    Comparison,
    /// String operations: LIKE, ILIKE, regex, etc.
    String,
    /// NULL checks: IS NULL, IS NOT NULL
    Null,
    /// Array/list containment: @>, <@, &&
    Array,
    /// pgvector distance operators
    Vector,
    /// `PostgreSQL` full-text search
    Fulltext,
    /// Containment for JSONB: @>, <@
    Containment,
    /// Network/IP operators
    Network,
    /// Date/range operators
    DateRange,
    /// Ltree (hierarchical) operators
    Ltree,
    /// Spatial/coordinate operators
    Spatial,
    /// Path operators
    Path,
}

/// Information about a single operator
#[derive(Debug, Clone)]
pub struct OperatorInfo {
    /// GraphQL operator name (e.g., "eq", "contains")
    pub name: &'static str,
    /// SQL operator or function (e.g., "=", "LIKE", "@>")
    pub sql_op: &'static str,
    /// Category of operator
    pub category: OperatorCategory,
    /// Whether this operator expects an array value
    pub requires_array: bool,
    /// Whether this operator needs special JSONB handling
    pub jsonb_operator: bool,
}

lazy_static! {
    /// Global registry of all supported operators
    pub static ref OPERATOR_REGISTRY: HashMap<&'static str, OperatorInfo> = {
        let mut m = HashMap::new();

        // ========== COMPARISON OPERATORS ==========
        m.insert("eq", OperatorInfo {
            name: "eq",
            sql_op: "=",
            category: OperatorCategory::Comparison,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("ne", OperatorInfo {
            name: "ne",
            sql_op: "!=",
            category: OperatorCategory::Comparison,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("gt", OperatorInfo {
            name: "gt",
            sql_op: ">",
            category: OperatorCategory::Comparison,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("gte", OperatorInfo {
            name: "gte",
            sql_op: ">=",
            category: OperatorCategory::Comparison,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("lt", OperatorInfo {
            name: "lt",
            sql_op: "<",
            category: OperatorCategory::Comparison,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("lte", OperatorInfo {
            name: "lte",
            sql_op: "<=",
            category: OperatorCategory::Comparison,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("in", OperatorInfo {
            name: "in",
            sql_op: "IN",
            category: OperatorCategory::Comparison,
            requires_array: true,
            jsonb_operator: false,
        });

        m.insert("nin", OperatorInfo {
            name: "nin",
            sql_op: "NOT IN",
            category: OperatorCategory::Comparison,
            requires_array: true,
            jsonb_operator: false,
        });

        // ========== STRING OPERATORS ==========
        m.insert("like", OperatorInfo {
            name: "like",
            sql_op: "LIKE",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("ilike", OperatorInfo {
            name: "ilike",
            sql_op: "ILIKE",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("nlike", OperatorInfo {
            name: "nlike",
            sql_op: "NOT LIKE",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("nilike", OperatorInfo {
            name: "nilike",
            sql_op: "NOT ILIKE",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("regex", OperatorInfo {
            name: "regex",
            sql_op: "~",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("iregex", OperatorInfo {
            name: "iregex",
            sql_op: "~*",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("nregex", OperatorInfo {
            name: "nregex",
            sql_op: "!~",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("niregex", OperatorInfo {
            name: "niregex",
            sql_op: "!~*",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        // ========== NULL OPERATORS ==========
        m.insert("is_null", OperatorInfo {
            name: "is_null",
            sql_op: "IS NULL",
            category: OperatorCategory::Null,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("is_not_null", OperatorInfo {
            name: "is_not_null",
            sql_op: "IS NOT NULL",
            category: OperatorCategory::Null,
            requires_array: false,
            jsonb_operator: false,
        });

        // ========== CONTAINMENT OPERATORS (JSONB) ==========
        m.insert("contains", OperatorInfo {
            name: "contains",
            sql_op: "@>",
            category: OperatorCategory::Containment,
            requires_array: false,
            jsonb_operator: true,
        });

        m.insert("contained_in", OperatorInfo {
            name: "contained_in",
            sql_op: "<@",
            category: OperatorCategory::Containment,
            requires_array: false,
            jsonb_operator: true,
        });

        m.insert("has_key", OperatorInfo {
            name: "has_key",
            sql_op: "?",
            category: OperatorCategory::Containment,
            requires_array: false,
            jsonb_operator: true,
        });

        m.insert("has_any_keys", OperatorInfo {
            name: "has_any_keys",
            sql_op: "?|",
            category: OperatorCategory::Containment,
            requires_array: true,
            jsonb_operator: true,
        });

        m.insert("has_all_keys", OperatorInfo {
            name: "has_all_keys",
            sql_op: "?&",
            category: OperatorCategory::Containment,
            requires_array: true,
            jsonb_operator: true,
        });

        // ========== ARRAY OPERATORS ==========
        m.insert("array_contains", OperatorInfo {
            name: "array_contains",
            sql_op: "@>",
            category: OperatorCategory::Array,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("array_contained_in", OperatorInfo {
            name: "array_contained_in",
            sql_op: "<@",
            category: OperatorCategory::Array,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("array_overlaps", OperatorInfo {
            name: "array_overlaps",
            sql_op: "&&",
            category: OperatorCategory::Array,
            requires_array: false,
            jsonb_operator: false,
        });

        // ========== VECTOR OPERATORS (pgvector) ==========
        m.insert("cosine_distance", OperatorInfo {
            name: "cosine_distance",
            sql_op: "<=>",
            category: OperatorCategory::Vector,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("l2_distance", OperatorInfo {
            name: "l2_distance",
            sql_op: "<->",
            category: OperatorCategory::Vector,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("inner_product", OperatorInfo {
            name: "inner_product",
            sql_op: "<#>",
            category: OperatorCategory::Vector,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("l1_distance", OperatorInfo {
            name: "l1_distance",
            sql_op: "<+>",
            category: OperatorCategory::Vector,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("hamming_distance", OperatorInfo {
            name: "hamming_distance",
            sql_op: "<~>",
            category: OperatorCategory::Vector,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("jaccard_distance", OperatorInfo {
            name: "jaccard_distance",
            sql_op: "<%>",
            category: OperatorCategory::Vector,
            requires_array: false,
            jsonb_operator: false,
        });

        // ========== FULLTEXT OPERATORS ==========
        m.insert("search", OperatorInfo {
            name: "search",
            sql_op: "@@",
            category: OperatorCategory::Fulltext,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("plainto_tsquery", OperatorInfo {
            name: "plainto_tsquery",
            sql_op: "@@",
            category: OperatorCategory::Fulltext,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("phraseto_tsquery", OperatorInfo {
            name: "phraseto_tsquery",
            sql_op: "@@",
            category: OperatorCategory::Fulltext,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("websearch_to_tsquery", OperatorInfo {
            name: "websearch_to_tsquery",
            sql_op: "@@",
            category: OperatorCategory::Fulltext,
            requires_array: false,
            jsonb_operator: false,
        });

        // ========== STRING PATTERN OPERATORS (Extended) ==========
        m.insert("startswith", OperatorInfo {
            name: "startswith",
            sql_op: "LIKE",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("istartswith", OperatorInfo {
            name: "istartswith",
            sql_op: "ILIKE",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("endswith", OperatorInfo {
            name: "endswith",
            sql_op: "LIKE",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("iendswith", OperatorInfo {
            name: "iendswith",
            sql_op: "ILIKE",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("icontains", OperatorInfo {
            name: "icontains",
            sql_op: "ILIKE",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("imatches", OperatorInfo {
            name: "imatches",
            sql_op: "~*",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("not_matches", OperatorInfo {
            name: "not_matches",
            sql_op: "!~",
            category: OperatorCategory::String,
            requires_array: false,
            jsonb_operator: false,
        });

        // ========== NETWORK/IP OPERATORS ==========
        m.insert("isIPv4", OperatorInfo {
            name: "isIPv4",
            sql_op: "family({}) = 4",
            category: OperatorCategory::Network,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("isIPv6", OperatorInfo {
            name: "isIPv6",
            sql_op: "family({}) = 6",
            category: OperatorCategory::Network,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("isPrivate", OperatorInfo {
            name: "isPrivate",
            sql_op: "CIDR_RANGE_CHECK",
            category: OperatorCategory::Network,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("isPublic", OperatorInfo {
            name: "isPublic",
            sql_op: "NOT_CIDR_RANGE_CHECK",
            category: OperatorCategory::Network,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("inSubnet", OperatorInfo {
            name: "inSubnet",
            sql_op: "{} <<= {}",
            category: OperatorCategory::Network,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("notInSubnet", OperatorInfo {
            name: "notInSubnet",
            sql_op: "NOT ({} <<= {})",
            category: OperatorCategory::Network,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("subnet_contains", OperatorInfo {
            name: "subnet_contains",
            sql_op: ">>",
            category: OperatorCategory::Network,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("subnet_overlaps", OperatorInfo {
            name: "subnet_overlaps",
            sql_op: "&&",
            category: OperatorCategory::Network,
            requires_array: false,
            jsonb_operator: false,
        });

        // ========== DATE/RANGE OPERATORS ==========
        m.insert("contains_date", OperatorInfo {
            name: "contains_date",
            sql_op: "@>",
            category: OperatorCategory::DateRange,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("adjacent", OperatorInfo {
            name: "adjacent",
            sql_op: "-|-",
            category: OperatorCategory::DateRange,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("strictly_left", OperatorInfo {
            name: "strictly_left",
            sql_op: "<<",
            category: OperatorCategory::DateRange,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("strictly_right", OperatorInfo {
            name: "strictly_right",
            sql_op: ">>",
            category: OperatorCategory::DateRange,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("not_left", OperatorInfo {
            name: "not_left",
            sql_op: "&>",
            category: OperatorCategory::DateRange,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("not_right", OperatorInfo {
            name: "not_right",
            sql_op: "&<",
            category: OperatorCategory::DateRange,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("overlaps", OperatorInfo {
            name: "overlaps",
            sql_op: "&&",
            category: OperatorCategory::DateRange,
            requires_array: false,
            jsonb_operator: false,
        });

        // ========== LTREE (HIERARCHICAL) OPERATORS ==========
        m.insert("ancestor_of", OperatorInfo {
            name: "ancestor_of",
            sql_op: "@>",
            category: OperatorCategory::Ltree,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("descendant_of", OperatorInfo {
            name: "descendant_of",
            sql_op: "<@",
            category: OperatorCategory::Ltree,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("matches_lquery", OperatorInfo {
            name: "matches_lquery",
            sql_op: "~",
            category: OperatorCategory::Ltree,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("matches_ltxtquery", OperatorInfo {
            name: "matches_ltxtquery",
            sql_op: "@",
            category: OperatorCategory::Ltree,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("matches_any_lquery", OperatorInfo {
            name: "matches_any_lquery",
            sql_op: "?",
            category: OperatorCategory::Ltree,
            requires_array: true,
            jsonb_operator: false,
        });

        // ========== PATH OPERATORS ==========
        m.insert("depth_eq", OperatorInfo {
            name: "depth_eq",
            sql_op: "nlevel({}) =",
            category: OperatorCategory::Path,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("depth_gt", OperatorInfo {
            name: "depth_gt",
            sql_op: "nlevel({}) >",
            category: OperatorCategory::Path,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("depth_lt", OperatorInfo {
            name: "depth_lt",
            sql_op: "nlevel({}) <",
            category: OperatorCategory::Path,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("isdescendant", OperatorInfo {
            name: "isdescendant",
            sql_op: "<@",
            category: OperatorCategory::Path,
            requires_array: false,
            jsonb_operator: false,
        });

        // ========== SPATIAL/COORDINATE OPERATORS ==========
        m.insert("distance_within", OperatorInfo {
            name: "distance_within",
            sql_op: "distance_within",
            category: OperatorCategory::Spatial,
            requires_array: false,
            jsonb_operator: false,
        });

        // ========== JSONB ADVANCED OPERATORS ==========
        m.insert("strictly_contains", OperatorInfo {
            name: "strictly_contains",
            sql_op: "@>",
            category: OperatorCategory::Containment,
            requires_array: false,
            jsonb_operator: true,
        });

        // ========== ADDITIONAL ALIASES ==========
        m.insert("neq", OperatorInfo {
            name: "neq",
            sql_op: "!=",
            category: OperatorCategory::Comparison,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("isnull", OperatorInfo {
            name: "isnull",
            sql_op: "IS NULL",
            category: OperatorCategory::Null,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("array_eq", OperatorInfo {
            name: "array_eq",
            sql_op: "=",
            category: OperatorCategory::Array,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("array_neq", OperatorInfo {
            name: "array_neq",
            sql_op: "!=",
            category: OperatorCategory::Array,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("array_contained_by", OperatorInfo {
            name: "array_contained_by",
            sql_op: "<@",
            category: OperatorCategory::Array,
            requires_array: false,
            jsonb_operator: false,
        });

        m.insert("notin", OperatorInfo {
            name: "notin",
            sql_op: "NOT IN",
            category: OperatorCategory::Comparison,
            requires_array: true,
            jsonb_operator: false,
        });

        m
    };
}

/// Get operator information by name
///
/// # Example
/// ```
/// use fraiseql_rs::query::operators::get_operator_info;
///
/// let op = get_operator_info("eq").unwrap();
/// assert_eq!(op.sql_op, "=");
/// ```
#[must_use]
pub fn get_operator_info(name: &str) -> Option<&'static OperatorInfo> {
    OPERATOR_REGISTRY.get(name)
}

/// Check if a string is a valid operator name
///
/// # Example
/// ```
/// use fraiseql_rs::query::operators::is_operator;
///
/// assert!(is_operator("eq"));
/// assert!(is_operator("contains"));
/// assert!(!is_operator("unknown_operator"));
/// ```
#[must_use]
pub fn is_operator(name: &str) -> bool {
    OPERATOR_REGISTRY.contains_key(name)
}

/// Get all operators in a specific category
///
/// # Example
/// ```
/// use fraiseql_rs::query::operators::{get_operators_by_category, OperatorCategory};
///
/// let comparison_ops = get_operators_by_category(OperatorCategory::Comparison);
/// assert!(comparison_ops.len() >= 8);
/// ```
#[must_use]
pub fn get_operators_by_category(category: OperatorCategory) -> Vec<&'static OperatorInfo> {
    OPERATOR_REGISTRY
        .values()
        .filter(|op| op.category == category)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_operator_registry_initialized() {
        // Should have all 40+ operators
        assert!(OPERATOR_REGISTRY.len() >= 40);
    }

    #[test]
    fn test_comparison_operators() {
        let operators = ["eq", "ne", "gt", "gte", "lt", "lte", "in", "nin"];

        for op_name in &operators {
            let op = get_operator_info(op_name);
            assert!(op.is_some(), "Operator {op_name} should exist");

            let op = op.unwrap();
            assert_eq!(op.category, OperatorCategory::Comparison);
            assert!(!op.jsonb_operator);
        }
    }

    #[test]
    fn test_string_operators() {
        let operators = [
            "like", "ilike", "nlike", "nilike", "regex", "iregex", "nregex", "niregex",
        ];

        for op_name in &operators {
            let op = get_operator_info(op_name);
            assert!(op.is_some(), "String operator {op_name} should exist");

            let op = op.unwrap();
            assert_eq!(op.category, OperatorCategory::String);
        }
    }

    #[test]
    fn test_null_operators() {
        let op1 = get_operator_info("is_null").unwrap();
        assert_eq!(op1.sql_op, "IS NULL");
        assert_eq!(op1.category, OperatorCategory::Null);

        let op2 = get_operator_info("is_not_null").unwrap();
        assert_eq!(op2.sql_op, "IS NOT NULL");
        assert_eq!(op2.category, OperatorCategory::Null);
    }

    #[test]
    fn test_containment_operators() {
        let operators = [
            "contains",
            "contained_in",
            "has_key",
            "has_any_keys",
            "has_all_keys",
        ];

        for op_name in &operators {
            let op = get_operator_info(op_name);
            assert!(op.is_some(), "Containment operator {op_name} should exist");

            let op = op.unwrap();
            assert_eq!(op.category, OperatorCategory::Containment);
            assert!(op.jsonb_operator, "{op_name} should be JSONB operator");
        }
    }

    #[test]
    fn test_array_operators() {
        let operators = ["array_contains", "array_contained_in", "array_overlaps"];

        for op_name in &operators {
            let op = get_operator_info(op_name);
            assert!(op.is_some(), "Array operator {op_name} should exist");

            let op = op.unwrap();
            assert_eq!(op.category, OperatorCategory::Array);
        }
    }

    #[test]
    fn test_vector_operators() {
        let operators = [
            ("cosine_distance", "<=>"),
            ("l2_distance", "<->"),
            ("inner_product", "<#>"),
            ("l1_distance", "<+>"),
            ("hamming_distance", "<~>"),
            ("jaccard_distance", "<%>"),
        ];

        for (op_name, expected_sql) in &operators {
            let op = get_operator_info(op_name);
            assert!(op.is_some(), "Vector operator {op_name} should exist");

            let op = op.unwrap();
            assert_eq!(op.category, OperatorCategory::Vector);
            assert_eq!(op.sql_op, *expected_sql);
        }
    }

    #[test]
    fn test_fulltext_operators() {
        let operators = [
            "search",
            "plainto_tsquery",
            "phraseto_tsquery",
            "websearch_to_tsquery",
        ];

        for op_name in &operators {
            let op = get_operator_info(op_name);
            assert!(op.is_some(), "Fulltext operator {op_name} should exist");

            let op = op.unwrap();
            assert_eq!(op.category, OperatorCategory::Fulltext);
            assert_eq!(op.sql_op, "@@");
        }
    }

    #[test]
    fn test_is_operator() {
        assert!(is_operator("eq"));
        assert!(is_operator("contains"));
        assert!(is_operator("cosine_distance"));
        assert!(!is_operator("invalid_operator"));
        assert!(!is_operator(""));
    }

    #[test]
    fn test_get_operators_by_category() {
        let comparison_ops = get_operators_by_category(OperatorCategory::Comparison);
        assert!(comparison_ops.len() >= 8);

        let vector_ops = get_operators_by_category(OperatorCategory::Vector);
        assert!(vector_ops.len() >= 6);

        let fulltext_ops = get_operators_by_category(OperatorCategory::Fulltext);
        assert!(fulltext_ops.len() >= 4);
    }

    #[test]
    fn test_requires_array_flag() {
        // IN and NOT IN require arrays
        assert!(get_operator_info("in").unwrap().requires_array);
        assert!(get_operator_info("nin").unwrap().requires_array);

        // Most operators don't require arrays
        assert!(!get_operator_info("eq").unwrap().requires_array);
        assert!(!get_operator_info("like").unwrap().requires_array);
    }

    #[test]
    fn test_jsonb_operator_flag() {
        // Containment operators are JSONB-specific
        assert!(get_operator_info("contains").unwrap().jsonb_operator);
        assert!(get_operator_info("has_key").unwrap().jsonb_operator);

        // Most operators are not JSONB-specific
        assert!(!get_operator_info("eq").unwrap().jsonb_operator);
        assert!(!get_operator_info("like").unwrap().jsonb_operator);
    }
}
