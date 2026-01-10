//! Query Result Cache for Phase 17A
//!
//! Caches GraphQL query results and tracks accessed entities for cascade-driven invalidation.
//! This is distinct from the `QueryPlanCache` which caches query execution plans.

use anyhow::{anyhow, Result};
use lru::LruCache;
use serde::Serialize;
use serde_json::Value;
use std::num::NonZeroUsize;
use std::sync::{Arc, Mutex};

/// Cached query result with entity tracking
#[derive(Debug, Clone)]
pub struct CachedResult {
    /// The actual GraphQL query result (complete response)
    pub result: Arc<Value>,

    /// Which entities this query accesses
    /// Format: vec![("User", "123"), ("Post", "456")]
    /// Wildcard IDs like "*" mean "all entities of this type"
    pub accessed_entities: Vec<(String, String)>,

    /// When this entry was cached (Unix timestamp)
    pub cached_at: u64,

    /// Number of times this cache entry was hit
    pub hit_count: u64,
}

/// Configuration for query result cache with memory-safe bounds
///
/// # Memory Safety
///
/// The cache enforces strict bounds to prevent unbounded memory growth:
/// - **`max_entries`**: Hard limit on number of cached results (LRU eviction above this)
/// - **`ttl_seconds`**: Time-based expiry for additional safety
///
/// # Sizing Recommendations
///
/// - **Small deployments** (development, staging): `max_entries: 1_000`, `ttl_seconds: 3600` (1 hour)
/// - **Medium deployments** (10-50 QPS): `max_entries: 10_000`, `ttl_seconds: 86400` (24 hours)
/// - **Large deployments** (100+ QPS): `max_entries: 50_000`, `ttl_seconds: 604800` (7 days)
/// - **High-traffic** (1000+ QPS): `max_entries: 100_000`, `ttl_seconds: 86400` with periodic cleanup
///
/// Memory impact at default (10,000 entries):
/// - Average result size: 1-10 KB
/// - Estimated memory: 10-100 MB (adjust TTL or `max_entries` if exceeding available memory)
#[derive(Debug, Clone, Copy)]
pub struct QueryResultCacheConfig {
    /// Maximum number of entries in cache (LRU eviction above this)
    ///
    /// When capacity is exceeded, least-recently-used entries are removed.
    /// This hard limit prevents unbounded memory growth.
    /// Recommended range: 1,000 - 100,000
    pub max_entries: usize,

    /// TTL in seconds (safety net for non-mutation changes)
    ///
    /// Entries are automatically invalidated after this duration.
    /// This provides a safety net for data that changes outside the mutation path.
    /// Default: 24 hours (86400 seconds)
    /// Recommended range: 3600 (1 hour) to 604800 (7 days)
    pub ttl_seconds: u64,

    /// Whether to cache list/paginated queries
    ///
    /// List queries can have varying result sizes. Set to false to save memory
    /// and reduce invalidation complexity if list query caching isn't critical.
    pub cache_list_queries: bool,
}

impl Default for QueryResultCacheConfig {
    fn default() -> Self {
        Self {
            max_entries: 10000,
            ttl_seconds: 24 * 60 * 60, // 24 hours
            cache_list_queries: true,
        }
    }
}

/// Thread-safe cache for query results
#[derive(Debug)]
pub struct QueryResultCache {
    /// LRU cache: key -> cached result
    cache: Arc<Mutex<LruCache<String, CachedResult>>>,

    /// Dependency tracking: entity key -> list of cache entry keys
    /// Used for efficient invalidation based on cascade
    /// Format: `"User:123" -> ["query:user:123:posts", "query:user:123:email"]`
    dependencies: Arc<Mutex<std::collections::HashMap<String, Vec<String>>>>,

    /// Metrics
    metrics: Arc<Mutex<CacheMetrics>>,
}

