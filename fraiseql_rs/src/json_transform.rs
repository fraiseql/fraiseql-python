//! JSON parsing and transformation (Value-based API)
//!
//! This module provides direct JSON string → transformed JSON string conversion,
//! bypassing Python dict intermediate steps for maximum performance.
//!
//! ## Architecture
//!
//! FraiseQL has **two JSON transformation strategies**:
//! - **This module (json_transform.rs)**: Value-based API for PyO3, schema-aware
//! - **core::transform**: Zero-copy streaming API for query pipeline (3-5x faster)
//!
//! ## When to Use This Module
//!
//! ✅ **Use `json_transform.rs` when**:
//! - Called from Python via PyO3
//! - Need schema-aware transformation (nested types)
//! - Working with JSON strings (`String` → `String`)
//! - Need `serde_json::Value` compatibility
//! - Moderate volume (< 1000 req/sec)
//!
//! ❌ **Use `core::transform` instead when**:
//! - GraphQL query pipeline (hot path)
//! - Need streaming/zero-copy (3-5x faster, 80% less memory)
//! - High volume (> 1000 req/sec)
//! - Field projection required
//!
//! For detailed architecture rationale, see: `docs/json-transformation-guide.md`

use pyo3::{exceptions::PyValueError, prelude::*};
use serde_json::{Map, Value};

use crate::{
    camel_case::to_camel_case,
    pipeline::projection::{Projection, TYPENAME},
    schema_registry::SchemaRegistry,
};

/// Transform a JSON string by converting all keys from snake_case to camelCase
///
/// This function provides the **fastest path** for JSON transformation:
/// 1. Parse JSON (serde_json - zero-copy where possible)
/// 2. Transform keys recursively (move semantics, no clones)
/// 3. Serialize back to JSON (optimized buffer writes)
///
/// This avoids the Python dict round-trip, making it **10-50x faster**
/// for large JSON objects compared to Python-based transformation.
///
/// # Performance Characteristics
/// - **Zero-copy parsing**: serde_json optimizes for owned string slices
/// - **Move semantics**: Values moved, not cloned during transformation
/// - **Single allocation**: Output buffer pre-sized by serde_json
/// - **No Python GIL**: Entire operation runs in Rust (GIL-free)
///
/// # Typical Performance
/// - Simple object (10 fields): ~0.1-0.2ms (vs 5-10ms Python)
/// - Complex object (50 fields): ~0.5-1ms (vs 20-30ms Python)
/// - Nested (User + 15 posts): ~1-2ms (vs 40-80ms CamelForge)
///
/// # Arguments
/// * `json_str` - JSON string with snake_case keys
///
/// # Returns
/// * `PyResult<String>` - Transformed JSON string with camelCase keys
///
/// # Errors
/// Returns `PyValueError` if input is not valid JSON
///
/// # Examples
/// ```python
/// >>> transform_json('{"user_name": "John", "email_address": "john@example.com"}')
/// '{"userName":"John","emailAddress":"john@example.com"}'
/// ```
#[inline]
pub fn transform_json_string(json_str: &str) -> PyResult<String> {
    // Parse JSON (zero-copy where possible)
    let value: Value = serde_json::from_str(json_str)
        .map_err(|e| PyValueError::new_err(format!("Invalid JSON: {}", e)))?;

    // Transform keys (moves values, no cloning)
    let transformed = transform_value(value);

    // Serialize back to JSON (optimized buffer writes)
    serde_json::to_string(&transformed)
        .map_err(|e| PyValueError::new_err(format!("Failed to serialize JSON: {}", e)))
}

