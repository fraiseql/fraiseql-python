//! Cache coherency validation (Phase 17A.6)
//!
//! Validates that the cache maintains consistency guarantees:
//! - No stale data served after invalidation
//! - All affected queries invalidated on mutations
//! - Dependency tracking is accurate
//! - State is consistent across all operations

use serde_json::Value;
use std::collections::{HashMap, HashSet};

/// Result of coherency validation
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CoherencyValidationResult {
    /// Cache is coherent and consistent
    Valid,

    /// Cache has coherency issues
    Invalid(Vec<String>),
}

/// Coherency validator for cache operations
#[derive(Debug)]
pub struct CoherencyValidator {
    /// Track all cached entries and their dependencies
    cached_entries: HashMap<String, CachedQueryInfo>,

    /// Track all entity->query mappings
    entity_to_queries: HashMap<String, HashSet<String>>,
}

/// Information about a cached query
#[derive(Debug, Clone)]
struct CachedQueryInfo {
    /// Entities this query accesses
    entities: Vec<(String, String)>,

    /// Data version (for tracking changes)
    version: u64,
}

impl CoherencyValidator {
    /// Create a new coherency validator
    #[must_use]
    pub fn new() -> Self {
        Self {
            cached_entries: HashMap::new(),
            entity_to_queries: HashMap::new(),
        }
    }

    /// Record that a query is now cached
    ///
    /// # Errors
    /// Returns error if recording fails
    pub fn record_cache_put(
        &mut self,
        cache_key: &str,
        entities: Vec<(String, String)>,
    ) -> Result<(), String> {
        // Check for duplicate (overwrite is ok)
        let version = self
            .cached_entries
            .get(cache_key)
            .map_or(0, |info| info.version + 1);

        let info = CachedQueryInfo {
            entities: entities.clone(),
            version,
        };

        // Update entry mapping
        self.cached_entries.insert(cache_key.to_string(), info);

        // Update entity->query reverse mapping
        for (entity_type, entity_id) in entities {
            let entity_key = format!("{entity_type}:{entity_id}");
            self.entity_to_queries
                .entry(entity_key)
                .or_default()
                .insert(cache_key.to_string());
        }

        Ok(())
    }

    /// Record that a query was invalidated
    ///
    /// # Errors
    /// Returns error if invalidation fails
    pub fn record_invalidation(&mut self, cache_key: &str) -> Result<(), String> {
        if let Some(info) = self.cached_entries.remove(cache_key) {
            // Remove from entity->query mappings
            for (entity_type, entity_id) in &info.entities {
                let entity_key = format!("{entity_type}:{entity_id}");
                if let Some(queries) = self.entity_to_queries.get_mut(&entity_key) {
                    queries.remove(cache_key);
                }
            }
        }
        Ok(())
    }

    /// Validate that invalidation is correct for a cascade
    #[must_use]
    pub fn validate_cascade_invalidation(
        &self,
        cascade: &Value,
        invalidated_queries: &[String],
    ) -> CoherencyValidationResult {
        let mut issues = Vec::new();

        // Extract entities from cascade
        let entities_to_invalidate = extract_cascade_entities(cascade);

        // Find all queries that should be invalidated
        let expected_invalidated = self.find_affected_queries(&entities_to_invalidate);

        // Check 1: No missing invalidations
        for query in &expected_invalidated {
            if !invalidated_queries.contains(query) {
                issues.push(format!(
                    "Expected query to be invalidated but wasn't: {query}"
                ));
            }
        }

        // Check 2: No spurious invalidations (shouldn't happen with correct algorithm)
        for query in invalidated_queries {
            if !expected_invalidated.contains(query) {
                // This is actually ok - extra invalidations are safe
                // just means being conservative
            }
        }

        // Check 3: Entity mappings are consistent
        for query_key in invalidated_queries {
            if self.cached_entries.contains_key(query_key) {
                issues.push(format!("Invalidated query still in cache: {query_key}"));
            }
        }

        if issues.is_empty() {
            CoherencyValidationResult::Valid
        } else {
            CoherencyValidationResult::Invalid(issues)
        }
    }

