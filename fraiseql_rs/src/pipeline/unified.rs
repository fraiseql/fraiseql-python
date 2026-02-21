//! Unified GraphQL execution pipeline (Phase 9).

use std::{collections::HashMap, sync::Arc};

use anyhow::Result;
use pyo3::{
    prelude::*,
    types::{PyBytes, PyDict},
};
use serde_json::Value as JsonValue;

use crate::{
    cache::{CachedQueryPlan, QueryPlanCache},
    graphql::{
        complexity::{ComplexityAnalyzer, ComplexityConfig},
        fragments::FragmentGraph,
        types::ParsedQuery,
        variables::VariableProcessor,
    },
    query::{composer::SQLComposer, schema::SchemaMetadata},
};

/// User context for authorization and personalization.
#[derive(Debug, Clone)]
pub struct UserContext {
    pub user_id:     Option<String>,
    pub permissions: Vec<String>,
    pub roles:       Vec<String>,
    pub exp:         u64, // Expiration timestamp for cache management
}

/// Complete unified GraphQL pipeline.
pub struct GraphQLPipeline {
    schema: SchemaMetadata,
    cache:  Arc<QueryPlanCache>,
    // Note: In a real implementation, this would include database pool
    // For Phase 9 demo, we'll mock the database operations
}

impl GraphQLPipeline {
    pub fn new(schema: SchemaMetadata, cache: Arc<QueryPlanCache>) -> Self {
        Self { schema, cache }
    }

    /// Execute complete GraphQL query end-to-end (async version for production).
    pub async fn execute(
        &self,
        query_string: &str,
        variables: HashMap<String, JsonValue>,
        user_context: UserContext,
    ) -> Result<Vec<u8>> {
        // For Phase 9, delegate to sync version
        self.execute_sync(query_string, variables, user_context)
    }

    /// Execute complete GraphQL query end-to-end (sync version for Phase 9 demo).
    pub fn execute_sync(
        &self,
        query_string: &str,
        variables: HashMap<String, JsonValue>,
        _user_context: UserContext,
    ) -> Result<Vec<u8>> {
        // Phase 6: Parse GraphQL query
        let parsed_query = crate::graphql::parser::parse_query(query_string)?;

        // Phase 13: Advanced GraphQL Features Validation
        self.validate_advanced_graphql_features(&parsed_query, &variables)?;

        // Phase 7 + 8: Build SQL (with caching)
        let signature = crate::cache::signature::generate_signature(&parsed_query);
        let sql = if let Ok(Some(cached_plan)) = self.cache.get(&signature) {
            // Cache hit - use cached SQL
            cached_plan.sql_template
        } else {
            // Cache miss - build SQL
            let composer = SQLComposer::new(self.schema.clone());
            let composed = composer.compose(&parsed_query)?;

            // Store in cache
            let cached_plan = CachedQueryPlan {
                signature:    signature.clone(),
                sql_template: composed.sql.clone(),
                parameters:   vec![], // Simplified for Phase 9
                created_at:   std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs(),
                hit_count:    0,
            };

            if let Err(e) = self.cache.put(signature, cached_plan) {
                eprintln!("Cache put error: {}", e); // Log but don't fail
            }

            composed.sql
        };

        // Phase 1 + 2 + 3: Database execution (mocked for Phase 9)
        // In production, this would execute the SQL and stream results
        let mock_results = self.execute_mock_query(&sql, &variables)?;

        // Phase 3 + 4: Transform to GraphQL response
        let response = self.build_graphql_response(&parsed_query, mock_results)?;

        // Return JSON bytes
        Ok(serde_json::to_vec(&response)?)
    }

    /// Validate advanced GraphQL features (Phase 13).
    fn validate_advanced_graphql_features(
        &self,
        query: &ParsedQuery,
        variables: &HashMap<String, JsonValue>,
    ) -> Result<()> {
        // 1. Fragment cycle detection
        let fragment_graph = FragmentGraph::new(query);
        fragment_graph
            .validate_fragments()
            .map_err(|e| anyhow::anyhow!("Fragment validation error: {}", e))?;

        // 2. Variable processing and validation
        let var_processor = VariableProcessor::new(query);
        let processed_vars = var_processor.process_variables(variables);
        if !processed_vars.errors.is_empty() {
            return Err(anyhow::anyhow!(
                "Variable processing errors: {}",
                processed_vars.errors.join(", ")
            ));
        }

        // 3. Query complexity analysis
        let complexity_config = ComplexityConfig {
            max_complexity:   1000, // Configurable limit
            field_cost:       1,
            depth_multiplier: 1.5,
            field_overrides:  HashMap::new(),
            type_multipliers: HashMap::new(),
        };
        let analyzer = ComplexityAnalyzer::with_config(complexity_config);
        analyzer
            .validate_complexity(query)
            .map_err(|e| anyhow::anyhow!("Complexity validation error: {}", e))?;

        Ok(())
    }

