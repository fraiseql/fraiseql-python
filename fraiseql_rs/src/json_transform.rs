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

use crate::{camel_case::to_camel_case, schema_registry::SchemaRegistry};

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
/// This function applies GraphQL field aliases during transformation.
/// Field selections define which fields to include and what aliases to use.
///
/// # Arguments
/// * `value` - The JSON value to transform
/// * `current_type` - The GraphQL type name for this value
/// * `selections` - Field selections with materialized paths and aliases
/// * `registry` - The schema registry for type lookups
///
/// # Field Selection Format
/// Each selection is a JSON object:
/// ```json
/// {
///   "materialized_path": "user.posts.author_name",
///   "alias": "postAuthor",
///   "type_info": {
///     "type_name": "String",
///     "is_list": false,
///     "is_nested_object": false
///   }
/// }
/// ```
///
/// # Returns
/// Transformed JSON value with:
/// - Aliases applied according to selections
/// - __typename injected at object boundaries
/// - Nested objects resolved via schema registry
///
/// # Examples
/// ```ignore
/// let input = json!({"user_name": "John"});
/// let selections = vec![
///     json!({"materialized_path": "user_name", "alias": "username", ...})
/// ];
/// let result = transform_with_selections(&input, "User", &selections, &registry);
/// // result: {"__typename": "User", "username": "John"}
/// ```
pub fn transform_with_selections(
    value: &Value,
    current_type: &str,
    selections: &[Value],
    registry: &SchemaRegistry,
) -> Value {
    // Build alias map, allowed fields, and selected paths from selections
    let (alias_map, allowed_fields, selected_paths) = build_alias_map(selections);

    // Transform with aliases and field projection applied
    transform_with_aliases(
        value,
        Some(current_type),
        "",
        &alias_map,
        &allowed_fields,
        &selected_paths,
        registry,
    )
}

/// Convert a dot-separated path to full camelCase
///
/// Example: "user_profile.contact_info" → "userProfile.contactInfo"
///
/// Performance: Uses String builder to avoid intermediate Vec allocation
#[inline]
fn to_camel_case_path(path: &str) -> String {
    if !path.contains('_') {
        return path.to_string();
    }

    let mut result = String::with_capacity(path.len());
    let mut segments = path.split('.');

    if let Some(first) = segments.next() {
        result.push_str(&to_camel_case(first));

        for segment in segments {
            result.push('.');
            result.push_str(&to_camel_case(segment));
        }
    }

    result
}

/// Convert a path to partial camelCase (parent segments camelCase, last segment unchanged)
///
/// This matches Python's materialized path format where GraphQL field names (camelCase)
/// are used for parent paths, but database column names (snake_case) for the current field.
///
/// Examples:
/// - "dns_1.ip_address" → "dns1.ip_address" (parent camelCase, child unchanged)
/// - "user.profile.bio" → "user.profile.bio" (no underscores, unchanged)
#[inline]
fn to_partial_camel_case_path(path: &str) -> Option<String> {
    let last_dot = path.rfind('.')?;
    let parent = &path[..last_dot];
    let child = &path[last_dot + 1..];

    if !parent.contains('_') {
        return None; // No conversion needed
    }

    let camel_parent = to_camel_case_path(parent);
    Some(format!("{}.{}", camel_parent, child))
}

/// Check if a selection path matches a field path (exact or prefix match)
///
/// Matches if:
/// 1. Exact match: selection == field_path
/// 2. Prefix match: selection starts with field_path + "." (i.e., selection is a child)
///
/// The byte-level check (`selection.as_bytes()[field_path.len()] == b'.'`) ensures
/// we don't match "userinfo" when checking "user" prefix.
#[inline]
fn path_matches_selection(
    selection: &str,
    field_path: &str,
    camel_field_path: &str,
    partial_camel_path: Option<&str>,
) -> bool {
    // Exact match check for all three variants
    if selection == field_path || selection == camel_field_path {
        return true;
    }

    if let Some(partial) = partial_camel_path {
        if selection == partial {
            return true;
        }
    }

    // Prefix match check (selection is a child of this field)
    for candidate in [field_path, camel_field_path] {
        if selection.len() > candidate.len() + 1
            && selection.starts_with(candidate)
            && selection.as_bytes()[candidate.len()] == b'.'
        {
            return true;
        }
    }

    if let Some(partial) = partial_camel_path {
        if selection.len() > partial.len() + 1
            && selection.starts_with(partial)
            && selection.as_bytes()[partial.len()] == b'.'
        {
            return true;
        }
    }

    false
}

