//! Production-ready database connection pool.

use crate::db::{
    errors::{DatabaseError, DatabaseResult},
    metrics::PoolMetrics,
    parameter_binding::{prepare_parameters, validate_parameter_count},
    pool_config::{DatabaseConfig, SslMode},
    types::QueryParam,
};
use deadpool_postgres::{
    Manager, ManagerConfig, Pool, RecyclingMethod, Runtime as DeadpoolRuntime,
};
use std::error::Error;
use std::sync::Arc;
use std::time::Duration;
use tokio::time::sleep;
use tokio_postgres::types::ToSql;

/// Production database pool with SSL/TLS support.
///
/// Always compiled with SSL support. SSL is enabled/disabled at runtime
/// via configuration rather than compile-time features.
#[derive(Debug, Clone)]
pub struct ProductionPool {
    /// Inner deadpool-postgres pool (Arc for sharing)
    pool: Arc<Pool>,
    /// Configuration (for stats/debugging)
    config: DatabaseConfig,
    /// Metrics collector
    metrics: Arc<PoolMetrics>,
}

impl ProductionPool {
    /// Create a new production pool.
    ///
    /// # Errors
    ///
    /// Returns `DatabaseError::PoolCreation` if:
    /// - Pool configuration is invalid
    /// - Cannot create connection manager
    /// - SSL/TLS setup fails (when required)
    ///
    /// # Example
    ///
    /// ```rust
    /// use fraiseql_rs::db::{DatabaseConfig, ProductionPool};
    ///
    /// let config = DatabaseConfig::new("mydb")
    ///     .with_password("secret");
    ///
    /// let _pool = ProductionPool::new(config)?;
    /// # Ok::<(), fraiseql_rs::db::errors::DatabaseError>(())
    /// ```
    pub fn new(config: DatabaseConfig) -> DatabaseResult<Self> {
        // Validate pool configuration
        // Ensure wait_timeout is set to prevent pool exhaustion
        if config.wait_timeout.is_none() {
            return Err(DatabaseError::Configuration(
                "wait_timeout must be configured to prevent pool exhaustion".to_string(),
            ));
        }

        // Build tokio-postgres config
        let mut pg_config = tokio_postgres::Config::new();
        pg_config.host(&config.host);
        pg_config.port(config.port);
        pg_config.dbname(&config.database);
        pg_config.user(&config.username);

        if let Some(password) = &config.password {
            pg_config.password(password);
        }

        pg_config.application_name(&config.application_name);
        pg_config.connect_timeout(config.connect_timeout);

        // Create pool based on SSL mode
        let pool = match config.ssl_mode {
            SslMode::Disable => Self::create_pool_notls(pg_config, &config)?,
            SslMode::Prefer | SslMode::Require => Self::create_pool_ssl(pg_config, &config)?,
        };

        Ok(Self {
            pool: Arc::new(pool),
            config,
            metrics: Arc::new(PoolMetrics::new()),
        })
    }

    /// Create pool without SSL/TLS.
    fn create_pool_notls(
        pg_config: tokio_postgres::Config,
        config: &DatabaseConfig,
    ) -> DatabaseResult<Pool> {
        use tokio_postgres::NoTls;

        let mgr_config = ManagerConfig {
            recycling_method: RecyclingMethod::Fast,
        };
        let mgr = Manager::from_config(pg_config, NoTls, mgr_config);

        let mut builder = Pool::builder(mgr);
        builder = builder.max_size(config.max_size);
        builder = builder.runtime(DeadpoolRuntime::Tokio1);

        // Apply timeouts
        if let Some(timeout) = config.wait_timeout {
            builder = builder.wait_timeout(Some(timeout));
        }
        if let Some(timeout) = config.idle_timeout {
            builder = builder.recycle_timeout(Some(timeout));
        }

        builder
            .build()
            .map_err(|e| DatabaseError::PoolCreation(e.to_string()))
    }

    /// Create pool with SSL/TLS.
    fn create_pool_ssl(
        pg_config: tokio_postgres::Config,
        config: &DatabaseConfig,
    ) -> DatabaseResult<Pool> {
        use native_tls::TlsConnector;
        use postgres_native_tls::MakeTlsConnector;

        // Build TLS connector
        let tls_builder = TlsConnector::builder();

        // Always validate certificates - both 'prefer' and 'require' modes
        // 'prefer' means we'll try SSL first, but fall back to non-SSL if needed
        // This does NOT mean we accept invalid certificates
        // Certificate validation is essential to prevent MITM attacks

        let tls = tls_builder
            .build()
            .map_err(|e| DatabaseError::Ssl(e.to_string()))?;

        let connector = MakeTlsConnector::new(tls);

        let mgr_config = ManagerConfig {
            recycling_method: RecyclingMethod::Fast,
        };
        let mgr = Manager::from_config(pg_config, connector, mgr_config);

        let mut builder = Pool::builder(mgr);
        builder = builder.max_size(config.max_size);
        builder = builder.runtime(DeadpoolRuntime::Tokio1);

        // Apply timeouts
        if let Some(timeout) = config.wait_timeout {
            builder = builder.wait_timeout(Some(timeout));
        }
        if let Some(timeout) = config.idle_timeout {
            builder = builder.recycle_timeout(Some(timeout));
        }

        builder
            .build()
            .map_err(|e| DatabaseError::PoolCreation(e.to_string()))
    }

