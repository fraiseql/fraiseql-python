//! PyO3 FFI wrapper for query building (Phase 6.2).
//!
//! This module provides Python bindings for the pure Rust query building
//! types from fraiseql_core::query::builder.
//!
//! Note: The pure query builder logic is in core/src/query/builder.rs

use fraiseql_core::query::builder::{
    CacheStats, GeneratedQuery as CoreGeneratedQuery,
    QueryBuilderWithCache as CoreQueryBuilderWithCache,
};
use pyo3::prelude::*;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

/// Python wrapper for GeneratedQuery.
///
/// Represents a completed SQL query with parameters ready for execution.
#[pyclass(name = "GeneratedQuery")]
#[derive(Debug, Clone)]
pub struct PyGeneratedQuery {
    /// The SQL query string
    #[pyo3(get)]
    pub sql: String,

    /// Parameters as list of (name, value) tuples
    #[pyo3(get)]
    pub parameters: Vec<(String, String)>,
}

#[pymethods]
impl PyGeneratedQuery {
    /// Create a new generated query.
    #[new]
    fn new(sql: String, parameters: Vec<(String, String)>) -> Self {
        PyGeneratedQuery { sql, parameters }
    }

    /// Get the SQL string.
    fn get_sql(&self) -> String {
        self.sql.clone()
    }

    /// Get parameters.
    fn get_parameters(&self) -> Vec<(String, String)> {
        self.parameters.clone()
    }
}

impl From<CoreGeneratedQuery> for PyGeneratedQuery {
    fn from(query: CoreGeneratedQuery) -> Self {
        PyGeneratedQuery {
            sql: query.sql,
            parameters: query.parameters,
        }
    }
}

/// Python wrapper for cache statistics.
#[pyclass(name = "CacheStats")]
#[derive(Debug, Clone)]
pub struct PyCacheStats {
    #[pyo3(get)]
    pub hits: usize,
    #[pyo3(get)]
    pub misses: usize,
    #[pyo3(get)]
    pub hit_rate: f64,
    #[pyo3(get)]
    pub size: usize,
    #[pyo3(get)]
    pub max_size: usize,
}

#[pymethods]
impl PyCacheStats {
    /// Create new cache statistics.
    #[new]
    fn new(hits: usize, misses: usize, size: usize, max_size: usize) -> Self {
        let hit_rate = if hits + misses == 0 {
            0.0
        } else {
            hits as f64 / (hits + misses) as f64
        };

        PyCacheStats {
            hits,
            misses,
            hit_rate,
            size,
            max_size,
        }
    }

    /// Get as Python dictionary.
    fn to_dict(&self, py: Python) -> PyResult<PyObject> {
        let dict = pyo3::types::PyDict::new(py);
        dict.set_item("hits", self.hits)?;
        dict.set_item("misses", self.misses)?;
        dict.set_item("hit_rate", self.hit_rate)?;
        dict.set_item("size", self.size)?;
        dict.set_item("max_size", self.max_size)?;
        Ok(dict.into())
    }
}

impl From<CacheStats> for PyCacheStats {
    fn from(stats: CacheStats) -> Self {
        PyCacheStats {
            hits: stats.hits,
            misses: stats.misses,
            hit_rate: stats.hit_rate,
            size: stats.size,
            max_size: stats.max_size,
        }
    }
}

/// Internal cache state holder for the FFI query builder with caching.
///
/// This tracks query cache state at the FFI boundary. The actual cache
/// is managed by the main crate's QUERY_PLAN_CACHE static.
#[derive(Debug)]
struct CacheState {
    /// Cached query plans by signature
    plans: HashMap<String, String>,
    /// Cache statistics
    stats: CacheStats,
}

/// Python wrapper for QueryBuilder with caching.
///
/// This is the primary Python-facing class for query building.
/// It wraps the pure Rust QueryBuilder with caching support.
#[pyclass(name = "QueryBuilder")]
#[derive(Debug)]
pub struct PyQueryBuilder {
    /// Cache state
    cache: Arc<Mutex<CacheState>>,
}

#[pymethods]
impl PyQueryBuilder {
    /// Create a new query builder.
    #[new]
    fn new() -> Self {
        PyQueryBuilder {
            cache: Arc::new(Mutex::new(CacheState {
                plans: HashMap::new(),
                stats: CacheStats::new(0, 0, 0, 5000),
            })),
        }
    }

