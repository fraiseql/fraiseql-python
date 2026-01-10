//! Prepared statement builder for SQL injection prevention.
//!
//! This module provides safe SQL generation using parameter placeholders
//! instead of string concatenation, preventing SQL injection attacks.

use serde_json::Value as JsonValue;

/// A prepared SQL statement with parameter placeholders.
///
/// This struct accumulates SQL fragments and parameters separately,
/// generating placeholders ($1, $2, etc.) to prevent SQL injection.
///
/// # Example
///
/// ```
/// use fraiseql_rs::query::prepared_statement::PreparedStatement;
/// use serde_json::json;
///
/// let mut stmt = PreparedStatement::new();
/// let sql = stmt.build_comparison("user_id", "=", json!(123));
/// assert_eq!(sql, "user_id = $1");
/// assert_eq!(stmt.params.len(), 1);
/// ```
#[derive(Debug, Clone)]
pub struct PreparedStatement {
    /// The accumulated SQL string (with placeholders)
    pub sql: String,
    /// The parameters to bind to the placeholders
    pub params: Vec<JsonValue>,
}

impl PreparedStatement {
    /// Create a new empty prepared statement.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            sql: String::new(),
            params: Vec::new(),
        }
    }

    /// Add a parameter and return its placeholder ($1, $2, etc.).
    ///
    /// # Example
    ///
    /// ```
    /// use fraiseql_rs::query::prepared_statement::PreparedStatement;
    /// use serde_json::json;
    ///
    /// let mut stmt = PreparedStatement::new();
    /// let p1 = stmt.add_param(json!("value1"));
    /// let p2 = stmt.add_param(json!(42));
    ///
    /// assert_eq!(p1, "$1");
    /// assert_eq!(p2, "$2");
    /// assert_eq!(stmt.params.len(), 2);
    /// ```
    pub fn add_param(&mut self, value: JsonValue) -> String {
        self.params.push(value);
        format!("${}", self.params.len())
    }

    /// Build a simple comparison expression (column op value).
    ///
    /// # Example
    ///
    /// ```
    /// use fraiseql_rs::query::prepared_statement::PreparedStatement;
    /// use serde_json::json;
    ///
    /// let mut stmt = PreparedStatement::new();
    /// let sql = stmt.build_comparison("status", "=", json!("active"));
    /// assert_eq!(sql, "status = $1");
    /// ```
    pub fn build_comparison(&mut self, column: &str, operator: &str, value: JsonValue) -> String {
        let placeholder = self.add_param(value);
        format!("{column} {operator} {placeholder}")
    }

    /// Build an IN clause (column IN ($1, $2, ...)).
    ///
    /// # Example
    ///
    /// ```
    /// use fraiseql_rs::query::prepared_statement::PreparedStatement;
    /// use serde_json::json;
    ///
    /// let mut stmt = PreparedStatement::new();
    /// let values = vec![json!(1), json!(2), json!(3)];
    /// let sql = stmt.build_in_clause("id", "IN", &values);
    /// assert_eq!(sql, "id IN ($1, $2, $3)");
    /// assert_eq!(stmt.params.len(), 3);
    /// ```
    pub fn build_in_clause(
        &mut self,
        column: &str,
        operator: &str,
        values: &[JsonValue],
    ) -> String {
        let placeholders: Vec<String> = values.iter().map(|v| self.add_param(v.clone())).collect();
        format!("{} {} ({})", column, operator, placeholders.join(", "))
    }

    /// Build a NULL check expression (column IS NULL or IS NOT NULL).
    ///
    /// # Example
    ///
    /// ```
    /// use fraiseql_rs::query::prepared_statement::PreparedStatement;
    ///
    /// let mut stmt = PreparedStatement::new();
    /// let sql = stmt.build_null_check("deleted_at", "IS NULL");
    /// assert_eq!(sql, "deleted_at IS NULL");
    /// assert_eq!(stmt.params.len(), 0); // NULL checks don't use parameters
    /// ```
    pub fn build_null_check(&mut self, column: &str, operator: &str) -> String {
        format!("{column} {operator}")
    }

    /// Build a LIKE pattern expression with proper escaping.
    ///
    /// # Example
    ///
    /// ```
    /// use fraiseql_rs::query::prepared_statement::PreparedStatement;
    /// use serde_json::json;
    ///
    /// let mut stmt = PreparedStatement::new();
    /// let sql = stmt.build_like("name", "LIKE", json!("%john%"));
    /// assert_eq!(sql, "name LIKE $1");
    /// ```
    pub fn build_like(&mut self, column: &str, operator: &str, pattern: JsonValue) -> String {
        let placeholder = self.add_param(pattern);
        format!("{column} {operator} {placeholder}")
    }

    /// Build a JSONB path expression (data->'path'->>'key').
    ///
    /// # Example
    ///
    /// ```
    /// use fraiseql_rs::query::prepared_statement::PreparedStatement;
    /// use serde_json::json;
    ///
    /// let mut stmt = PreparedStatement::new();
    /// let path = vec!["device", "sensor", "value"];
    /// let column_expr = stmt.build_jsonb_path("data", &path, true);
    /// // Returns: data->'device'->'sensor'->>'value'
    /// ```
    pub fn build_jsonb_path(
        &mut self,
        jsonb_column: &str,
        path: &[&str],
        text_output: bool,
    ) -> String {
        if path.is_empty() {
            return jsonb_column.to_string();
        }

        let mut result = jsonb_column.to_string();

        // All but last segment use -> (JSON output)
        for segment in &path[..path.len().saturating_sub(1)] {
            result.push_str("->'");
            result.push_str(segment);
            result.push('\'');
        }

        // Last segment uses ->> (text output) if text_output is true
        if let Some(last) = path.last() {
            result.push_str(if text_output { "->>'" } else { "->'" });
            result.push_str(last);
            result.push('\'');
        }

        result
    }

    /// Build a JSONB operator expression (data @> $1, data ? $1, etc.).
    ///
    /// # Example
    ///
    /// ```
    /// use fraiseql_rs::query::prepared_statement::PreparedStatement;
    /// use serde_json::json;
    ///
    /// let mut stmt = PreparedStatement::new();
    /// let sql = stmt.build_jsonb_operator("data", "@>", json!({"status": "active"}));
    /// assert_eq!(sql, "data @> $1");
    /// ```
    pub fn build_jsonb_operator(
        &mut self,
        column: &str,
        operator: &str,
        value: JsonValue,
    ) -> String {
        let placeholder = self.add_param(value);
        format!("{column} {operator} {placeholder}")
    }

    /// Build a vector distance expression (embedding <=> $1).
    ///
    /// # Example
    ///
    /// ```
    /// use fraiseql_rs::query::prepared_statement::PreparedStatement;
    /// use serde_json::json;
    ///
    /// let mut stmt = PreparedStatement::new();
    /// let vector = json!([0.1, 0.2, 0.3]);
    /// let sql = stmt.build_vector_distance("embedding", "<=>", vector);
    /// assert_eq!(sql, "embedding <=> $1");
    /// ```
    pub fn build_vector_distance(
        &mut self,
        column: &str,
        operator: &str,
        vector: JsonValue,
    ) -> String {
        let placeholder = self.add_param(vector);
        format!("{column} {operator} {placeholder}")
    }

    /// Build a full-text search expression (tsvector @@ `query_func($1)`).
    ///
    /// # Example
    ///
    /// ```
    /// use fraiseql_rs::query::prepared_statement::PreparedStatement;
    /// use serde_json::json;
    ///
    /// let mut stmt = PreparedStatement::new();
    /// let sql = stmt.build_fulltext_search(
    ///     "search_vector",
    ///     "plainto_tsquery",
    ///     json!("search term")
    /// );
    /// assert_eq!(sql, "search_vector @@ plainto_tsquery($1)");
    /// ```
    pub fn build_fulltext_search(
        &mut self,
        column: &str,
        query_func: &str,
        search_term: JsonValue,
    ) -> String {
        let placeholder = self.add_param(search_term);
        format!("{column} @@ {query_func}({placeholder})")
    }

    /// Build an array operator expression (tags @> $1, tags && $1, etc.).
    ///
    /// # Example
    ///
    /// ```
    /// use fraiseql_rs::query::prepared_statement::PreparedStatement;
    /// use serde_json::json;
    ///
    /// let mut stmt = PreparedStatement::new();
    /// let sql = stmt.build_array_operator("tags", "@>", json!(["urgent"]));
    /// assert_eq!(sql, "tags @> $1");
    /// ```
    pub fn build_array_operator(
        &mut self,
        column: &str,
        operator: &str,
        value: JsonValue,
    ) -> String {
        let placeholder = self.add_param(value);
        format!("{column} {operator} {placeholder}")
    }

    /// Clear the statement (for reuse).
    pub fn clear(&mut self) {
        self.sql.clear();
        self.params.clear();
    }

    /// Get the number of parameters.
    #[must_use]
    pub const fn param_count(&self) -> usize {
        self.params.len()
    }

    /// Check if the statement is empty.
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.sql.is_empty() && self.params.is_empty()
    }
}