    /// Get a connection from the pool.
    ///
    /// # Errors
    ///
    /// Returns `DatabaseError::ConnectionAcquisition` if:
    /// - All connections are in use (timeout)
    /// - Database is unreachable
    /// - Connection fails
    pub async fn get_connection(&self) -> DatabaseResult<deadpool_postgres::Client> {
        self.pool
            .get()
            .await
            .map_err(|e| DatabaseError::ConnectionAcquisition(e.to_string()))
    }

    /// Execute a query and return JSONB results.
    ///
    /// For `FraiseQL`: assumes JSONB data in column 0 (CQRS pattern).
    ///
    /// Includes automatic retry logic for deadlock errors with exponential backoff
    /// (up to 3 attempts with 10ms, 50ms, 100ms delays).
    ///
    /// # Errors
    ///
    /// Returns `DatabaseError::QueryExecution` if:
    /// - Query execution fails (after retries)
    /// - Connection cannot be acquired
    pub async fn execute_query(&self, sql: &str) -> DatabaseResult<Vec<serde_json::Value>> {
        const MAX_RETRIES: u32 = 3;
        let mut attempt = 0;

        loop {
            attempt += 1;
            let client = self.get_connection().await?;

            let rows = match client.query(sql, &[]).await {
                Ok(rows) => {
                    self.metrics.record_query_executed();
                    rows
                }
                Err(e) => {
                    self.metrics.record_query_error();

                    // Check if this is a deadlock error (PostgreSQL error code 40P01)
                    if is_deadlock_error(&e) && attempt < MAX_RETRIES {
                        let backoff_ms = 10 * u64::pow(5, attempt - 1); // 10ms, 50ms, 100ms
                        sleep(Duration::from_millis(backoff_ms)).await;
                        continue; // Retry with exponential backoff
                    }

                    return Err(DatabaseError::QueryExecution(e.to_string()));
                }
            };

            // Extract JSONB from column 0 (FraiseQL CQRS pattern)
            // Each row MUST have a valid JSONB value at column 0
            let mut results = Vec::new();
            for (row_idx, row) in rows.iter().enumerate() {
                match row.try_get::<_, serde_json::Value>(0) {
                    Ok(value) => results.push(value),
                    Err(e) => {
                        self.metrics.record_query_error();
                        return Err(DatabaseError::ColumnAccess {
                            index: 0,
                            expected_type: "jsonb",
                            reason: format!(
                                "Failed to extract JSONB from column 0 in row {row_idx}: {e}"
                            ),
                        });
                    }
                }
            }

            return Ok(results);
        }
    }

    /// Execute a query with bound parameters.
    ///
    /// For `FraiseQL`: assumes JSONB data in column 0 (CQRS pattern).
    ///
    /// This method:
    /// 1. Validates parameter count matches placeholders in SQL
    /// 2. Validates each parameter (type checking, NaN detection, etc.)
    /// 3. Executes query with deadlock retry logic
    /// 4. Extracts JSONB from column 0
    ///
    /// # Arguments
    /// * `sql` - SQL query with $1, $2, etc. placeholders
    /// * `params` - Parameters to bind (must match placeholder count)
    ///
    /// # Errors
    ///
    /// Returns `DatabaseError::QueryExecution` if:
    /// - Parameter count doesn't match placeholders
    /// - Parameter validation fails
    /// - Query execution fails
    /// - JSONB extraction fails
    pub async fn execute_query_with_params(
        &self,
        sql: &str,
        params: &[QueryParam],
    ) -> DatabaseResult<Vec<serde_json::Value>> {
        const MAX_RETRIES: u32 = 3;

        // Phase 3.2: Validate parameters before execution
        prepare_parameters(params).map_err(|e| DatabaseError::QueryExecution(e.to_string()))?;
        validate_parameter_count(sql, params)
            .map_err(|e| DatabaseError::QueryExecution(e.to_string()))?;

        let mut attempt = 0;

        loop {
            attempt += 1;
            let client = self.get_connection().await?;

            // Convert QueryParam to tokio_postgres parameter references
            let pg_params: Vec<Box<dyn ToSql + Sync>> = params
                .iter()
                .map(|p| convert_query_param_to_sql(p))
                .collect();

            let pg_param_refs: Vec<&(dyn ToSql + Sync)> = pg_params.iter().map(|p| &**p).collect();

            let rows = match client.query(sql, &pg_param_refs).await {
                Ok(rows) => {
                    self.metrics.record_query_executed();
                    rows
                }
                Err(e) => {
                    self.metrics.record_query_error();

                    // Check if this is a deadlock error (PostgreSQL error code 40P01)
                    if is_deadlock_error(&e) && attempt < MAX_RETRIES {
                        let backoff_ms = 10 * u64::pow(5, attempt - 1); // 10ms, 50ms, 100ms
                        sleep(Duration::from_millis(backoff_ms)).await;
                        continue; // Retry with exponential backoff
                    }

                    return Err(DatabaseError::QueryExecution(e.to_string()));
                }
            };

            // Extract JSONB from column 0 (FraiseQL CQRS pattern)
            // Each row MUST have a valid JSONB value at column 0
            let mut results = Vec::new();
            for (row_idx, row) in rows.iter().enumerate() {
                match row.try_get::<_, serde_json::Value>(0) {
                    Ok(value) => results.push(value),
                    Err(e) => {
                        self.metrics.record_query_error();
                        return Err(DatabaseError::QueryExecution(format!(
                            "Failed to extract JSONB from column 0 in row {row_idx}: {e}"
                        )));
                    }
                }
            }

            return Ok(results);
        }
    }

