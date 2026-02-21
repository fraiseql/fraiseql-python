//! Mutation execution module (INSERT, UPDATE, DELETE)

use serde_json::Value;
use tokio_postgres::Client;

use crate::db::types::{DatabaseError, QueryParam};

pub enum MutationType {
    Insert,
    Update,
    Delete,
}

impl MutationType {
    pub fn parse(s: &str) -> Result<Self, DatabaseError> {
        match s {
            "insert" => Ok(MutationType::Insert),
            "update" => Ok(MutationType::Update),
            "delete" => Ok(MutationType::Delete),
            _ => Err(DatabaseError::Query(format!("Unknown mutation type: {}", s))),
        }
    }
}

pub async fn execute_mutation(
    client: &mut Client,
    mutation_type: MutationType,
    table: &str,
    input: Option<&Value>,
    filters: Option<&Value>,
    return_fields: Option<&Vec<String>>,
) -> Result<Value, DatabaseError> {
    match mutation_type {
        MutationType::Insert => insert_record(client, table, input, return_fields).await,
        MutationType::Update => update_record(client, table, input, filters, return_fields).await,
        MutationType::Delete => delete_record(client, table, filters).await,
    }
}

async fn insert_record(
    client: &mut Client,
    table: &str,
    input: Option<&Value>,
    return_fields: Option<&Vec<String>>,
) -> Result<Value, DatabaseError> {
    let input =
        input.ok_or_else(|| DatabaseError::Query("Input required for INSERT".to_string()))?;

    let (sql, params) = build_insert_sql(table, input)?;

    let sql_params: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> =
        params.iter().map(|p| p as &(dyn tokio_postgres::types::ToSql + Sync)).collect();
    let rows = client
        .execute(&sql, &sql_params)
        .await
        .map_err(|e| DatabaseError::Query(format!("INSERT failed: {}", e)))?;

    // If return_fields specified, query the inserted record
    if let Some(fields) = return_fields {
        // For simplicity, return the input data transformed
        // In a full implementation, we'd query the inserted record
        let mut result = serde_json::Map::new();
        if let Value::Object(obj) = input {
            for field in fields {
                if let Some(value) = obj.get(field) {
                    result.insert(field.clone(), value.clone());
                }
            }
        }
        Ok(Value::Object(result))
    } else {
        Ok(Value::Object(
            serde_json::json!({
                "affected_rows": rows
            })
            .as_object()
            .unwrap()
            .clone(),
        ))
    }
}

async fn update_record(
    client: &mut Client,
    table: &str,
    input: Option<&Value>,
    filters: Option<&Value>,
    return_fields: Option<&Vec<String>>,
) -> Result<Value, DatabaseError> {
    let input =
        input.ok_or_else(|| DatabaseError::Query("Input required for UPDATE".to_string()))?;

    let (sql, params) = build_update_sql(table, input, filters)?;

    let sql_params: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> =
        params.iter().map(|p| p as &(dyn tokio_postgres::types::ToSql + Sync)).collect();
    let rows = client
        .execute(&sql, &sql_params)
        .await
        .map_err(|e| DatabaseError::Query(format!("UPDATE failed: {}", e)))?;

    // If return_fields specified, query the updated records
    if let Some(_fields) = return_fields {
        // For simplicity, return affected row count
        // In a full implementation, we'd use RETURNING clause
        Ok(Value::Object(
            serde_json::json!({
                "affected_rows": rows
            })
            .as_object()
            .unwrap()
            .clone(),
        ))
    } else {
        Ok(Value::Object(
            serde_json::json!({
                "affected_rows": rows
            })
            .as_object()
            .unwrap()
            .clone(),
        ))
    }
}

async fn delete_record(
    client: &mut Client,
    table: &str,
    filters: Option<&Value>,
) -> Result<Value, DatabaseError> {
    let (sql, params) = build_delete_sql_with_params(table, filters)?;

    let sql_params: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> =
        params.iter().map(|p| p as &(dyn tokio_postgres::types::ToSql + Sync)).collect();
    let rows = client
        .execute(&sql, &sql_params)
        .await
        .map_err(|e| DatabaseError::Query(format!("DELETE failed: {}", e)))?;

    Ok(Value::Object(
        serde_json::json!({
            "affected_rows": rows,
            "success": true
        })
        .as_object()
        .unwrap()
        .clone(),
    ))
}

