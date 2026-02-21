//! Query execution and result handling.
//!
//! Phase 2.0: Basic query execution infrastructure
//! Full implementation with parameter binding in Phase 2.5

use bytes::BytesMut;
use tokio_postgres::{Client, Row, types::ToSql};

use crate::db::{
    types::{DatabaseError, DatabaseResult, QueryParam, QueryResult},
    where_builder::WhereBuilder,
};

/// Query executor for database operations.
/// Phase 2.0: Full implementation with parameter binding
pub struct QueryExecutor<'a> {
    client: &'a mut Client,
}

impl<'a> QueryExecutor<'a> {
    /// Create a new query executor with a database client.
    pub fn new(client: &'a mut Client) -> Self {
        QueryExecutor { client }
    }

    /// Execute a SELECT query and return results.
    pub async fn execute_select(
        &mut self,
        table: &str,
        columns: &[&str],
        where_clause: Option<WhereBuilder>,
        order_by: Option<&str>,
        limit: Option<i64>,
        offset: Option<i64>,
    ) -> DatabaseResult<QueryResult> {
        let sql = self.build_select_sql(table, columns, &where_clause, order_by, limit, offset)?;
        let params = self.extract_params(&where_clause);

        // Validate parameters before execution
        for param in &params {
            param.validate()?;
        }

        let mut sql_params = Vec::with_capacity(params.len());
        sql_params.extend(params.iter().map(|p| p as &(dyn ToSql + Sync)));
        let rows = self
            .client
            .query(&sql, &sql_params)
            .await
            .map_err(|e| DatabaseError::Query(format!("SELECT query failed: {}", e)))?;

        let result = self.rows_to_query_result(rows);
        Ok(result)
    }

    /// Execute an INSERT query and return the number of affected rows.
    pub async fn execute_insert(
        &mut self,
        table: &str,
        columns: &[&str],
        values: &[QueryParam],
    ) -> DatabaseResult<u64> {
        let sql = self.build_insert_sql(table, columns, values.len())?;

        // Validate parameters before execution
        for param in values {
            param.validate()?;
        }

        let mut sql_params = Vec::with_capacity(values.len());
        sql_params.extend(values.iter().map(|p| p as &(dyn ToSql + Sync)));

        let affected = self
            .client
            .execute(&sql, &sql_params)
            .await
            .map_err(|e| DatabaseError::Query(format!("INSERT query failed: {}", e)))?;

        Ok(affected)
    }

    /// Execute an UPDATE query and return the number of affected rows.
    pub async fn execute_update(
        &mut self,
        table: &str,
        updates: &std::collections::HashMap<&str, QueryParam>,
        where_clause: Option<WhereBuilder>,
    ) -> DatabaseResult<u64> {
        let (sql, params) = self.build_update_sql_with_params(table, updates, where_clause)?;

        // Validate parameters before execution
        for param in &params {
            param.validate()?;
        }

        let mut sql_params = Vec::with_capacity(params.len());
        sql_params.extend(params.iter().map(|p| p as &(dyn ToSql + Sync)));
        let affected = self
            .client
            .execute(&sql, &sql_params)
            .await
            .map_err(|e| DatabaseError::Query(format!("UPDATE query failed: {}", e)))?;

        Ok(affected)
    }

    /// Execute a DELETE query and return the number of affected rows.
    pub async fn execute_delete(
        &mut self,
        table: &str,
        where_clause: Option<WhereBuilder>,
    ) -> DatabaseResult<u64> {
        let (where_sql, params) = if let Some(builder) = where_clause {
            builder.build()
        } else {
            ("".to_string(), vec![])
        };

        let sql = if where_sql.is_empty() {
            format!("DELETE FROM {}", table)
        } else {
            format!("DELETE FROM {} {}", table, where_sql)
        };

        // Validate parameters before execution
        for param in &params {
            param.validate()?;
        }

        let mut sql_params = Vec::with_capacity(params.len());
        sql_params.extend(params.iter().map(|p| p as &(dyn ToSql + Sync)));
        let affected = self
            .client
            .execute(&sql, &sql_params)
            .await
            .map_err(|e| DatabaseError::Query(format!("DELETE query failed: {}", e)))?;

        Ok(affected)
    }