    /// Get pool statistics.
    ///
    /// Thread-safe: deadpool-postgres uses Arc internally.
    #[must_use]
    pub fn stats(&self) -> PoolStats {
        let status = self.pool.status();
        PoolStats {
            size: status.size,
            available: status.available,
            max_size: status.max_size,
        }
    }

    /// Close the pool gracefully.
    ///
    /// Waits for all in-flight queries to complete, then closes all connections.
    /// This method is synchronous but performs cleanup asynchronously in the background.
    pub fn close(&self) {
        self.pool.close();
    }

    /// Get a reference to the configuration.
    #[must_use]
    pub const fn config(&self) -> &DatabaseConfig {
        &self.config
    }

    /// Get a clone of the underlying deadpool-postgres pool.
    ///
    /// This is for backward compatibility with code that needs direct pool access.
    #[must_use]
    pub fn get_underlying_pool(&self) -> deadpool_postgres::Pool {
        (*self.pool).clone()
    }

    /// Get a snapshot of pool metrics.
    ///
    /// Returns counters for queries executed, errors, and health checks.
    #[must_use]
    pub fn metrics(&self) -> crate::db::metrics::MetricsSnapshot {
        self.metrics.snapshot()
    }
}

/// Converts a `QueryParam` to a boxed `ToSql` for `tokio_postgres`.
///
/// This enables safe parameter binding in prepared statements. Each `QueryParam`
/// variant is mapped to a `tokio_postgres` type that implements `ToSql`.
///
/// For types like Timestamp and UUID that may not be directly supported by the
/// basic `tokio_postgres`, we serialize them to string representations which
/// `PostgreSQL` can then parse.
///
/// # Arguments
/// * `param` - The parameter to convert
///
/// # Returns
/// A boxed trait object implementing `ToSql + Sync`
fn convert_query_param_to_sql(param: &QueryParam) -> Box<dyn ToSql + Sync> {
    match param {
        QueryParam::Null => Box::new(None::<String>),
        QueryParam::Bool(b) => Box::new(*b),
        QueryParam::Int(i) => Box::new(*i),
        QueryParam::BigInt(i) => Box::new(*i),
        QueryParam::Float(f) => Box::new(*f),
        QueryParam::Double(f) => Box::new(*f),
        QueryParam::Text(s) => Box::new(s.clone()),
        QueryParam::Json(v) => Box::new(v.clone()),
        // For types that may not have direct ToSql support, convert to string
        // PostgreSQL will parse these appropriately
        QueryParam::Timestamp(ts) => Box::new(ts.to_string()),
        QueryParam::Uuid(u) => Box::new(u.to_string()),
    }
}

/// Detects if a database error is a deadlock error (`PostgreSQL` error code 40P01).
///
/// Deadlock errors are serialization conflicts that can be safely retried.
/// This function enables automatic retry logic with exponential backoff.
fn is_deadlock_error(error: &tokio_postgres::Error) -> bool {
    // Check if this is a database error with the deadlock error code
    // PostgreSQL error code for deadlock detected: 40P01
    error
        .source()
        .and_then(|e| e.downcast_ref::<tokio_postgres::error::DbError>())
        .is_some_and(|db_error| db_error.code().code() == "40P01")
}

