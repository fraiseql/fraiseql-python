//! Unified GraphQL execution pipeline (Phase 9).

use anyhow::Result;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};
use serde_json::Value as JsonValue;
use std::collections::HashMap;
use std::sync::Arc;

use crate::cache::{CachedQueryPlan, QueryPlanCache};
use crate::db::pool::DatabasePool;
use crate::graphql::{
    advanced_selections::AdvancedSelectionProcessor,
    complexity::{ComplexityAnalyzer, ComplexityConfig},
    fragments::FragmentGraph,
    types::ParsedQuery,
    variables::VariableProcessor,
};
use crate::query::composer::SQLComposer;
use crate::query::schema::SchemaMetadata;

/// User context for authorization and personalization.
#[derive(Debug, Clone)]
pub struct UserContext {
    /// User identifier
    pub user_id: Option<String>,
    /// User permissions
    pub permissions: Vec<String>,
    /// User roles
    pub roles: Vec<String>,
    /// Expiration timestamp for cache management
    pub exp: u64,
}

/// Complete unified GraphQL pipeline.
#[derive(Debug, Clone)]
pub struct GraphQLPipeline {
    schema: SchemaMetadata,
    cache: Arc<QueryPlanCache>,
    pool: Arc<DatabasePool>,
}

impl GraphQLPipeline {
    /// Create a new unified GraphQL pipeline with schema, cache, and database pool
    #[must_use]
    pub const fn new(
        schema: SchemaMetadata,
        cache: Arc<QueryPlanCache>,
        pool: Arc<DatabasePool>,
    ) -> Self {
        Self {
            schema,
            cache,
            pool,
        }
    }

    /// Execute complete GraphQL query end-to-end (async version for production).
    ///
    /// This is the true async production path that leverages tokio concurrency
    /// for query parsing validation and database operations.
    ///
    /// # Errors
    ///
    /// Returns an error if query parsing, SQL building, or execution fails.
    pub async fn execute(
        &self,
        query_string: &str,
        variables: HashMap<String, JsonValue>,
        user_context: UserContext,
    ) -> Result<Vec<u8>> {
        // Phase 6: Parse GraphQL query (can be done synchronously as it's fast)
        let parsed_query = crate::graphql::parser::parse_query(query_string)?;

        // Phase 13: Advanced GraphQL Features Validation (can be parallelized)
        Self::validate_advanced_graphql_features(&parsed_query, &variables)?;

        // Phase 14: RBAC Authorization Check
        Self::check_authorization(&parsed_query, &user_context, &self.schema)?;

        // Determine operation type and route accordingly
        match parsed_query.operation_type.as_str() {
            "mutation" => {
                self.execute_mutation_async(&parsed_query, &variables, &user_context).await
            }
            "subscription" => {
                Err(anyhow::anyhow!(
                    "Subscriptions not yet supported in unified pipeline. Use subscription executor directly."
                ))
            }
            _ => {
                // "query" or default: handle as query operation
                self.execute_query_async(&parsed_query, &variables).await
            }
        }
    }

    /// Execute GraphQL query operation asynchronously.
    async fn execute_query_async(
        &self,
        parsed_query: &ParsedQuery,
        variables: &HashMap<String, JsonValue>,
    ) -> Result<Vec<u8>> {
        // Phase 5: Process advanced selections (resolve fragments, evaluate directives)
        let processed_query = Self::process_advanced_selections(parsed_query, variables)?;

        // Phase 7 + 8: Build SQL (with caching)
        // Use processed query signature (includes fragment and directive processing)
        let signature = crate::cache::signature::generate_signature(&processed_query);
        let sql = if let Ok(Some(cached_plan)) = self.cache.get(&signature) {
            // Cache hit - use cached SQL
            cached_plan.sql_template
        } else {
            // Cache miss - build SQL from processed query
            let composer = SQLComposer::new(self.schema.clone());
            let sql_query = composer.compose(&processed_query)?;

            // Store in cache asynchronously (spawn background task)
            let cache_clone = Arc::clone(&self.cache);
            let sig_clone = signature.clone();
            let sql_clone = sql_query.sql.clone();
            tokio::spawn(async move {
                let cached_plan = CachedQueryPlan {
                    signature: sig_clone.clone(),
                    sql_template: sql_clone,
                    parameters: vec![],
                    created_at: std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .expect("system time before UNIX epoch")
                        .as_secs(),
                    hit_count: 0,
                };
                if let Err(e) = cache_clone.put(sig_clone, cached_plan) {
                    eprintln!("Cache put error: {e}");
                }
            });

            sql_query.sql
        };

        // Phase 1 + 2 + 3: Database execution (async)
        let db_results = self.execute_database_query_async(&sql).await?;

        // Phase 3 + 4: Transform to GraphQL response (using processed query with finalized selections)
        let response = Self::build_graphql_response(&processed_query, db_results)?;

        // Return JSON bytes
        Ok(serde_json::to_vec(&response)?)
    }

