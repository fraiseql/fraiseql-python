//! Input processor for GraphQL variables with ID policy validation
//!
//! This module provides utilities to validate GraphQL input variables,
//! particularly ID fields, according to the configured ID policy.
//!
//! **SECURITY CRITICAL**: Input validation is a critical security layer that
//! prevents invalid data from propagating through the GraphQL pipeline.

use super::id_policy::{validate_id, IDPolicy};
use serde_json::{Map, Value};
use std::collections::HashSet;

/// Configuration for input processing
#[derive(Debug, Clone)]
pub struct InputProcessingConfig {
    /// ID policy to enforce for ID fields
    pub id_policy: IDPolicy,

    /// Enable ID validation on all inputs (recommended)
    pub validate_ids: bool,

    /// List of field names known to be ID types
    /// (in a real implementation, this would come from the schema)
    pub id_field_names: HashSet<String>,
}

impl Default for InputProcessingConfig {
    fn default() -> Self {
        Self {
            id_policy: IDPolicy::default(),
            validate_ids: true,
            id_field_names: Self::default_id_field_names(),
        }
    }
}

impl InputProcessingConfig {
    /// Get default set of common ID field names
    fn default_id_field_names() -> HashSet<String> {
        [
            "id",
            "userId",
            "user_id",
            "postId",
            "post_id",
            "commentId",
            "comment_id",
            "authorId",
            "author_id",
            "ownerId",
            "owner_id",
            "creatorId",
            "creator_id",
            "tenantId",
            "tenant_id",
        ]
        .iter()
        .map(|s| (*s).to_string())
        .collect()
    }

    /// Add a custom ID field name to validation
    pub fn add_id_field(&mut self, field_name: String) {
        self.id_field_names.insert(field_name);
    }

    /// Create a configuration for strict UUID validation
    #[must_use]
    pub fn strict_uuid() -> Self {
        Self {
            id_policy: IDPolicy::UUID,
            validate_ids: true,
            id_field_names: Self::default_id_field_names(),
        }
    }

    /// Create a configuration for opaque IDs (GraphQL spec compliant)
    #[must_use]
    pub fn opaque() -> Self {
        Self {
            id_policy: IDPolicy::OPAQUE,
            validate_ids: false, // No validation needed for opaque
            id_field_names: Self::default_id_field_names(),
        }
    }
}

/// Process and validate GraphQL input variables
///
/// **SECURITY CRITICAL**: This validates all ID fields in input variables
/// according to the configured ID policy.
///
/// # Arguments
///
/// * `variables` - GraphQL operation variables (JSON object)
/// * `config` - Input processing configuration
///
/// # Returns
///
/// `Ok(processed_variables)` with validated data, or
/// `Err(ProcessingError)` if validation fails
///
/// # Errors
///
/// Returns `ProcessingError` if any ID field fails validation according to the configured policy.
///
/// # Examples
///
/// ```ignore
/// use fraiseql_rs::validation::input_processor::{InputProcessingConfig, process_variables};
/// use fraiseql_rs::validation::IDPolicy;
///
/// let config = InputProcessingConfig::strict_uuid();
/// let variables = json!({"userId": "550e8400-e29b-41d4-a716-446655440000"});
///
/// match process_variables(&variables, &config) {
///     Ok(processed) => { /* Use processed variables */ },
///     Err(e) => { /* Handle validation error */ },
/// }
/// ```
pub fn process_variables(
    variables: &Value,
    config: &InputProcessingConfig,
) -> Result<Value, ProcessingError> {
    if !config.validate_ids {
        return Ok(variables.clone());
    }

    match variables {
        Value::Object(obj) => {
            let mut result = Map::new();

            for (key, value) in obj {
                let processed_value = process_value(value, config, key)?;
                result.insert(key.clone(), processed_value);
            }

            Ok(Value::Object(result))
        }
        Value::Null => Ok(Value::Null),
        other => Ok(other.clone()),
    }
}

/// Process a single JSON value, validating ID fields
fn process_value(
    value: &Value,
    config: &InputProcessingConfig,
    field_name: &str,
) -> Result<Value, ProcessingError> {
    match value {
        // Validate ID string fields
        // Extract base field name (before array indices like [0])
        Value::String(s)
            if {
                let base_field = field_name.split('[').next().unwrap_or(field_name);
                config.id_field_names.contains(base_field)
            } =>
        {
            validate_id(s, config.id_policy).map_err(|e| ProcessingError {
                field_path: field_name.to_string(),
                reason: format!("Invalid ID value: {e}"),
            })?;
            Ok(Value::String(s.clone()))
        }

        // Recursively process nested objects
        Value::Object(obj) => {
            let mut result = Map::new();

            for (key, nested_value) in obj {
                let processed = process_value(nested_value, config, key)?;
                result.insert(key.clone(), processed);
            }

            Ok(Value::Object(result))
        }

        // Process array items
        Value::Array(arr) => {
            let processed_items: Result<Vec<_>, _> = arr
                .iter()
                .enumerate()
                .map(|(idx, item)| {
                    let array_field = format!("{field_name}[{idx}]");
                    process_value(item, config, &array_field)
                })
                .collect();

            Ok(Value::Array(processed_items?))
        }

        // Pass through other values unchanged
        other => Ok(other.clone()),
    }
}