    /// Find all queries affected by these entities
    fn find_affected_queries(&self, entities: &[(String, String)]) -> HashSet<String> {
        let mut affected = HashSet::new();

        for (entity_type, entity_id) in entities {
            // Check specific entity
            let specific_key = format!("{entity_type}:{entity_id}");
            if let Some(queries) = self.entity_to_queries.get(&specific_key) {
                affected.extend(queries.iter().cloned());
            }

            // Check wildcard (all entities of this type)
            let wildcard_key = format!("{entity_type}:*");
            if let Some(queries) = self.entity_to_queries.get(&wildcard_key) {
                affected.extend(queries.iter().cloned());
            }
        }

        affected
    }

    /// Validate that all cached entries are consistent
    #[must_use]
    pub fn validate_consistency(&self) -> CoherencyValidationResult {
        let mut issues = Vec::new();
        issues.extend(self.check_cached_entries_have_mappings());
        issues.extend(self.check_no_orphaned_entries());

        if issues.is_empty() {
            CoherencyValidationResult::Valid
        } else {
            CoherencyValidationResult::Invalid(issues)
        }
    }

    /// Check that all cached entries have valid entity mappings
    fn check_cached_entries_have_mappings(&self) -> Vec<String> {
        let mut issues = Vec::new();
        for (cache_key, info) in &self.cached_entries {
            for (entity_type, entity_id) in &info.entities {
                let entity_key = format!("{entity_type}:{entity_id}");
                self.check_entity_mapping(&entity_key, cache_key, &mut issues);
            }
        }
        issues
    }

    /// Check single entity mapping consistency
    fn check_entity_mapping(&self, entity_key: &str, cache_key: &str, issues: &mut Vec<String>) {
        if let Some(queries) = self.entity_to_queries.get(entity_key) {
            if !queries.contains(cache_key) {
                issues.push(format!(
                    "Cache entry {cache_key} not in reverse mapping for entity {entity_key}"
                ));
            }
        } else {
            issues.push(format!(
                "Cache entry {cache_key} references missing entity {entity_key}"
            ));
        }
    }

    /// Check that no orphaned entries exist in entity mappings
    fn check_no_orphaned_entries(&self) -> Vec<String> {
        let mut issues = Vec::new();
        for (entity_key, queries) in &self.entity_to_queries {
            for query_key in queries {
                if !self.cached_entries.contains_key(query_key) {
                    issues.push(format!(
                        "Entity mapping {entity_key} references missing cache entry {query_key}"
                    ));
                }
            }
        }
        issues
    }

    /// Get the set of cached queries
    #[must_use]
    pub fn cached_queries(&self) -> HashSet<String> {
        self.cached_entries.keys().cloned().collect()
    }

    /// Get entities affected by a query
    #[must_use]
    pub fn query_entities(&self, cache_key: &str) -> Vec<(String, String)> {
        self.cached_entries
            .get(cache_key)
            .map(|info| info.entities.clone())
            .unwrap_or_default()
    }

    /// Get all queries accessing an entity
    #[must_use]
    pub fn entity_queries(&self, entity_type: &str, entity_id: &str) -> HashSet<String> {
        let entity_key = format!("{entity_type}:{entity_id}");
        self.entity_to_queries
            .get(&entity_key)
            .cloned()
            .unwrap_or_default()
    }

    /// Clear all state
    pub fn clear(&mut self) {
        self.cached_entries.clear();
        self.entity_to_queries.clear();
    }
}

impl Default for CoherencyValidator {
    fn default() -> Self {
        Self::new()
    }
}

