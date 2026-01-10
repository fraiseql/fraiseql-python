//! Storage trait and types for APQ backends
//!
//! This module defines the abstract storage interface that all APQ backends must implement,
//! allowing for pluggable storage backends (memory, `PostgreSQL`, etc.).

use async_trait::async_trait;
use serde_json::json;

/// Storage backend for persisted queries
///
/// Implementations of this trait provide different storage strategies:
/// - Memory: In-process LRU cache (single instance, fast)
/// - `PostgreSQL`: Distributed storage (multi-instance, persistent)
#[async_trait]
pub trait ApqStorage: Send + Sync {
    /// Get query by hash
    ///
    /// # Arguments
    ///
    /// * `hash` - The SHA-256 hash of the query (hexadecimal)
    ///
    /// # Returns
    ///
    /// * `Ok(Some(query))` if query found
    /// * `Ok(None)` if query not found
    /// * `Err(e)` if storage access fails
    async fn get(&self, hash: &str) -> Result<Option<String>, ApqError>;

    /// Store query with hash
    ///
    /// # Arguments
    ///
    /// * `hash` - The SHA-256 hash of the query
    /// * `query` - The full GraphQL query string
    ///
    /// # Returns
    ///
    /// * `Ok(())` on success
    /// * `Err(e)` if storage fails
    async fn set(&self, hash: String, query: String) -> Result<(), ApqError>;

    /// Check if query exists
    ///
    /// # Arguments
    ///
    /// * `hash` - The SHA-256 hash to check
    ///
    /// # Returns
    ///
    /// * `Ok(true)` if query exists
    /// * `Ok(false)` if not found
    /// * `Err(e)` if check fails
    async fn exists(&self, hash: &str) -> Result<bool, ApqError>;

    /// Remove query from storage
    ///
    /// # Arguments
    ///
    /// * `hash` - The hash to remove
    ///
    /// # Returns
    ///
    /// * `Ok(())` on success
    /// * `Err(e)` if removal fails
    async fn remove(&self, hash: &str) -> Result<(), ApqError>;

    /// Get storage statistics
    ///
    /// # Returns
    ///
    /// Statistics about the storage backend
    async fn stats(&self) -> Result<ApqStats, ApqError>;

    /// Clear all stored queries
    ///
    /// # Returns
    ///
    /// * `Ok(())` on success
    /// * `Err(e)` if clear fails
    async fn clear(&self) -> Result<(), ApqError>;
}

/// Statistics about APQ storage
#[derive(Debug, Clone)]
pub struct ApqStats {
    /// Total number of stored queries
    pub total_queries: usize,

    /// Storage backend name
    pub backend: String,

    /// Additional backend-specific stats (as JSON)
    pub extra: serde_json::Value,
}

impl ApqStats {
    /// Create new statistics
    #[must_use]
    pub fn new(total_queries: usize, backend: String) -> Self {
        Self {
            total_queries,
            backend,
            extra: json!({}),
        }
    }

    /// Create new statistics with extra data
    #[must_use]
    pub const fn with_extra(
        total_queries: usize,
        backend: String,
        extra: serde_json::Value,
    ) -> Self {
        Self {
            total_queries,
            backend,
            extra,
        }
    }
}

/// APQ errors
#[derive(Debug, thiserror::Error)]
pub enum ApqError {
    /// Query not found in storage
    #[error("Query not found")]
    NotFound,

    /// Query size exceeded limit (100KB)
    #[error("Query size exceeds maximum limit (100KB)")]
    QueryTooLarge,

    /// Storage backend error
    #[error("Storage error: {0}")]
    StorageError(String),

    /// Serialization/deserialization error
    #[error("Serialization error: {0}")]
    SerializationError(String),

    /// Database error (for `PostgreSQL` backend)
    #[error("Database error: {0}")]
    DatabaseError(String),

    /// Configuration error
    #[error("Configuration error: {0}")]
    ConfigError(String),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_apq_stats_creation() {
        let stats = ApqStats::new(100, "memory".to_string());
        assert_eq!(stats.total_queries, 100);
        assert_eq!(stats.backend, "memory");
        assert_eq!(stats.extra, json!({}));
    }

    #[test]
    fn test_apq_stats_with_extra() {
        let extra = json!({
            "hits": 500,
            "misses": 50,
            "hit_rate": 0.909
        });

        let stats = ApqStats::with_extra(100, "postgresql".to_string(), extra.clone());
        assert_eq!(stats.total_queries, 100);
        assert_eq!(stats.backend, "postgresql");
        assert_eq!(stats.extra, extra);
    }

    #[test]
    fn test_apq_error_display() {
        let err = ApqError::QueryTooLarge;
        assert_eq!(err.to_string(), "Query size exceeds maximum limit (100KB)");

        let err = ApqError::StorageError("connection failed".to_string());
        assert!(err.to_string().contains("connection failed"));
    }
}
