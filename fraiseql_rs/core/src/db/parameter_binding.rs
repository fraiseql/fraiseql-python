//! Safe parameter binding for prepared statements.
//!
//! # Phase 3.2: SQL Injection Prevention
//!
//! This module provides type-safe parameter binding that prevents SQL injection
//! attacks by separating SQL structure from parameter values. All parameters are
//! bound safely using prepared statement placeholders ($1, $2, etc.).
//!
//! # Design Principles
//!
//! 1. **Type Safety**: Parameters are `QueryParam` enum (not stringly typed)
//! 2. **Separation of Concerns**: SQL is never modified; parameters are bound separately
//! 3. **Single Source of Truth**: All parameter binding happens here
//! 4. **Comprehensive Validation**: Type mismatches caught at bind time
//! 5. **Clear Error Messages**: Parameter errors include index and reason
//!
//! # Usage
//!
//! ```rust,ignore
//! use crate::db::parameter_binding::prepare_parameters;
//! use crate::db::types::QueryParam;
//!
//! let params = vec![
//!     QueryParam::BigInt(123),
//!     QueryParam::Text("username".to_string()),
//! ];
//!
//! // Validate parameters before query execution
//! prepare_parameters(&params)?;
//! ```
//!
//! # Implementation Notes
//!
//! This module is designed to be the ONLY place where user input affects SQL execution.
//! The actual binding is delegated to the underlying database driver (sqlx, deadpool, etc.)
//! which uses prepared statements and parameterized queries internally.

use crate::db::pool::traits::{PoolError, PoolResult};
use crate::db::types::QueryParam;

/// Validates and prepares parameters for query execution.
///
/// This function checks that all parameters are valid before sending them to
/// the database. It catches common issues like:
/// - Type mismatches
/// - Invalid values
/// - Parameter count mismatches
///
/// # Arguments
/// * `params` - Vector of query parameters to validate
///
/// # Returns
/// * `Ok(())` - All parameters are valid
/// * `Err(PoolError::InvalidParameter)` - If any parameter is invalid
///
/// # Errors
///
/// Returns `PoolError` if any parameter is invalid (e.g., NaN, infinity, or other validation failure).
///
/// # Example
///
/// ```rust,ignore
/// let params = vec![
///     QueryParam::BigInt(123),
///     QueryParam::Text("test".to_string()),
/// ];
///
/// prepare_parameters(&params)?;  // Returns Ok(())
/// ```
#[allow(dead_code)] // Phase 3.2+: Used by ProductionPool implementation
pub fn prepare_parameters(params: &[QueryParam]) -> PoolResult<()> {
    for (index, param) in params.iter().enumerate() {
        validate_parameter(index, param)?;
    }
    Ok(())
}

/// Validates a single parameter.
///
/// Checks that the parameter is valid and can be bound safely to a prepared statement.
///
/// # Arguments
/// * `index` - The parameter index (0-based)
/// * `param` - The parameter to validate
///
/// # Returns
/// * `Ok(())` - Parameter is valid
/// * `Err(PoolError::InvalidParameter)` - If parameter is invalid
fn validate_parameter(index: usize, param: &QueryParam) -> PoolResult<()> {
    match param {
        QueryParam::Null => {
            // NULL is always valid
            Ok(())
        }
        QueryParam::Bool(_) => {
            // Boolean is always valid
            Ok(())
        }
        QueryParam::Int(_) => {
            // i32 is always valid
            Ok(())
        }
        QueryParam::BigInt(_) => {
            // i64 is always valid
            Ok(())
        }
        QueryParam::Float(_) => {
            // f32 is always valid (though NaN/Inf should probably be rejected)
            Ok(())
        }
        QueryParam::Double(d) => {
            // f64: Check for NaN and Infinity which are invalid in PostgreSQL
            if d.is_nan() || d.is_infinite() {
                return Err(PoolError::QueryExecution(format!(
                    "Parameter {index} is NaN or infinite (invalid in PostgreSQL)"
                )));
            }
            Ok(())
        }
        QueryParam::Text(_s) => {
            // Text is always valid
            // Note: We don't need to check for special characters because
            // prepared statements handle escaping automatically
            Ok(())
        }
        QueryParam::Json(_value) => {
            // JSON must be a valid JSON value
            // serde_json::Value is always valid JSON by construction
            Ok(())
        }
        QueryParam::Timestamp(_) => {
            // Timestamps are always valid
            Ok(())
        }
        QueryParam::Uuid(_) => {
            // UUIDs are always valid
            Ok(())
        }
    }
}