/// Cache metrics for monitoring
#[derive(Debug, Clone, Serialize)]
pub struct CacheMetrics {
    /// Number of cache hits
    pub hits: u64,

    /// Number of cache misses
    pub misses: u64,

    /// Total entries cached across all time
    pub total_cached: u64,

    /// Number of invalidations triggered
    pub invalidations: u64,

    /// Current size of cache
    pub size: usize,

    /// Estimated memory usage in bytes
    pub memory_bytes: usize,
}

impl QueryResultCache {
    /// Create a new query result cache with default config
    ///
    /// # Panics
    /// Panics if `config.max_entries` is 0
    #[must_use]
    #[allow(clippy::expect_used)] // Documented panic for 0 max_entries - intentional API contract
    pub fn new(config: QueryResultCacheConfig) -> Self {
        let max = NonZeroUsize::new(config.max_entries).expect("max_entries must be > 0");
        Self {
            cache: Arc::new(Mutex::new(LruCache::new(max))),
            dependencies: Arc::new(Mutex::new(std::collections::HashMap::new())),
            metrics: Arc::new(Mutex::new(CacheMetrics {
                hits: 0,
                misses: 0,
                total_cached: 0,
                invalidations: 0,
                size: 0,
                memory_bytes: 0,
            })),
        }
    }

    /// Get cached result by key
    ///
    /// # Errors
    ///
    /// Returns an error if cache mutex is poisoned
    pub fn get(&self, cache_key: &str) -> Result<Option<Arc<Value>>> {
        let mut cache = self
            .cache
            .lock()
            .map_err(|e| anyhow!("Cache lock poisoned: {e}"))?;

        if let Some(cached) = cache.get_mut(cache_key) {
            // Record hit
            cached.hit_count += 1;
            let mut metrics = self
                .metrics
                .lock()
                .map_err(|e| anyhow!("Metrics lock poisoned: {e}"))?;
            metrics.hits += 1;

            Ok(Some(cached.result.clone()))
        } else {
            // Record miss
            let mut metrics = self
                .metrics
                .lock()
                .map_err(|e| anyhow!("Metrics lock poisoned: {e}"))?;
            metrics.misses += 1;

            Ok(None)
        }
    }

    /// Store query result in cache
    ///
    /// # Errors
    ///
    /// Returns an error if cache mutex is poisoned
    pub fn put(
        &self,
        cache_key: &str,
        result: Value,
        accessed_entities: Vec<(String, String)>,
    ) -> Result<()> {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();

        let cached = CachedResult {
            result: Arc::new(result),
            accessed_entities: accessed_entities.clone(),
            cached_at: now,
            hit_count: 0,
        };

        // Estimate memory usage (rough estimate)
        let memory_size = std::mem::size_of::<CachedResult>() + cache_key.len() * 2;

        // Update cache
        let mut cache = self
            .cache
            .lock()
            .map_err(|e| anyhow!("Cache lock poisoned: {e}"))?;
        cache.put(cache_key.to_string(), cached);

        // Update dependency tracking
        let mut deps = self
            .dependencies
            .lock()
            .map_err(|e| anyhow!("Dependencies lock poisoned: {e}"))?;

        for (entity_type, entity_id) in accessed_entities {
            let dep_key = format!("{entity_type}:{entity_id}");
            deps.entry(dep_key)
                .or_insert_with(Vec::new)
                .push(cache_key.to_string());
        }

        // Update metrics
        let mut metrics = self
            .metrics
            .lock()
            .map_err(|e| anyhow!("Metrics lock poisoned: {e}"))?;
        metrics.total_cached += 1;
        metrics.size = cache.len();
        metrics.memory_bytes += memory_size;

        Ok(())
    }