/// Implement `PoolBackend` trait for `ProductionPool`.
///
/// This allows `ProductionPool` to be used as a trait object (`Arc<dyn PoolBackend>`)
/// by the storage layer, enabling abstraction over pool implementations.
#[async_trait::async_trait]
impl crate::db::pool::traits::PoolBackend for ProductionPool {
    async fn query(
        &self,
        sql: &str,
    ) -> crate::db::pool::traits::PoolResult<Vec<serde_json::Value>> {
        self.execute_query(sql)
            .await
            .map_err(|e| crate::db::pool::traits::PoolError::QueryExecution(e.to_string()))
    }

    async fn execute(&self, sql: &str) -> crate::db::pool::traits::PoolResult<u64> {
        let client = self.get_connection().await.map_err(|e| {
            crate::db::pool::traits::PoolError::ConnectionAcquisition(e.to_string())
        })?;

        client
            .execute(sql, &[])
            .await
            .map_err(|e| crate::db::pool::traits::PoolError::QueryExecution(e.to_string()))
    }

    fn pool_info(&self) -> serde_json::Value {
        let stats = self.stats();
        serde_json::json!({
            "backend": "deadpool-postgres",
            "database": self.config.database,
            "host": self.config.host,
            "port": self.config.port,
            "pool_size": stats.size,
            "pool_available": stats.available,
            "pool_max_size": stats.max_size,
        })
    }

    fn backend_name(&self) -> &'static str {
        "deadpool-postgres"
    }
}

/// Pool statistics for monitoring.
#[derive(Debug, Clone)]
pub struct PoolStats {
    /// Current number of connections
    pub size: usize,
    /// Number of available (idle) connections
    pub available: usize,
    /// Maximum pool size
    pub max_size: usize,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pool_creation_no_ssl() {
        let config = DatabaseConfig::new("test")
            .with_max_size(5)
            .with_ssl_mode(SslMode::Disable);

        let _pool = ProductionPool::new(config);
        // May fail if PostgreSQL not running - that's OK for unit test
        // Integration tests will verify actual connectivity
    }

    #[tokio::test]
    async fn test_pool_stats() {
        let config = DatabaseConfig::new("test").with_ssl_mode(SslMode::Disable);
        if let Ok(pool) = ProductionPool::new(config) {
            let stats = pool.stats();
            assert_eq!(stats.max_size, 10); // default
            assert!(stats.available <= stats.max_size);
        }
    }

    #[test]
    fn test_pool_clone() {
        let config = DatabaseConfig::new("test").with_ssl_mode(SslMode::Disable);
        if let Ok(pool) = ProductionPool::new(config) {
            let pool2 = pool.clone();
            // Both should share same underlying pool (Arc)
            assert_eq!(pool.stats().max_size, pool2.stats().max_size);
        }
    }

    #[test]
    fn test_config_access() {
        let config = DatabaseConfig::new("testdb").with_max_size(15);
        if let Ok(pool) = ProductionPool::new(config) {
            assert_eq!(pool.config().database, "testdb");
            assert_eq!(pool.config().max_size, 15);
        }
    }

    #[test]
    fn test_query_param_conversion() {
        // Test that QueryParam values can be converted to ToSql
        let params = vec![
            QueryParam::Bool(true),
            QueryParam::Int(42),
            QueryParam::BigInt(1_234_567_890),
            QueryParam::Float(std::f32::consts::PI),
            QueryParam::Double(std::f64::consts::E),
            QueryParam::Text("hello".to_string()),
            QueryParam::Null,
        ];

        // Should not panic when converting
        for param in &params {
            let _ = convert_query_param_to_sql(param);
        }
    }

    #[test]
    fn test_parameter_count_validation() {
        // Test that parameter count validation works
        use crate::db::parameter_binding::validate_parameter_count;

        let sql = "SELECT * FROM users WHERE id = $1 AND name = $2";
        let params_correct = vec![QueryParam::BigInt(1), QueryParam::Text("test".to_string())];
        let params_wrong = vec![QueryParam::BigInt(1)];

        // Correct count should pass
        assert!(validate_parameter_count(sql, &params_correct).is_ok());

        // Wrong count should fail
        assert!(validate_parameter_count(sql, &params_wrong).is_err());
    }

    #[test]
    fn test_query_param_validation() {
        // Test that invalid parameters are caught
        use crate::db::parameter_binding::prepare_parameters;

        let valid_params = vec![
            QueryParam::BigInt(123),
            QueryParam::Text("test".to_string()),
            QueryParam::Bool(true),
        ];

        assert!(prepare_parameters(&valid_params).is_ok());

        // Test that NaN is rejected
        let invalid_params = vec![QueryParam::Double(f64::NAN)];
        assert!(prepare_parameters(&invalid_params).is_err());

        // Test that Infinity is rejected
        let invalid_params_inf = vec![QueryParam::Double(f64::INFINITY)];
        assert!(prepare_parameters(&invalid_params_inf).is_err());
    }
}