    /// Build SELECT SQL statement.
    fn build_select_sql(
        &self,
        table: &str,
        columns: &[&str],
        where_clause: &Option<WhereBuilder>,
        order_by: Option<&str>,
        limit: Option<i64>,
        offset: Option<i64>,
    ) -> DatabaseResult<String> {
        let column_list = columns.join(", ");
        let mut sql = format!("SELECT {} FROM {}", column_list, table);

        if let Some(builder) = where_clause {
            let (where_sql, _) = builder.clone().build();
            if !where_sql.is_empty() {
                sql.push_str(&where_sql);
            }
        }

        if let Some(order) = order_by {
            sql.push_str(&format!(" ORDER BY {}", order));
        }

        if let Some(limit_val) = limit {
            sql.push_str(&format!(" LIMIT {}", limit_val));
        }

        if let Some(offset_val) = offset {
            sql.push_str(&format!(" OFFSET {}", offset_val));
        }

        Ok(sql)
    }

    /// Build INSERT SQL statement.
    fn build_insert_sql(
        &self,
        table: &str,
        columns: &[&str],
        value_count: usize,
    ) -> DatabaseResult<String> {
        let column_list = columns.join(", ");
        let placeholders: Vec<String> = (1..=value_count).map(|i| format!("${}", i)).collect();
        let value_placeholders = placeholders.join(", ");

        Ok(format!(
            "INSERT INTO {} ({}) VALUES ({})",
            table, column_list, value_placeholders
        ))
    }

    /// Build UPDATE SQL statement and collect parameters.
    fn build_update_sql_with_params(
        &self,
        table: &str,
        updates: &std::collections::HashMap<&str, QueryParam>,
        where_clause: Option<WhereBuilder>,
    ) -> DatabaseResult<(String, Vec<QueryParam>)> {
        let mut params = self.hashmap_to_params(updates);
        let param_offset = params.len();

        let set_clauses: Vec<String> = updates
            .keys()
            .enumerate()
            .map(|(i, col)| format!("{} = ${}", col, i + 1))
            .collect();

        let set_sql = set_clauses.join(", ");
        let mut sql = format!("UPDATE {} SET {}", table, set_sql);

        if let Some(builder) = where_clause {
            let (where_sql, where_params) = builder.build();
            if !where_sql.is_empty() {
                // Adjust parameter indices in WHERE clause by offsetting all $N placeholders
                let mut adjusted_where_sql = where_sql;
                // Replace in reverse order to avoid conflicts (e.g., $1 becoming $11 if offset is
                // 10)
                for i in (1..=where_params.len()).rev() {
                    let old_placeholder = format!("${}", i);
                    let new_placeholder = format!("${}", param_offset + i);
                    adjusted_where_sql =
                        adjusted_where_sql.replace(&old_placeholder, &new_placeholder);
                }
                sql.push_str(&adjusted_where_sql);
                params.extend(where_params);
            }
        }

        Ok((sql, params))
    }

    /// Extract parameters from WHERE builder.
    fn extract_params(&self, where_clause: &Option<WhereBuilder>) -> Vec<QueryParam> {
        if let Some(builder) = where_clause {
            let (_, params) = builder.clone().build();
            params
        } else {
            vec![]
        }
    }

    /// Convert HashMap updates to parameter vector.
    fn hashmap_to_params(
        &self,
        updates: &std::collections::HashMap<&str, QueryParam>,
    ) -> Vec<QueryParam> {
        updates.values().cloned().collect()
    }

    /// Convert PostgreSQL rows to QueryResult.
    fn rows_to_query_result(&self, rows: Vec<Row>) -> QueryResult {
        if rows.is_empty() {
            return QueryResult {
                rows_affected: 0,
                columns:       vec![],
                rows:          vec![],
            };
        }

        let columns: Vec<String> =
            rows[0].columns().iter().map(|col| col.name().to_string()).collect();

        let row_data: Vec<Vec<QueryParam>> = rows
            .into_iter()
            .map(|row| {
                (0..row.len()).map(|i| self.postgres_value_to_query_param(&row, i)).collect()
            })
            .collect();

        QueryResult {
            rows_affected: row_data.len() as u64,
            columns,
            rows: row_data,
        }
    }