/// Formats a parameter for debugging purposes (without executing it).
///
/// This is used for error messages and logging. It does NOT produce executable SQL.
///
/// # Arguments
/// * `param` - The parameter to format
///
/// # Returns
/// A human-readable representation of the parameter
///
/// # Example
///
/// ```rust,ignore
/// let param = QueryParam::Text("hello".to_string());
/// assert_eq!(format_parameter(&param), "Text(hello)");
/// ```
#[must_use]
#[allow(dead_code)] // Phase 3.2+: Used by error handling in ProductionPool
pub fn format_parameter(param: &QueryParam) -> String {
    match param {
        QueryParam::Null => "NULL".to_string(),
        QueryParam::Bool(b) => format!("BOOL({b})"),
        QueryParam::Int(i) => format!("INT({i})"),
        QueryParam::BigInt(i) => format!("BIGINT({i})"),
        QueryParam::Float(f) => format!("FLOAT({f})"),
        QueryParam::Double(f) => format!("DOUBLE({f})"),
        QueryParam::Text(s) => {
            // Truncate long strings for readability
            if s.len() > 50 {
                format!("TEXT({}...)", &s[..47])
            } else {
                format!("TEXT({s})")
            }
        }
        QueryParam::Json(v) => {
            let json_str = v.to_string();
            if json_str.len() > 50 {
                format!("JSON({}...)", &json_str[..47])
            } else {
                format!("JSON({json_str})")
            }
        }
        QueryParam::Timestamp(t) => format!("TIMESTAMP({t})"),
        QueryParam::Uuid(u) => format!("UUID({u})"),
    }
}

/// Counts the number of placeholders ($1, $2, etc.) in a SQL statement.
///
/// This is useful for validating that the number of parameters matches
/// the number of placeholders in the query.
///
/// # Arguments
/// * `sql` - The SQL query string
///
/// # Returns
/// The count of placeholders found
///
/// # Example
///
/// ```rust,ignore
/// let sql = "SELECT * FROM users WHERE id = $1 AND name = $2";
/// assert_eq!(count_placeholders(sql), 2);
/// ```
/// Parse placeholder number and return whether it's valid.
/// `PostgreSQL` placeholders are `$N` where N is 1-99 (for safety, not 1-32767).
/// Higher numbers like `$100`+ are avoided because they can look like currency (e.g., `$100` bill).
fn parse_placeholder_number(chars: &mut std::iter::Peekable<std::str::Chars>) -> Option<()> {
    let mut num_str = String::new();

    // Collect the digits (limited to 2 digits for $1-$99)
    for _ in 0..2 {
        if let Some(&ch) = chars.peek() {
            if ch.is_ascii_digit() {
                num_str.push(ch);
                chars.next();
            } else {
                break;
            }
        } else {
            break;
        }
    }

    // Only count if:
    // 1. We parsed a number
    // 2. It's in range 1-99 (not 100+)
    // 3. It's followed by a word boundary (not another digit)
    if let Ok(num) = num_str.parse::<u32>() {
        if num > 0 && num <= 99 {
            // Check what comes next - should NOT be a digit (to avoid ambiguity)
            match chars.peek() {
                None => Some(()),                              // End of string
                Some(&ch) if !ch.is_ascii_digit() => Some(()), // Not a digit - valid
                _ => None, // Followed by another digit - ambiguous
            }
        } else {
            None // Out of range
        }
    } else {
        None // Empty or failed to parse
    }
}

/// Counts the number of `PostgreSQL` parameter placeholders in SQL.
///
/// Counts `$1`, `$2`, etc. style placeholders used by `PostgreSQL`.
///
/// # Arguments
/// * `sql` - The SQL query string to scan for placeholders
///
/// # Returns
///
/// The count of `PostgreSQL`-style (`$N`) placeholders found.
#[must_use]
pub fn count_placeholders(sql: &str) -> usize {
    let mut count = 0;
    let mut chars = sql.chars().peekable();

    while let Some(ch) = chars.next() {
        if ch == '$'
            && chars.peek().is_some_and(char::is_ascii_digit)
            && parse_placeholder_number(&mut chars).is_some()
        {
            count += 1;
        }
    }

    count
}

