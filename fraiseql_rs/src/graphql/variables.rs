//! Advanced variable processing and validation.
//!
//! This module implements GraphQL variable type validation, coercion,
//! and default value handling according to the GraphQL specification.

use std::collections::HashMap;

use crate::graphql::types::{GraphQLType, ParsedQuery, VariableDefinition};

/// Variable processing result
pub struct VariableResult {
    /// Processed variables with coerced values
    pub variables: HashMap<String, serde_json::Value>,
    /// Any validation errors encountered
    pub errors:    Vec<String>,
}

/// Variable processor for advanced GraphQL variable handling
pub struct VariableProcessor {
    /// Variable definitions from the query
    definitions: HashMap<String, VariableDefinition>,
}

impl VariableProcessor {
    /// Create a new variable processor
    pub fn new(query: &ParsedQuery) -> Self {
        // Extract variable definitions from query
        let definitions =
            query.variables.iter().map(|var| (var.name.clone(), var.clone())).collect();

        Self { definitions }
    }

    /// Process and validate variables against their definitions
    pub fn process_variables(
        &self,
        input_variables: &HashMap<String, serde_json::Value>,
    ) -> VariableResult {
        let mut processed = HashMap::new();
        let mut errors = Vec::new();

        for (var_name, definition) in &self.definitions {
            match self.process_variable(var_name, definition, input_variables) {
                Ok(value) => {
                    processed.insert(var_name.clone(), value);
                },
                Err(error) => {
                    errors.push(error);
                },
            }
        }

        // Check for undefined variables
        for var_name in input_variables.keys() {
            if !self.definitions.contains_key(var_name) {
                errors.push(format!("Variable '${}' is not defined in query", var_name));
            }
        }

        VariableResult {
            variables: processed,
            errors,
        }
    }

    /// Process a single variable
    fn process_variable(
        &self,
        var_name: &str,
        definition: &VariableDefinition,
        input_variables: &HashMap<String, serde_json::Value>,
    ) -> Result<serde_json::Value, String> {
        let input_value = input_variables.get(var_name);

        match input_value {
            Some(value) => {
                // Validate and coerce the provided value
                self.validate_and_coerce_value(value, &definition.var_type)
            },
            None => {
                // Use default value if available
                if let Some(default_str) = &definition.default_value {
                    // Parse the JSON string to serde_json::Value
                    serde_json::from_str(default_str)
                        .map_err(|_| format!("Invalid default value for variable '${}'", var_name))
                } else if definition.var_type.nullable {
                    Ok(serde_json::Value::Null)
                } else {
                    Err(format!("Required variable '${}' is not provided", var_name))
                }
            },
        }
    }

    /// Validate and coerce a value to the expected GraphQL type
    fn validate_and_coerce_value(
        &self,
        value: &serde_json::Value,
        expected_type: &GraphQLType,
    ) -> Result<serde_json::Value, String> {
        match expected_type.name.as_str() {
            "String" => self.coerce_to_string(value),
            "Int" => self.coerce_to_int(value),
            "Float" => self.coerce_to_float(value),
            "Boolean" => self.coerce_to_boolean(value),
            "ID" => self.coerce_to_id(value),
            _ => {
                // For custom types, just validate nullability
                if value.is_null() && !expected_type.nullable {
                    return Err(format!(
                        "Non-nullable type '{}' cannot be null",
                        expected_type.name
                    ));
                }
                Ok(value.clone())
            },
        }
    }

    fn coerce_to_string(&self, value: &serde_json::Value) -> Result<serde_json::Value, String> {
        match value {
            serde_json::Value::String(s) => Ok(serde_json::Value::String(s.clone())),
            serde_json::Value::Number(n) => Ok(serde_json::Value::String(n.to_string())),
            serde_json::Value::Bool(b) => Ok(serde_json::Value::String(b.to_string())),
            _ => Err("Cannot coerce value to String".to_string()),
        }
    }

    fn coerce_to_int(&self, value: &serde_json::Value) -> Result<serde_json::Value, String> {
        match value {
            serde_json::Value::Number(n) if n.is_i64() => Ok(serde_json::Value::Number(n.clone())),
            serde_json::Value::String(s) => s
                .parse::<i64>()
                .map(|n| serde_json::Value::Number(serde_json::Number::from(n)))
                .map_err(|_| "Cannot coerce string to Int".to_string()),
            _ => Err("Cannot coerce value to Int".to_string()),
        }
    }

    fn coerce_to_float(&self, value: &serde_json::Value) -> Result<serde_json::Value, String> {
        match value {
            serde_json::Value::Number(n) => Ok(serde_json::Value::Number(n.clone())),
            serde_json::Value::String(s) => s
                .parse::<f64>()
                .map(|n| {
                    serde_json::Number::from_f64(n)
                        .map(serde_json::Value::Number)
                        .unwrap_or_else(|| serde_json::Value::String(s.clone()))
                })
                .map_err(|_| "Cannot coerce string to Float".to_string()),
            _ => Err("Cannot coerce value to Float".to_string()),
        }
    }

    fn coerce_to_boolean(&self, value: &serde_json::Value) -> Result<serde_json::Value, String> {
        match value {
            serde_json::Value::Bool(b) => Ok(serde_json::Value::Bool(*b)),
            serde_json::Value::String(s) => match s.to_lowercase().as_str() {
                "true" => Ok(serde_json::Value::Bool(true)),
                "false" => Ok(serde_json::Value::Bool(false)),
                _ => Err("Cannot coerce string to Boolean".to_string()),
            },
            _ => Err("Cannot coerce value to Boolean".to_string()),
        }
    }