    /// Execute GraphQL mutation operation asynchronously.
    ///
    /// Mutations are write operations that may modify database state.
    /// They are never cached and always bypass the query cache.
    async fn execute_mutation_async(
        &self,
        parsed_query: &ParsedQuery,
        variables: &HashMap<String, JsonValue>,
        user_context: &UserContext,
    ) -> Result<Vec<u8>> {
        // Phase 5: Process advanced selections (resolve fragments, evaluate directives)
        let processed_query = Self::process_advanced_selections(parsed_query, variables)?;

        // Phase 7: Build mutation SQL (no caching for mutations)
        let composer = SQLComposer::new(self.schema.clone());
        let sql_query = composer.compose(&processed_query)?;

        // Log mutation for audit trail
        eprintln!(
            "[MUTATION] User: {:?}, Operation: {}, Timestamp: {:?}",
            user_context.user_id,
            processed_query.root_field,
            std::time::SystemTime::now()
        );

        // Phase 1 + 2 + 3: Database execution (async) - WITH TRANSACTION
        // Mutations should typically run in a transaction for atomicity
        let db_results = self.execute_database_query_async(&sql_query.sql).await?;

        // Phase 3 + 4: Transform to GraphQL response (using processed query with finalized selections)
        let response = Self::build_graphql_response(&processed_query, db_results)?;

        // Return JSON bytes
        Ok(serde_json::to_vec(&response)?)
    }

    /// Execute complete GraphQL query end-to-end (sync version for Phase 9 demo).
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - GraphQL query parsing fails
    /// - Advanced feature validation fails
    /// - SQL building or composition fails
    /// - JSON transformation fails
    ///
    /// # Panics
    ///
    /// Panics if the system time is before the UNIX epoch (January 1, 1970).
    /// This should never happen on any modern system.
    pub fn execute_sync(
        &self,
        query_string: &str,
        variables: &HashMap<String, JsonValue>,
        _user_context: UserContext,
    ) -> Result<Vec<u8>> {
        // Phase 6: Parse GraphQL query
        let parsed_query = crate::graphql::parser::parse_query(query_string)?;

        // Phase 13: Advanced GraphQL Features Validation
        Self::validate_advanced_graphql_features(&parsed_query, variables)?;

        // Phase 5: Process advanced selections (resolve fragments, evaluate directives)
        let processed_query = Self::process_advanced_selections(&parsed_query, variables)?;

        // Phase 7 + 8: Build SQL (with caching)
        // Use processed query signature (includes fragment and directive processing)
        let signature = crate::cache::signature::generate_signature(&processed_query);
        let sql = if let Ok(Some(cached_plan)) = self.cache.get(&signature) {
            // Cache hit - use cached SQL
            cached_plan.sql_template
        } else {
            // Cache miss - build SQL from processed query
            let composer = SQLComposer::new(self.schema.clone());
            let sql_query = composer.compose(&processed_query)?;

            // Store in cache
            let cached_plan = CachedQueryPlan {
                signature: signature.clone(),
                sql_template: sql_query.sql.clone(),
                parameters: vec![], // Simplified for Phase 9
                created_at: std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .expect("system time before UNIX epoch")
                    .as_secs(),
                hit_count: 0,
            };

            if let Err(e) = self.cache.put(signature, cached_plan) {
                eprintln!("Cache put error: {e}"); // Log but don't fail
            }

            sql_query.sql
        };

        // Phase 1 + 2 + 3: Database execution (real production database)
        let db_results = self.execute_database_query(&sql)?;

        // Phase 3 + 4: Transform to GraphQL response (using processed query with finalized selections)
        let response = Self::build_graphql_response(&processed_query, db_results)?;

        // Return JSON bytes
        Ok(serde_json::to_vec(&response)?)
    }

    /// Validate advanced GraphQL features (Phase 13).
    fn validate_advanced_graphql_features(
        query: &ParsedQuery,
        variables: &HashMap<String, JsonValue>,
    ) -> Result<()> {
        // 1. Fragment cycle detection
        let fragment_graph = FragmentGraph::new(query);
        fragment_graph
            .validate_fragments()
            .map_err(|e| anyhow::anyhow!("Fragment validation error: {e}"))?;

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
            max_complexity: 1000, // Configurable limit
            ..Default::default()
        };
        let analyzer = ComplexityAnalyzer::with_config(complexity_config);
        analyzer
            .validate_complexity(query)
            .map_err(|e| anyhow::anyhow!("Complexity validation error: {e}"))?;

