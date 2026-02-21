//! WHERE clause builder for GraphQL query filtering.
//!
//! Migrates WHERE clause generation from Python to Rust for performance.

use crate::db::types::QueryParam;

/// Represents a WHERE clause filter condition.
#[derive(Debug, Clone)]
pub enum WhereCondition {
    /// Equality: field = value
    Eq(String, QueryParam),
    /// Inequality: field != value
    Ne(String, QueryParam),
    /// Greater than: field > value
    Gt(String, QueryParam),
    /// Greater than or equal: field >= value
    Gte(String, QueryParam),
    /// Less than: field < value
    Lt(String, QueryParam),
    /// Less than or equal: field <= value
    Lte(String, QueryParam),
    /// IN clause: field IN (value1, value2, ...)
    In(String, Vec<QueryParam>),
    /// LIKE pattern matching: field LIKE pattern
    Like(String, String),
    /// IS NULL check: field IS NULL
    IsNull(String),
    /// IS NOT NULL check: field IS NOT NULL
    IsNotNull(String),
    /// AND combination: condition1 AND condition2
    And(Box<WhereCondition>, Box<WhereCondition>),
    /// OR combination: condition1 OR condition2
    Or(Box<WhereCondition>, Box<WhereCondition>),
    /// NOT negation: NOT condition
    Not(Box<WhereCondition>),
}

/// WHERE clause builder for constructing SQL WHERE statements.
#[derive(Debug, Default, Clone)]
pub struct WhereBuilder {
    conditions:  Vec<WhereCondition>,
    params:      Vec<QueryParam>,
    param_index: usize,
}

impl WhereBuilder {
    /// Create a new WHERE clause builder.
    pub fn new() -> Self {
        WhereBuilder {
            conditions:  Vec::new(),
            params:      Vec::new(),
            param_index: 1, // PostgreSQL parameters start at $1
        }
    }

    /// Add an equality condition.
    pub fn eq<T: Into<QueryParam>>(mut self, field: &str, value: T) -> Self {
        let param = value.into();
        self.conditions.push(WhereCondition::Eq(field.to_string(), param.clone()));
        self.params.push(param);
        self
    }

    /// Add an inequality condition.
    pub fn ne<T: Into<QueryParam>>(mut self, field: &str, value: T) -> Self {
        let param = value.into();
        self.conditions.push(WhereCondition::Ne(field.to_string(), param.clone()));
        self.params.push(param);
        self
    }

    /// Add a greater than condition.
    pub fn gt<T: Into<QueryParam>>(mut self, field: &str, value: T) -> Self {
        let param = value.into();
        self.conditions.push(WhereCondition::Gt(field.to_string(), param.clone()));
        self.params.push(param);
        self
    }

    /// Add a greater than or equal condition.
    pub fn gte<T: Into<QueryParam>>(mut self, field: &str, value: T) -> Self {
        let param = value.into();
        self.conditions.push(WhereCondition::Gte(field.to_string(), param.clone()));
        self.params.push(param);
        self
    }

    /// Add a less than condition.
    pub fn lt<T: Into<QueryParam>>(mut self, field: &str, value: T) -> Self {
        let param = value.into();
        self.conditions.push(WhereCondition::Lt(field.to_string(), param.clone()));
        self.params.push(param);
        self
    }

    /// Add a less than or equal condition.
    pub fn lte<T: Into<QueryParam>>(mut self, field: &str, value: T) -> Self {
        let param = value.into();
        self.conditions.push(WhereCondition::Lte(field.to_string(), param.clone()));
        self.params.push(param);
        self
    }

    /// Add an IN condition.
    pub fn in_list<T: Into<QueryParam>>(mut self, field: &str, values: Vec<T>) -> Self {
        let params: Vec<QueryParam> = values.into_iter().map(|v| v.into()).collect();
        self.conditions.push(WhereCondition::In(field.to_string(), params.clone()));
        self.params.extend(params);
        self
    }

    /// Add a LIKE condition.
    pub fn like(mut self, field: &str, pattern: &str) -> Self {
        self.conditions
            .push(WhereCondition::Like(field.to_string(), pattern.to_string()));
        self.params.push(QueryParam::Text(pattern.to_string()));
        self
    }

    /// Add an IS NULL condition.
    pub fn is_null(mut self, field: &str) -> Self {
        self.conditions.push(WhereCondition::IsNull(field.to_string()));
        self
    }

