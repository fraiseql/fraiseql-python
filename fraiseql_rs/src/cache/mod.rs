//! Query plan caching module.

pub mod signature;

use std::sync::{Arc, Mutex};

use anyhow::{Result, anyhow};
use lru::LruCache;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CachedQueryPlan {
    pub signature:    String,
    pub sql_template: String,
    pub parameters:   Vec<ParamInfo>,
    pub created_at:   u64, // Unix timestamp
    pub hit_count:    u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParamInfo {
    pub name:          String,
    pub position:      usize,
    pub expected_type: String, // "string", "int", "float", "bool", "json"
}

/// Thread-safe query plan cache.
pub struct QueryPlanCache {
    cache:    Arc<Mutex<LruCache<String, CachedQueryPlan>>>,
    max_size: usize,
    hits:     Arc<Mutex<u64>>,
    misses:   Arc<Mutex<u64>>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CacheStats {
    pub hits:     u64,
    pub misses:   u64,
    pub hit_rate: f64,
    pub size:     usize,
    pub max_size: usize,
}

impl QueryPlanCache {
    pub fn new(max_size: usize) -> Self {
        Self {
            cache: Arc::new(Mutex::new(LruCache::new(
                std::num::NonZeroUsize::new(max_size).unwrap(),
            ))),
            max_size,
            hits: Arc::new(Mutex::new(0)),
            misses: Arc::new(Mutex::new(0)),
        }
    }

    pub fn get(&self, signature: &str) -> Result<Option<CachedQueryPlan>> {
        let mut cache = self.cache.lock().map_err(|e| anyhow!("Cache lock error: {}", e))?;

        if let Some(plan) = cache.get_mut(signature) {
            plan.hit_count += 1;
            *self.hits.lock().unwrap() += 1;
            Ok(Some(plan.clone()))
        } else {
            *self.misses.lock().unwrap() += 1;
            Ok(None)
        }
    }

    pub fn put(&self, signature: String, plan: CachedQueryPlan) -> Result<()> {
        let mut cache = self.cache.lock().map_err(|e| anyhow!("Cache lock error: {}", e))?;
        cache.put(signature, plan);
        Ok(())
    }

    pub fn clear(&self) -> Result<()> {
        let mut cache = self.cache.lock().map_err(|e| anyhow!("Cache lock error: {}", e))?;
        cache.clear();

        // Reset counters
        *self.hits.lock().unwrap() = 0;
        *self.misses.lock().unwrap() = 0;

        Ok(())
    }

    pub fn stats(&self) -> Result<CacheStats> {
        let hits = *self.hits.lock().unwrap();
        let misses = *self.misses.lock().unwrap();
        let size = self.cache.lock().map_err(|e| anyhow!("Cache lock error: {}", e))?.len();

        Ok(CacheStats {
            hits,
            misses,
            hit_rate: if hits + misses > 0 {
                hits as f64 / (hits + misses) as f64
            } else {
                0.0
            },
            size,
            max_size: self.max_size,
        })
    }
}

impl Default for QueryPlanCache {
    fn default() -> Self {
        Self::new(5000) // 5000 cached plans by default
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cache_put_get() {
        let cache = QueryPlanCache::new(100);
        let plan = CachedQueryPlan {
            signature:    "test_query".to_string(),
            sql_template: "SELECT * FROM users".to_string(),
            parameters:   vec![],
            created_at:   0,
            hit_count:    0,
        };

        cache.put("test_query".to_string(), plan.clone()).unwrap();
        let retrieved = cache.get("test_query").unwrap().unwrap();

        assert_eq!(retrieved.signature, "test_query");
    }

    #[test]
    fn test_cache_hit_counting() {
        let cache = QueryPlanCache::new(100);
        let plan = CachedQueryPlan {
            signature:    "test".to_string(),
            sql_template: "SELECT *".to_string(),
            parameters:   vec![],
            created_at:   0,
            hit_count:    0,
        };

        cache.put("test".to_string(), plan).unwrap();

        // Access 5 times
        for _ in 0..5 {
            cache.get("test").unwrap();
        }

        let stats = cache.stats().unwrap();
        assert_eq!(stats.hits, 5);
    }

    #[test]
    fn test_cache_lru_eviction() {
        let cache = QueryPlanCache::new(3);

        for i in 0..5 {
            let plan = CachedQueryPlan {
                signature:    format!("query_{}", i),
                sql_template: "SELECT *".to_string(),
                parameters:   vec![],
                created_at:   0,
                hit_count:    0,
            };
            cache.put(format!("query_{}", i), plan).unwrap();
        }

        let stats = cache.stats().unwrap();
        assert_eq!(stats.size, 3); // Only 3 entries (LRU eviction)
    }
}
