//! Pipeline response builder for GraphQL responses
//!
//! This module provides the high-level API for building complete GraphQL
//! responses from PostgreSQL JSON rows using schema-aware transformation.

use pyo3::prelude::*;
use serde_json::{Value, json};

use crate::{
    core::{
        arena::Arena,
        transform::{ByteBuf, MAX_JSON_DEPTH, TransformConfig, ZeroCopyTransformer},
    },
    json_transform,
    pipeline::projection::FieldSet,
    schema_registry,
};

/// Type alias for multi-field response field definition.
///
/// Represents a single field in a multi-field GraphQL query response:
/// - String: field_name (e.g., "users")
/// - String: type_name (e.g., "User")
/// - Vec<String>: json_rows (raw JSON from database)
/// - Option<String>: field_selections (JSON-encoded field selection metadata)
/// - Option<bool>: is_list (whether field returns list or single object)
type MultiFieldDef = (String, String, Vec<String>, Option<String>, Option<bool>);

/// Build complete GraphQL response from PostgreSQL JSON rows
///
/// This is the TOP-LEVEL API called from lib.rs (FFI layer):
/// ```rust
/// let response_bytes = pipeline::builder::build_graphql_response(
///     json_rows,
///     field_name,
///     type_name,
///     field_paths,
///     field_selections,
/// )
/// ```
///
/// Pipeline:
/// ┌──────────────┐
/// │ PostgreSQL   │ → JSON strings (already in memory)
/// │ json_rows    │
/// └──────┬───────┘
///        │
///        ▼
/// ┌──────────────┐
/// │ Arena        │ → Allocate scratch space
/// │ Setup        │
/// └──────┬───────┘
///        │
///        ▼
/// ┌──────────────┐
/// │ Estimate     │ → Size output buffer (eliminate reallocs)
/// │ Capacity     │
/// └──────┬───────┘
///        │
///        ▼
/// ┌──────────────┐
/// │ Zero-Copy    │ → Transform each row (no parsing!)
/// │ Transform    │    - Wrap in GraphQL structure
/// └──────┬───────┘    - Project fields
///        │            - Add __typename
///        │            - CamelCase keys
///        │            - Apply aliases
///        ▼
/// ┌──────────────┐
/// │ HTTP Bytes   │ → Return to Python (zero-copy)
/// │ (Vec<u8>)    │
/// └──────────────┘
pub fn build_graphql_response(
    json_rows: Vec<String>,
    field_name: &str,
    type_name: Option<&str>,
    field_paths: Option<Vec<Vec<String>>>,
    field_selections: Option<Vec<Value>>,
    is_list: Option<bool>,
    include_graphql_wrapper: Option<bool>,
) -> PyResult<Vec<u8>> {
    let registry = schema_registry::get_registry();

    if schema_registry::is_initialized() {
        if let Some(type_name_str) = type_name {
            return build_with_schema(
                json_rows,
                field_name,
                type_name_str,
                field_paths,
                field_selections,
                &registry,
                is_list,
                include_graphql_wrapper,
            );
        }
    }

    build_zero_copy(json_rows, field_name, type_name, field_paths, is_list, include_graphql_wrapper)
}

