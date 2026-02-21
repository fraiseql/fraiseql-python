//! User context caching with LRU eviction.

use std::{
    num::NonZeroUsize,
    sync::{Arc, Mutex},
    time::{Duration, SystemTime},
};

use lru::LruCache;
use sha2::{Digest, Sha256};

use crate::pipeline::unified::UserContext;

/// User context cache with LRU eviction and TTL validation.
pub struct UserContextCache {
    cache: Arc<Mutex<LruCache<String, (UserContext, SystemTime)>>>,
    ttl:   Duration,
}

impl UserContextCache {
    /// Create a new user context cache.
    pub fn new(capacity: usize, ttl_seconds: u64) -> Self {
        Self {
            cache: Arc::new(Mutex::new(LruCache::new(NonZeroUsize::new(capacity).unwrap()))),
            ttl:   Duration::from_secs(ttl_seconds),
        }
    }

    /// Get user context from cache.
    pub fn get(&self, token: &str) -> Option<UserContext> {
        let key = Self::hash_token(token);

        let mut cache = self.cache.lock().unwrap();

        if let Some((context, cached_at)) = cache.get(&key) {
            // Check TTL
            let elapsed = SystemTime::now()
                .duration_since(*cached_at)
                .unwrap_or(Duration::from_secs(u64::MAX));

            if elapsed < self.ttl {
                // Also check token expiration
                let now =
                    SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).unwrap().as_secs();

                if context.exp > now {
                    return Some(context.clone());
                }
            }

            // Expired - remove from cache
            cache.pop(&key);
        }

        None
    }

    /// Store user context in cache.
    pub fn put(&self, token: &str, context: UserContext) {
        let key = Self::hash_token(token);

        let mut cache = self.cache.lock().unwrap();
        cache.put(key, (context, SystemTime::now()));
    }

    /// Clear all cached contexts.
    pub fn clear(&self) {
        let mut cache = self.cache.lock().unwrap();
        cache.clear();
    }

    /// Hash token for cache key (for security).
    fn hash_token(token: &str) -> String {
        let mut hasher = Sha256::new();
        hasher.update(token.as_bytes());
        format!("{:x}", hasher.finalize())
    }
}

impl Default for UserContextCache {
    fn default() -> Self {
        // Default: 1000 entries, 5 minute TTL
        Self::new(1000, 300)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cache_put_and_get() {
        let cache = UserContextCache::new(10, 300);

        let context = UserContext {
            user_id:     Some("user123".to_string()),
            permissions: vec!["read".to_string()],
            roles:       vec!["admin".to_string()],
            exp:         SystemTime::now()
                .duration_since(SystemTime::UNIX_EPOCH)
                .unwrap()
                .as_secs()
                + 3600,
        };

        cache.put("token123", context.clone());

        let cached = cache.get("token123");
        assert!(cached.is_some());
        assert_eq!(cached.unwrap().user_id, Some("user123".to_string()));
    }

    #[test]
    fn test_cache_expiration() {
        let cache = UserContextCache::new(10, 1); // 1 second TTL

        let context = UserContext {
            user_id:     Some("user123".to_string()),
            permissions: vec![],
            roles:       vec![],
            exp:         SystemTime::now()
                .duration_since(SystemTime::UNIX_EPOCH)
                .unwrap()
                .as_secs()
                + 3600,
        };

        cache.put("token123", context);

        // Should exist immediately
        assert!(cache.get("token123").is_some());

        // Wait for expiration
        std::thread::sleep(Duration::from_secs(2));

        // Should be expired
        assert!(cache.get("token123").is_none());
    }
}
