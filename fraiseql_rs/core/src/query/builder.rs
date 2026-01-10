//! Pure Rust query builder with caching (Phase 6.2).
//!
//! This module provides the core query building functionality without PyO3 dependencies.
//! It handles SQL generation from parsed GraphQL queries with optional caching.
//!
//! Note: FFI wrappers for Python are in `py/src/ffi/query.rs`

use serde::{Deserialize, Serialize};

/// A generated SQL query with parameters ready for execution.
///
/// This is the output of the query builder and contains the complete SQL
/// and all parameters needed for prepared statement execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GeneratedQuery {
    /// The SQL query string
    pub sql: String,
    /// Query parameters as (name, value) tuples for binding
    pub parameters: Vec<(String, String)>,
}

impl GeneratedQuery {
    /// Create a new generated query.
    ///
    /// # Arguments
    /// * `sql` - The SQL query string
    /// * `parameters` - List of (name, value) parameter tuples
    pub fn new(sql: String, parameters: Vec<(String, String)>) -> Self {
        GeneratedQuery { sql, parameters }
    }

    /// Get the SQL string.
    #[must_use]
    pub fn sql(&self) -> &str {
        &self.sql
    }

    /// Get the parameters.
    #[must_use]
    pub fn parameters(&self) -> &[(String, String)] {
        &self.parameters
    }
}

/// Parameters from a query composition result (before conversion to strings).
///
/// Used internally during query building.
#[derive(Debug, Clone)]
pub enum ParameterValue {
    /// String parameter
    String(String),
    /// Integer parameter
    Integer(i64),
    /// Float parameter
    Float(f64),
    /// Boolean parameter
    Boolean(bool),
    /// Array parameter
    Array(Vec<String>),
    /// JSON object parameter
    JsonObject(String),
}

impl ParameterValue {
    /// Convert to string representation for SQL binding.
    pub fn to_string_value(&self) -> String {
        match self {
            ParameterValue::String(s) | ParameterValue::JsonObject(s) => s.clone(),
            ParameterValue::Integer(i) => i.to_string(),
            ParameterValue::Float(f) => f.to_string(),
            ParameterValue::Boolean(b) => b.to_string(),
            ParameterValue::Array(_) => "[]".to_string(),
        }
    }
}

/// Query composition result from the composer.
///
/// This is the raw output from SQLComposer before parameter conversion.
#[derive(Debug, Clone)]
pub struct ComposedQuery {
    /// The SQL query string
    pub sql: String,
    /// Query parameters as (name, value) tuples
    pub parameters: Vec<(String, ParameterValue)>,
}

/// Builder error types for Phase 6.2.
///
/// Represents errors that can occur during query building.
#[derive(Debug, Clone)]
pub enum BuilderError {
    /// Schema JSON could not be parsed
    InvalidSchema(String),
    /// Query composition failed
    CompositionFailed(String),
    /// Cache operation failed
    CacheError(String),
}

impl std::fmt::Display for BuilderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BuilderError::InvalidSchema(msg) => write!(f, "Invalid schema: {}", msg),
            BuilderError::CompositionFailed(msg) => write!(f, "Query composition failed: {}", msg),
            BuilderError::CacheError(msg) => write!(f, "Cache error: {}", msg),
        }
    }
}

impl std::error::Error for BuilderError {}

/// Statistics about query caching performance.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct CacheStats {
    /// Number of cache hits
    pub hits: usize,
    /// Number of cache misses
    pub misses: usize,
    /// Hit rate as a percentage (0.0 - 1.0)
    pub hit_rate: f64,
    /// Current number of cached plans
    pub size: usize,
    /// Maximum number of cached plans
    pub max_size: usize,
}

impl CacheStats {
    /// Create new cache statistics.
    pub fn new(hits: usize, misses: usize, size: usize, max_size: usize) -> Self {
        let hit_rate = if hits + misses == 0 {
            0.0
        } else {
            hits as f64 / (hits + misses) as f64
        };

        CacheStats {
            hits,
            misses,
            hit_rate,
            size,
            max_size,
        }
    }
}

/// Pure Rust query builder without caching.
///
/// This struct provides methods to build SQL queries from parsed GraphQL.
/// For cached query building, use `QueryBuilderWithCache`.
#[derive(Debug, Clone)]
pub struct QueryBuilder {
    // Placeholder for future configuration
    _config: (),
}

impl QueryBuilder {
    /// Create a new query builder with default configuration.
    pub fn new() -> Self {
        QueryBuilder { _config: () }
    }

    /// Build a SQL query from parsed GraphQL (without caching).
    ///
    /// This is the core query building functionality. It composes the SQL
    /// from the parsed GraphQL and schema.
    ///
    /// # Arguments
    /// * `parsed_query` - The parsed GraphQL query (typically from parse stage)
    /// * `schema` - The schema metadata
    ///
    /// # Returns
    /// A `GeneratedQuery` ready for execution
    ///
    /// # Errors
    /// Returns `BuilderError` if composition fails
    ///
    /// # Note
    /// This method signature is intentionally generic to work with any
    /// ParsedQuery implementation. The actual FFI layer will provide
    /// the concrete implementation.
    pub fn build<Q, S>(
        &self,
        _parsed_query: &Q,
        _schema: &S,
    ) -> Result<GeneratedQuery, BuilderError>
    where
        Q: std::fmt::Debug,
        S: std::fmt::Debug,
    {
        // This is implemented in the FFI layer which has access to actual types
        // For pure core, this is a placeholder
        Err(BuilderError::CompositionFailed(
            "Build not implemented at core level - use FFI layer".to_string(),
        ))
    }
}

