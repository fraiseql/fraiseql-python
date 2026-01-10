//! Health check utilities for database pools.

use crate::db::{
    errors::{DatabaseError, DatabaseResult},
    pool_production::ProductionPool,
};
use std::time::{Duration, Instant};

/// Health check result.
#[derive(Debug, Clone)]
pub struct HealthCheckResult {
    /// Whether the check passed
    pub healthy: bool,
    /// Check duration
    pub duration: Duration,
    /// Optional error message
    pub error: Option<String>,
    /// Pool statistics at check time
    pub pool_stats: PoolHealthStats,
}

/// Pool health statistics.
#[derive(Debug, Clone)]
pub struct PoolHealthStats {
    /// Number of active connections
    pub active_connections: usize,
    /// Number of idle connections
    pub idle_connections: usize,
    /// Pool utilization (0.0 - 1.0)
    pub utilization: f64,
}

impl ProductionPool {
    /// Perform a health check on the pool.
    ///
    /// Attempts to:
    /// 1. Acquire a connection
    /// 2. Execute a simple query (SELECT 1) with timeout
    /// 3. Return the connection to the pool
    ///
    /// # Errors
    ///
    /// Returns `DatabaseError::HealthCheck` if the health check fails.
    pub async fn health_check(&self) -> DatabaseResult<HealthCheckResult> {
        let start = Instant::now();

        // Get pool stats before check
        let stats = self.stats();
        let pool_stats = PoolHealthStats {
            active_connections: stats.size - stats.available,
            idle_connections: stats.available,
            utilization: if stats.max_size > 0 {
                #[allow(clippy::cast_precision_loss)]
                {
                    (stats.size - stats.available) as f64 / stats.max_size as f64
                }
            } else {
                0.0
            },
        };

        // Use connection timeout from config (default: 30s)
        let timeout = self.config().connect_timeout;

        // Try to acquire connection and execute simple query with timeout
        let result = tokio::time::timeout(timeout, async {
            let client = self.get_connection().await?;
            client
                .simple_query("SELECT 1")
                .await
                .map_err(|e| DatabaseError::HealthCheck(format!("Query failed: {e}")))
        })
        .await;

        let duration = start.elapsed();

        match result {
            Ok(Ok(_)) => Ok(HealthCheckResult {
                healthy: true,
                duration,
                error: None,
                pool_stats,
            }),
            Ok(Err(e)) => Ok(HealthCheckResult {
                healthy: false,
                duration,
                error: Some(e.to_string()),
                pool_stats,
            }),
            Err(_) => Ok(HealthCheckResult {
                healthy: false,
                duration,
                error: Some(format!(
                    "Health check timed out after {}s",
                    timeout.as_secs()
                )),
                pool_stats,
            }),
        }
    }

    /// Check if pool is healthy (simple boolean check).
    ///
    /// # Errors
    ///
    /// Returns an error if health check fails.
    pub async fn is_healthy(&self) -> DatabaseResult<bool> {
        self.health_check().await.map(|result| result.healthy)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::db::{pool_config::SslMode, DatabaseConfig};

    #[tokio::test]
    #[ignore = "Requires PostgreSQL database connection"]
    async fn test_health_check() {
        let config = DatabaseConfig::new("postgres").with_ssl_mode(SslMode::Disable);
        let pool = ProductionPool::new(config).unwrap();

        let result = pool.health_check().await.unwrap();
        assert!(result.healthy);
        assert!(result.duration.as_millis() < 1000);
        assert!(result.error.is_none());
    }

    #[tokio::test]
    #[ignore = "Requires PostgreSQL database connection"]
    async fn test_is_healthy() {
        let config = DatabaseConfig::new("postgres").with_ssl_mode(SslMode::Disable);
        let pool = ProductionPool::new(config).unwrap();

        let healthy = pool.is_healthy().await.unwrap();
        assert!(healthy);
    }

    #[tokio::test]
    #[ignore = "Requires PostgreSQL database connection"]
    async fn test_health_stats() {
        let config = DatabaseConfig::new("postgres").with_ssl_mode(SslMode::Disable);
        let pool = ProductionPool::new(config).unwrap();

        let result = pool.health_check().await.unwrap();
        assert!(result.pool_stats.utilization >= 0.0);
        assert!(result.pool_stats.utilization <= 1.0);
    }
}