/// Extract entities mentioned in cascade invalidation
fn extract_cascade_entities(cascade: &Value) -> Vec<(String, String)> {
    let mut entities = Vec::new();

    if let Some(invalidations) = cascade.get("invalidations") {
        // Extract from "updated"
        if let Some(updated) = invalidations.get("updated").and_then(|v| v.as_array()) {
            for item in updated {
                if let (Some(entity_type), Some(entity_id)) = (
                    item.get("type").and_then(|v| v.as_str()),
                    item.get("id").and_then(|v| v.as_str()),
                ) {
                    entities.push((entity_type.to_string(), entity_id.to_string()));
                }
            }
        }

        // Extract from "deleted"
        if let Some(deleted) = invalidations.get("deleted").and_then(|v| v.as_array()) {
            for item in deleted {
                if let (Some(entity_type), Some(entity_id)) = (
                    item.get("type").and_then(|v| v.as_str()),
                    item.get("id").and_then(|v| v.as_str()),
                ) {
                    entities.push((entity_type.to_string(), entity_id.to_string()));
                }
            }
        }
    }

    entities
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validator_creation() {
        let validator = CoherencyValidator::new();
        assert_eq!(validator.cached_queries().len(), 0);
    }

    #[test]
    fn test_record_cache_put() {
        let mut validator = CoherencyValidator::new();

        validator
            .record_cache_put("query:user:1", vec![("User".to_string(), "1".to_string())])
            .unwrap();

        assert!(validator.cached_queries().contains("query:user:1"));
        assert!(validator
            .entity_queries("User", "1")
            .contains("query:user:1"));
    }

    #[test]
    fn test_record_invalidation() {
        let mut validator = CoherencyValidator::new();

        validator
            .record_cache_put("query:user:1", vec![("User".to_string(), "1".to_string())])
            .unwrap();

        assert!(validator.cached_queries().contains("query:user:1"));

        validator.record_invalidation("query:user:1").unwrap();

        assert!(!validator.cached_queries().contains("query:user:1"));
        assert!(!validator
            .entity_queries("User", "1")
            .contains("query:user:1"));
    }

    #[test]
    fn test_validate_cascade_invalidation_correct() {
        let mut validator = CoherencyValidator::new();

        validator
            .record_cache_put("query:user:1", vec![("User".to_string(), "1".to_string())])
            .unwrap();

        let cascade = serde_json::json!({
            "invalidations": {
                "updated": [{"type": "User", "id": "1"}],
                "deleted": []
            }
        });

        let invalidated = vec!["query:user:1".to_string()];
        let result = validator.validate_cascade_invalidation(&cascade, &invalidated);

        assert_eq!(result, CoherencyValidationResult::Valid);
    }

    #[test]
    fn test_validate_cascade_invalidation_missing() {
        let mut validator = CoherencyValidator::new();

        validator
            .record_cache_put("query:user:1", vec![("User".to_string(), "1".to_string())])
            .unwrap();

        let cascade = serde_json::json!({
            "invalidations": {
                "updated": [{"type": "User", "id": "1"}],
                "deleted": []
            }
        });

        let invalidated = vec![]; // Missing invalidation!
        let result = validator.validate_cascade_invalidation(&cascade, &invalidated);

        assert_ne!(result, CoherencyValidationResult::Valid);
    }

    #[test]
    fn test_validate_consistency() {
        let mut validator = CoherencyValidator::new();

        validator
            .record_cache_put("query:user:1", vec![("User".to_string(), "1".to_string())])
            .unwrap();

        let result = validator.validate_consistency();
        assert_eq!(result, CoherencyValidationResult::Valid);
    }

    #[test]
    fn test_wildcard_invalidation() {
        let mut validator = CoherencyValidator::new();

        validator
            .record_cache_put(
                "query:users:all",
                vec![("User".to_string(), "*".to_string())],
            )
            .unwrap();

        validator
            .record_cache_put("query:user:1", vec![("User".to_string(), "1".to_string())])
            .unwrap();

        let _cascade = serde_json::json!({
            "invalidations": {
                "updated": [{"type": "User", "id": "2"}],
                "deleted": []
            }
        });

        let affected = validator.find_affected_queries(&[("User".to_string(), "2".to_string())]);

        // Should only include wildcard, not specific user:1
        assert!(affected.contains("query:users:all"));
        assert!(!affected.contains("query:user:1"));
    }

    #[test]
    fn test_multiple_entities_per_query() {
        let mut validator = CoherencyValidator::new();

        validator
            .record_cache_put(
                "query:user:1:posts",
                vec![
                    ("User".to_string(), "1".to_string()),
                    ("Post".to_string(), "100".to_string()),
                ],
            )
            .unwrap();

        let entities = validator.query_entities("query:user:1:posts");
        assert_eq!(entities.len(), 2);

        let user_queries = validator.entity_queries("User", "1");
        assert!(user_queries.contains("query:user:1:posts"));

        let post_queries = validator.entity_queries("Post", "100");
        assert!(post_queries.contains("query:user:1:posts"));
    }
}