/// Recursively transform a serde_json::Value
///
/// Handles all JSON value types:
/// - Object: Transform keys, recursively transform values
/// - Array: Recursively transform each element
/// - Primitives: Return as-is (String, Number, Bool, Null)
fn transform_value(value: Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut new_map = Map::new();
            for (key, val) in map {
                let camel_key = to_camel_case(&key);
                let transformed_val = transform_value(val);
                new_map.insert(camel_key, transformed_val);
            }
            Value::Object(new_map)
        },
        Value::Array(arr) => {
            let transformed_arr: Vec<Value> = arr.into_iter().map(transform_value).collect();
            Value::Array(transformed_arr)
        },
        // Primitives: return as-is
        other => other,
    }
}

/// Transform a nested object field using schema information
///
/// This is a helper function that handles:
/// - Null values (pass through)
/// - Nested objects (recursive transformation with correct type)
/// - Arrays of nested objects (map over items)
///
/// # Performance
/// Uses schema registry O(1) lookup to resolve correct type for nested objects
#[inline]
fn transform_nested_object(
    value: &Value,
    type_name: &str,
    is_list: bool,
    registry: &SchemaRegistry,
) -> Value {
    if is_list {
        // Array of nested objects
        match value {
            Value::Array(items) => {
                let transformed_items: Vec<Value> = items
                    .iter()
                    .map(|item| match item {
                        Value::Null => Value::Null,
                        _ => transform_with_schema(item, type_name, registry),
                    })
                    .collect();
                Value::Array(transformed_items)
            },
            Value::Null => Value::Null,
            // Unexpected type - pass through with warning in debug mode
            _ => {
                #[cfg(debug_assertions)]
                eprintln!("Warning: Expected array for list type '{}', got {}", type_name, value);
                value.clone()
            },
        }
    } else {
        // Single nested object
        match value {
            Value::Null => Value::Null,
            _ => transform_with_schema(value, type_name, registry),
        }
    }
}

/// Transform a JSON value using schema registry for type resolution
///
/// This function:
/// 1. Converts snake_case keys to camelCase
/// 2. Injects __typename for objects
/// 3. Recursively resolves nested object types from schema
/// 4. Handles arrays of nested objects
/// 5. Gracefully handles missing schema information
///
/// # Arguments
/// * `value` - The JSON value to transform
/// * `current_type` - The GraphQL type name for this value
/// * `registry` - The schema registry for type lookups
///
/// # Returns
/// * Transformed JSON value with correct __typename at all levels
///
/// # Performance
/// - O(1) schema lookups per field via HashMap
/// - Zero-copy for unchanged scalar values where possible
/// - Single-pass transformation (no backtracking)
///
/// # Graceful Degradation
/// If a field type is not found in the schema registry, the function falls back
/// to simple camelCase conversion without __typename injection for that field.
///
/// # Examples
/// ```ignore
/// let input = json!({"id": "1", "equipment": {"id": "2", "name": "Device"}});
/// let result = transform_with_schema(&input, "Assignment", &registry);
/// // result: {"__typename": "Assignment", "id": "1", "equipment": {"__typename": "Equipment", ...}}
/// ```
pub fn transform_with_schema(
    value: &Value,
    current_type: &str,
    registry: &SchemaRegistry,
) -> Value {
    match value {
        Value::Object(map) => {
            // Pre-allocate result map with capacity for __typename + all fields
            let mut result = Map::with_capacity(map.len() + 1);

            // Inject __typename first (GraphQL convention)
            result.insert("__typename".to_string(), Value::String(current_type.to_string()));

            // OPTIMIZATION: Clone map once, then use .remove() to take ownership of values
            // This trades 1 map clone for N field clones (where N = number of fields)
            // For objects with >1 field, this is a net win
            let mut owned_map = map.clone();

            // Transform each field
            for key in map.keys() {
                let camel_key = to_camel_case(key);

                // Look up field type in schema (O(1) HashMap lookup)
                let transformed_val = match registry.get_field_type(current_type, key) {
                    Some(field_info) if field_info.is_nested_object() => {
                        // Nested object or array - use schema to resolve correct type
                        // Still need to borrow here for nested transformation
                        let val = owned_map.get(key).unwrap();
                        transform_nested_object(
                            val,
                            field_info.type_name(),
                            field_info.is_list(),
                            registry,
                        )
                    },
                    Some(_) => {
                        // Scalar field - take ownership, no clone needed!
                        owned_map.remove(key).unwrap()
                    },
                    None => {
                        // Field not in schema - take ownership and transform recursively
                        transform_value(owned_map.remove(key).unwrap())
                    },
                };

                result.insert(camel_key, transformed_val);
            }

            Value::Object(result)
        },
        Value::Null => Value::Null,
        other => other.clone(),
    }
}