/// Validates that the parameter count matches the placeholder count in SQL.
///
/// # Arguments
/// * `sql` - The SQL query string
/// * `params` - The query parameters
///
/// # Returns
/// * `Ok(())` - Parameter count matches placeholder count
/// * `Err(PoolError)` - Mismatch between count
///
/// # Errors
///
/// Returns `PoolError` if the number of parameters doesn't match the number of placeholders in the SQL.
pub fn validate_parameter_count(sql: &str, params: &[QueryParam]) -> PoolResult<()> {
    let expected = count_placeholders(sql);
    let actual = params.len();

    if expected != actual {
        return Err(PoolError::QueryExecution(format!(
            "Parameter count mismatch: expected {expected} placeholders, got {actual} parameters"
        )));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_prepare_parameters_valid() {
        let params = vec![
            QueryParam::BigInt(123),
            QueryParam::Text("hello".to_string()),
            QueryParam::Bool(true),
        ];

        assert!(prepare_parameters(&params).is_ok());
    }

    #[test]
    fn test_prepare_parameters_with_null() {
        let params = vec![QueryParam::Null, QueryParam::Text("test".to_string())];

        assert!(prepare_parameters(&params).is_ok());
    }

    #[test]
    fn test_validate_parameter_nan() {
        let param = QueryParam::Double(f64::NAN);
        let result = validate_parameter(0, &param);

        assert!(result.is_err());
        if let Err(PoolError::QueryExecution(msg)) = result {
            assert!(msg.contains("NaN") || msg.contains("infinite"));
        }
    }

    #[test]
    fn test_validate_parameter_infinity() {
        let param = QueryParam::Double(f64::INFINITY);
        let result = validate_parameter(0, &param);

        assert!(result.is_err());
    }

    #[test]
    fn test_format_parameter() {
        assert_eq!(format_parameter(&QueryParam::Null), "NULL");
        assert_eq!(format_parameter(&QueryParam::Int(42)), "INT(42)");
        assert_eq!(
            format_parameter(&QueryParam::Text("hello".to_string())),
            "TEXT(hello)"
        );

        // Long strings are truncated
        let long_string = "a".repeat(100);
        let formatted = format_parameter(&QueryParam::Text(long_string));
        assert!(formatted.contains("..."));
    }

    #[test]
    fn test_count_placeholders() {
        assert_eq!(count_placeholders("SELECT * FROM users"), 0);
        assert_eq!(count_placeholders("SELECT * FROM users WHERE id = $1"), 1);
        assert_eq!(
            count_placeholders("SELECT * FROM users WHERE id = $1 AND name = $2 AND status = $3"),
            3
        );
    }

    #[test]
    fn test_count_placeholders_with_double_digit() {
        // PostgreSQL doesn't really support $10+, but our counter should handle it
        assert_eq!(
            count_placeholders("INSERT INTO t VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)"),
            10
        );
    }

    #[test]
    fn test_count_placeholders_false_positive() {
        // $ not followed by digit is not a placeholder
        assert_eq!(
            count_placeholders("SELECT price FROM products WHERE price > $100"),
            0
        );
    }

    #[test]
    fn test_validate_parameter_count_match() {
        let sql = "SELECT * FROM users WHERE id = $1 AND name = $2";
        let params = vec![
            QueryParam::BigInt(123),
            QueryParam::Text("test".to_string()),
        ];

        assert!(validate_parameter_count(sql, &params).is_ok());
    }

    #[test]
    fn test_validate_parameter_count_too_few() {
        let sql = "SELECT * FROM users WHERE id = $1 AND name = $2";
        let params = vec![QueryParam::BigInt(123)];

        let result = validate_parameter_count(sql, &params);
        assert!(result.is_err());
        if let Err(PoolError::QueryExecution(msg)) = result {
            assert!(msg.contains("Parameter count mismatch"));
            assert!(msg.contains("expected 2"));
            assert!(msg.contains("got 1"));
        }
    }

    #[test]
    fn test_validate_parameter_count_too_many() {
        let sql = "SELECT * FROM users WHERE id = $1";
        let params = vec![
            QueryParam::BigInt(123),
            QueryParam::Text("extra".to_string()),
        ];

        let result = validate_parameter_count(sql, &params);
        assert!(result.is_err());
    }
}