/// Build a mapping from materialized paths to aliases and allowed field names
///
/// **Performance Optimization**: Pre-computes all three path variants (snake_case,
/// camelCase, partial camelCase) and stores them in `selected_paths`. This trades
/// memory (3x HashSet size) for speed (O(1) lookups instead of O(N) path conversions
/// per field).
///
/// Returns a tuple of:
/// - HashMap: materialized path -> alias
/// - HashSet: allowed root-level field names for field projection
/// - HashSet: all selected materialized paths WITH all three variants pre-computed
fn build_alias_map(
    selections: &[Value],
) -> (
    std::collections::HashMap<String, String>,
    std::collections::HashSet<String>,
    std::collections::HashSet<String>,
) {
    let mut alias_map = std::collections::HashMap::new();
    let mut allowed_fields = std::collections::HashSet::new();
    let mut selected_paths = std::collections::HashSet::new();

    for selection in selections {
        // Extract materialized_path (required)
        if let Some(path) = selection.get("materialized_path").and_then(|v| v.as_str()) {
            // **Performance Optimization**: Pre-compute all three path variants upfront
            // This trades memory for speed - we compute paths once here instead of
            // O(N fields) times during transformation.
            //
            // Three variants needed to match Python's materialized paths:
            // 1. Original (snake_case): "dns_1.ip_address" (database column names)
            // 2. Full camelCase: "dns1.ipAddress" (GraphQL response format)
            // 3. Partial camelCase: "dns1.ip_address" (Python's GraphQL field name + db column)
            selected_paths.insert(path.to_string());

            // Add full camelCase variant if path contains underscores
            if path.contains('_') {
                let camel_path = to_camel_case_path(path);
                selected_paths.insert(camel_path);

                // Add partial camelCase variant if it's different from original
                if let Some(partial_path) = to_partial_camel_case_path(path) {
                    selected_paths.insert(partial_path);
                }
            }

            // Extract root-level field name for field projection (always add to allowed_fields)
            // e.g., "profile.bio" -> "profile", "id" -> "id"
            if let Some(first_segment) = path.split('.').next() {
                allowed_fields.insert(first_segment.to_string());
                // Also add camelCase variant of root field
                if first_segment.contains('_') {
                    allowed_fields.insert(to_camel_case(first_segment));
                }
            }

            // Extract alias (optional) - only add to alias_map if present
            if let Some(alias) = selection.get("alias").and_then(|v| v.as_str()) {
                alias_map.insert(path.to_string(), alias.to_string());
            }
        }
    }

    (alias_map, allowed_fields, selected_paths)
}

