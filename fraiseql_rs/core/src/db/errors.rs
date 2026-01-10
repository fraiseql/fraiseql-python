//! Error types for database operations with rich context.
//!
//! All errors include detailed context to facilitate debugging:
//! - What operation was attempted
//! - Why it failed (specific error code/message)
//! - Recovery hints where applicable
//!
//! # Error Classification
//!
//! - **Configuration errors** (400-level equivalent): Invalid setup, auth, missing credentials
//! - **Connectivity errors** (500-level equivalent): Network issues, pool exhaustion, timeouts
//! - **Query execution errors** (400-500 mixed): Syntax, deadlocks, constraint violations
//! - **Data access errors** (400-level): Type mismatches, missing columns, schema issues

use std::fmt;

/// Database operation errors with debugging context.
///
/// Each variant includes sufficient information for operators to diagnose issues
/// without needing to check application logs separately.
#[derive(Debug, Clone)]
pub enum DatabaseError {
    /// Runtime initialization failed
    ///
    /// Indicates failure to create the async runtime (tokio).
    /// Usually due to resource exhaustion or thread pool configuration.
    RuntimeInitialization(String),

    /// Pool creation failed
    ///
    /// Indicates failure to create the database connection pool.
    /// Common causes:
    /// - Invalid connection string or credentials
    /// - Database server unreachable
    /// - Insufficient resources
    PoolCreation(String),

    /// Connection acquisition failed
    ///
    /// Indicates timeout or failure when acquiring a connection from the pool.
    /// Common causes:
    /// - All connections in use (pool exhausted)
    /// - Wait timeout exceeded
    /// - Database server down or slow
    /// - Connection lifecycle issue (dropped connection)
    ConnectionAcquisition(String),

    /// Query execution failed
    ///
    /// Indicates query failed to execute on the database.
    /// Can be categorized by message content:
    /// - Deadlock errors (retriable with backoff)
    /// - Syntax errors (non-retriable)
    /// - Constraint violations (non-retriable)
    /// - Timeout errors (retriable or adjustment needed)
    QueryExecution(String),

    /// Health check failed
    ///
    /// Indicates database health check query failed.
    /// Usually means database server is unreachable or unresponsive.
    HealthCheck(String),

    /// Configuration error
    ///
    /// Indicates invalid configuration provided to database client.
    /// Common causes:
    /// - Missing required parameters (`wait_timeout`, `max_size`)
    /// - Invalid parameter values (negative pool size)
    /// - SSL mode misconfiguration
    Configuration(String),

    /// SSL/TLS error
    ///
    /// Indicates SSL/TLS connection establishment failed.
    /// Common causes:
    /// - Certificate validation failure
    /// - Protocol version mismatch
    /// - Missing or invalid CA certificates
    Ssl(String),

    /// Column access error (e.g., JSONB extraction failed)
    ///
    /// This error occurs when attempting to extract a column from a query result fails.
    /// This typically indicates:
    /// - Column type mismatch (expected JSONB, got different type)
    /// - Missing column in result set
    /// - Schema mismatch between code and database
    /// - Data corruption
    ///
    /// **Debugging hints:**
    /// 1. Check that the query returns the expected columns
    /// 2. Verify column types in database schema
    /// 3. Ensure no recent schema changes
    /// 4. Check for data type conversions in the query
    ColumnAccess {
        /// Zero-based column index
        index: usize,
        /// Expected data type (e.g., "json" or "jsonb")
        expected_type: &'static str,
        /// Detailed reason from database driver
        reason: String,
    },
}

impl fmt::Display for DatabaseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::RuntimeInitialization(e) => write!(f, "Runtime initialization failed: {e}"),
            Self::PoolCreation(e) => write!(f, "Pool creation failed: {e}"),
            Self::ConnectionAcquisition(e) => write!(f, "Connection acquisition failed: {e}"),
            Self::QueryExecution(e) => write!(f, "Query execution failed: {e}"),
            Self::HealthCheck(e) => write!(f, "Health check failed: {e}"),
            Self::Configuration(e) => write!(f, "Configuration error: {e}"),
            Self::Ssl(e) => write!(f, "SSL/TLS error: {e}"),
            Self::ColumnAccess {
                index,
                expected_type,
                reason,
            } => write!(
                f,
                "Column access error at index {index} (expected {expected_type}): {reason}"
            ),
        }
    }
}

impl std::error::Error for DatabaseError {}

/// Result type alias for database operations.
pub type DatabaseResult<T> = Result<T, DatabaseError>;