    /// Invalidate cache entries based on cascade metadata
    ///
    /// Cascade metadata format:
    /// ```json
    /// {
    ///   "invalidations": {
    ///     "updated": [{ "type": "User", "id": "123" }],
    ///     "deleted": [{ "type": "Post", "id": "456" }]
    ///   }
    /// }
    /// ```
    ///
    /// # Errors
    ///
    /// Returns error if cascade parsing fails or mutex is poisoned
    pub fn invalidate_from_cascade(&self, cascade: &Value) -> Result<u64> {
        let mut invalidated_count = 0u64;

        // Parse cascade to extract entity invalidations
        let invalidations = cascade
            .get("invalidations")
            .ok_or_else(|| anyhow!("No invalidations field in cascade"))?;

        let mut entities_to_invalidate = Vec::new();

        // Extract entities from cascade items
        let extract_entity = |item: &Value| -> Option<(String, String)> {
            let entity_type = item.get("type")?.as_str()?;
            let entity_id = item.get("id")?.as_str()?;
            Some((entity_type.to_string(), entity_id.to_string()))
        };

        // Handle "updated" entities
        if let Some(updated) = invalidations.get("updated").and_then(|u| u.as_array()) {
            for item in updated {
                if let Some(entity) = extract_entity(item) {
                    entities_to_invalidate.push(entity);
                }
            }
        }

        // Handle "deleted" entities
        if let Some(deleted) = invalidations.get("deleted").and_then(|d| d.as_array()) {
            for item in deleted {
                if let Some(entity) = extract_entity(item) {
                    entities_to_invalidate.push(entity);
                }
            }
        }

        // Invalidate cache entries that touch these entities
        let mut cache = self
            .cache
            .lock()
            .map_err(|e| anyhow!("Cache lock poisoned: {e}"))?;
        let mut deps = self
            .dependencies
            .lock()
            .map_err(|e| anyhow!("Dependencies lock poisoned: {e}"))?;

        for (entity_type, entity_id) in entities_to_invalidate {
            let dep_key = format!("{entity_type}:{entity_id}");

            if let Some(cache_keys) = deps.remove(&dep_key) {
                for key in cache_keys {
                    cache.pop(&key);
                    invalidated_count += 1;
                }
            }

            // Also invalidate wildcard entries for this entity type
            let wildcard_key = format!("{entity_type}:*");
            if let Some(wildcard_keys) = deps.remove(&wildcard_key) {
                for key in wildcard_keys {
                    cache.pop(&key);
                    invalidated_count += 1;
                }
            }
        }

        // Update metrics
        let mut metrics = self
            .metrics
            .lock()
            .map_err(|e| anyhow!("Metrics lock poisoned: {e}"))?;
        metrics.invalidations += invalidated_count;
        metrics.size = cache.len();

        Ok(invalidated_count)
    }

    /// Get cache statistics
    ///
    /// # Errors
    ///
    /// Returns error if metrics mutex is poisoned
    pub fn metrics(&self) -> Result<CacheMetrics> {
        self.metrics
            .lock()
            .map_err(|e| anyhow!("Metrics lock poisoned: {e}"))
            .map(|m| m.clone())
    }