/// Transform JSON rows using schema registry and build GraphQL response.
///
/// This internal function handles schema-aware transformation with optional
/// field selections. The parameters are grouped as received from the caller
/// (build_graphql_response) to maintain API clarity.
#[allow(clippy::too_many_arguments)]
fn build_with_schema(
    json_rows: Vec<String>,
    field_name: &str,
    type_name: &str,
    _field_paths: Option<Vec<Vec<String>>>,
    field_selections: Option<Vec<Value>>,
    registry: &schema_registry::SchemaRegistry,
    is_list: Option<bool>,
    include_graphql_wrapper: Option<bool>,
) -> PyResult<Vec<u8>> {
    let transformed_items: Result<Vec<Value>, _> = json_rows
        .iter()
        .map(|row_str| {
            serde_json::from_str::<Value>(row_str)
                .map_err(|e| {
                    pyo3::exceptions::PyValueError::new_err(format!("Failed to parse JSON: {}", e))
                })
                .map(|value| {
                    if let Some(ref selections) = field_selections {
                        json_transform::transform_with_selections(
                            &value, type_name, selections, registry,
                        )
                    } else {
                        json_transform::transform_with_schema(&value, type_name, registry)
                    }
                })
        })
        .collect();

    let transformed_items = transformed_items?;

    // Check if we should include GraphQL wrapper (defaults to true for backward compatibility)
    let include_wrapper = include_graphql_wrapper.unwrap_or(true);

    if !include_wrapper {
        // Field-only mode: return just the array/object data without GraphQL wrapper
        // Used for multi-field queries where graphql-core handles the merging
        let field_data = if is_list.unwrap_or(true) {
            Value::Array(transformed_items)
        } else if !transformed_items.is_empty() {
            transformed_items.first().cloned().unwrap_or(Value::Null)
        } else {
            Value::Array(vec![])
        };

        return serde_json::to_vec(&field_data).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!(
                "Failed to serialize field data: {}",
                e
            ))
        });
    }

    // Standard mode: wrap in GraphQL response structure
    // Respect is_list parameter (defaults to true for backward compatibility)
    // When true: wrap in array regardless of item count
    // When false: return single unwrapped object
    let response_data = if is_list.unwrap_or(true) {
        json!({
            "data": {
                field_name: transformed_items
            }
        })
    } else if !transformed_items.is_empty() {
        json!({
            "data": {
                field_name: transformed_items.first().cloned().unwrap_or(Value::Null)
            }
        })
    } else {
        // Empty result for is_list=False: return [] so Python null detection works
        json!({
            "data": {
                field_name: Value::Array(vec![])
            }
        })
    };

    serde_json::to_vec(&response_data).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("Failed to serialize response: {}", e))
    })
}

fn build_zero_copy(
    json_rows: Vec<String>,
    field_name: &str,
    type_name: Option<&str>,
    field_paths: Option<Vec<Vec<String>>>,
    is_list: Option<bool>,
    include_graphql_wrapper: Option<bool>,
) -> PyResult<Vec<u8>> {
    let arena = Arena::with_capacity(estimate_arena_size(&json_rows));

    let config = TransformConfig {
        add_typename:        type_name.is_some(),
        camel_case:          true,
        project_fields:      field_paths.is_some(),
        add_graphql_wrapper: false,
        max_depth:           MAX_JSON_DEPTH,
    };

    let field_set = field_paths.map(|paths| FieldSet::from_paths(&paths, &arena));

    let mut transformer = ZeroCopyTransformer::new(&arena, config, type_name, field_set.as_ref());

    let total_input_size: usize = json_rows.iter().map(|s| s.len()).sum();

    // Check if we should include GraphQL wrapper (defaults to true for backward compatibility)
    let include_wrapper = include_graphql_wrapper.unwrap_or(true);

    let wrapper_overhead = if include_wrapper {
        50 + field_name.len()
    } else {
        10 // Just for array brackets/object
    };
    let estimated_size = total_input_size + wrapper_overhead;

    let mut result = Vec::with_capacity(estimated_size);

    // Field-only mode: Build just the array/object data without GraphQL wrapper
    // Used for multi-field queries where graphql-core handles the merging
    if !include_wrapper {
        // Respect is_list parameter (defaults to true for backward compatibility)
        if is_list.unwrap_or(true) {
            result.push(b'[');

            for (i, row) in json_rows.iter().enumerate() {
                let mut temp_buf = ByteBuf::with_estimated_capacity(row.len(), &config);
                transformer.transform_bytes(row.as_bytes(), &mut temp_buf)?;
                result.extend_from_slice(&temp_buf.into_vec());

                if i < json_rows.len() - 1 {
                    result.push(b',');
                }
            }

            result.push(b']');
        } else if !json_rows.is_empty() {
            let row = &json_rows[0];
            let mut temp_buf = ByteBuf::with_estimated_capacity(row.len(), &config);
            transformer.transform_bytes(row.as_bytes(), &mut temp_buf)?;
            result.extend_from_slice(&temp_buf.into_vec());
        } else {
            // Empty result for is_list=False: return [] so Python null detection works
            result.extend_from_slice(b"[]");
        }

        return Ok(result);
    }

    // Standard mode: Build GraphQL response: {"data":{"<field_name>":<content>}}
    result.extend_from_slice(b"{\"data\":{\"");
    result.extend_from_slice(field_name.as_bytes());
    result.extend_from_slice(b"\":");

    // Respect is_list parameter (defaults to true for backward compatibility)
    // When true: wrap transformed items in array
    // When false: return single unwrapped item
    if is_list.unwrap_or(true) {
        result.push(b'[');

        for (i, row) in json_rows.iter().enumerate() {
            let mut temp_buf = ByteBuf::with_estimated_capacity(row.len(), &config);
            transformer.transform_bytes(row.as_bytes(), &mut temp_buf)?;
            result.extend_from_slice(&temp_buf.into_vec());

            if i < json_rows.len() - 1 {
                result.push(b',');
            }
        }

        result.push(b']');
    } else if !json_rows.is_empty() {
        let row = &json_rows[0];
        let mut temp_buf = ByteBuf::with_estimated_capacity(row.len(), &config);
        transformer.transform_bytes(row.as_bytes(), &mut temp_buf)?;
        result.extend_from_slice(&temp_buf.into_vec());
    } else {
        // Empty result for is_list=False: return [] so Python null detection works
        result.extend_from_slice(b"[]");
    }

    result.push(b'}');
    result.push(b'}');

    Ok(result)
}

