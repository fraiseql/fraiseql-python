//! Type definitions and configurations for database operations.
//!
//! # Phase 3.2: Query Execution Foundation
//!
//! This module defines the types used for query execution and parameter binding.
//! Note: FraiseQL uses JSONB data extraction from column 0, not row-by-row transformation.

use std::time::Duration;

/// Configuration for database connection pool
#[derive(Debug, Clone)]
pub struct PoolConfig {
    /// Maximum number of connections in the pool
    pub max_size: u32,
    /// Minimum number of idle connections to maintain
    pub min_idle: u32,
    /// Timeout for acquiring a connection from the pool
    pub connection_timeout: Duration,
    /// Timeout for idle connections
    pub idle_timeout: Duration,
    /// Maximum lifetime of a connection
    pub max_lifetime: Option<Duration>,
    /// How often to check for idle connections
    pub reap_frequency: Duration,
}

impl Default for PoolConfig {
    fn default() -> Self {
        Self {
            max_size: 10,
            min_idle: 1,
            connection_timeout: Duration::from_secs(30),
            idle_timeout: Duration::from_secs(300), // 5 minutes
            max_lifetime: Some(Duration::from_secs(3600)), // 1 hour
            reap_frequency: Duration::from_secs(60), // 1 minute
        }
    }
}

/// Query parameter types for prepared statements
#[derive(Debug, Clone)]
pub enum QueryParam {
    /// SQL NULL value
    Null,
    /// Boolean value
    Bool(bool),
    /// 32-bit integer
    Int(i32),
    /// 64-bit integer (BIGINT)
    BigInt(i64),
    /// 32-bit floating point
    Float(f32),
    /// 64-bit floating point (DOUBLE PRECISION)
    Double(f64),
    /// Text/string value (TEXT/VARCHAR)
    Text(String),
    /// JSON/JSONB value
    Json(serde_json::Value),
    /// Timestamp without timezone
    Timestamp(chrono::NaiveDateTime),
    /// UUID value
    Uuid(uuid::Uuid),
}

// Phase 2.0: ToSql implementation placeholder
// Full type support will be added in Phase 2.5
// For now, QueryParam is used for API compatibility

// Implement From traits for QueryParam to enable easy construction
impl From<i32> for QueryParam {
    fn from(value: i32) -> Self {
        Self::Int(value)
    }
}

impl From<i64> for QueryParam {
    fn from(value: i64) -> Self {
        Self::BigInt(value)
    }
}

impl From<f32> for QueryParam {
    fn from(value: f32) -> Self {
        Self::Float(value)
    }
}

impl From<f64> for QueryParam {
    fn from(value: f64) -> Self {
        Self::Double(value)
    }
}

impl From<bool> for QueryParam {
    fn from(value: bool) -> Self {
        Self::Bool(value)
    }
}

impl From<String> for QueryParam {
    fn from(value: String) -> Self {
        Self::Text(value)
    }
}

impl From<&str> for QueryParam {
    fn from(value: &str) -> Self {
        Self::Text(value.to_string())
    }
}

impl From<serde_json::Value> for QueryParam {
    fn from(value: serde_json::Value) -> Self {
        Self::Json(value)
    }
}

impl From<chrono::NaiveDateTime> for QueryParam {
    fn from(value: chrono::NaiveDateTime) -> Self {
        Self::Timestamp(value)
    }
}

impl From<uuid::Uuid> for QueryParam {
    fn from(value: uuid::Uuid) -> Self {
        Self::Uuid(value)
    }
}

/// Result of a SELECT query
///
/// This structure represents the results of a SELECT query with:
/// - Number of rows affected
/// - Column metadata
/// - Rows as `QueryParam` vectors (matches `PostgreSQL` column types)
///
/// # Note
///
/// `FraiseQL`'s CQRS pattern extracts JSONB directly from column 0 via the pool.
/// This type is used by the query executor for intermediate representation.
#[derive(Debug, Clone)]
pub struct QueryResult {
    /// Number of rows affected by the query
    pub rows_affected: u64,
    /// Column names in result set
    pub columns: Vec<String>,
    /// Query result rows (each row is a vector of `QueryParam` values)
    pub rows: Vec<Vec<QueryParam>>,
}

/// Error types for database operations
#[derive(Debug, thiserror::Error)]
pub enum DatabaseError {
    /// Connection pool errors (acquisition, timeout, etc.)
    #[error("Connection pool error: {0}")]
    Pool(String),
    /// Query execution errors (syntax, constraints, etc.)
    #[error("Query execution error: {0}")]
    Query(String),
    /// Database connection errors (network, authentication, etc.)
    #[error("Connection error: {0}")]
    Connection(String),
    /// Configuration errors (invalid URL, bad parameters, etc.)
    #[error("Configuration error: {0}")]
    Config(String),
    /// Transaction errors (commit, rollback, isolation, etc.)
    #[error("Transaction error: {0}")]
    Transaction(String),
}

/// Convenience type alias for database operation results
pub type DatabaseResult<T> = Result<T, DatabaseError>;

/// Connection state information
#[derive(Debug, Clone)]
pub struct ConnectionInfo {
    /// Database host
    pub host: String,
    /// Database port
    pub port: u16,
    /// Database name
    pub database: String,
    /// Database user
    pub user: String,
    /// Total number of connections in pool
    pub connection_count: u32,
    /// Number of idle connections
    pub idle_count: u32,
}