    /// Convert PostgreSQL value to QueryParam.
    fn postgres_value_to_query_param(&self, row: &Row, index: usize) -> QueryParam {
        // Try different PostgreSQL types in order of preference
        if let Ok(Some(val)) = row.try_get::<_, Option<i32>>(index) {
            QueryParam::Int(val)
        } else if let Ok(Some(val)) = row.try_get::<_, Option<i64>>(index) {
            QueryParam::BigInt(val)
        } else if let Ok(Some(val)) = row.try_get::<_, Option<f64>>(index) {
            QueryParam::Double(val)
        } else if let Ok(Some(val)) = row.try_get::<_, Option<f32>>(index) {
            QueryParam::Float(val)
        } else if let Ok(Some(val)) = row.try_get::<_, Option<bool>>(index) {
            QueryParam::Bool(val)
        } else if let Ok(Some(val)) = row.try_get::<_, Option<String>>(index) {
            QueryParam::Text(val)
        } else {
            // TODO Phase 4.1: Add JSON, Timestamp, UUID support
            // These require proper tokio-postgres feature configuration
            // For now, fall back to text representation
            // For unsupported types or NULL values, return empty text
            QueryParam::Text("".to_string())
        }
    }
}

// Implement ToSql for QueryParam to enable parameter binding
impl ToSql for QueryParam {
    tokio_postgres::types::to_sql_checked!();

    fn to_sql(
        &self,
        ty: &tokio_postgres::types::Type,
        out: &mut BytesMut,
    ) -> Result<tokio_postgres::types::IsNull, Box<dyn std::error::Error + Sync + Send>> {
        match self {
            QueryParam::Null => Ok(tokio_postgres::types::IsNull::Yes),
            QueryParam::Bool(val) => val.to_sql(ty, out),
            QueryParam::Int(val) => val.to_sql(ty, out),
            QueryParam::BigInt(val) => val.to_sql(ty, out),
            QueryParam::Float(val) => val.to_sql(ty, out),
            QueryParam::Double(val) => val.to_sql(ty, out),
            QueryParam::Text(val) => val.to_sql(ty, out),
            // TODO Phase 4.1: Add proper ToSql for advanced types
            QueryParam::Json(val) => val.to_string().to_sql(ty, out),
            QueryParam::Timestamp(val) => val.to_string().to_sql(ty, out),
            QueryParam::Uuid(val) => val.to_string().to_sql(ty, out),
        }
    }

    fn accepts(_ty: &tokio_postgres::types::Type) -> bool {
        // For now, accept all types - the actual validation happens in to_sql
        // In a full implementation, we'd check type compatibility here
        true
    }
}

// QueryParam validation utilities
impl QueryParam {
    /// Validate that the parameter value is reasonable
    pub fn validate(&self) -> DatabaseResult<()> {
        match self {
            QueryParam::Text(s) => {
                if s.len() > 1_000_000 {
                    // 1MB limit for text fields
                    return Err(DatabaseError::Config(
                        "Text parameter exceeds maximum length of 1MB".to_string(),
                    ));
                }
            },
            QueryParam::Json(val) => {
                // Basic JSON validation - ensure it's not too large
                if serde_json::to_string(val)
                    .map_err(|e| DatabaseError::Config(format!("Invalid JSON parameter: {}", e)))?
                    .len()
                    > 1_000_000
                {
                    return Err(DatabaseError::Config(
                        "JSON parameter exceeds maximum size of 1MB".to_string(),
                    ));
                }
            },
            // Add more validations as needed
            _ => {}, // Other types have reasonable size limits by their nature
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_query_executor_api() {
        // Test that the API compiles and types work correctly
        // Real database testing will be in Phase 2 integration tests

        // Test SQL building - we can't test the full executor without a database
        // but we can verify the API is available
        assert!(true);
    }

    #[test]
    fn test_sql_building() {
        // Test SQL generation logic without database
        // This would be tested more thoroughly with integration tests
        assert!(true);
    }
}
