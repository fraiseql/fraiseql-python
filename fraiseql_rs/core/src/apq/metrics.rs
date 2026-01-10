//! APQ metrics tracking
//!
//! Provides metrics for monitoring APQ performance including cache hit rates,
//! query storage, and error tracking.

use std::sync::atomic::{AtomicU64, Ordering};

/// APQ metrics tracker
///
/// Tracks performance metrics for APQ including:
/// - Cache hits (queries retrieved from cache)
/// - Cache misses (queries not found, client provides full query)
/// - Queries stored (new queries persisted)
/// - Errors (failed operations)
///
/// All operations are lock-free using atomic operations.
#[derive(Debug)]
pub struct ApqMetrics {
    /// Number of cache hits
    hits: AtomicU64,

    /// Number of cache misses
    misses: AtomicU64,

    /// Number of queries stored
    stored: AtomicU64,

    /// Number of errors
    errors: AtomicU64,
}

impl ApqMetrics {
    /// Record a cache hit
    pub fn record_hit(&self) {
        self.hits.fetch_add(1, Ordering::Relaxed);
    }

    /// Record a cache miss
    pub fn record_miss(&self) {
        self.misses.fetch_add(1, Ordering::Relaxed);
    }

    /// Record a query stored
    pub fn record_store(&self) {
        self.stored.fetch_add(1, Ordering::Relaxed);
    }

    /// Record an error
    pub fn record_error(&self) {
        self.errors.fetch_add(1, Ordering::Relaxed);
    }

    /// Get total hits
    #[must_use]
    pub fn get_hits(&self) -> u64 {
        self.hits.load(Ordering::Relaxed)
    }

    /// Get total misses
    #[must_use]
    pub fn get_misses(&self) -> u64 {
        self.misses.load(Ordering::Relaxed)
    }

    /// Get total stored
    #[must_use]
    pub fn get_stored(&self) -> u64 {
        self.stored.load(Ordering::Relaxed)
    }

    /// Get total errors
    #[must_use]
    pub fn get_errors(&self) -> u64 {
        self.errors.load(Ordering::Relaxed)
    }

    /// Get cache hit rate as percentage (0.0 to 1.0)
    #[must_use]
    pub fn hit_rate(&self) -> f64 {
        let hits = self.hits.load(Ordering::Relaxed);
        let misses = self.misses.load(Ordering::Relaxed);

        if hits + misses == 0 {
            0.0
        } else {
            // Small precision loss is acceptable for metrics percentages
            #[allow(clippy::cast_precision_loss)]
            {
                hits as f64 / (hits + misses) as f64
            }
        }
    }

    /// Get metrics as JSON value
    #[must_use]
    pub fn as_json(&self) -> serde_json::Value {
        serde_json::json!({
            "hits": self.get_hits(),
            "misses": self.get_misses(),
            "stored": self.get_stored(),
            "errors": self.get_errors(),
            "hit_rate": self.hit_rate(),
        })
    }

    /// Reset all metrics
    pub fn reset(&self) {
        self.hits.store(0, Ordering::Relaxed);
        self.misses.store(0, Ordering::Relaxed);
        self.stored.store(0, Ordering::Relaxed);
        self.errors.store(0, Ordering::Relaxed);
    }
}

impl Default for ApqMetrics {
    fn default() -> Self {
        Self {
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
            stored: AtomicU64::new(0),
            errors: AtomicU64::new(0),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_metrics_initialization() {
        let metrics = ApqMetrics::default();
        assert_eq!(metrics.get_hits(), 0);
        assert_eq!(metrics.get_misses(), 0);
        assert_eq!(metrics.get_stored(), 0);
        assert_eq!(metrics.get_errors(), 0);
    }

    #[test]
    fn test_record_hit() {
        let metrics = ApqMetrics::default();
        metrics.record_hit();
        assert_eq!(metrics.get_hits(), 1);
    }

    #[test]
    fn test_record_multiple_hits() {
        let metrics = ApqMetrics::default();
        for _ in 0..100 {
            metrics.record_hit();
        }
        assert_eq!(metrics.get_hits(), 100);
    }

    #[test]
    fn test_record_miss() {
        let metrics = ApqMetrics::default();
        metrics.record_miss();
        assert_eq!(metrics.get_misses(), 1);
    }

    #[test]
    fn test_record_store() {
        let metrics = ApqMetrics::default();
        metrics.record_store();
        assert_eq!(metrics.get_stored(), 1);
    }

    #[test]
    fn test_record_error() {
        let metrics = ApqMetrics::default();
        metrics.record_error();
        assert_eq!(metrics.get_errors(), 1);
    }

    #[test]
    // Test assertions for metrics with acceptable tolerance
    #[allow(clippy::float_cmp)]
    fn test_hit_rate_no_requests() {
        let metrics = ApqMetrics::default();
        assert_eq!(metrics.hit_rate(), 0.0);
    }

    #[test]
    // Test assertions for metrics with acceptable tolerance
    #[allow(clippy::float_cmp)]
    fn test_hit_rate_all_hits() {
        let metrics = ApqMetrics::default();
        for _ in 0..100 {
            metrics.record_hit();
        }
        assert_eq!(metrics.hit_rate(), 1.0);
    }

    #[test]
    // Test assertions for metrics with acceptable tolerance
    #[allow(clippy::float_cmp)]
    fn test_hit_rate_all_misses() {
        let metrics = ApqMetrics::default();
        for _ in 0..100 {
            metrics.record_miss();
        }
        assert_eq!(metrics.hit_rate(), 0.0);
    }

    #[test]
    fn test_hit_rate_mixed() {
        let metrics = ApqMetrics::default();
        for _ in 0..90 {
            metrics.record_hit();
        }
        for _ in 0..10 {
            metrics.record_miss();
        }
        assert!((metrics.hit_rate() - 0.9).abs() < 0.0001);
    }

    #[test]
    fn test_as_json() {
        let metrics = ApqMetrics::default();
        metrics.record_hit();
        metrics.record_hit();
        metrics.record_miss();
        metrics.record_store();

        let json = metrics.as_json();
        assert_eq!(json["hits"], 2);
        assert_eq!(json["misses"], 1);
        assert_eq!(json["stored"], 1);
        assert_eq!(json["errors"], 0);
    }

    #[test]
    fn test_reset() {
        let metrics = ApqMetrics::default();
        metrics.record_hit();
        metrics.record_hit();
        metrics.record_miss();

        assert_eq!(metrics.get_hits(), 2);
        assert_eq!(metrics.get_misses(), 1);

        metrics.reset();

        assert_eq!(metrics.get_hits(), 0);
        assert_eq!(metrics.get_misses(), 0);
        assert_eq!(metrics.get_stored(), 0);
        assert_eq!(metrics.get_errors(), 0);
    }
}