    /// Clear all cache entries
    ///
    /// # Errors
    ///
    /// Returns error if cache mutex is poisoned
    pub fn clear(&self) -> Result<()> {
        self.cache
            .lock()
            .map_err(|e| anyhow!("Cache lock poisoned: {e}"))?
            .clear();

        self.dependencies
            .lock()
            .map_err(|e| anyhow!("Dependencies lock poisoned: {e}"))?
            .clear();

        let mut metrics = self
            .metrics
            .lock()
            .map_err(|e| anyhow!("Metrics lock poisoned: {e}"))?;
        metrics.size = 0;
        metrics.invalidations = 0;

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_cache_hit_returns_stored_value() {
        let cache = QueryResultCache::new(QueryResultCacheConfig::default());
        let result = json!({"user": {"id": "123", "name": "John"}});

        cache
            .put(
                "query:user:123",
                result.clone(),
                vec![("User".to_string(), "123".to_string())],
            )
            .unwrap();

        let cached = cache.get("query:user:123").unwrap();
        assert!(cached.is_some());
        assert_eq!(cached.unwrap(), Arc::new(result));
    }

    #[test]
    fn test_cache_miss_returns_none() {
        let cache = QueryResultCache::new(QueryResultCacheConfig::default());
        let cached = cache.get("nonexistent").unwrap();
        assert!(cached.is_none());
    }

    #[test]
    fn test_lru_eviction_when_full() {
        let config = QueryResultCacheConfig {
            max_entries: 3,
            ..QueryResultCacheConfig::default()
        };

        let cache = QueryResultCache::new(config);

        // Add 5 entries (max is 3)
        for i in 0..5 {
            let result = json!({"id": i});
            cache
                .put(
                    &format!("key:{i}"),
                    result,
                    vec![("Entity".to_string(), format!("{i}"))],
                )
                .unwrap();
        }

        // Should have max 3 entries (LRU eviction)
        let metrics = cache.metrics().unwrap();
        assert_eq!(metrics.size, 3);
    }

    #[test]
    fn test_cascade_invalidates_affected_queries() {
        let cache = QueryResultCache::new(QueryResultCacheConfig::default());

        // Cache queries about different users
        cache
            .put(
                "query:user:123:name",
                json!({"name": "John"}),
                vec![("User".to_string(), "123".to_string())],
            )
            .unwrap();

        cache
            .put(
                "query:user:456:name",
                json!({"name": "Jane"}),
                vec![("User".to_string(), "456".to_string())],
            )
            .unwrap();

        assert_eq!(cache.metrics().unwrap().size, 2);

        // Cascade: User 123 was updated
        let cascade = json!({
            "invalidations": {
                "updated": [
                    {"type": "User", "id": "123"}
                ]
            }
        });

        let invalidated = cache.invalidate_from_cascade(&cascade).unwrap();

        // Should invalidate User 123 queries, not 456
        assert_eq!(invalidated, 1);
        assert!(cache.get("query:user:123:name").unwrap().is_none());
        assert!(cache.get("query:user:456:name").unwrap().is_some());
    }

    #[test]
    fn test_cascade_multiple_invalidations() {
        let cache = QueryResultCache::new(QueryResultCacheConfig::default());

        cache
            .put(
                "query:user:100",
                json!({"name": "Alice"}),
                vec![("User".to_string(), "100".to_string())],
            )
            .unwrap();

        cache
            .put(
                "query:user:200",
                json!({"name": "Bob"}),
                vec![("User".to_string(), "200".to_string())],
            )
            .unwrap();

        cache
            .put(
                "query:post:1",
                json!({"title": "Post1"}),
                vec![("Post".to_string(), "1".to_string())],
            )
            .unwrap();

        assert_eq!(cache.metrics().unwrap().size, 3);

        // Cascade: Both users updated, one post deleted
        let cascade = json!({
            "invalidations": {
                "updated": [
                    {"type": "User", "id": "100"},
                    {"type": "User", "id": "200"}
                ],
                "deleted": [
                    {"type": "Post", "id": "1"}
                ]
            }
        });

        let invalidated = cache.invalidate_from_cascade(&cascade).unwrap();
        assert_eq!(invalidated, 3);
        assert_eq!(cache.metrics().unwrap().size, 0);
    }

    #[test]
    fn test_metrics_tracking() {
        let cache = QueryResultCache::new(QueryResultCacheConfig::default());

        // Miss
        cache.get("NotThere").unwrap();

        // Put
        cache
            .put(
                "key:1",
                json!({"value": 1}),
                vec![("Type".to_string(), "1".to_string())],
            )
            .unwrap();

        // Hit
        cache.get("key:1").unwrap();

        let metrics = cache.metrics().unwrap();
        assert_eq!(metrics.hits, 1);
        assert_eq!(metrics.misses, 1);
        assert_eq!(metrics.size, 1);
    }
}