fn estimate_arena_size(json_rows: &[String]) -> usize {
    let total_input_size: usize = json_rows.iter().map(|s| s.len()).sum();
    (total_input_size / 4).clamp(8192, 65536)
}

/// Build complete multi-field GraphQL response from PostgreSQL JSON rows
///
/// This function handles multi-field queries entirely in Rust, bypassing graphql-core
/// to avoid type validation errors. It processes multiple root fields and combines
/// them into a single {"data": {...}} response.
///
/// Pipeline:
/// ```
/// Fields: [
///   ("dnsServers", "DnsServer", [...rows...], selections),
///   ("gateways", "Gateway", [...rows...], selections)
/// ]
///     ↓
/// For each field:
///   - Parse field_selections JSON
///   - Transform rows with schema
///   - Build field array/object
///     ↓
/// Combine into: {"data": {"dnsServers": [...], "gateways": [...]}}
///     ↓
/// Return as UTF-8 bytes
/// ```
///
/// Args:
///     fields: List of (field_name, type_name, json_rows, field_selections, is_list)
///
/// Returns:
///     Complete GraphQL response as UTF-8 bytes
pub fn build_multi_field_response(fields: Vec<MultiFieldDef>) -> PyResult<Vec<u8>> {
    let registry = schema_registry::get_registry();

    // Build the response object
    let mut data_obj = serde_json::Map::new();

    // Process each field
    for (field_name, type_name, json_rows, field_selections, is_list) in fields {
        // Parse field selections if provided
        let selections_json = match field_selections {
            Some(json_str) if !json_str.is_empty() => serde_json::from_str::<Vec<Value>>(&json_str)
                .map_err(|e| {
                    pyo3::exceptions::PyValueError::new_err(format!(
                        "Invalid field_selections JSON for field '{}': {}",
                        field_name, e
                    ))
                })?,
            _ => Vec::new(),
        };

        let selections_opt = if selections_json.is_empty() {
            None
        } else {
            Some(selections_json)
        };

        // Transform rows for this field
        let transformed_items: Result<Vec<Value>, _> = json_rows
            .iter()
            .map(|row_str| {
                serde_json::from_str::<Value>(row_str)
                    .map_err(|e| {
                        pyo3::exceptions::PyValueError::new_err(format!(
                            "Failed to parse JSON for field '{}': {}",
                            field_name, e
                        ))
                    })
                    .map(|value| {
                        if let Some(ref selections) = selections_opt {
                            json_transform::transform_with_selections(
                                &value, &type_name, selections, &registry,
                            )
                        } else {
                            json_transform::transform_with_schema(&value, &type_name, &registry)
                        }
                    })
            })
            .collect();

        let transformed_items = transformed_items?;

        // Build field data (array or single object based on is_list)
        let field_data = if is_list.unwrap_or(true) {
            Value::Array(transformed_items)
        } else if !transformed_items.is_empty() {
            transformed_items.first().cloned().unwrap_or(Value::Null)
        } else {
            Value::Null
        };

        // Add to response data
        data_obj.insert(field_name, field_data);
    }

    // Build complete response: {"data": {...}}
    let response = json!({
        "data": Value::Object(data_obj)
    });

    // Serialize to UTF-8 bytes
    serde_json::to_vec(&response).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!(
            "Failed to serialize multi-field response: {}",
            e
        ))
    })
}