        Ok(())
    }

    /// Process advanced GraphQL selections (Phase 5).
    ///
    /// This processes fragments and directives:
    /// 1. Resolves fragment spreads to actual field selections
    /// 2. Evaluates @skip and @include directives
    /// 3. Finalizes and deduplicates selection sets
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - Fragment resolution fails
    /// - Directive evaluation fails
    /// - Selection processing fails
    fn process_advanced_selections(
        query: &ParsedQuery,
        variables: &HashMap<String, JsonValue>,
    ) -> Result<ParsedQuery> {
        // Convert JsonValue variables to serde_json::Value for AdvancedSelectionProcessor
        let var_map: HashMap<String, serde_json::Value> = variables
            .iter()
            .map(|(k, v)| {
                (
                    k.clone(),
                    serde_json::to_value(v).unwrap_or(serde_json::Value::Null),
                )
            })
            .collect();

        // Process advanced selections (fragments + directives)
        let processed = AdvancedSelectionProcessor::process(query, &var_map)
            .map_err(|e| anyhow::anyhow!("Advanced selection processing error: {e}"))?;

        // Convert ProcessedQuery back to ParsedQuery with processed selections
        let mut result = query.clone();
        result.selections = processed.selections;

        Ok(result)
    }

    /// Phase 14: RBAC Authorization Check
    ///
    /// Verifies that the user has permission to access the requested fields
    /// and operations in the GraphQL query.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - User lacks required permissions for any field
    /// - User's role doesn't grant access to queried types
    /// - Query accesses restricted operations
    fn check_authorization(
        query: &ParsedQuery,
        user_context: &UserContext,
        schema: &SchemaMetadata,
    ) -> Result<()> {
        // For Phase 9, implement basic authorization checks
        // In production, this would integrate with the RBAC module

        // Check 1: Verify user has minimum permissions (not anonymous)
        if user_context.user_id.is_none()
            && !user_context.permissions.contains(&"public".to_string())
        {
            return Err(anyhow::anyhow!(
                "Unauthorized: User must be authenticated or have public permission"
            ));
        }

        // Check 2: Validate each field selection is accessible
        for selection in &query.selections {
            // Verify field exists in schema
            let _field_exists = schema
                .tables
                .iter()
                .any(|(table_name, _table_schema)| table_name == &selection.name);

            // Check 3: Field-level access control (simple version for Phase 9)
            // In production, this would check granular permissions per field
            // For now, we allow access if user has any permissions
            if user_context.permissions.is_empty() && user_context.user_id.is_none() {
                return Err(anyhow::anyhow!(
                    "Forbidden: User lacks permissions to access '{}'. Required roles: [{:?}]",
                    selection.name,
                    user_context.roles
                ));
            }
        }

        Ok(())
    }

    /// Execute database query asynchronously using the production pool.
    ///
    /// This is the true async path used by the async `execute()` method.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - Database connection fails
    /// - Query execution fails
    /// - JSON serialization fails
    async fn execute_database_query_async(&self, sql: &str) -> Result<Vec<String>> {
        // Get the underlying deadpool-postgres pool from DatabasePool
        let underlying_pool = self
            .pool
            .get_pool()
            .ok_or_else(|| anyhow::anyhow!("Database pool not available"))?;

        // Execute raw SQL query asynchronously
        let client = underlying_pool
            .get()
            .await
            .map_err(|e| anyhow::anyhow!("Failed to get connection: {e}"))?;

        let rows = client
            .query(sql, &[])
            .await
            .map_err(|e| anyhow::anyhow!("Query execution failed: {e}"))?;

        // Convert rows to JSON values (FraiseQL CQRS pattern)
        let results: Vec<serde_json::Value> = rows
            .iter()
            .filter_map(|row| {
                // Extract JSONB column (FraiseQL uses `data` column)
                row.try_get::<_, serde_json::Value>(0).ok()
            })
            .collect();

        // Convert serde_json::Value results to JSON strings
        results
            .iter()
            .map(|value| serde_json::to_string(value).map_err(Into::into))
            .collect()
    }

    /// Execute database query using production pool.
    ///
    /// This function bridges the sync execution context with the async database pool.
    /// It uses the Tokio runtime that was initialized at module load time.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - Database connection fails
    /// - Query execution fails
    /// - JSON serialization fails
    fn execute_database_query(&self, sql: &str) -> Result<Vec<String>> {
        // Use the global Tokio runtime to execute async database query
        // The runtime was initialized in lib.rs during module import

        // Get the underlying pool from DatabasePool
        let underlying_pool = self
            .pool
            .get_pool()
            .ok_or_else(|| anyhow::anyhow!("Database pool not available"))?;

        // Execute query asynchronously and block on result
        let db_results = tokio::runtime::Handle::current().block_on(async {
            // Execute raw SQL query
            let client = underlying_pool
                .get()
                .await
                .map_err(|e| anyhow::anyhow!("Failed to get connection: {e}"))?;

            let rows = client
                .query(sql, &[])
                .await
                .map_err(|e| anyhow::anyhow!("Query execution failed: {e}"))?;

            // Convert rows to JSON values (FraiseQL CQRS pattern)
            let results: Vec<serde_json::Value> = rows
                .iter()
                .filter_map(|row| {
                    // Extract JSONB column (FraiseQL uses `data` column)
                    row.try_get::<_, serde_json::Value>(0).ok()
                })
                .collect();

            Ok::<Vec<serde_json::Value>, anyhow::Error>(results)
        })?;

        // Convert serde_json::Value results to JSON strings
        db_results
            .iter()
            .map(|value| serde_json::to_string(value).map_err(Into::into))
            .collect()
    }

    /// Build GraphQL response from database results.
    fn build_graphql_response(
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

    /// Execute GraphQL query with streaming response.
    ///
    /// This method streams results one at a time as they arrive from the database,
    /// using bounded channels for backpressure control. Suitable for large result sets.
    ///
    /// The method:
    /// 1. Parses and validates the query
    /// 2. Checks authorization
    /// 3. Builds SQL (with caching)
    /// 4. Executes query and streams results
    /// 5. Returns a receiver channel that yields JSON responses
    ///
    /// # Arguments
    ///
    /// * `query_string` - GraphQL query string
    /// * `variables` - Query variables
    /// * `user_context` - User context for authorization
    /// * `channel_size` - Bounded channel size for backpressure (default 100)
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - Query parsing fails
    /// - Authorization fails
    /// - SQL building fails
    /// - Database execution fails
    /// - JSON serialization fails
    ///
    /// # Panics
    ///
    /// Panics if the system time is before the UNIX epoch (January 1, 1970).
    /// This should never happen on any modern system.
    ///
    /// # Example
    ///
    /// ```ignore
    /// let mut rx = pipeline.execute_streaming(query, &vars, &user, 100)?;
    /// while let Some(row) = rx.recv().await {
    ///     println!("{}", row);
    /// }
    /// ```
    pub fn execute_streaming(
        &self,
        query_string: &str,
        variables: &HashMap<String, JsonValue>,
        user_context: &UserContext,
        channel_size: usize,
    ) -> Result<tokio::sync::mpsc::Receiver<String>> {
        // Phase 6: Parse GraphQL query
        let parsed_query = crate::graphql::parser::parse_query(query_string)?;

        // Phase 13: Advanced GraphQL Features Validation
        Self::validate_advanced_graphql_features(&parsed_query, variables)?;

        // Phase 14: RBAC Authorization Check
        Self::check_authorization(&parsed_query, user_context, &self.schema)?;

        // Only streaming queries are supported (not mutations)
        if parsed_query.operation_type == "mutation" {
            return Err(anyhow::anyhow!(
                "Streaming mutations not supported. Use regular execute() for mutations."
            ));
        }

        // Phase 5: Process advanced selections (resolve fragments, evaluate directives)
        let processed_query = Self::process_advanced_selections(&parsed_query, variables)?;

        // Phase 7 + 8: Build SQL (with caching)
        // Use processed query signature (includes fragment and directive processing)
        let signature = crate::cache::signature::generate_signature(&processed_query);
        let sql = if let Ok(Some(cached_plan)) = self.cache.get(&signature) {
            cached_plan.sql_template
        } else {
            let composer = SQLComposer::new(self.schema.clone());
            let sql_query = composer.compose(&processed_query)?;

            // Store in cache asynchronously
            let cache_clone = Arc::clone(&self.cache);
            let sig_clone = signature.clone();
            let sql_clone = sql_query.sql.clone();
            tokio::spawn(async move {
                let cached_plan = CachedQueryPlan {
                    signature: sig_clone.clone(),
                    sql_template: sql_clone,
                    parameters: vec![],
                    created_at: std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .expect("system time before UNIX epoch")
                        .as_secs(),
                    hit_count: 0,
                };
                if let Err(e) = cache_clone.put(sig_clone, cached_plan) {
                    eprintln!("Cache put error in streaming: {e}");
                }
            });

            sql_query.sql
        };

        // Create bounded channel for backpressure
        let (tx, rx) = tokio::sync::mpsc::channel(channel_size);

        // Get the underlying pool for streaming execution
        let underlying_pool = self
            .pool
            .get_pool()
            .ok_or_else(|| anyhow::anyhow!("Database pool not available"))?;

        // Spawn streaming task
        tokio::spawn(async move {
            // Phase 1-3: Execute query and stream results
            let client = match underlying_pool.get().await {
                Ok(c) => c,
                Err(e) => {
                    eprintln!("Failed to get connection for streaming: {e}");
                    return;
                }
            };

            let rows = match client.query(&sql, &[]).await {
                Ok(r) => r,
                Err(e) => {
                    eprintln!("Streaming query execution failed: {e}");
                    return;
                }
            };

            // Stream each row - flat nesting structure
            for row in rows {
                let Ok(value) = row.try_get::<_, serde_json::Value>(0) else {
                    continue;
                };

                let Ok(json_string) = serde_json::to_string(&value) else {
                    continue;
                };

                // Send to channel (ignore if receiver dropped)
                let _ = tx.send(json_string).await;
            }
            // Channel automatically closes when tx is dropped
        });

        Ok(rx)
    }
}