/// Error type for input processing failures
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessingError {
    /// The field path where the error occurred
    pub field_path: String,
    /// The reason for the error
    pub reason: String,
}

impl std::fmt::Display for ProcessingError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Error in field '{}': {}", self.field_path, self.reason)
    }
}

impl std::error::Error for ProcessingError {}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_process_valid_uuid_id() {
        let config = InputProcessingConfig::strict_uuid();
        let variables = json!({
            "userId": "550e8400-e29b-41d4-a716-446655440000"
        });

        let result = process_variables(&variables, &config);
        assert!(result.is_ok());
    }

    #[test]
    fn test_process_invalid_uuid_id() {
        let config = InputProcessingConfig::strict_uuid();
        let variables = json!({
            "userId": "invalid-id"
        });

        let result = process_variables(&variables, &config);
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.field_path.contains("userId"));
    }

    #[test]
    fn test_process_multiple_ids() {
        let config = InputProcessingConfig::strict_uuid();
        let variables = json!({
            "userId": "550e8400-e29b-41d4-a716-446655440000",
            "postId": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            "name": "John"
        });

        let result = process_variables(&variables, &config);
        assert!(result.is_ok());
    }

    #[test]
    fn test_process_nested_ids() {
        let config = InputProcessingConfig::strict_uuid();
        let variables = json!({
            "input": {
                "userId": "550e8400-e29b-41d4-a716-446655440000",
                "profile": {
                    "authorId": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
                }
            }
        });

        let result = process_variables(&variables, &config);
        assert!(result.is_ok());
    }

    #[test]
    fn test_process_nested_invalid_id() {
        let config = InputProcessingConfig::strict_uuid();
        let variables = json!({
            "input": {
                "userId": "550e8400-e29b-41d4-a716-446655440000",
                "profile": {
                    "authorId": "invalid"
                }
            }
        });

        let result = process_variables(&variables, &config);
        assert!(result.is_err());
    }

    #[test]
    fn test_process_array_of_ids() {
        let config = InputProcessingConfig::strict_uuid();
        let variables = json!({
            "userIds": [
                "550e8400-e29b-41d4-a716-446655440000",
                "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
            ]
        });

        let result = process_variables(&variables, &config);
        assert!(result.is_ok());
    }

    #[test]
    fn test_process_array_with_invalid_id() {
        let mut config = InputProcessingConfig::strict_uuid();
        // Add "userIds" as a recognized ID field
        config.add_id_field("userIds".to_string());
        let variables = json!({
            "userIds": [
                "550e8400-e29b-41d4-a716-446655440000",
                "invalid-id"
            ]
        });

        let result = process_variables(&variables, &config);
        assert!(result.is_err());
    }

    #[test]
    fn test_opaque_policy_accepts_any_id() {
        let config = InputProcessingConfig::opaque();
        let variables = json!({
            "userId": "any-string-here"
        });

        let result = process_variables(&variables, &config);
        assert!(result.is_ok());
    }

    #[test]
    fn test_disabled_validation_skips_checks() {
        let mut config = InputProcessingConfig::strict_uuid();
        config.validate_ids = false;

        let variables = json!({
            "userId": "invalid-id"
        });

        let result = process_variables(&variables, &config);
        assert!(result.is_ok());
    }

    #[test]
    fn test_custom_id_field_names() {
        let mut config = InputProcessingConfig::strict_uuid();
        config.add_id_field("customId".to_string());

        let variables = json!({
            "customId": "550e8400-e29b-41d4-a716-446655440000"
        });

        let result = process_variables(&variables, &config);
        assert!(result.is_ok());
    }

    #[test]
    fn test_process_null_variables() {
        let config = InputProcessingConfig::strict_uuid();
        let result = process_variables(&Value::Null, &config);
        assert!(result.is_ok());
        assert!(result.unwrap().is_null());
    }

    #[test]
    fn test_non_id_fields_pass_through() {
        let config = InputProcessingConfig::strict_uuid();
        let variables = json!({
            "name": "not-a-uuid",
            "email": "invalid-format@email",
            "age": 25
        });

        let result = process_variables(&variables, &config);
        assert!(result.is_ok());
    }
}
