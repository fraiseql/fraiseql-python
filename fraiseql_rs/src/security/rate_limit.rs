//! Token bucket rate limiting with Redis backend.

use std::{
    collections::HashMap,
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use tokio::sync::Mutex;

use super::errors::{Result, SecurityError};

/// Rate limit strategy
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum RateLimitStrategy {
    FixedWindow,
    SlidingWindow,
    TokenBucket,
}

/// Rate limit configuration
#[derive(Debug, Clone)]
pub struct RateLimit {
    pub requests:    usize,
    pub window_secs: u64,
    pub burst:       Option<usize>,
    pub strategy:    RateLimitStrategy,
}

impl Default for RateLimit {
    fn default() -> Self {
        Self {
            requests:    100,
            window_secs: 60,
            burst:       Some(20),
            strategy:    RateLimitStrategy::TokenBucket,
        }
    }
}

/// Rate limiter with token bucket algorithm
pub struct RateLimiter {
    limits: HashMap<String, RateLimit>,
    store:  Arc<Mutex<RateLimitStore>>,
}

impl Default for RateLimiter {
    fn default() -> Self {
        Self::new()
    }
}

impl RateLimiter {
    pub fn new() -> Self {
        Self {
            limits: HashMap::new(),
            store:  Arc::new(Mutex::new(RateLimitStore::new())),
        }
    }

    /// Add rate limit rule for path pattern
    pub fn add_rule(&mut self, path_pattern: String, limit: RateLimit) {
        self.limits.insert(path_pattern, limit);
    }

    /// Check if request is allowed (returns Ok or rate limit error)
    pub async fn check(&self, key: &str, path: &str) -> Result<()> {
        // Find matching limit
        let limit = self
            .limits
            .get(path)
            .or_else(|| self.limits.get("*")) // Default limit
            .ok_or_else(|| {
                SecurityError::SecurityConfigError("No rate limit configured".to_string())
            })?;

        let mut store = self.store.lock().await;

        match limit.strategy {
            RateLimitStrategy::TokenBucket => self.check_token_bucket(&mut store, key, limit).await,
            RateLimitStrategy::FixedWindow => self.check_fixed_window(&mut store, key, limit).await,
            RateLimitStrategy::SlidingWindow => {
                self.check_sliding_window(&mut store, key, limit).await
            },
        }
    }

    /// Token bucket algorithm (recommended)
    async fn check_token_bucket(
        &self,
        store: &mut RateLimitStore,
        key: &str,
        limit: &RateLimit,
    ) -> Result<()> {
        let now = current_timestamp();
        let bucket = store.get_bucket(key, limit.requests, limit.window_secs);

        // Refill tokens based on time elapsed
        let elapsed = now - bucket.last_refill;
        let refill_rate = limit.requests as f64 / limit.window_secs as f64;
        let tokens_to_add = (elapsed as f64 * refill_rate) as usize;

        bucket.tokens = (bucket.tokens + tokens_to_add).min(limit.requests);
        bucket.last_refill = now;

        // Check if token available
        if bucket.tokens > 0 {
            bucket.tokens -= 1;
            Ok(())
        } else {
            let retry_after = (1.0 / refill_rate) as u64;
            Err(SecurityError::RateLimitExceeded {
                retry_after,
                limit: limit.requests,
                window_secs: limit.window_secs,
            })
        }
    }

    /// Fixed window algorithm
    async fn check_fixed_window(
        &self,
        store: &mut RateLimitStore,
        key: &str,
        limit: &RateLimit,
    ) -> Result<()> {
        let now = current_timestamp();
        let window = store.get_window(key);

        // Reset if window expired
        if now - window.start >= limit.window_secs {
            window.start = now;
            window.count = 0;
        }

        // Check limit
        if window.count < limit.requests {
            window.count += 1;
            Ok(())
        } else {
            let retry_after = limit.window_secs - (now - window.start);
            Err(SecurityError::RateLimitExceeded {
                retry_after,
                limit: limit.requests,
                window_secs: limit.window_secs,
            })
        }
    }

    /// Sliding window algorithm
    async fn check_sliding_window(
        &self,
        store: &mut RateLimitStore,
        key: &str,
        limit: &RateLimit,
    ) -> Result<()> {
        let now = current_timestamp();
        let requests = store.get_requests(key);

        // Remove old requests outside window
        requests.retain(|&ts| now - ts < limit.window_secs);

        // Check limit
        if requests.len() < limit.requests {
            requests.push(now);
            Ok(())
        } else {
            let oldest = requests[0];
            let retry_after = limit.window_secs - (now - oldest);
            Err(SecurityError::RateLimitExceeded {
                retry_after,
                limit: limit.requests,
                window_secs: limit.window_secs,
            })
        }
    }

    /// Get statistics for monitoring
    pub async fn stats(&self) -> RateLimitStats {
        let store = self.store.lock().await;
        RateLimitStats {
            rules_count:    self.limits.len(),
            buckets_count:  store.buckets.len(),
            windows_count:  store.windows.len(),
            requests_count: store.requests.len(),
        }
    }
}

/// In-memory rate limit store (production would use Redis)
struct RateLimitStore {
    buckets:  HashMap<String, TokenBucket>,
    windows:  HashMap<String, FixedWindow>,
    requests: HashMap<String, Vec<u64>>,
}

impl RateLimitStore {
    fn new() -> Self {
        Self {
            buckets:  HashMap::new(),
            windows:  HashMap::new(),
            requests: HashMap::new(),
        }
    }

    fn get_bucket(&mut self, key: &str, capacity: usize, _window: u64) -> &mut TokenBucket {
        self.buckets.entry(key.to_string()).or_insert_with(|| TokenBucket {
            tokens:      capacity,
            last_refill: current_timestamp(),
        })
    }

    fn get_window(&mut self, key: &str) -> &mut FixedWindow {
        self.windows.entry(key.to_string()).or_insert_with(|| FixedWindow {
            start: current_timestamp(),
            count: 0,
        })
    }

    fn get_requests(&mut self, key: &str) -> &mut Vec<u64> {
        self.requests.entry(key.to_string()).or_default()
    }
}

#[derive(Debug)]
pub struct RateLimitStats {
    pub rules_count:    usize,
    pub buckets_count:  usize,
    pub windows_count:  usize,
    pub requests_count: usize,
}

#[derive(Debug)]
struct TokenBucket {
    tokens:      usize,
    last_refill: u64,
}

#[derive(Debug)]
struct FixedWindow {
    start: u64,
    count: usize,
}

/// Get current Unix timestamp in seconds.
/// Returns 0 on system time error (extremely rare edge case).
#[inline]
fn current_timestamp() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or_else(|e| {
            // System clock is before Unix epoch - should never happen in production
            // Log and return 0 to avoid panic
            #[cfg(debug_assertions)]
            eprintln!("ERROR: System clock before Unix epoch: {}", e);
            0
        })
}