impl Default for PreparedStatement {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_new_statement() {
        let stmt = PreparedStatement::new();
        assert!(stmt.params.is_empty());
        assert!(stmt.sql.is_empty());
    }

    #[test]
    fn test_add_param() {
        let mut stmt = PreparedStatement::new();
        let p1 = stmt.add_param(json!("value1"));
        let p2 = stmt.add_param(json!(42));
        let p3 = stmt.add_param(json!(true));

        assert_eq!(p1, "$1");
        assert_eq!(p2, "$2");
        assert_eq!(p3, "$3");
        assert_eq!(stmt.params.len(), 3);
    }

    #[test]
    fn test_build_comparison() {
        let mut stmt = PreparedStatement::new();
        let sql = stmt.build_comparison("user_id", "=", json!(123));
        assert_eq!(sql, "user_id = $1");
        assert_eq!(stmt.params[0], json!(123));
    }

    #[test]
    fn test_build_in_clause() {
        let mut stmt = PreparedStatement::new();
        let values = vec![json!(1), json!(2), json!(3)];
        let sql = stmt.build_in_clause("id", "IN", &values);
        assert_eq!(sql, "id IN ($1, $2, $3)");
        assert_eq!(stmt.params.len(), 3);
    }

    #[test]
    fn test_build_in_clause_not_in() {
        let mut stmt = PreparedStatement::new();
        let values = vec![json!("draft"), json!("deleted")];
        let sql = stmt.build_in_clause("status", "NOT IN", &values);
        assert_eq!(sql, "status NOT IN ($1, $2)");
    }

