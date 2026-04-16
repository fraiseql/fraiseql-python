//! Type definitions and configurations for database operations.

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
        PoolConfig {
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
    Null,
    Bool(bool),
    Int(i32),
    BigInt(i64),
    Float(f32),
    Double(f64),
    Text(String),
    Json(serde_json::Value),
    Timestamp(chrono::NaiveDateTime),
    Uuid(uuid::Uuid),
}

// Phase 2.0: ToSql implementation placeholder
// Full type support will be added in Phase 2.5
// For now, QueryParam is used for API compatibility

// Implement From traits for QueryParam to enable easy construction
impl From<i32> for QueryParam {
    fn from(value: i32) -> Self {
        QueryParam::Int(value)
    }
}

impl From<i64> for QueryParam {
    fn from(value: i64) -> Self {
        QueryParam::BigInt(value)
    }
}

impl From<f32> for QueryParam {
    fn from(value: f32) -> Self {
        QueryParam::Float(value)
    }
}

impl From<f64> for QueryParam {
    fn from(value: f64) -> Self {
        QueryParam::Double(value)
    }
}

impl From<bool> for QueryParam {
    fn from(value: bool) -> Self {
        QueryParam::Bool(value)
    }
}

impl From<String> for QueryParam {
    fn from(value: String) -> Self {
        QueryParam::Text(value)
    }
}

impl From<&str> for QueryParam {
    fn from(value: &str) -> Self {
        QueryParam::Text(value.to_string())
    }
}

impl From<serde_json::Value> for QueryParam {
    fn from(value: serde_json::Value) -> Self {
        QueryParam::Json(value)
    }
}

impl From<chrono::NaiveDateTime> for QueryParam {
    fn from(value: chrono::NaiveDateTime) -> Self {
        QueryParam::Timestamp(value)
    }
}

impl From<uuid::Uuid> for QueryParam {
    fn from(value: uuid::Uuid) -> Self {
        QueryParam::Uuid(value)
    }
}

/// Result of a database query
#[derive(Debug)]
pub struct QueryResult {
    pub rows_affected: u64,
    pub columns: Vec<String>,
    pub rows: Vec<Vec<QueryParam>>,
}

/// Error types for database operations
#[derive(Debug, thiserror::Error)]
pub enum DatabaseError {
    #[error("Connection pool error: {0}")]
    Pool(String),
    #[error("Query execution error: {0}")]
    Query(String),
    #[error("Connection error: {0}")]
    Connection(String),
    #[error("Configuration error: {0}")]
    Config(String),
    #[error("Transaction error: {0}")]
    Transaction(String),
}

pub type DatabaseResult<T> = Result<T, DatabaseError>;

/// Connection state information
#[derive(Debug, Clone)]
pub struct ConnectionInfo {
    pub host: String,
    pub port: u16,
    pub database: String,
    pub user: String,
    pub connection_count: u32,
    pub idle_count: u32,
}
