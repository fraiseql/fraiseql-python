//! WHERE clause building logic.

use anyhow::{Result, anyhow};
use serde_json::Value as JsonValue;

use crate::{graphql::types::GraphQLArgument, query::schema::SchemaMetadata};

pub struct WhereClauseBuilder {
    schema:        SchemaMetadata,
    view_name:     String,
    params:        Vec<(String, ParameterValue)>,
    param_counter: usize,
}

#[derive(Debug, Clone)]
pub enum ParameterValue {
    String(String),
    Integer(i64),
    Float(f64),
    Boolean(bool),
    JsonObject(String),
    Array(Vec<ParameterValue>),
}

impl WhereClauseBuilder {
    pub fn new(schema: SchemaMetadata, view_name: String) -> Self {
        Self {
            schema,
            view_name,
            params: Vec::new(),
            param_counter: 0,
        }
    }

    /// Build WHERE clause from arguments.
    pub fn build_where(&mut self, where_arg: &GraphQLArgument) -> Result<String> {
        // Parse WHERE argument as JSON
        let where_json: JsonValue = serde_json::from_str(&where_arg.value_json)
            .map_err(|e| anyhow!("Invalid WHERE argument JSON: {}", e))?;

        // Build WHERE clause recursively
        self.build_where_recursive(&where_json)
    }

    /// Build WHERE clause recursively (handles nested AND/OR/NOT).
    fn build_where_recursive(&mut self, where_obj: &JsonValue) -> Result<String> {
        match where_obj {
            JsonValue::Object(map) => {
                // Handle logical operators
                if let Some(and_value) = map.get("AND") {
                    return self.build_and_clause(and_value);
                }
                if let Some(or_value) = map.get("OR") {
                    return self.build_or_clause(or_value);
                }
                if let Some(not_value) = map.get("NOT") {
                    return self.build_not_clause(not_value);
                }

                // Handle field conditions
                let conditions: Vec<String> = map
                    .iter()
                    .map(|(field_name, field_value)| {
                        self.build_field_condition(field_name, field_value)
                    })
                    .collect::<Result<Vec<_>>>()?;

                Ok(conditions.join(" AND "))
            },
            _ => Err(anyhow!("WHERE clause must be an object")),
        }
    }

    /// Build condition for a single field.
    fn build_field_condition(
        &mut self,
        field_name: &str,
        condition_value: &JsonValue,
    ) -> Result<String> {
        // Determine if field is SQL column, FK, or JSONB
        let column_expr = if self.schema.is_sql_column(&self.view_name, field_name) {
            // Direct SQL column
            format!("t.{}", field_name)
        } else if let Some(fk_col) = self.schema.get_fk_column(&self.view_name, field_name) {
            // Foreign key column
            format!("t.{}", fk_col)
        } else {
            // JSONB field
            let table = self
                .schema
                .get_table(&self.view_name)
                .ok_or_else(|| anyhow!("Table not found: {}", self.view_name))?;
            format!("t.{}->>'{}'", table.jsonb_column, field_name)
        };

        // Build condition SQL based on operator
        match condition_value {
            JsonValue::Object(ops) => {
                let op_conditions: Vec<String> = ops
                    .iter()
                    .map(|(op, val)| self.build_operator_sql(&column_expr, op, val))
                    .collect::<Result<Vec<_>>>()?;
                Ok(op_conditions.join(" AND "))
            },
            JsonValue::String(val) => {
                // Simple equality
                let param = self.next_param();
                self.params.push((param, ParameterValue::String(val.clone())));
                Ok(format!("{} = ${}", column_expr, self.param_counter))
            },
            _ => Err(anyhow!("Invalid field condition for {}", field_name)),
        }
    }

