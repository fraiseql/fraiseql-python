//! Entity processing module
//!
//! Handles entity extraction, __typename injection, and CASCADE processing.

use serde_json::{Map, Value};

use crate::camel_case::to_camel_case;

/// Process entity: extract from wrapper if needed
pub fn process_entity(entity: &Value, entity_field_name: Option<&str>) -> ProcessedEntity {
    // Check if entity is a wrapper object
    let (actual_entity, wrapper_fields) = detect_and_extract_wrapper(entity, entity_field_name);

    ProcessedEntity {
        entity: actual_entity.clone(),
        wrapper_fields,
    }
}

/// Result of entity processing
#[derive(Debug, Clone)]
pub struct ProcessedEntity {
    /// Entity data (extracted from wrapper if needed)
    pub entity:         Value,
    /// Fields extracted from wrapper (if any)
    pub wrapper_fields: Map<String, Value>,
}

/// Detect if entity is a wrapper and extract nested entity
///
/// Wrapper format: {"post": {...}, "message": "..."}
/// Direct format: {"id": "123", "title": "..."}
///
/// Returns: (actual_entity, wrapper_fields)
fn detect_and_extract_wrapper<'a>(
    entity: &'a Value,
    entity_field_name: Option<&str>,
) -> (&'a Value, Map<String, Value>) {
    let mut wrapper_fields = Map::new();

    // Only process objects
    let Value::Object(entity_map) = entity else {
        return (entity, wrapper_fields);
    };

    // Check if entity contains a field matching entity_field_name
    if let Some(field_name) = entity_field_name {
        if let Some(nested_entity) = entity_map.get(field_name) {
            // This is a wrapper! Extract nested entity and other fields
            for (key, value) in entity_map {
                if key != field_name {
                    // Copy non-entity fields from wrapper
                    wrapper_fields.insert(key.clone(), value.clone());
                }
            }

            return (nested_entity, wrapper_fields);
        }
    }

    // Not a wrapper, return as-is
    (entity, wrapper_fields)
}

/// Add __typename to entity (recursively for nested objects)
pub fn add_typename_to_entity(entity: &Value, entity_type: &str, auto_camel_case: bool) -> Value {
    match entity {
        Value::Object(map) => {
            let mut result = Map::with_capacity(map.len() + 1);

            // Add __typename first
            result.insert("__typename".to_string(), serde_json::json!(entity_type));

            // Transform keys and recursively process nested values
            for (key, val) in map {
                let transformed_key = if auto_camel_case {
                    to_camel_case(key)
                } else {
                    key.clone()
                };

                // Recursively transform nested objects (but don't add __typename)
                let transformed_val = transform_value(val, auto_camel_case);
                result.insert(transformed_key, transformed_val);
            }

            Value::Object(result)
        },
        Value::Array(arr) => {
            // For arrays, add __typename to each element
            let transformed: Vec<Value> = arr
                .iter()
                .map(|v| add_typename_to_entity(v, entity_type, auto_camel_case))
                .collect();
            Value::Array(transformed)
        },
        other => other.clone(),
    }
}

/// Transform value (camelCase conversion, no __typename)
fn transform_value(value: &Value, auto_camel_case: bool) -> Value {
    match value {
        Value::Object(map) => {
            let mut result = Map::new();
            for (key, val) in map {
                let transformed_key = if auto_camel_case {
                    to_camel_case(key)
                } else {
                    key.clone()
                };
                result.insert(transformed_key, transform_value(val, auto_camel_case));
            }
            Value::Object(result)
        },
        Value::Array(arr) => {
            let transformed: Vec<Value> =
                arr.iter().map(|v| transform_value(v, auto_camel_case)).collect();
            Value::Array(transformed)
        },
        other => other.clone(),
    }
}

/// Update ProcessedEntity to include entity with __typename
pub fn process_entity_with_typename(
    entity: &Value,
    entity_type: &str,
    entity_field_name: Option<&str>,
    auto_camel_case: bool,
) -> ProcessedEntity {
    // Extract from wrapper
    let (actual_entity, wrapper_fields) = detect_and_extract_wrapper(entity, entity_field_name);

    // Add __typename
    let entity_with_typename = add_typename_to_entity(actual_entity, entity_type, auto_camel_case);

    ProcessedEntity {
        entity: entity_with_typename,
        wrapper_fields,
    }
}