    /// Mock database execution for Phase 9 demo.
    fn execute_mock_query(
        &self,
        sql: &str,
        _variables: &HashMap<String, JsonValue>,
    ) -> Result<Vec<String>> {
        // Simple mock based on SQL content
        if sql.contains("user") {
            // Matches "users", "v_user", etc.
            let limit = if sql.contains("LIMIT") {
                // Extract limit from SQL (simplified)
                if let Some(limit_part) = sql.split("LIMIT ").nth(1) {
                    limit_part
                        .split_whitespace()
                        .next()
                        .and_then(|s| s.parse::<usize>().ok())
                        .unwrap_or(10)
                } else {
                    10
                }
            } else {
                10
            };

            // Generate mock user data
            let mut results = Vec::new();
            for i in 0..limit {
                let user = serde_json::json!({
                    "id": i + 1,
                    "name": format!("User {}", i + 1),
                    "email": format!("user{}@example.com", i + 1),
                    "status": if i % 2 == 0 { "active" } else { "inactive" }
                });
                results.push(serde_json::to_string(&user)?);
            }
            Ok(results)
        } else {
            Ok(vec![])
        }
    }

    /// Build GraphQL response from database results.
    fn build_graphql_response(
        &self,
        parsed_query: &ParsedQuery,
        db_results: Vec<String>,
    ) -> Result<serde_json::Value> {
        let root_field = &parsed_query.selections[0];

        // Build data array from results
        let data_array: Vec<serde_json::Value> = db_results
            .into_iter()
            .map(|row| serde_json::from_str(&row))
            .collect::<Result<Vec<_>, _>>()?;

        // Create GraphQL response
        let response = serde_json::json!({
            "data": {
                root_field.name.clone(): data_array
            }
        });

        Ok(response)
    }
}

/// Python wrapper for the unified pipeline.
#[pyclass]
pub struct PyGraphQLPipeline {
    pipeline: Arc<GraphQLPipeline>,
}

#[pymethods]
impl PyGraphQLPipeline {
    #[new]
    pub fn new(schema_json: String) -> PyResult<Self> {
        let schema: SchemaMetadata = serde_json::from_str(&schema_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;

        let cache = Arc::new(QueryPlanCache::new(5000));

        let pipeline = Arc::new(GraphQLPipeline::new(schema, cache));

        Ok(Self { pipeline })
    }

    /// Execute GraphQL query (Python interface).
    #[pyo3(name = "execute")]
    pub fn execute_py(
        &self,
        py: Python,
        query_string: String,
        variables: &Bound<'_, PyDict>,
        user_context: &Bound<'_, PyDict>,
    ) -> PyResult<PyObject> {
        let vars = dict_to_hashmap(variables)?;
        let user = dict_to_user_context(user_context)?;

        // For Phase 9 demo, execute synchronously with mock data
        let result_bytes = self
            .pipeline
            .execute_sync(&query_string, vars, user)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        Ok(PyBytes::new(py, &result_bytes).into())
    }
}

/// Convert PyDict to HashMap for variables.
fn dict_to_hashmap(dict: &Bound<'_, PyDict>) -> PyResult<HashMap<String, JsonValue>> {
    let mut result = HashMap::new();
    for (key, value) in dict.iter() {
        let key_str = key.extract::<String>()?;
        let value_json = py_to_json(&value)?;
        result.insert(key_str, value_json);
    }
    Ok(result)
}

/// Convert Python object to JSON value.
fn py_to_json(obj: &Bound<'_, PyAny>) -> PyResult<JsonValue> {
    if obj.is_none() {
        Ok(JsonValue::Null)
    } else if let Ok(s) = obj.extract::<String>() {
        Ok(JsonValue::String(s))
    } else if let Ok(i) = obj.extract::<i64>() {
        Ok(JsonValue::Number(i.into()))
    } else if let Ok(f) = obj.extract::<f64>() {
        Ok(JsonValue::Number(serde_json::Number::from_f64(f).unwrap()))
    } else if let Ok(b) = obj.extract::<bool>() {
        Ok(JsonValue::Bool(b))
    } else {
        Ok(JsonValue::Null) // Simplified fallback
    }
}

/// Convert PyDict to UserContext.
fn dict_to_user_context(dict: &Bound<'_, PyDict>) -> PyResult<UserContext> {
    let user_id = dict.get_item("user_id")?.and_then(|v| {
        if v.is_none() {
            None
        } else {
            v.extract::<String>().ok()
        }
    });

    let permissions = dict
        .get_item("permissions")?
        .and_then(|v| v.extract::<Vec<String>>().ok())
        .unwrap_or_default();

    let roles = dict
        .get_item("roles")?
        .and_then(|v| v.extract::<Vec<String>>().ok())
        .unwrap_or_default();

    Ok(UserContext {
        user_id,
        permissions,
        roles,
        exp: 0, // Default for mock contexts
    })
}