    #[test]
    fn test_build_null_check() {
        let mut stmt = PreparedStatement::new();
        let sql1 = stmt.build_null_check("deleted_at", "IS NULL");
        let sql2 = stmt.build_null_check("active_until", "IS NOT NULL");

        assert_eq!(sql1, "deleted_at IS NULL");
        assert_eq!(sql2, "active_until IS NOT NULL");
        assert_eq!(stmt.params.len(), 0); // NULL checks don't use params
    }

    #[test]
    fn test_build_like() {
        let mut stmt = PreparedStatement::new();
        let sql = stmt.build_like("name", "LIKE", json!("%john%"));
        assert_eq!(sql, "name LIKE $1");
        assert_eq!(stmt.params[0], json!("%john%"));
    }

    #[test]
    fn test_build_jsonb_path_single() {
        let mut stmt = PreparedStatement::new();
        let path = vec!["status"];
        let column = stmt.build_jsonb_path("data", &path, true);
        assert_eq!(column, "data->>'status'");
    }

    #[test]
    fn test_build_jsonb_path_nested() {
        let mut stmt = PreparedStatement::new();
        let path = vec!["device", "sensor", "value"];
        let column = stmt.build_jsonb_path("data", &path, true);
        assert_eq!(column, "data->'device'->'sensor'->>'value'");
    }