/// Process CASCADE data: add __typename
pub fn process_cascade(cascade: &Value, auto_camel_case: bool) -> Value {
    match cascade {
        Value::Object(map) => {
            let mut result = Map::with_capacity(map.len() + 1);

            // Add __typename for GraphQL
            result.insert("__typename".to_string(), serde_json::json!("Cascade"));

            // Transform keys and recursively process values
            for (key, val) in map {
                let transformed_key = if auto_camel_case {
                    to_camel_case(key)
                } else {
                    key.clone()
                };
                result.insert(transformed_key, transform_value(val, auto_camel_case));
            }

            Value::Object(result)
        },
        other => other.clone(),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn test_detect_wrapper() {
        let entity = json!({
            "post": {"id": "123", "title": "Test"},
            "message": "Success",
            "extra": "data"
        });

        let (actual, wrapper_fields) = detect_and_extract_wrapper(&entity, Some("post"));

        assert_eq!(actual.get("id").unwrap(), "123");
        assert_eq!(wrapper_fields.get("message").unwrap(), "Success");
        assert_eq!(wrapper_fields.get("extra").unwrap(), "data");
    }

    #[test]
    fn test_direct_entity() {
        let entity = json!({"id": "123", "title": "Test"});

        let (actual, wrapper_fields) = detect_and_extract_wrapper(&entity, Some("post"));

        assert_eq!(actual, &entity);
        assert!(wrapper_fields.is_empty());
    }

    #[test]
    fn test_no_field_name_no_wrapper() {
        let entity = json!({"post": {"id": "123"}, "message": "Test"});

        let (actual, wrapper_fields) = detect_and_extract_wrapper(&entity, None);

        // Without field name hint, treat entire object as entity
        assert_eq!(actual, &entity);
        assert!(wrapper_fields.is_empty());
    }

    #[test]
    fn test_process_entity_wrapper() {
        let entity = json!({
            "user": {"id": "123", "name": "John"},
            "count": 5
        });

        let processed = process_entity(&entity, Some("user"));

        assert_eq!(processed.entity.get("id").unwrap(), "123");
        assert_eq!(processed.wrapper_fields.get("count").unwrap(), 5);
    }

    #[test]
    fn test_add_typename() {
        let entity = json!({
            "id": "123",
            "first_name": "John",
            "nested": {"key": "value"}
        });

        let result = add_typename_to_entity(&entity, "User", true);

        assert_eq!(result.get("__typename").unwrap(), "User");
        assert_eq!(result.get("firstName").unwrap(), "John"); // camelCase
        assert!(result.get("first_name").is_none()); // Original removed
    }

    #[test]
    fn test_add_typename_no_camel_case() {
        let entity = json!({
            "id": "123",
            "first_name": "John"
        });

        let result = add_typename_to_entity(&entity, "User", false);

        assert_eq!(result.get("__typename").unwrap(), "User");
        assert_eq!(result.get("first_name").unwrap(), "John"); // Kept original
    }

    #[test]
    fn test_typename_in_array() {
        let entity = json!([
            {"id": "1", "name": "Alice"},
            {"id": "2", "name": "Bob"}
        ]);

        let result = add_typename_to_entity(&entity, "User", false);

        if let Value::Array(arr) = result {
            assert_eq!(arr.len(), 2);
            assert_eq!(arr[0].get("__typename").unwrap(), "User");
            assert_eq!(arr[1].get("__typename").unwrap(), "User");
        } else {
            panic!("Expected array");
        }
    }

    #[test]
    fn test_process_with_typename() {
        let entity = json!({
            "user": {"id": "123", "first_name": "John"},
            "count": 5
        });

        let processed = process_entity_with_typename(&entity, "User", Some("user"), true);

        // Entity should have __typename and camelCase
        assert_eq!(processed.entity.get("__typename").unwrap(), "User");
        assert_eq!(processed.entity.get("firstName").unwrap(), "John");

        // Wrapper fields should be extracted
        assert_eq!(processed.wrapper_fields.get("count").unwrap(), 5);
    }

    #[test]
    fn test_process_cascade() {
        let cascade = json!({
            "updated": [],
            "deleted": [],
            "invalidations": []
        });

        let result = process_cascade(&cascade, true);

        assert_eq!(result.get("__typename").unwrap(), "Cascade");
        assert!(result.get("updated").is_some());
        assert!(result.get("deleted").is_some());
        assert!(result.get("invalidations").is_some());
    }

    #[test]
    fn test_cascade_with_data() {
        let cascade = json!({
            "updated": [
                {"type_name": "User", "id": "123"}
            ],
            "deleted": [],
            "invalidations": ["users"]
        });

        let result = process_cascade(&cascade, false);

        assert_eq!(result.get("__typename").unwrap(), "Cascade");
        let updated = result.get("updated").unwrap().as_array().unwrap();
        assert_eq!(updated.len(), 1);
    }
}