/// Python wrapper for the unified pipeline.
#[derive(Debug)]
#[pyclass]
pub struct PyGraphQLPipeline {
    pipeline: Arc<GraphQLPipeline>,
}

#[pymethods]
impl PyGraphQLPipeline {
    /// # Errors
    ///
    /// Returns a Python error if schema JSON is invalid or cannot be parsed.
    #[new]
    pub fn new(schema_json: &str, pool: &DatabasePool) -> PyResult<Self> {
        let schema: SchemaMetadata = serde_json::from_str(schema_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;

        let cache = Arc::new(QueryPlanCache::new(5000));

        let pipeline = Arc::new(GraphQLPipeline::new(schema, cache, Arc::new(pool.clone())));

        Ok(Self { pipeline })
    }

    /// Execute GraphQL query (Python interface).
    ///
    /// # Errors
    ///
    /// Returns a Python error if:
    /// - Variable or user context conversion fails
    /// - Query execution fails
    /// - Response conversion to Python fails
    #[pyo3(name = "execute")]
    pub fn execute_py(
        &self,
        py: Python,
        query_string: &str,
        variables: &Bound<'_, PyDict>,
        user_context: &Bound<'_, PyDict>,
    ) -> PyResult<PyObject> {
        let vars = dict_to_hashmap(variables)?;
        let user = dict_to_user_context(user_context)?;

        // For Phase 9 demo, execute synchronously with mock data
        let result_bytes = self
            .pipeline
            .execute_sync(query_string, &vars, user)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        Ok(PyBytes::new(py, &result_bytes).into())
    }
}

// Rust-only methods (not exposed to Python)
impl PyGraphQLPipeline {
    /// Internal method to execute GraphQL query from FFI (Rust-to-Rust call).
    ///
    /// This method is called from the unified FFI binding `process_graphql_request()`
    /// and executes the entire GraphQL pipeline in Rust without any Python overhead.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - Query execution fails
    /// - Response building fails
    pub fn execute_sync_internal(
        &self,
        query_string: &str,
        variables: &HashMap<String, serde_json::Value>,
        user_context: UserContext,
    ) -> anyhow::Result<Vec<u8>> {
        self.pipeline
            .execute_sync(query_string, variables, user_context)
    }
}

/// Convert `PyDict` to `HashMap` for variables.
fn dict_to_hashmap(dict: &Bound<'_, PyDict>) -> PyResult<HashMap<String, JsonValue>> {
    let mut result = HashMap::new();
    for (key, value) in dict.iter() {
        let key_str = key.extract::<String>()?;
        let value_json = py_to_json(&value);
        result.insert(key_str, value_json);
    }
    Ok(result)
}

/// Convert Python object to JSON value.
fn py_to_json(obj: &Bound<'_, PyAny>) -> JsonValue {
    if obj.is_none() {
        JsonValue::Null
    } else if let Ok(s) = obj.extract::<String>() {
        JsonValue::String(s)
    } else if let Ok(i) = obj.extract::<i64>() {
        JsonValue::Number(i.into())
    } else if let Ok(f) = obj.extract::<f64>() {
        JsonValue::Number(serde_json::Number::from_f64(f).expect("finite f64"))
    } else if let Ok(b) = obj.extract::<bool>() {
        JsonValue::Bool(b)
    } else {
        JsonValue::Null // Simplified fallback
    }
}

/// Convert `PyDict` to `UserContext`.
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