    /// Add an IS NOT NULL condition.
    pub fn is_not_null(mut self, field: &str) -> Self {
        self.conditions.push(WhereCondition::IsNotNull(field.to_string()));
        self
    }

    /// Combine with AND.
    pub fn and(mut self, other: WhereBuilder) -> Self {
        if let (Some(left), Some(right)) =
            (self.conditions.pop(), other.conditions.first().cloned())
        {
            self.conditions.push(WhereCondition::And(Box::new(left), Box::new(right)));
        }
        self.params.extend(other.params);
        self
    }

    /// Combine with OR.
    pub fn or(mut self, other: WhereBuilder) -> Self {
        if let (Some(left), Some(right)) =
            (self.conditions.pop(), other.conditions.first().cloned())
        {
            self.conditions.push(WhereCondition::Or(Box::new(left), Box::new(right)));
        }
        self.params.extend(other.params);
        self
    }

    /// Build the WHERE clause SQL and return parameters.
    pub fn build(self) -> (String, Vec<QueryParam>) {
        if self.conditions.is_empty() {
            return ("".to_string(), vec![]);
        }

        let mut sql_parts = Vec::new();
        for condition in &self.conditions {
            sql_parts.push(self.build_condition_sql(condition));
        }

        let sql = if sql_parts.len() == 1 {
            format!("WHERE {}", sql_parts[0])
        } else {
            format!("WHERE {}", sql_parts.join(" AND "))
        };

        (sql, self.params)
    }

    /// Build SQL for a single condition.
    fn build_condition_sql(&self, condition: &WhereCondition) -> String {
        match condition {
            WhereCondition::Eq(field, _) => format!("{} = ${}", field, self.param_index),
            WhereCondition::Ne(field, _) => format!("{} != ${}", field, self.param_index),
            WhereCondition::Gt(field, _) => format!("{} > ${}", field, self.param_index),
            WhereCondition::Gte(field, _) => format!("{} >= ${}", field, self.param_index),
            WhereCondition::Lt(field, _) => format!("{} < ${}", field, self.param_index),
            WhereCondition::Lte(field, _) => format!("{} <= ${}", field, self.param_index),
            WhereCondition::In(field, values) => {
                let placeholders: Vec<String> =
                    (0..values.len()).map(|_| format!("${}", self.param_index)).collect();
                format!("{} IN ({})", field, placeholders.join(", "))
            },
            WhereCondition::Like(field, _) => format!("{} LIKE ${}", field, self.param_index),
            WhereCondition::IsNull(field) => format!("{} IS NULL", field),
            WhereCondition::IsNotNull(field) => format!("{} IS NOT NULL", field),
            WhereCondition::And(left, right) => format!(
                "({}) AND ({})",
                self.build_condition_sql(left),
                self.build_condition_sql(right)
            ),
            WhereCondition::Or(left, right) => format!(
                "({}) OR ({})",
                self.build_condition_sql(left),
                self.build_condition_sql(right)
            ),
            WhereCondition::Not(cond) => format!("NOT ({})", self.build_condition_sql(cond)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_where_builder_eq() {
        let (sql, params) = WhereBuilder::new().eq("id", 42).build();

        assert_eq!(sql, "WHERE id = $1");
        assert_eq!(params.len(), 1);
        match &params[0] {
            QueryParam::Int(val) => assert_eq!(*val, 42),
            _ => panic!("Expected Int parameter"),
        }
    }

    #[test]
    fn test_where_builder_multiple_conditions() {
        let (sql, params) = WhereBuilder::new()
            .eq("status", "active")
            .gt("created_at", "2023-01-01")
            .build();

        assert_eq!(sql, "WHERE status = $1 AND created_at > $2");
        assert_eq!(params.len(), 2);
    }

    #[test]
    fn test_where_builder_in_clause() {
        let (sql, params) = WhereBuilder::new().in_list("category_id", vec![1, 2, 3]).build();

        assert_eq!(sql, "WHERE category_id IN ($1, $2, $3)");
        assert_eq!(params.len(), 3);
    }

    #[test]
    fn test_where_builder_empty() {
        let (sql, params) = WhereBuilder::new().build();
        assert_eq!(sql, "");
        assert_eq!(params.len(), 0);
    }
}
