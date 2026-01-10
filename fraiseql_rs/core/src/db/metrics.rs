//! Database pool metrics for monitoring and observability.
//!
//! Provides thread-safe counters for tracking:
//! - Query executions
//! - Query errors
//! - Connection health checks
//!
//! Metrics can be exported for Prometheus or other monitoring systems.

use std::sync::atomic::{AtomicU64, Ordering};

/// Thread-safe metrics collector for database pool operations.
///
/// Uses atomic counters for lock-free performance tracking.
#[derive(Debug, Default)]
pub struct PoolMetrics {
    /// Total number of queries executed successfully
    queries_executed: AtomicU64,
    /// Total number of query errors
    query_errors: AtomicU64,
    /// Total number of health checks performed
    health_checks: AtomicU64,
    /// Total number of failed health checks
    health_check_failures: AtomicU64,
}

impl PoolMetrics {
    /// Create a new metrics collector.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            queries_executed: AtomicU64::new(0),
            query_errors: AtomicU64::new(0),
            health_checks: AtomicU64::new(0),
            health_check_failures: AtomicU64::new(0),
        }
    }

    /// Record a successful query execution.
    pub fn record_query_executed(&self) {
        self.queries_executed.fetch_add(1, Ordering::Relaxed);
    }

    /// Record a query error.
    pub fn record_query_error(&self) {
        self.query_errors.fetch_add(1, Ordering::Relaxed);
    }

    /// Record a health check.
    pub fn record_health_check(&self) {
        self.health_checks.fetch_add(1, Ordering::Relaxed);
    }

    /// Record a failed health check.
    pub fn record_health_check_failure(&self) {
        self.health_check_failures.fetch_add(1, Ordering::Relaxed);
    }

    /// Get a snapshot of all metrics.
    #[must_use]
    pub fn snapshot(&self) -> MetricsSnapshot {
        MetricsSnapshot {
            queries_executed: self.queries_executed.load(Ordering::Relaxed),
            query_errors: self.query_errors.load(Ordering::Relaxed),
            health_checks: self.health_checks.load(Ordering::Relaxed),
            health_check_failures: self.health_check_failures.load(Ordering::Relaxed),
        }
    }

    /// Reset all metrics to zero.
    ///
    /// Useful for testing or periodic resets.
    pub fn reset(&self) {
        self.queries_executed.store(0, Ordering::Relaxed);
        self.query_errors.store(0, Ordering::Relaxed);
        self.health_checks.store(0, Ordering::Relaxed);
        self.health_check_failures.store(0, Ordering::Relaxed);
    }
}

/// Immutable snapshot of metrics at a specific point in time.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MetricsSnapshot {
    /// Total queries executed
    pub queries_executed: u64,
    /// Total query errors
    pub query_errors: u64,
    /// Total health checks
    pub health_checks: u64,
    /// Total failed health checks
    pub health_check_failures: u64,
}

impl MetricsSnapshot {
    /// Calculate query success rate (0.0 to 1.0).
    ///
    /// Returns 1.0 if no queries have been executed.
    #[must_use]
    pub fn query_success_rate(&self) -> f64 {
        let total = self.queries_executed + self.query_errors;
        if total == 0 {
            1.0
        } else {
            #[allow(clippy::cast_precision_loss)]
            {
                self.queries_executed as f64 / total as f64
            }
        }
    }

    /// Calculate health check success rate (0.0 to 1.0).
    ///
    /// Returns 1.0 if no health checks have been performed.
    #[must_use]
    pub fn health_check_success_rate(&self) -> f64 {
        if self.health_checks == 0 {
            1.0
        } else {
            let successful = self.health_checks - self.health_check_failures;
            #[allow(clippy::cast_precision_loss)]
            {
                successful as f64 / self.health_checks as f64
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_metrics_recording() {
        let metrics = PoolMetrics::new();

        metrics.record_query_executed();
        metrics.record_query_executed();
        metrics.record_query_error();

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.queries_executed, 2);
        assert_eq!(snapshot.query_errors, 1);
    }

    #[test]
    fn test_health_check_metrics() {
        let metrics = PoolMetrics::new();

        metrics.record_health_check();
        metrics.record_health_check();
        metrics.record_health_check_failure();

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.health_checks, 2);
        assert_eq!(snapshot.health_check_failures, 1);
    }

    #[test]
    // Test assertions for metrics with acceptable tolerance
    #[allow(clippy::float_cmp)]
    fn test_success_rates() {
        let metrics = PoolMetrics::new();

        metrics.record_query_executed();
        metrics.record_query_executed();
        metrics.record_query_executed();
        metrics.record_query_error();

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.query_success_rate(), 0.75);
    }

    #[test]
    // Test assertions for metrics with acceptable tolerance
    #[allow(clippy::float_cmp)]
    fn test_success_rate_no_queries() {
        let metrics = PoolMetrics::new();
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.query_success_rate(), 1.0);
    }

    #[test]
    fn test_metrics_reset() {
        let metrics = PoolMetrics::new();

        metrics.record_query_executed();
        metrics.record_query_error();

        metrics.reset();

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.queries_executed, 0);
        assert_eq!(snapshot.query_errors, 0);
    }

    #[test]
    fn test_concurrent_updates() {
        use std::sync::Arc;
        use std::thread;

        let metrics = Arc::new(PoolMetrics::new());
        let mut handles = vec![];

        // Spawn 10 threads, each recording 100 queries
        for _ in 0..10 {
            let metrics_clone = Arc::clone(&metrics);
            let handle = thread::spawn(move || {
                for _ in 0..100 {
                    metrics_clone.record_query_executed();
                }
            });
            handles.push(handle);
        }

        for handle in handles {
            handle.join().unwrap();
        }

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.queries_executed, 1000);
    }
}
