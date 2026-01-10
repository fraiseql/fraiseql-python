//! PyO3 FFI wrapper for APQ hasher (Phase 6.4).
//!
//! This module provides Python bindings for the pure Rust APQ query hashing
//! functionality defined in fraiseql_core::apq::hasher.
//!
//! Note: The pure hasher types are in core/src/apq/hasher.rs

use fraiseql_core::apq::hasher as core_hasher;
use pyo3::prelude::*;
use serde_json::Value as JsonValue;

/// Compute SHA-256 hash of a GraphQL query
///
/// # Arguments
///
/// * `query` - The GraphQL query string
///
/// # Returns
///
/// A hexadecimal string representation of the SHA-256 hash (64 characters)
///
/// # Examples
///
/// ```python
/// import _fraiseql_rs
///
/// query = "{ users { id name } }"
/// hash_value = _fraiseql_rs.hash_query(query)
/// assert len(hash_value) == 64  # SHA-256 produces 64 hex chars
/// ```
#[pyfunction]
#[must_use]
pub fn hash_query(query: &str) -> String {
    core_hasher::hash_query(query)
}

/// Verify that a query matches the provided hash
///
/// # Arguments
///
/// * `query` - The GraphQL query string
/// * `expected_hash` - The expected SHA-256 hash (hexadecimal)
///
/// # Returns
///
/// `true` if the query hash matches the expected hash, `false` otherwise
///
/// # Examples
///
/// ```python
/// import _fraiseql_rs
///
/// query = "{ users { id name } }"
/// hash_value = _fraiseql_rs.hash_query(query)
/// assert _fraiseql_rs.verify_hash(query, hash_value)
/// assert not _fraiseql_rs.verify_hash(query, "invalid_hash")
/// ```
#[pyfunction]
#[must_use]
pub fn verify_hash(query: &str, expected_hash: &str) -> bool {
    core_hasher::verify_hash(query, expected_hash)
}

/// Compute combined hash of query + variables for response caching
///
/// **SECURITY CRITICAL**: This function combines query hash with normalized
/// variables to create a cache key that prevents data leakage between requests
/// with different variable values.
///
/// # Arguments
///
/// * `query` - The GraphQL query string
/// * `variables` - Optional GraphQL variables as JSON string (JSON serialized)
///
/// # Returns
///
/// A hexadecimal string representing the combined SHA-256 hash
///
/// # Examples
///
/// ```python
/// import _fraiseql_rs
/// import json
///
/// query = "query getUser($id: ID!) { user(id: $id) { name } }"
/// variables_dict = {"id": "123"}
/// variables_json = json.dumps(variables_dict)
/// cache_key = _fraiseql_rs.hash_query_with_variables(query, variables_json)
/// assert len(cache_key) == 64  # SHA-256 produces 64 hex chars
/// ```
///
/// # Security Notes
///
/// - Variables are normalized with sorted keys for consistent hashing
/// - Different variable values ALWAYS produce different hashes
/// - None/null variables fall back to query-only hash
/// - Safe for use as response cache key
///
/// # Data Leakage Prevention
///
/// Without variable-aware hashing:
/// - Client A: POST { user(id: "123") } → cached response for user 123
/// - Client B: POST { user(id: "456") } → receives cached response for user 123!
///
/// With hash_query_with_variables():
/// - Client A: cache_key = hash(query, variables_json_a)
/// - Client B: cache_key = hash(query, variables_json_b) (different!)
/// - No data leakage possible
#[pyfunction]
#[pyo3(signature = (query, variables=None))]
#[must_use]
pub fn hash_query_with_variables(query: &str, variables: Option<&str>) -> String {
    // Convert optional JSON string to serde_json::Value
    let json_value = match variables {
        None => JsonValue::Null,
        Some(json_str) => serde_json::from_str(json_str).unwrap_or(JsonValue::Null),
    };

    core_hasher::hash_query_with_variables(query, &json_value)
}

/// Verify that query + variables match the provided combined hash
///
/// **SECURITY CRITICAL**: Use this to validate APQ response cache hits.
///
/// # Arguments
///
/// * `query` - The GraphQL query string
/// * `expected_hash` - The expected combined hash (hexadecimal)
/// * `variables` - GraphQL variables as JSON string (JSON serialized, optional)
///
/// # Returns
///
/// `true` if the combined hash matches, `false` otherwise
///
/// # Examples
///
/// ```python
/// import _fraiseql_rs
/// import json
///
/// query = "{ users { id } }"
/// variables_dict = {"limit": 10}
/// variables_json = json.dumps(variables_dict)
/// hash_value = _fraiseql_rs.hash_query_with_variables(query, variables_json)
/// assert _fraiseql_rs.verify_hash_with_variables(query, hash_value, variables_json)
/// ```
#[pyfunction]
#[pyo3(signature = (query, expected_hash, variables=None))]
#[must_use]
pub fn verify_hash_with_variables(query: &str, expected_hash: &str, variables: Option<&str>) -> bool {
    // Convert optional JSON string to serde_json::Value
    let json_value = match variables {
        None => JsonValue::Null,
        Some(json_str) => serde_json::from_str(json_str).unwrap_or(JsonValue::Null),
    };

    core_hasher::verify_hash_with_variables(query, &json_value, expected_hash)
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hash_query_ffi() {
        let query = "{ users { id name } }";
        let hash = hash_query(query);

        // Should produce 64-character SHA-256 hash
        assert_eq!(hash.len(), 64);
        assert!(hash.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn test_verify_hash_ffi() {
        let query = "{ users { id name } }";
        let hash = hash_query(query);

        assert!(verify_hash(query, &hash));
        assert!(!verify_hash(query, "invalid_hash"));
    }

    #[test]
    fn test_hash_query_with_variables_null_ffi() {
        let query = "{ users { id } }";

        // When variables is None, should use query hash only
        let hash = core_hasher::hash_query_with_variables(query, &JsonValue::Null);
        let query_only = hash_query(query);

        assert_eq!(hash, query_only);
    }

    #[test]
    fn test_hash_deterministic_across_calls_ffi() {
        let query = "query test($x: Int!) { test(x: $x) { id } }";

        let hashes: Vec<String> = (0..5).map(|_| hash_query(query)).collect();

        // All hashes should be identical
        for i in 1..5 {
            assert_eq!(hashes[0], hashes[i]);
        }
    }

    #[test]
    fn test_verify_hash_with_variables_no_vars_ffi() {
        let query = "{ users { id } }";
        let expected_hash = "0c3f1c1f1c1f1c1f1c1f1c1f1c1f1c1f1c1f1c1f1c1f1c1f1c1f1c1f1c1f1c1f";

        // This should fail verification
        assert!(!verify_hash_with_variables(query, expected_hash, None));
    }

    #[test]
    fn test_verify_hash_with_variables_json_ffi() {
        let query = "{ users { id } }";
        let variables_json = r#"{"limit": 10}"#;

        let hash = hash_query_with_variables(query, Some(variables_json));

        // Verification should pass with same variables
        assert!(verify_hash_with_variables(query, &hash, Some(variables_json)));

        // Verification should fail with different variables
        let different_vars = r#"{"limit": 20}"#;
        assert!(!verify_hash_with_variables(query, &hash, Some(different_vars)));
    }
}