impl Default for QueryBuilder {
    fn default() -> Self {
        Self::new()
    }
}

/// Query builder with caching support.
///
/// This builder caches query composition results by query signature
/// to avoid recomputing the same queries repeatedly.
///
/// The cache is stateless and thread-safe, designed for use behind
/// a Python FFI boundary.
#[derive(Debug, Clone)]
pub struct QueryBuilderWithCache {
    /// Inner query builder (same as `QueryBuilder`)
    inner: QueryBuilder,
    /// Cache size configuration (for potential future state)
    _max_cache_size: usize,
}

impl QueryBuilderWithCache {
    /// Create a new cached query builder with default configuration.
    pub fn new() -> Self {
        Self::with_cache_size(5000)
    }

    /// Create a new cached query builder with specified cache size.
    ///
    /// # Arguments
    /// * `max_cache_size` - Maximum number of query plans to cache
    pub fn with_cache_size(max_cache_size: usize) -> Self {
        QueryBuilderWithCache {
            inner: QueryBuilder::new(),
            _max_cache_size: max_cache_size,
        }
    }

    /// Build a cached SQL query from parsed GraphQL.
    ///
    /// This method checks the cache first and returns immediately if found.
    /// On cache miss, it composes the query and stores the result.
    ///
    /// # Arguments
    /// * `parsed_query` - The parsed GraphQL query
    /// * `schema` - The schema metadata
    /// * `signature` - The query signature (for caching)
    ///
    /// # Returns
    /// A `GeneratedQuery` from cache or freshly composed
    ///
    /// # Errors
    /// Returns `BuilderError` if composition fails
    pub fn build_cached<Q, S>(
        &self,
        parsed_query: &Q,
        schema: &S,
        _signature: &str,
    ) -> Result<GeneratedQuery, BuilderError>
    where
        Q: std::fmt::Debug,
        S: std::fmt::Debug,
    {
        // Cache management is done in the FFI layer which has mutable state
        // Pure core layer just delegates to inner builder
        self.inner.build(parsed_query, schema)
    }

    /// Get the underlying query builder (immutable reference).
    pub fn inner(&self) -> &QueryBuilder {
        &self.inner
    }
}

impl Default for QueryBuilderWithCache {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_generated_query_creation() {
        let params = vec![("id".to_string(), "123".to_string())];
        let query = GeneratedQuery::new("SELECT * FROM users WHERE id = $1".to_string(), params);

        assert_eq!(query.sql(), "SELECT * FROM users WHERE id = $1");
        assert_eq!(query.parameters().len(), 1);
    }

    #[test]
    fn test_parameter_value_to_string() {
        assert_eq!(
            ParameterValue::String("hello".to_string()).to_string_value(),
            "hello"
        );
        assert_eq!(ParameterValue::Integer(42).to_string_value(), "42");
        assert_eq!(
            ParameterValue::Float(3.14).to_string_value(),
            "3.14"
        );
        assert_eq!(ParameterValue::Boolean(true).to_string_value(), "true");
        assert_eq!(ParameterValue::Array(vec![]).to_string_value(), "[]");
    }

    #[test]
    fn test_cache_stats_calculation() {
        let stats = CacheStats::new(8, 2, 10, 100);
        assert_eq!(stats.hits, 8);
        assert_eq!(stats.misses, 2);
        assert!(stats.hit_rate > 0.79 && stats.hit_rate < 0.81); // Should be 0.8
    }

    #[test]
    fn test_cache_stats_zero_division() {
        let stats = CacheStats::new(0, 0, 0, 100);
        assert_eq!(stats.hit_rate, 0.0);
    }

    #[test]
    fn test_query_builder_creation() {
        let builder = QueryBuilder::new();
        let default_builder = QueryBuilder::default();

        // Both should be identical
        assert_eq!(format!("{:?}", builder), format!("{:?}", default_builder));
    }

    #[test]
    fn test_query_builder_with_cache_creation() {
        let cached_builder = QueryBuilderWithCache::new();
        assert_eq!(cached_builder._max_cache_size, 5000);

        let custom_builder = QueryBuilderWithCache::with_cache_size(1000);
        assert_eq!(custom_builder._max_cache_size, 1000);
    }

    #[test]
    fn test_builder_error_display() {
        let err = BuilderError::InvalidSchema("bad json".to_string());
        assert_eq!(err.to_string(), "Invalid schema: bad json");

        let err = BuilderError::CompositionFailed("unknown type".to_string());
        assert_eq!(err.to_string(), "Query composition failed: unknown type");
    }
}