    #[test]
    fn test_build_jsonb_path_json_output() {
        let mut stmt = PreparedStatement::new();
        let path = vec!["device", "config"];
        let column = stmt.build_jsonb_path("data", &path, false);
        assert_eq!(column, "data->'device'->'config'");
    }

    #[test]
    fn test_build_jsonb_operator() {
        let mut stmt = PreparedStatement::new();
        let sql = stmt.build_jsonb_operator("data", "@>", json!({"status": "active"}));
        assert_eq!(sql, "data @> $1");
    }

    #[test]
    fn test_build_vector_distance() {
        let mut stmt = PreparedStatement::new();
        let vector = json!([0.1, 0.2, 0.3]);
        let sql = stmt.build_vector_distance("embedding", "<=>", vector);
        assert_eq!(sql, "embedding <=> $1");
    }

    #[test]
    fn test_build_fulltext_search() {
        let mut stmt = PreparedStatement::new();
        let sql = stmt.build_fulltext_search("search_vector", "plainto_tsquery", json!("test"));
        assert_eq!(sql, "search_vector @@ plainto_tsquery($1)");
    }

    #[test]
    fn test_build_array_operator() {
        let mut stmt = PreparedStatement::new();
        let sql = stmt.build_array_operator("tags", "@>", json!(["urgent"]));
        assert_eq!(sql, "tags @> $1");
    }

    #[test]
    fn test_clear() {
        let mut stmt = PreparedStatement::new();
        stmt.add_param(json!(1));
        stmt.add_param(json!(2));
        stmt.sql = "test".to_string();

        stmt.clear();
        assert!(stmt.params.is_empty());
        assert!(stmt.sql.is_empty());
    }

    #[test]
    fn test_param_count() {
        let mut stmt = PreparedStatement::new();
        assert_eq!(stmt.param_count(), 0);

        stmt.add_param(json!(1));
        assert_eq!(stmt.param_count(), 1);

        stmt.add_param(json!(2));
        assert_eq!(stmt.param_count(), 2);
    }

    #[test]
    fn test_is_empty() {
        let mut stmt = PreparedStatement::new();
        assert!(stmt.is_empty());

        stmt.add_param(json!(1));
        assert!(!stmt.is_empty());

        stmt.clear();
        assert!(stmt.is_empty());
    }

    #[test]
    fn test_sequential_operations() {
        let mut stmt = PreparedStatement::new();

        // Add multiple conditions
        let sql1 = stmt.build_comparison("status", "=", json!("active"));
        let sql2 = stmt.build_comparison("age", ">", json!(18));
        let values = vec![json!("admin"), json!("user")];
        let sql3 = stmt.build_in_clause("role", "IN", &values);

        // Check that placeholders increment correctly
        assert_eq!(sql1, "status = $1");
        assert_eq!(sql2, "age > $2");
        assert_eq!(sql3, "role IN ($3, $4)");
        assert_eq!(stmt.params.len(), 4);
    }

    #[test]
    fn test_special_characters_in_values() {
        let mut stmt = PreparedStatement::new();

        // SQL injection attempt - should be safely parameterized
        let sql = stmt.build_comparison("name", "=", json!("'; DROP TABLE users; --"));
        assert_eq!(sql, "name = $1");
        assert_eq!(stmt.params[0], json!("'; DROP TABLE users; --"));

        // The parameter will be safely escaped by PostgreSQL's parameter binding
    }
}