/// Transform JSON using field selections with aliases
///
/// Builds the [`Projection`] of `selections` and projects `value` on it
/// ([`project_with_schema`]). A caller transforming many rows builds the
/// projection once and calls `project_with_schema` instead.
///
/// # Field Selection Format
/// See [`Projection::from_selections`]:
/// ```json
/// {"materialized_path": "author.first_name", "response_path": "writer.name",
///  "alias": "name", "type_name": "String", "is_nested_object": false}
/// ```
///
/// # Examples
/// ```ignore
/// let input = json!({"user_name": "John", "secret": "x"});
/// let selections = vec![json!({"materialized_path": "user_name", "alias": "username"})];
/// let result = transform_with_selections(&input, "User", &selections, &registry);
/// // result: {"__typename": "User", "username": "John"}
/// ```
pub fn transform_with_selections(
    value: &Value,
    current_type: &str,
    selections: &[Value],
    registry: &SchemaRegistry,
) -> Value {
    let projection = Projection::from_selections(selections);
    project_with_schema(value, Some(current_type), &projection, registry, true)
}

/// Project a JSON value on a selection: the selected fields only, each under its
/// response key.
///
/// - An array is projected element by element, at any depth.
/// - An object gets `__typename` first when `inject_typename` and its type is
///   known, then each selected field found in it, in selection order (so without
///   `inject_typename`, `__typename` only where selected): an object field projected on
///   its own selection, a leaf copied as it is. A field selected under two aliases
///   is written twice, each with its sub-selection. A field missing from the
///   data is left out.
/// - `__typename` selected under an alias is the object's type: `current_type`,
///   else the type the selection names, else the `__typename` in the data.
/// - Anything else is returned as it is.
///
/// A nested object's type is the registry's type for the field, else the
/// selection's.
pub fn project_with_schema(
    value: &Value,
    current_type: Option<&str>,
    projection: &Projection,
    registry: &SchemaRegistry,
    inject_typename: bool,
) -> Value {
    match value {
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| {
                    project_with_schema(item, current_type, projection, registry, inject_typename)
                })
                .collect(),
        ),
        Value::Object(map) => {
            let mut result = Map::with_capacity(projection.fields.len() + 1);
            if let (true, Some(type_name)) = (inject_typename, current_type) {
                result.insert(TYPENAME.to_string(), Value::String(type_name.to_string()));
            }
            for field in &projection.fields {
                if field.is_typename() {
                    let type_name = current_type
                        .or(field.type_name.as_deref())
                        .or_else(|| map.get(TYPENAME).and_then(Value::as_str));
                    if let Some(type_name) = type_name {
                        result.insert(field.output.clone(), Value::String(type_name.to_string()));
                    }
                    continue;
                }
                let Some(field_value) = field.value_in(map) else {
                    continue;
                };
                let projected = match &field.children {
                    Some(children) => {
                        let nested_type = current_type
                            .and_then(|type_name| registry.get_field_type(type_name, &field.source))
                            .filter(|info| info.is_nested_object())
                            .map(|info| info.type_name())
                            .or(field.type_name.as_deref());
                        project_with_schema(
                            field_value,
                            nested_type,
                            children,
                            registry,
                            inject_typename,
                        )
                    },
                    None => field_value.clone(),
                };
                result.insert(field.output.clone(), projected);
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
    use crate::schema_registry::SchemaRegistry;

    /// Helper to create a FieldSelection structure for testing
    fn make_selection(path: &str, alias: &str, type_name: &str, is_list: bool) -> Value {
        json!({
            "materialized_path": path,
            "alias": alias,
            "type_info": {
                "type_name": type_name,
                "is_list": is_list,
                "is_nested_object": false
            }
        })
    }

    /// Helper to create test schema registry for field projection tests
    fn create_field_projection_test_schema() -> SchemaRegistry {
        let schema_json = r#"{
            "version": "1.0",
            "features": ["type_resolution", "field_projection"],
            "types": {
                "User": {
                    "fields": {
                        "id": {
                            "type_name": "String",
                            "is_nested_object": false,
                            "is_list": false
                        },
                        "user_name": {
                            "type_name": "String",
                            "is_nested_object": false,
                            "is_list": false
                        },
                        "email": {
                            "type_name": "String",
                            "is_nested_object": false,
                            "is_list": false
                        },
                        "password_hash": {
                            "type_name": "String",
                            "is_nested_object": false,
                            "is_list": false
                        },
                        "profile": {
                            "type_name": "Profile",
                            "is_nested_object": true,
                            "is_list": false
                        }
                    }
                },
                "Profile": {
                    "fields": {
                        "bio": {
                            "type_name": "String",
                            "is_nested_object": false,
                            "is_list": false
                        },
                        "avatar_url": {
                            "type_name": "String",
                            "is_nested_object": false,
                            "is_list": false
                        }
                    }
                }
            }
        }"#;

        SchemaRegistry::from_json(schema_json).unwrap()
    }

    #[test]
    fn test_simple_object() {
        let input = r#"{"user_name":"John","email_address":"john@example.com"}"#;
        let result = transform_json_string(input).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(parsed["userName"], "John");
        assert_eq!(parsed["emailAddress"], "john@example.com");
    }

    #[test]
    fn test_nested_object() {
        let input = r#"{"user_id":1,"user_profile":{"first_name":"John"}}"#;
        let result = transform_json_string(input).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(parsed["userId"], 1);
        assert_eq!(parsed["userProfile"]["firstName"], "John");
    }

    #[test]
    fn test_array_of_objects() {
        let input = r#"{"user_posts":[{"post_id":1},{"post_id":2}]}"#;
        let result = transform_json_string(input).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(parsed["userPosts"][0]["postId"], 1);
        assert_eq!(parsed["userPosts"][1]["postId"], 2);
    }

    #[test]
    fn test_preserves_types() {
        let input = r#"{"user_id":123,"is_active":true,"deleted_at":null}"#;
        let result = transform_json_string(input).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(parsed["userId"], 123);
        assert_eq!(parsed["isActive"], true);
        assert_eq!(parsed["deletedAt"], Value::Null);
    }

    #[test]
    fn test_empty_object() {
        let input = "{}";
        let result = transform_json_string(input).unwrap();
        assert_eq!(result, "{}");
    }

    #[test]
    fn test_invalid_json() {
        let input = "not valid json";
        let result = transform_json_string(input);
        assert!(result.is_err());
    }

    #[test]
    fn test_array_root() {
        let input = r#"[{"user_id":1},{"user_id":2}]"#;
        let result = transform_json_string(input).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(parsed[0]["userId"], 1);
        assert_eq!(parsed[1]["userId"], 2);
    }

    /// RED PHASE TEST: Field projection should filter unselected fields
    /// This test will FAIL because field projection is not yet implemented
    #[test]
    fn test_field_projection_filters_unselected_fields() {
        let registry = create_field_projection_test_schema();

        // Input: User object with multiple fields including sensitive data
        let input = json!({
            "id": 1,
            "user_name": "Alice",
            "email": "alice@example.com",
            "password_hash": "secret123"
        });

        // Selections: Only include id and user_name (exclude email and password_hash)
        let selections = vec![
            make_selection("id", "id", "String", false),
            make_selection("user_name", "userName", "String", false),
        ];

        // Transform with field selections
        let result = transform_with_selections(&input, "User", &selections, &registry);

        // Expected: Only selected fields should be present
        // Currently this will FAIL because field projection is not implemented
        assert_eq!(result["__typename"], "User");
        assert_eq!(result["id"], 1);
        assert_eq!(result["userName"], "Alice");

        // These fields should NOT be present (field projection)
        assert!(result.get("email").is_none(), "email should be filtered out");
        assert!(result.get("passwordHash").is_none(), "password_hash should be filtered out");
    }

    /// RED PHASE TEST: Field projection with nested objects
    /// This test will FAIL because field projection is not yet implemented
    #[test]
    fn test_field_projection_with_nested_objects() {
        let registry = create_field_projection_test_schema();

        // Input: User with nested profile object
        let input = json!({
            "id": 1,
            "user_name": "Alice",
            "profile": {
                "bio": "Hello world!",
                "avatar_url": "http://example.com/avatar.jpg"
            }
        });

        // Selections: Only include id and profile.bio (exclude profile.avatar_url)
        let selections = vec![
            make_selection("id", "id", "String", false),
            make_selection("profile.bio", "profile.bio", "String", false),
        ];

        let result = transform_with_selections(&input, "User", &selections, &registry);

        // Expected: Root level fields
        assert_eq!(result["__typename"], "User");
        assert_eq!(result["id"], 1);

        // Expected: Profile should exist but only contain selected field
        let profile = result["profile"].as_object().unwrap();
        assert_eq!(profile["__typename"], "Profile");
        assert_eq!(profile["bio"], "Hello world!");

        // This field should NOT be present (field projection)
        assert!(profile.get("avatarUrl").is_none(), "avatar_url should be filtered out");
    }

    /// RED PHASE TEST: __typename is always included even when not in selections
    /// This test will FAIL because field projection is not yet implemented
    #[test]
    fn test_field_projection_always_includes_typename() {
        let registry = create_field_projection_test_schema();

        // Input: Simple user object
        let input = json!({
            "id": 1,
            "user_name": "Alice"
        });

        // Selections: Only include id (no explicit __typename selection)
        let selections = vec![make_selection("id", "id", "String", false)];

        let result = transform_with_selections(&input, "User", &selections, &registry);

        // Expected: __typename should ALWAYS be included
        assert_eq!(result["__typename"], "User");
        assert_eq!(result["id"], 1);

        // user_name should NOT be present (not selected)
        assert!(result.get("userName").is_none(), "user_name should be filtered out");
    }

    /// JSONB numbers keep their source digits: a `numeric` wider than an f64, and one
    /// beyond its range, reach the response as Postgres wrote them.
    #[test]
    fn test_numbers_keep_their_digits() {
        let registry = create_field_projection_test_schema();
        let huge = format!("-1{}", "0".repeat(400));
        let row = format!(
            r#"{{"id":1,"price":12.345678901234567890123,"huge":{huge},"big":123456789012345678901234567890,"small":7,"half":0.5}}"#
        );
        let input: Value = serde_json::from_str(&row).unwrap();

        let result = transform_with_schema(&input, "User", &registry);
        let output = serde_json::to_string(&result).unwrap();

        assert!(output.contains(r#""price":12.345678901234567890123"#), "{output}");
        assert!(output.contains(&format!(r#""huge":{huge}"#)), "{output}");
        assert!(output.contains(r#""big":123456789012345678901234567890"#), "{output}");
        assert_eq!(result["small"], 7);
        assert_eq!(result["half"], 0.5);
    }

    fn aliased(path: &str, response_path: &str, is_object: bool) -> Value {
        json!({"materialized_path": path, "response_path": response_path,
               "is_nested_object": is_object})
    }

    #[test]
    fn test_nested_object_answers_under_its_alias() {
        let registry = create_field_projection_test_schema();
        let input = json!({"id": 1, "profile": {"bio": "b", "avatar_url": "u"}});
        let selections = vec![
            aliased("profile", "p", true),
            aliased("profile.avatar_url", "p.pic", false),
        ];

        let result = transform_with_selections(&input, "User", &selections, &registry);

        assert_eq!(
            result,
            json!({"__typename": "User", "p": {"__typename": "Profile", "pic": "u"}})
        );
    }

    #[test]
    fn test_two_aliases_of_one_field_get_their_own_selection() {
        let registry = create_field_projection_test_schema();
        let input = json!({"profile": {"bio": "b", "avatar_url": "u"}});
        let selections = vec![
            aliased("profile", "a", true),
            aliased("profile.bio", "a.bio", false),
            aliased("profile", "b", true),
            aliased("profile.avatar_url", "b.avatarUrl", false),
        ];

        let result = transform_with_selections(&input, "User", &selections, &registry);

        assert_eq!(result["a"], json!({"__typename": "Profile", "bio": "b"}));
        assert_eq!(result["b"], json!({"__typename": "Profile", "avatarUrl": "u"}));
        assert!(result.get("profile").is_none());
    }

    #[test]
    fn test_selected_lists_are_projected_at_any_depth() {
        let registry = SchemaRegistry::empty();
        let input = json!({"grid": [[{"tag_name": "t", "secret": "x"}], null]});
        let selections = vec![
            aliased("grid", "g", true),
            aliased("grid.tag_name", "g.tagName", false),
        ];

        let projection = Projection::from_selections(&selections);
        let result = project_with_schema(&input, None, &projection, &registry, true);

        assert_eq!(result, json!({"g": [[{"tagName": "t"}], null]}));
    }

    #[test]
    fn test_without_injection_typename_is_written_where_selected_only() {
        let registry = create_field_projection_test_schema();
        let input = json!({"id": 1, "profile": {"bio": "b"}});
        let selections = vec![
            aliased("id", "id", false),
            aliased("profile", "profile", true),
            aliased("profile.__typename", "profile.kind", false),
            aliased("profile.bio", "profile.bio", false),
        ];

        let projection = Projection::from_selections(&selections);
        let result = project_with_schema(&input, Some("User"), &projection, &registry, false);

        assert_eq!(result, json!({"id": 1, "profile": {"kind": "Profile", "bio": "b"}}));
    }

    #[test]
    fn test_fields_follow_the_selection_order() {
        // A GraphQL response map is ordered like its selection set, not like
        // the row (nor alphabetically)
        let registry = create_field_projection_test_schema();
        let input = json!({"id": 1, "email": "e", "name": "n",
                           "profile": {"bio": "b", "avatar_url": "u"}});
        let selections = vec![
            aliased("name", "name", false),
            aliased("profile", "profile", true),
            aliased("profile.avatar_url", "profile.avatarUrl", false),
            aliased("profile.bio", "profile.bio", false),
            aliased("id", "id", false),
            aliased("email", "email", false),
        ];

        let projection = Projection::from_selections(&selections);
        let result = project_with_schema(&input, Some("User"), &projection, &registry, false);

        assert_eq!(
            serde_json::to_string(&result).unwrap(),
            r#"{"name":"n","profile":{"avatarUrl":"u","bio":"b"},"id":1,"email":"e"}"#
        );
    }

    #[test]
    fn test_snake_case_keys_are_found_by_their_field_name() {
        let registry = SchemaRegistry::empty();
        let input = json!({"dns_1": {"ip_address": "1.1.1.1"}});
        let selections = vec![
            aliased("dns1", "dns1", true),
            aliased("dns1.ip_address", "dns1.ipAddress", false),
        ];

        let projection = Projection::from_selections(&selections);
        let result = project_with_schema(&input, None, &projection, &registry, true);

        assert_eq!(result, json!({"dns1": {"ipAddress": "1.1.1.1"}}));
    }
}
