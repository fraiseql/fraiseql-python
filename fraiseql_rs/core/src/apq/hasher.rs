//! Query hashing for APQ (Automatic Persisted Queries) - Phase 6.4
//!
//! Provides SHA-256 hashing for GraphQL queries to create persisted query IDs.
//!
//! **SECURITY CRITICAL**: Response cache keys MUST include variables to prevent
//! data leakage between requests with different variable values.
//!
//! Example vulnerability if variables not included in cache key:
//! - Client A: POST { user(id: "123") } → cached response for user 123
//! - Client B: POST { user(id: "456") } → receives cached response for user 123!
//!
//! Mitigation: Use `hash_query_with_variables()` for response caching.

use serde_json::Value as JsonValue;
use sha2::{Digest, Sha256};

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
/// ```ignore
/// let query = "{ users { id name } }";
/// let hash = hash_query(query);
/// assert_eq!(hash.len(), 64); // SHA-256 produces 64 hex chars
/// ```
#[must_use]
pub fn hash_query(query: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(query.as_bytes());
    let result = hasher.finalize();
    hex::encode(result)
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
/// ```ignore
/// let query = "{ users { id name } }";
/// let hash = hash_query(query);
/// assert!(verify_hash(query, &hash));
/// assert!(!verify_hash(query, "invalid_hash"));
/// ```
#[must_use]
pub fn verify_hash(query: &str, expected_hash: &str) -> bool {
    hash_query(query) == expected_hash
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
/// * `variables` - Optional GraphQL variables as JSON object
///
/// # Returns
///
/// A hexadecimal string representing the combined SHA-256 hash
///
/// # Examples
///
/// ```ignore
/// use serde_json::json;
///
/// let query = "query getUser($id: ID!) { user(id: $id) { name } }";
/// let vars = json!({"id": "123"});
/// let cache_key = hash_query_with_variables(query, &vars);
/// assert_eq!(cache_key.len(), 64); // SHA-256 produces 64 hex chars
/// ```
///
/// # Security Notes
///
/// - Variables are normalized with sorted keys for consistent hashing
/// - Different variable values ALWAYS produce different hashes
/// - Empty/null variables fall back to query-only hash
/// - Safe for use as response cache key
#[must_use]
pub fn hash_query_with_variables(query: &str, variables: &JsonValue) -> String {
    // Step 1: Compute base query hash
    let query_hash = hash_query(query);

    // Step 2: Check if variables are empty/null
    let is_empty =
        variables.is_null() || variables.as_object().is_some_and(serde_json::Map::is_empty);

    if is_empty {
        // No variables, use query hash only
        return query_hash;
    }

    // Step 3: Normalize variables - serialize to JSON with sorted keys
    // This ensures {"a":1,"b":2} and {"b":2,"a":1} produce the same hash
    let variables_json = serde_json::to_string(variables).unwrap_or_default();

    // Step 4: Combine query hash and normalized variables
    let combined = format!("{query_hash}:{variables_json}");

    // Step 5: Hash the combination for final cache key
    let mut hasher = Sha256::new();
    hasher.update(combined.as_bytes());
    hex::encode(hasher.finalize())
}

/// Verify that query + variables match the provided combined hash
///
/// **SECURITY CRITICAL**: Use this to validate APQ response cache hits.
///
/// # Arguments
///
/// * `query` - The GraphQL query string
/// * `variables` - GraphQL variables as JSON object
/// * `expected_hash` - The expected combined hash (hexadecimal)
///
/// # Returns
///
/// `true` if the combined hash matches, `false` otherwise
///
/// # Examples
///
/// ```ignore
/// use serde_json::json;
///
/// let query = "{ users { id } }";
/// let vars = json!({"limit": 10});
/// let hash = hash_query_with_variables(query, &vars);
/// assert!(verify_hash_with_variables(query, &vars, &hash));
/// ```
#[must_use]
pub fn verify_hash_with_variables(query: &str, variables: &JsonValue, expected_hash: &str) -> bool {
    hash_query_with_variables(query, variables) == expected_hash
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hash_query_deterministic() {
        let query = "{ users { id name } }";
        let hash1 = hash_query(query);
        let hash2 = hash_query(query);

        // Hash should be deterministic
        assert_eq!(hash1, hash2);
    }

    #[test]
    fn test_hash_query_length() {
        let query = "{ users { id name } }";
        let hash = hash_query(query);

        // SHA-256 hex is 64 characters
        assert_eq!(hash.len(), 64);
    }

    #[test]
    fn test_hash_query_hex_format() {
        let query = "{ users { id name } }";
        let hash = hash_query(query);

        // Should only contain hex characters
        assert!(hash.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn test_verify_hash_valid() {
        let query = "{ users { id name } }";
        let hash = hash_query(query);

        assert!(verify_hash(query, &hash));
    }

    #[test]
    fn test_verify_hash_invalid() {
        let query = "{ users { id name } }";
        assert!(!verify_hash(query, "invalid_hash"));
    }

    #[test]
    fn test_different_queries_different_hashes() {
        let query1 = "{ users { id } }";
        let query2 = "{ users { name } }";

        let hash1 = hash_query(query1);
        let hash2 = hash_query(query2);

        assert_ne!(hash1, hash2);
    }

    #[test]
    fn test_whitespace_affects_hash() {
        let query1 = "{ users { id } }";
        let query2 = "{users{id}}"; // No whitespace

        let hash1 = hash_query(query1);
        let hash2 = hash_query(query2);

        // Different whitespace = different hash
        assert_ne!(hash1, hash2);
    }

    #[test]
    fn test_hash_empty_query() {
        let hash = hash_query("");
        assert_eq!(hash.len(), 64);
        // Empty string has a well-known SHA-256 hash
        assert_eq!(
            hash,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }

    #[test]
    fn test_hash_large_query() {
        let large_query =
            "{ users { id name email address { street city state zip } posts { id title } } }";
        let hash = hash_query(large_query);

        assert_eq!(hash.len(), 64);
        assert!(hash.chars().all(|c| c.is_ascii_hexdigit()));
    }

    // =================================================================
    // SECURITY CRITICAL TESTS: Variable-aware hashing to prevent data leakage
    // =================================================================

    #[test]
    fn test_hash_query_with_variables_deterministic() {
        use serde_json::json;

        let query = "query getUser($id: ID!) { user(id: $id) { name } }";
        let vars = json!({"id": "123"});

        let hash1 = hash_query_with_variables(query, &vars);
        let hash2 = hash_query_with_variables(query, &vars);

        assert_eq!(hash1, hash2, "Same variables must produce same hash");
    }

    #[test]
    fn test_hash_query_with_variables_different_values_produce_different_hashes() {
        use serde_json::json;

        let query = "query getUser($id: ID!) { user(id: $id) { name } }";

        let vars1 = json!({"id": "user-123"});
        let vars2 = json!({"id": "user-456"});

        let hash1 = hash_query_with_variables(query, &vars1);
        let hash2 = hash_query_with_variables(query, &vars2);

        assert_ne!(
            hash1, hash2,
            "Different variable values MUST produce different hashes (SECURITY)"
        );
    }

    #[test]
    fn test_hash_query_with_variables_different_param_names_different_hashes() {
        use serde_json::json;

        let query = "{ users { id } }";

        let vars1 = json!({"limit": 10});
        let vars2 = json!({"offset": 10});

        let hash1 = hash_query_with_variables(query, &vars1);
        let hash2 = hash_query_with_variables(query, &vars2);

        assert_ne!(
            hash1, hash2,
            "Different parameter names must produce different hashes"
        );
    }

    #[test]
    fn test_hash_query_with_empty_variables_uses_query_hash_only() {
        use serde_json::json;

        let query = "{ users { id } }";
        let empty_vars = json!({});

        let hash_with_empty = hash_query_with_variables(query, &empty_vars);
        let hash_query_only = hash_query(query);

        assert_eq!(
            hash_with_empty, hash_query_only,
            "Empty variables should use query hash only"
        );
    }

    #[test]
    fn test_hash_query_with_null_variables_uses_query_hash_only() {
        use serde_json::Value;

        let query = "{ users { id } }";
        let null_vars = Value::Null;

        let hash_with_null = hash_query_with_variables(query, &null_vars);
        let hash_query_only = hash_query(query);

        assert_eq!(
            hash_with_null, hash_query_only,
            "Null variables should use query hash only"
        );
    }

    #[test]
    fn test_hash_query_with_variables_multiple_params() {
        use serde_json::json;

        let query =
            "query search($q: String!, $limit: Int!) { search(q: $q, limit: $limit) { id } }";

        let vars = json!({"q": "test", "limit": 50});

        let hash = hash_query_with_variables(query, &vars);

        assert_eq!(hash.len(), 64);
        assert!(hash.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn test_hash_query_with_variables_complex_nested_variables() {
        use serde_json::json;

        let query = "mutation createUser($input: UserInput!) { createUser(input: $input) { id } }";

        let vars = json!({
            "input": {
                "name": "Alice",
                "email": "alice@example.com",
                "roles": ["admin", "user"],
                "metadata": {
                    "tier": "premium",
                    "verified": true
                }
            }
        });

        let hash = hash_query_with_variables(query, &vars);

        assert_eq!(hash.len(), 64);
        assert!(hash.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn test_hash_query_with_variables_key_order_independence() {
        use serde_json::json;

        let query = "{ users { id } }";

        // Same variables, different JSON key order
        let vars1 = json!({"a": 1, "b": 2, "c": 3});
        let vars2 = json!({"c": 3, "a": 1, "b": 2});

        let hash1 = hash_query_with_variables(query, &vars1);
        let hash2 = hash_query_with_variables(query, &vars2);

        assert_eq!(
            hash1, hash2,
            "Variable key order must not affect hash (JSON normalized)"
        );
    }

    #[test]
    fn test_verify_hash_with_variables_valid() {
        use serde_json::json;

        let query = "{ users { id } }";
        let vars = json!({"limit": 10});

        let hash = hash_query_with_variables(query, &vars);

        assert!(verify_hash_with_variables(query, &vars, &hash));
    }

    #[test]
    fn test_verify_hash_with_variables_invalid() {
        use serde_json::json;

        let query = "{ users { id } }";
        let vars = json!({"limit": 10});

        assert!(!verify_hash_with_variables(query, &vars, "invalid_hash"));
    }

    #[test]
    fn test_verify_hash_with_variables_different_variables_fails() {
        use serde_json::json;

        let query = "query getUser($id: ID!) { user(id: $id) { name } }";

        let vars_original = json!({"id": "123"});
        let vars_different = json!({"id": "456"});

        let hash = hash_query_with_variables(query, &vars_original);

        // Verification fails if variables don't match
        assert!(!verify_hash_with_variables(query, &vars_different, &hash));
    }

    #[test]
    fn test_hash_deterministic_across_runs() {
        use serde_json::json;

        let query = "query test($x: Int!) { test(x: $x) { id } }";
        let vars = json!({"x": 42});

        // Run the hash multiple times
        let hashes: Vec<String> = (0..10)
            .map(|_| hash_query_with_variables(query, &vars))
            .collect();

        // All hashes should be identical
        for i in 1..10 {
            assert_eq!(
                hashes[0], hashes[i],
                "Hash must be deterministic across multiple runs"
            );
        }
    }

    #[test]
    fn test_hash_query_with_variables_length() {
        use serde_json::json;

        let query = "{ users { id } }";
        let vars = json!({"limit": 10});

        let hash = hash_query_with_variables(query, &vars);

        // SHA-256 hex is 64 characters
        assert_eq!(
            hash.len(),
            64,
            "Combined hash must be SHA-256 length (64 hex chars)"
        );
    }

    #[test]
    fn test_hash_query_with_variables_hex_format() {
        use serde_json::json;

        let query = "{ users { id } }";
        let vars = json!({"limit": 10});

        let hash = hash_query_with_variables(query, &vars);

        // Should only contain hex characters
        assert!(
            hash.chars().all(|c| c.is_ascii_hexdigit()),
            "Combined hash must be valid hexadecimal"
        );
    }

    // SECURITY TEST: Simulates the data leakage vulnerability
    #[test]
    fn test_security_scenario_prevents_data_leakage() {
        use serde_json::json;

        // Scenario: Same query, different user IDs
        let query = "query getUser($userId: ID!) { user(id: $userId) { name email } }";

        // User A's request
        let alice_vars = json!({"userId": "alice-uuid-123"});
        let alice_cache_key = hash_query_with_variables(query, &alice_vars);

        // User B's request with different ID
        let bob_vars = json!({"userId": "bob-uuid-456"});
        let bob_cache_key = hash_query_with_variables(query, &bob_vars);

        // CRITICAL: Different variables MUST produce different cache keys
        assert_ne!(
            alice_cache_key, bob_cache_key,
            "SECURITY: Different user IDs must produce different cache keys to prevent data leakage"
        );

        // Even if cached, verification should fail with wrong variables
        assert!(
            !verify_hash_with_variables(query, &bob_vars, &alice_cache_key),
            "SECURITY: Cache hit should not occur with different variables"
        );
    }
}