fn build_insert_sql(
    table: &str,
    input: &Value,
) -> Result<(String, Vec<QueryParam>), DatabaseError> {
    let mut columns = Vec::new();
    let mut values = Vec::new();
    let mut params = Vec::new();

    if let Value::Object(obj) = input {
        for (key, value) in obj {
            columns.push(key.clone());
            values.push(format!("${}", params.len() + 1));
            params.push(value_to_query_param(value));
        }
    }

    let columns_str = columns.join(", ");
    let values_str = values.join(", ");
    let sql = format!("INSERT INTO {} ({}) VALUES ({})", table, columns_str, values_str);

    Ok((sql, params))
}

fn build_update_sql(
    table: &str,
    input: &Value,
    filters: Option<&Value>,
) -> Result<(String, Vec<QueryParam>), DatabaseError> {
    let mut sets = Vec::new();
    let mut params = Vec::new();
    let mut param_index = 1;

    if let Value::Object(obj) = input {
        for (key, value) in obj {
            sets.push(format!("{} = ${}", key, param_index));
            params.push(value_to_query_param(value));
            param_index += 1;
        }
    }

    let sets_str = sets.join(", ");
    let mut sql = format!("UPDATE {} SET {}", table, sets_str);

    // Add WHERE clause if filters provided
    if let Some(where_clause) = build_where_clause(filters, param_index) {
        sql.push_str(&where_clause.0);
        params.extend(where_clause.1);
    }

    Ok((sql, params))
}

fn build_delete_sql_with_params(
    table: &str,
    filters: Option<&Value>,
) -> Result<(String, Vec<QueryParam>), DatabaseError> {
    let mut sql = format!("DELETE FROM {}", table);
    let mut params = Vec::new();

    // Add WHERE clause if filters provided
    if let Some(where_clause) = build_where_clause(filters, params.len() + 1) {
        sql.push_str(&where_clause.0);
        params.extend(where_clause.1);
    }

    Ok((sql, params))
}

fn build_where_clause(
    filters: Option<&Value>,
    param_index: usize,
) -> Option<(String, Vec<QueryParam>)> {
    let filter_obj = filters?;
    let Value::Object(filter_map) = filter_obj else {
        return None;
    };

    let field = filter_map.get("field")?;
    let operator = filter_map.get("operator")?;
    let value = filter_map.get("value")?;

    let (Value::String(field_str), Value::String(op_str)) = (field, operator) else {
        return None;
    };

    let op = match op_str.as_str() {
        "eq" => "=",
        "ne" => "!=",
        "gt" => ">",
        "gte" => ">=",
        "lt" => "<",
        "lte" => "<=",
        "like" => "LIKE",
        _ => "=",
    };

    let sql = format!(" WHERE {} {} ${}", field_str, op, param_index);
    let params = vec![value_to_query_param(value)];

    Some((sql, params))
}

fn value_to_query_param(value: &Value) -> QueryParam {
    match value {
        Value::Null => QueryParam::Null,
        Value::Bool(b) => QueryParam::Bool(*b),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                QueryParam::BigInt(i)
            } else if let Some(f) = n.as_f64() {
                QueryParam::Double(f)
            } else {
                QueryParam::Text(n.to_string())
            }
        },
        Value::String(s) => QueryParam::Text(s.clone()),
        Value::Array(_) => QueryParam::Text(value.to_string()), // JSON array
        Value::Object(_) => QueryParam::Text(value.to_string()), // JSON object
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn test_mutation_type_parse() {
        assert!(matches!(MutationType::parse("insert").unwrap(), MutationType::Insert));
        assert!(matches!(MutationType::parse("update").unwrap(), MutationType::Update));
        assert!(matches!(MutationType::parse("delete").unwrap(), MutationType::Delete));
        assert!(MutationType::parse("invalid").is_err());
    }

    #[test]
    fn test_value_to_query_param() {
        assert!(matches!(value_to_query_param(&json!(null)), QueryParam::Null));
        assert!(matches!(value_to_query_param(&json!(true)), QueryParam::Bool(true)));
        assert!(matches!(value_to_query_param(&json!(42)), QueryParam::BigInt(42)));
        assert!(matches!(value_to_query_param(&json!(3.14)), QueryParam::Double(3.14)));
        assert!(
            matches!(value_to_query_param(&json!("hello")), QueryParam::Text(s) if s == "hello")
        );
    }
}
