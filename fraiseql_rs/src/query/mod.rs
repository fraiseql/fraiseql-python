//! Query building module.

pub mod composer;
pub mod schema;
pub mod where_builder;

use lazy_static::lazy_static;
use pyo3::prelude::*;

use crate::{
    cache::QueryPlanCache,
    graphql::types::ParsedQuery,
    query::{composer::SQLComposer, schema::SchemaMetadata},
};

lazy_static! {
    static ref QUERY_PLAN_CACHE: QueryPlanCache = QueryPlanCache::new(5000);
}

/// Build complete SQL query from parsed GraphQL.
#[pyfunction]
pub fn build_sql_query(
    _py: Python,
    parsed_query: ParsedQuery,
    schema_json: String,
) -> PyResult<GeneratedQuery> {
    // Deserialize schema
    let schema: SchemaMetadata = serde_json::from_str(&schema_json).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid schema JSON: {}", e))
    })?;

    // Compose SQL
    let composer = SQLComposer::new(schema);
    let composed = composer.compose(&parsed_query).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
            "Query composition failed: {}",
            e
        ))
    })?;

    // Return GeneratedQuery
    Ok(GeneratedQuery {
        sql:        composed.sql,
        parameters: composed
            .parameters
            .into_iter()
            .map(|(name, value)| {
                let value_str = match value {
                    where_builder::ParameterValue::String(s) => s,
                    where_builder::ParameterValue::Integer(i) => i.to_string(),
                    where_builder::ParameterValue::Float(f) => f.to_string(),
                    where_builder::ParameterValue::Boolean(b) => b.to_string(),
                    where_builder::ParameterValue::JsonObject(s) => s,
                    where_builder::ParameterValue::Array(_) => "[]".to_string(),
                };
                (name, value_str)
            })
            .collect(),
    })
}

/// Build complete SQL query with caching.
#[pyfunction]
pub fn build_sql_query_cached(
    _py: Python,
    parsed_query: ParsedQuery,
    schema_json: String,
) -> PyResult<GeneratedQuery> {
    // Generate query signature
    let signature = crate::cache::signature::generate_signature(&parsed_query);

    // Check cache
    if let Ok(Some(cached_plan)) = QUERY_PLAN_CACHE.get(&signature) {
        // Cache hit - return cached plan
        return Ok(GeneratedQuery {
            sql:        cached_plan.sql_template,
            parameters: vec![], // Parameters already bound
        });
    }

    // Cache miss - build query normally
    let schema: SchemaMetadata = serde_json::from_str(&schema_json).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid schema JSON: {}", e))
    })?;

    let composer = SQLComposer::new(schema);
    let composed = composer.compose(&parsed_query).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
            "Query composition failed: {}",
            e
        ))
    })?;

    let result = GeneratedQuery {
        sql:        composed.sql.clone(),
        parameters: composed
            .parameters
            .into_iter()
            .map(|(name, value)| {
                let value_str = match value {
                    where_builder::ParameterValue::String(s) => s,
                    where_builder::ParameterValue::Integer(i) => i.to_string(),
                    where_builder::ParameterValue::Float(f) => f.to_string(),
                    where_builder::ParameterValue::Boolean(b) => b.to_string(),
                    where_builder::ParameterValue::JsonObject(s) => s,
                    where_builder::ParameterValue::Array(_) => "[]".to_string(),
                };
                (name, value_str)
            })
            .collect(),
    };

    // Store in cache
    let _ = QUERY_PLAN_CACHE.put(
        signature.clone(),
        crate::cache::CachedQueryPlan {
            signature,
            sql_template: composed.sql,
            parameters: vec![],
            created_at: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs(),
            hit_count: 0,
        },
    );

    Ok(result)
}

/// Get cache statistics.
#[pyfunction]
pub fn get_cache_stats(_py: Python) -> PyResult<PyObject> {
    let stats = QUERY_PLAN_CACHE.stats().map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Cache stats error: {}", e))
    })?;

    let dict = pyo3::types::PyDict::new(_py);
    dict.set_item("hits", stats.hits)?;
    dict.set_item("misses", stats.misses)?;
    dict.set_item("hit_rate", stats.hit_rate)?;
    dict.set_item("cached_plans", stats.size)?;
    dict.set_item("max_cached_plans", stats.max_size)?;

    Ok(dict.into())
}

/// Clear cache (for schema changes).
#[pyfunction]
pub fn clear_cache() -> PyResult<()> {
    QUERY_PLAN_CACHE.clear().map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Cache clear error: {}", e))
    })
}

#[pyclass]
pub struct GeneratedQuery {
    #[pyo3(get)]
    pub sql: String,

    #[pyo3(get)]
    pub parameters: Vec<(String, String)>,
}
