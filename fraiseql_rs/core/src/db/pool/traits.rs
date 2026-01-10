//! Pool backend trait abstraction.
//!
//! This trait defines the interface that all connection pools must implement,
//! allowing the storage layer to work with any pool implementation.
//!
//! # Design
//! - `PoolBackend` is a trait object that abstracts pool implementations
//! - Enables easy swapping between deadpool, sqlx, or other pool types
//! - Storage layer depends on trait, not concrete pool types
//!
//! # Example
//! ```rust,ignore
//! let pool: Arc<dyn PoolBackend> = Arc::new(ProductionPool::new(config)?);
//! let results = pool.query("SELECT * FROM users").await?;
//! ```

use async_trait::async_trait;

/// Result type for pool operations
pub type PoolResult<T> = Result<T, PoolError>;

/// Errors from pool operations
#[derive(Debug, Clone)]
pub enum PoolError {
    /// Failed to acquire connection from pool
    ConnectionAcquisition(String),
    /// Failed to execute query
    QueryExecution(String),
    /// Pool configuration is invalid
    Configuration(String),
}

impl std::fmt::Display for PoolError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ConnectionAcquisition(msg) => write!(f, "Failed to acquire connection: {msg}"),
            Self::QueryExecution(msg) => write!(f, "Query execution failed: {msg}"),
            Self::Configuration(msg) => write!(f, "Pool configuration error: {msg}"),
        }
    }
}

impl std::error::Error for PoolError {}

/// Connection pool abstraction trait.
///
/// All pool implementations must implement this trait to be usable with the storage layer.
/// This enables swapping between different pool types (deadpool, sqlx, etc.) without
/// changing the storage layer code.
#[async_trait]
pub trait PoolBackend: Send + Sync {
    /// Execute a query and return JSONB results.
    ///
    /// For `FraiseQL`'s CQRS pattern, assumes JSONB data is in column 0 of the result set.
    /// Each row MUST contain a valid JSONB value at column 0.
    ///
    /// # Arguments
    /// * `sql` - SQL query string (no parameters for now)
    ///
    /// # Returns
    /// * `Ok(Vec<serde_json::Value>)` - JSONB values extracted from column 0
    /// * `Err(PoolError)` - If query execution fails
    ///
    /// # Example
    /// ```rust,ignore
    /// let results = pool.query("SELECT data FROM tv_user LIMIT 10").await?;
    /// // Each element is a JSONB document from the projection table
    /// ```
    async fn query(&self, sql: &str) -> PoolResult<Vec<serde_json::Value>>;

    /// Execute a statement (INSERT/UPDATE/DELETE) and return rows affected.
    ///
    /// # Arguments
    /// * `sql` - SQL statement string
    ///
    /// # Returns
    /// * `Ok(u64)` - Number of rows affected
    /// * `Err(PoolError)` - If execution fails
    async fn execute(&self, sql: &str) -> PoolResult<u64>;

    /// Get the underlying pool for advanced operations.
    ///
    /// Returns a generic JSON value representing pool metadata.
    /// Specific pool types can provide implementation-specific details.
    fn pool_info(&self) -> serde_json::Value;

    /// Get the backend name for identification (e.g., "deadpool", "sqlx").
    fn backend_name(&self) -> &str;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pool_error_display() {
        let err = PoolError::ConnectionAcquisition("timeout".to_string());
        assert!(err.to_string().contains("Failed to acquire connection"));

        let err = PoolError::QueryExecution("syntax error".to_string());
        assert!(err.to_string().contains("Query execution failed"));

        let err = PoolError::Configuration("invalid config".to_string());
        assert!(err.to_string().contains("Pool configuration error"));
    }
}