    /// Build a SQL query from parsed GraphQL (without caching).
    ///
    /// # Arguments
    /// * `parsed_query` - The parsed GraphQL query (as JSON string for now)
    /// * `schema_json` - The schema as a JSON string
    ///
    /// # Returns
    /// A `PyGeneratedQuery` ready for execution
    ///
    /// # Errors
    /// Returns PyErr if schema is invalid or composition fails
    fn build(&self, _parsed_query: &str, _schema_json: &str) -> PyResult<PyGeneratedQuery> {
        // Note: Actual implementation requires integration with composer
        // For Phase 6.2, we provide the FFI structure; actual query building
        // happens through the main crate's build_sql_query function
        Err(pyo3::exceptions::PyNotImplementedError::new_err(
            "Use build_sql_query() function for actual query building",
        ))
    }

    /// Build a cached SQL query.
    ///
    /// # Arguments
    /// * `parsed_query` - The parsed GraphQL query
    /// * `schema_json` - The schema as JSON
    /// * `query_signature` - The signature for caching
    ///
    /// # Returns
    /// A `PyGeneratedQuery` from cache or freshly built
    fn build_cached(
        &self,
        _parsed_query: &str,
        _schema_json: &str,
        _query_signature: &str,
    ) -> PyResult<PyGeneratedQuery> {
        Err(pyo3::exceptions::PyNotImplementedError::new_err(
            "Use build_sql_query_cached() function for actual cached query building",
        ))
    }

    /// Get current cache statistics.
    fn cache_stats(&self) -> PyResult<PyCacheStats> {
        let cache = self
            .cache
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("Cache lock poisoned"))?;

        Ok(cache.stats.into())
    }

    /// Clear the query cache.
    fn clear_cache(&self) -> PyResult<()> {
        let mut cache = self
            .cache
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("Cache lock poisoned"))?;

        cache.plans.clear();
        cache.stats = CacheStats::new(0, 0, 0, cache.stats.max_size);

        Ok(())
    }

    /// Record a cache hit.
    fn record_hit(&self) -> PyResult<()> {
        let mut cache = self
            .cache
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("Cache lock poisoned"))?;

        let stats = cache.stats;
        cache.stats = CacheStats::new(stats.hits + 1, stats.misses, stats.size, stats.max_size);

        Ok(())
    }

    /// Record a cache miss.
    fn record_miss(&self) -> PyResult<()> {
        let mut cache = self
            .cache
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("Cache lock poisoned"))?;

        let stats = cache.stats;
        cache.stats = CacheStats::new(stats.hits, stats.misses + 1, stats.size, stats.max_size);

        Ok(())
    }
}

impl Default for PyQueryBuilder {
    fn default() -> Self {
        Self::new()
    }
}

/// Backward compatibility: module-level function to build SQL queries.
///
/// This function wraps the pure Rust QueryBuilder for use from Python.
/// Note: The actual implementation with composer integration is in src/query/mod.rs
#[pyfunction]
pub fn build_sql_query(parsed_query: &str, schema_json: &str) -> PyResult<PyGeneratedQuery> {
    // Validate schema JSON
    let _schema: serde_json::Value = serde_json::from_str(schema_json)
        .map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Invalid schema JSON: {}", e))
        })?;

    // In actual implementation, this would:
    // 1. Deserialize schema
    // 2. Parse GraphQL query
    // 3. Compose SQL
    // 4. Return GeneratedQuery

    Err(pyo3::exceptions::PyNotImplementedError::new_err(
        "Use the main crate's build_sql_query() function",
    ))
}

/// Build cached SQL query.
///
/// Uses the QueryBuilder's cache to avoid recomposing identical queries.
#[pyfunction]
pub fn build_sql_query_cached(
    parsed_query: &str,
    schema_json: &str,
) -> PyResult<PyGeneratedQuery> {
    // Validate inputs
    let _schema: serde_json::Value = serde_json::from_str(schema_json)
        .map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Invalid schema JSON: {}", e))
        })?;

    let _parsed: serde_json::Value = serde_json::from_str(parsed_query).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("Invalid query JSON: {}", e))
    })?;

    Err(pyo3::exceptions::PyNotImplementedError::new_err(
        "Use the main crate's build_sql_query_cached() function",
    ))
}

/// Get current cache statistics.
#[pyfunction]
pub fn get_cache_stats() -> PyResult<PyCacheStats> {
    // Placeholder - actual implementation in main crate
    Ok(PyCacheStats::new(0, 0, 0, 5000))
}

/// Clear the query cache.
#[pyfunction]
pub fn clear_cache() -> PyResult<()> {
    // Placeholder - actual implementation in main crate
    Ok(())
}