/// Transform JSON value with alias support and field projection
///
/// This is the core aliasing algorithm that applies GraphQL field aliases during
/// transformation. It recursively traverses the JSON structure, maintaining a
/// materialized path to match against the alias map, and filters fields based on
/// allowed field names for field projection.
///
/// # Algorithm
/// 1. **Path Construction**: Build materialized path as we traverse (e.g.,
///    "user.posts.author_name")
/// 2. **Alias Lookup**: Check if current path has an alias in the map
/// 3. **Field Projection**: Check if field is in allowed set (skip if not)
/// 4. **Key Selection**: Use alias if present, otherwise camelCase
/// 5. **Recursive Transform**: Apply same logic to nested objects/arrays
///
/// # Arguments
/// * `value` - JSON value to transform
/// * `current_type` - GraphQL type name for schema lookup
/// * `current_path` - Materialized path to current position (e.g., "user.posts")
/// * `alias_map` - Precomputed map from paths to aliases
/// * `allowed_fields` - Set of allowed root-level field names (None for no filtering)
/// * `selected_paths` - Set of all selected materialized paths (for nested field filtering)
/// * `registry` - Schema registry for type resolution
///
/// # Performance
/// - O(1) alias lookup via HashMap
/// - O(1) field filtering via HashSet
/// - Single-pass transformation (no backtracking)
/// - Minimal allocations (path string constructed once per field)
fn transform_with_aliases(
    value: &Value,
    current_type: Option<&str>,
    current_path: &str,
    alias_map: &std::collections::HashMap<String, String>,
    allowed_fields: &std::collections::HashSet<String>,
    selected_paths: &std::collections::HashSet<String>,
    registry: &SchemaRegistry,
) -> Value {
    match value {
        Value::Object(map) => {
            // Pre-allocate result map (field count + optional __typename)
            let capacity = if current_type.is_some() {
                map.len() + 1
            } else {
                map.len()
            };
            let mut result = Map::with_capacity(capacity);

            // Inject __typename first (GraphQL convention) if type is known
            if let Some(type_name) = current_type {
                result.insert("__typename".to_string(), Value::String(type_name.to_string()));
            }

            // OPTIMIZATION: Clone map once, then use .remove() to take ownership of values
            // This trades 1 map clone for N field clones (where N = number of fields)
            // For objects with >1 field, this is a net win
            let mut owned_map = map.clone();

            // Transform each field with alias support and field projection
            for key in map.keys() {
                // Build materialized path for this field
                // Example: "" + "user_name" → "user_name"
                //          "user.posts" + "author_name" → "user.posts.author_name"
                let field_path = if current_path.is_empty() {
                    key.to_string()
                } else {
                    format!("{}.{}", current_path, key)
                };

                // Field projection: Check if this field is allowed at current path level
                // At root level: check allowed_fields directly
                // At nested level: check if any selection starts with current path + field
                let is_field_allowed = if current_path.is_empty() {
                    // Root level: check if field is in allowed set
                    allowed_fields.contains(key) || allowed_fields.contains(&to_camel_case(key))
                } else {
                    // Nested level: check if field_path (or any of its variants) is in
                    // selected_paths
                    //
                    // **Performance Optimization**: Since we pre-computed all path variants in
                    // `build_alias_map()`, we can now use simple HashSet lookups instead of
                    // computing variants for every field. This reduces O(N fields × 3 path builds)
                    // to O(N fields × 1 path build).
                    //
                    // The `path_matches_selection` helper checks:
                    // 1. Exact match: field_path is in selected_paths
                    // 2. Prefix match: any selected path is a child of field_path
                    //
                    // We only need to build camel_field_path and partial_camel_path here
                    // because we're checking against the pre-computed set.
                    let camel_field_path = to_camel_case_path(&field_path);
                    let partial_camel_path = to_partial_camel_case_path(&field_path);

                    selected_paths.iter().any(|selection| {
                        path_matches_selection(
                            selection,
                            &field_path,
                            &camel_field_path,
                            partial_camel_path.as_deref(),
                        )
                    })
                };

                if !is_field_allowed {
                    continue;
                }

                // Determine output key: alias or camelCase
                // If alias is "user.posts.writerName", extract "writerName"
                let output_key = if let Some(alias) = alias_map.get(&field_path) {
                    // Extract final segment after last '.' (handles nested paths)
                    alias.rsplit('.').next().unwrap_or(alias).to_string()
                } else {
                    // No alias - default to camelCase transformation
                    to_camel_case(key)
                };

                // Transform value based on schema type
                let field_type_opt =
                    current_type.and_then(|type_name| registry.get_field_type(type_name, key));

                let transformed_val = match field_type_opt {
                    Some(field_info) if field_info.is_nested_object() => {
                        // Nested object or array - recursively transform with updated path
                        // Still need to borrow here for nested transformation
                        let val = owned_map.get(key).unwrap();
                        transform_nested_field_with_aliases(
                            val,
                            Some(field_info.type_name()),
                            field_info.is_list(),
                            &field_path,
                            alias_map,
                            allowed_fields,
                            selected_paths,
                            registry,
                        )
                    },
                    Some(_) => {
                        // Scalar field - take ownership, no clone needed!
                        owned_map.remove(key).unwrap()
                    },
                    None => {
                        // Field not in schema
                        // Check if we have nested selections for this field in selected_paths
                        let has_nested_selections = selected_paths.iter().any(|path| {
                            path.len() > field_path.len() + 1
                                && path.starts_with(&field_path)
                                && path.as_bytes()[field_path.len()] == b'.'
                        });

                        if has_nested_selections {
                            // Field has nested selections, so recursively transform with filtering
                            let val = owned_map.get(key).unwrap();
                            // Determine if it's a list by checking the value type
                            let is_list = matches!(val, Value::Array(_));
                            // Type not in schema - pass None to skip __typename injection
                            transform_nested_field_with_aliases(
                                val,
                                None,
                                is_list,
                                &field_path,
                                alias_map,
                                allowed_fields,
                                selected_paths,
                                registry,
                            )
                        } else {
                            // No nested selections - use generic transformation
                            transform_value(owned_map.remove(key).unwrap())
                        }
                    },
                };

                result.insert(output_key, transformed_val);
            }

            Value::Object(result)
        },
        Value::Null => Value::Null,
        other => other.clone(),
    }
}

/// Helper to transform nested fields (objects and arrays) with alias support and field projection
///
/// Extracted to reduce code duplication between list and single object cases.
#[inline]
#[allow(clippy::too_many_arguments)] // Reason: all args are distinct and required by the transform logic
fn transform_nested_field_with_aliases(
    value: &Value,
    nested_type: Option<&str>,
    is_list: bool,
    current_path: &str,
    alias_map: &std::collections::HashMap<String, String>,
    allowed_fields: &std::collections::HashSet<String>,
    selected_paths: &std::collections::HashSet<String>,
    registry: &SchemaRegistry,
) -> Value {
    if is_list {
        // Array of nested objects - map over items
        match value {
            Value::Array(items) => {
                let transformed_items: Vec<Value> = items
                    .iter()
                    .map(|item| match item {
                        Value::Null => Value::Null,
                        _ => transform_with_aliases(
                            item,
                            nested_type,
                            current_path,
                            alias_map,
                            allowed_fields,
                            selected_paths,
                            registry,
                        ),
                    })
                    .collect();
                Value::Array(transformed_items)
            },
            Value::Null => Value::Null,
            _ => value.clone(), // Unexpected type - pass through
        }
    } else {
        // Single nested object
        match value {
            Value::Null => Value::Null,
            _ => transform_with_aliases(
                value,
                nested_type,
                current_path,
                alias_map,
                allowed_fields,
                selected_paths,
                registry,
            ),
        }
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
}