    /// Build SQL for comparison operator.
    fn build_operator_sql(
        &mut self,
        column_expr: &str,
        operator: &str,
        value: &JsonValue,
    ) -> Result<String> {
        match operator {
            "eq" => {
                let param = self.next_param();
                self.add_param(param, value)?;
                Ok(format!("{} = ${}", column_expr, self.param_counter))
            },
            "neq" | "ne" => {
                let param = self.next_param();
                self.add_param(param, value)?;
                Ok(format!("{} != ${}", column_expr, self.param_counter))
            },
            "gt" => {
                let param = self.next_param();
                self.add_param(param, value)?;
                Ok(format!("{} > ${}", column_expr, self.param_counter))
            },
            "gte" | "ge" => {
                let param = self.next_param();
                self.add_param(param, value)?;
                Ok(format!("{} >= ${}", column_expr, self.param_counter))
            },
            "lt" => {
                let param = self.next_param();
                self.add_param(param, value)?;
                Ok(format!("{} < ${}", column_expr, self.param_counter))
            },
            "lte" | "le" => {
                let param = self.next_param();
                self.add_param(param, value)?;
                Ok(format!("{} <= ${}", column_expr, self.param_counter))
            },
            "in" => {
                // Handle IN clause with array
                match value {
                    JsonValue::Array(items) => {
                        let placeholders: Vec<String> = items
                            .iter()
                            .map(|item| {
                                let param = self.next_param();
                                self.add_param(param, item)?;
                                Ok(format!("${}", self.param_counter))
                            })
                            .collect::<Result<Vec<_>>>()?;
                        Ok(format!("{} IN ({})", column_expr, placeholders.join(", ")))
                    },
                    _ => Err(anyhow!("IN operator requires array value")),
                }
            },
            "like" | "contains" => {
                let param = self.next_param();
                match value {
                    JsonValue::String(s) => {
                        let pattern = format!("%{}%", s);
                        self.params.push((param, ParameterValue::String(pattern)));
                        Ok(format!("{} LIKE ${}", column_expr, self.param_counter))
                    },
                    _ => Err(anyhow!("LIKE requires string value")),
                }
            },
            "startsWith" | "startswith" => {
                let param = self.next_param();
                match value {
                    JsonValue::String(s) => {
                        let pattern = format!("{}%", s);
                        self.params.push((param, ParameterValue::String(pattern)));
                        Ok(format!("{} LIKE ${}", column_expr, self.param_counter))
                    },
                    _ => Err(anyhow!("startsWith requires string value")),
                }
            },
            "endsWith" | "endswith" => {
                let param = self.next_param();
                match value {
                    JsonValue::String(s) => {
                        let pattern = format!("%{}", s);
                        self.params.push((param, ParameterValue::String(pattern)));
                        Ok(format!("{} LIKE ${}", column_expr, self.param_counter))
                    },
                    _ => Err(anyhow!("endsWith requires string value")),
                }
            },
            _ => Err(anyhow!("Unknown operator: {}", operator)),
        }
    }

    fn build_and_clause(&mut self, value: &JsonValue) -> Result<String> {
        match value {
            JsonValue::Array(items) => {
                let clauses: Vec<String> = items
                    .iter()
                    .map(|item| self.build_where_recursive(item))
                    .collect::<Result<Vec<_>>>()?;
                Ok(format!("({})", clauses.join(" AND ")))
            },
            _ => Err(anyhow!("AND must have array value")),
        }
    }

    fn build_or_clause(&mut self, value: &JsonValue) -> Result<String> {
        match value {
            JsonValue::Array(items) => {
                let clauses: Vec<String> = items
                    .iter()
                    .map(|item| self.build_where_recursive(item))
                    .collect::<Result<Vec<_>>>()?;
                Ok(format!("({})", clauses.join(" OR ")))
            },
            _ => Err(anyhow!("OR must have array value")),
        }
    }

    fn build_not_clause(&mut self, value: &JsonValue) -> Result<String> {
        let inner = self.build_where_recursive(value)?;
        Ok(format!("NOT ({})", inner))
    }

    fn next_param(&mut self) -> String {
        self.param_counter += 1;
        format!("param_{}", self.param_counter)
    }

    fn add_param(&mut self, name: String, value: &JsonValue) -> Result<()> {
        let param_value = match value {
            JsonValue::String(s) => ParameterValue::String(s.clone()),
            JsonValue::Number(n) => {
                if let Some(i) = n.as_i64() {
                    ParameterValue::Integer(i)
                } else if let Some(f) = n.as_f64() {
                    ParameterValue::Float(f)
                } else {
                    return Err(anyhow!("Invalid number"));
                }
            },
            JsonValue::Bool(b) => ParameterValue::Boolean(*b),
            JsonValue::Object(_) => ParameterValue::JsonObject(value.to_string()),
            _ => return Err(anyhow!("Unsupported parameter type")),
        };
        self.params.push((name, param_value));
        Ok(())
    }

    pub fn get_params(self) -> Vec<(String, ParameterValue)> {
        self.params
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_equality() {
        let schema = create_test_schema();
        let mut builder = WhereClauseBuilder::new(schema, "v_users".to_string());

        let arg = GraphQLArgument {
            name:       "where".to_string(),
            value_type: "object".to_string(),
            value_json: r#"{"status": "active"}"#.to_string(),
        };

        let sql = builder.build_where(&arg).unwrap();
        assert!(sql.contains("status"));
        assert!(sql.contains("="));
    }

    fn create_test_schema() -> SchemaMetadata {
        // Create minimal test schema
        let mut tables = std::collections::HashMap::new();
        tables.insert(
            "v_users".to_string(),
            crate::query::schema::TableSchema {
                view_name:      "v_users".to_string(),
                sql_columns:    vec!["id".to_string(), "email".to_string()],
                jsonb_column:   "data".to_string(),
                fk_mappings:    Default::default(),
                has_jsonb_data: true,
            },
        );

        SchemaMetadata {
            tables,
            types: Default::default(),
        }
    }
}