    fn coerce_to_id(&self, value: &serde_json::Value) -> Result<serde_json::Value, String> {
        // ID is serialized as String
        self.coerce_to_string(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graphql::types::{GraphQLType, VariableDefinition};

    #[test]
    fn test_string_coercion() {
        let mut query = ParsedQuery::default();
        query.variables = vec![VariableDefinition {
            name:          "test".to_string(),
            var_type:      GraphQLType {
                name:          "String".to_string(),
                nullable:      false,
                list:          false,
                list_nullable: false,
            },
            default_value: None,
        }];
        let processor = VariableProcessor::new(&query);

        let result = processor
            .process_variables(&HashMap::from([("test".to_string(), serde_json::json!("hello"))]));

        assert!(result.errors.is_empty());
        assert_eq!(result.variables.get("test"), Some(&serde_json::json!("hello")));
    }

    #[test]
    fn test_int_coercion() {
        let processor = VariableProcessor::new(&ParsedQuery::default());

        let var_def = VariableDefinition {
            name:          "test".to_string(),
            var_type:      GraphQLType {
                name:          "Int".to_string(),
                nullable:      false,
                list:          false,
                list_nullable: false,
            },
            default_value: None,
        };

        let result = processor.process_variable(
            "test",
            &var_def,
            &HashMap::from([("test".to_string(), serde_json::json!(42))]),
        );

        assert!(result.is_ok());
        assert_eq!(result.unwrap(), serde_json::json!(42));
    }

    #[test]
    fn test_string_coercion_from_int() {
        let processor = VariableProcessor::new(&ParsedQuery::default());

        let var_def = VariableDefinition {
            name:          "test".to_string(),
            var_type:      GraphQLType {
                name:          "String".to_string(),
                nullable:      false,
                list:          false,
                list_nullable: false,
            },
            default_value: None,
        };

        let result = processor.process_variable(
            "test",
            &var_def,
            &HashMap::from([("test".to_string(), serde_json::json!(123))]),
        );

        assert!(result.is_ok());
        assert_eq!(result.unwrap(), serde_json::json!("123"));
    }

    #[test]
    fn test_float_coercion() {
        let processor = VariableProcessor::new(&ParsedQuery::default());

        let var_def = VariableDefinition {
            name:          "test".to_string(),
            var_type:      GraphQLType {
                name:          "Float".to_string(),
                nullable:      false,
                list:          false,
                list_nullable: false,
            },
            default_value: None,
        };

        let result = processor.process_variable(
            "test",
            &var_def,
            &HashMap::from([("test".to_string(), serde_json::json!(3.14))]),
        );

        assert!(result.is_ok());
        assert_eq!(result.unwrap(), serde_json::json!(3.14));
    }

    #[test]
    fn test_boolean_coercion() {
        let processor = VariableProcessor::new(&ParsedQuery::default());

        let var_def = VariableDefinition {
            name:          "test".to_string(),
            var_type:      GraphQLType {
                name:          "Boolean".to_string(),
                nullable:      false,
                list:          false,
                list_nullable: false,
            },
            default_value: None,
        };

        let result = processor.process_variable(
            "test",
            &var_def,
            &HashMap::from([("test".to_string(), serde_json::json!(true))]),
        );

        assert!(result.is_ok());
        assert_eq!(result.unwrap(), serde_json::json!(true));
    }

    #[test]
    fn test_default_value_usage() {
        let mut query = ParsedQuery::default();
        query.variables = vec![VariableDefinition {
            name:          "test".to_string(),
            var_type:      GraphQLType {
                name:          "String".to_string(),
                nullable:      false,
                list:          false,
                list_nullable: false,
            },
            default_value: Some("\"default_value\"".to_string()),
        }];
        let processor = VariableProcessor::new(&query);

        // Test with no variable provided - should use default
        let result = processor.process_variables(&HashMap::new());
        assert!(result.errors.is_empty());
        assert_eq!(result.variables.get("test"), Some(&serde_json::json!("default_value")));
    }

    #[test]
    fn test_missing_required_variable() {
        let mut query = ParsedQuery::default();
        query.variables = vec![VariableDefinition {
            name:          "required_var".to_string(),
            var_type:      GraphQLType {
                name:          "String".to_string(),
                nullable:      false,
                list:          false,
                list_nullable: false,
            },
            default_value: None,
        }];
        let processor = VariableProcessor::new(&query);

        let result = processor.process_variables(&HashMap::new());
        assert!(!result.errors.is_empty());
        assert!(result.errors[0].contains("required"));
    }

    #[test]
    fn test_invalid_variable_type() {
        let processor = VariableProcessor::new(&ParsedQuery::default());

        let var_def = VariableDefinition {
            name:          "test".to_string(),
            var_type:      GraphQLType {
                name:          "Int".to_string(),
                nullable:      false,
                list:          false,
                list_nullable: false,
            },
            default_value: None,
        };

        let result = processor.process_variable(
            "test",
            &var_def,
            &HashMap::from([("test".to_string(), serde_json::json!("not_a_number"))]),
        );

        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Int"));
    }
}
