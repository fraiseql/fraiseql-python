//! GraphQL Response Builder
//!
//! Builds GraphQL-compliant Success and Error responses from mutation results.

#![allow(clippy::excessive_nesting)] // TODO Phase 4.1: Refactor nested blocks

use serde_json::{Map, Value, json};

use super::{MutationResult, MutationStatus, filter_entity_fields};
use crate::camel_case::to_camel_case;

/// Build GraphQL response from mutation result
///
/// This is the main entry point that dispatches to success or error builders
/// based on the mutation status.
#[allow(clippy::too_many_arguments)]
pub fn build_graphql_response(
    result: &MutationResult,
    field_name: &str,
    success_type: &str,
    error_type: &str,
    entity_field_name: Option<&str>,
    _entity_type: Option<&str>,
    auto_camel_case: bool,
    success_type_fields: Option<&Vec<String>>,
    error_type_fields: Option<&Vec<String>>,
    cascade_selections: Option<&str>,
    entity_selections: Option<&str>,
) -> Result<Value, String> {
    // Success status returns Success type, all others return Error type
    let response_obj = if result.status.is_success() {
        build_success_response(
            result,
            success_type,
            entity_field_name,
            auto_camel_case,
            success_type_fields,
            cascade_selections,
            entity_selections,
        )?
    } else {
        // NEW: Error response includes REST-like code
        // For error responses, use error_type_fields for field selection
        build_error_response_with_code(
            result,
            error_type,
            auto_camel_case,
            error_type_fields, // Use error type field selection
            cascade_selections,
            entity_selections, // Also support entity filtering in error responses
        )?
    };

    // Wrap in GraphQL response structure
    Ok(json!({
        "data": {
            field_name: response_obj
        }
    }))
}

/// Add cascade to response object if selected in GraphQL query
fn add_cascade_if_selected(
    obj: &mut Map<String, Value>,
    result: &MutationResult,
    cascade_selections: Option<&str>,
    auto_camel_case: bool,
) -> Result<(), String> {
    let Some(cascade) = &result.cascade else {
        return Ok(());
    };

    let Some(selections_json) = cascade_selections else {
        return Ok(());
    };

    let selections: crate::mutation::CascadeSelections = serde_json::from_str(selections_json)
        .map_err(|e| format!("Invalid CASCADE selections JSON: {}", e))?;

    let filtered_cascade =
        crate::mutation::filter_cascade_by_selections(cascade, &selections, auto_camel_case)?;

    obj.insert("cascade".to_string(), filtered_cascade);

    Ok(())
}

/// Build success response object
///
/// Key behaviors:
/// - CASCADE at success level (sibling to entity, NOT nested inside entity)
/// - Entity field name derived from entity_type or explicit parameter
/// - Wrapper fields promoted to success level
/// - __typename added to response and entity
/// - camelCase applied if requested
/// - Entity fields filtered based on GraphQL selections (GitHub issue #525)
#[allow(clippy::too_many_arguments)]
pub fn build_success_response(
    result: &MutationResult,
    success_type: &str,
    entity_field_name: Option<&str>,
    auto_camel_case: bool,
    success_type_fields: Option<&Vec<String>>,
    cascade_selections: Option<&str>,
    entity_selections: Option<&str>,
) -> Result<Value, String> {
    let mut obj = Map::new();

    // Add __typename (always included, special GraphQL field)
    obj.insert("__typename".to_string(), json!(success_type));

    // Check if field selection filtering is active
    let should_filter = success_type_fields.is_some();
    let empty_vec = Vec::new();
    let selected_fields = success_type_fields.unwrap_or(&empty_vec);

    // Helper function to check if field is selected
    let is_selected = |field_name: &str| -> bool {
        !should_filter || selected_fields.contains(&field_name.to_string())
    };

    // Add id from entity_id if present AND selected
    if is_selected("id") {
        if let Some(ref entity_id) = result.entity_id {
            obj.insert("id".to_string(), json!(entity_id));
        }
    }

    // Add message if selected
    if is_selected("message") {
        obj.insert("message".to_string(), json!(result.message));
    }

    // Add status if selected
    if is_selected("status") {
        obj.insert("status".to_string(), json!(result.status.to_string()));
    }

    // Success types do not have errors field
    // Only Error types include errors array

    // Success type requires non-null entity
    if result.entity.is_none() {
        return Err(format!(
            "Success type '{}' requires non-null entity. \
             Status '{}' returned null entity. \
             This indicates a logic error: non-success statuses (noop:*, failed:*, etc.) \
             should return Error type, not Success type.",
            success_type, result.status
        ));
    }

    // Add entity with __typename and camelCase keys ONLY if selected
    if let Some(entity) = &result.entity {
        let entity_type = result.entity_type.as_deref().unwrap_or("Entity");

        // Determine the field name for the entity in the response
        let field_name = entity_field_name
            .map(|name| {
                // Convert entity_field_name based on auto_camel_case flag
                if auto_camel_case {
                    to_camel_case(name)
                } else {
                    name.to_string()
                }
            })
            .unwrap_or_else(|| {
                // No entity_field_name provided, derive from type
                if auto_camel_case {
                    to_camel_case(&entity_type.to_lowercase())
                } else {
                    entity_type.to_lowercase()
                }
            });

        // Only add entity if the field is selected
        if is_selected(&field_name) {
            // Check if entity is a wrapper object containing entity_field_name
            // This happens when Python entity_flattener skips flattening (CASCADE case)
            // The entity looks like: {"post": {...}, "message": "..."}
            let actual_entity = if let Value::Object(entity_map) = entity {
                // Check if the entity wrapper contains a field matching entity_field_name
                if let Some(entity_field_name_raw) = entity_field_name {
                    if let Some(nested_entity) = entity_map.get(entity_field_name_raw) {
                        // Found nested entity - extract it
                        nested_entity
                    } else {
                        // No nested field, use entire entity
                        entity
                    }
                } else {
                    // No entity_field_name hint, use entire entity
                    entity
                }
            } else {
                // Entity is not an object (array or primitive), use as-is
                entity
            };

            let mut transformed = transform_entity(actual_entity, entity_type, auto_camel_case);

            // Apply entity field filtering if selections provided (GitHub issue #525)
            if let Some(selections_json) = entity_selections {
                // Parse selections JSON
                if let Ok(selections) = serde_json::from_str::<Value>(selections_json) {
                    // Filter entity fields based on GraphQL query
                    transformed = filter_entity_fields(&transformed, &selections);
                }
                // If parsing fails, silently skip filtering (backward compat)
            }

            obj.insert(field_name, transformed);

            // If entity was a wrapper, copy other fields from it (like "message")
            // But only if those fields are also selected
            if let Value::Object(entity_map) = entity {
                if let Some(entity_field_name_raw) = entity_field_name {
                    if entity_map.contains_key(entity_field_name_raw) {
                        // Entity was a wrapper - copy other fields
                        for (key, value) in entity_map {
                            if key != entity_field_name_raw && key != "entity" && key != "cascade" {
                                // Don't copy the entity field itself, nested "entity", or CASCADE
                                // CASCADE must only appear at success type level, never in entity
                                let field_key = if auto_camel_case {
                                    to_camel_case(key)
                                } else {
                                    key.clone()
                                };
                                // Only add if not already present AND field is selected
                                if !obj.contains_key(&field_key) && is_selected(&field_key) {
                                    obj.insert(field_key, transform_value(value, auto_camel_case));
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Add updatedFields (convert to camelCase) if selected
    if is_selected("updatedFields") {
        if let Some(fields) = &result.updated_fields {
            let transformed_fields: Vec<Value> = fields
                .iter()
                .map(|f| {
                    json!(if auto_camel_case {
                        to_camel_case(f)
                    } else {
                        f.to_string()
                    })
                })
                .collect();
            obj.insert("updatedFields".to_string(), json!(transformed_fields));
        }
    }

    // Add cascade if present AND requested in selection
    add_cascade_if_selected(&mut obj, result, cascade_selections, auto_camel_case)?;

    // Phase 3: Schema validation - check that all expected fields are present
    if let Some(expected_fields) = success_type_fields {
        let mut missing_fields = Vec::new();
        let mut extra_fields = Vec::new();

        // Check for missing expected fields
        for field in expected_fields {
            if !obj.contains_key(field) {
                missing_fields.push(field.clone());
            }
        }

        // Check for unexpected fields (warn about them)
        for key in obj.keys() {
            if !expected_fields.contains(key) && !key.starts_with("__") {
                // Allow special fields like __typename
                extra_fields.push(key.clone());
            }
        }

        // Report validation results
        if !missing_fields.is_empty() {
            eprintln!(
                "Schema validation warning: Missing expected fields in {}: {:?}",
                success_type, missing_fields
            );
        }

        if !extra_fields.is_empty() {
            eprintln!(
                "Schema validation warning: Extra fields in {} not in schema: {:?}",
                success_type, extra_fields
            );
        }
    }

    Ok(Value::Object(obj))
}

/// Build error response object with REST-like code field
///
/// Key behaviors:
/// - Adds `code` field (422, 404, 409, 500) for DX
/// - Preserves `status` field (domain semantics)
/// - Includes `message` field (human-readable)
/// - Adds CASCADE if selected
/// - HTTP 200 OK at transport layer (code is application-level only)
pub fn build_error_response_with_code(
    result: &MutationResult,
    error_type: &str,
    auto_camel_case: bool,
    error_type_fields: Option<&Vec<String>>,
    cascade_selections: Option<&str>,
    entity_selections: Option<&str>,
) -> Result<Value, String> {
    // DEBUG: Log function call and parameters
    eprintln!("\n╔══════════════════════════════════════════════════════════════╗");
    eprintln!("║ DEBUG: build_error_response_with_code() called              ║");
    eprintln!("╠══════════════════════════════════════════════════════════════╣");
    eprintln!("  error_type: {}", error_type);
    eprintln!("  auto_camel_case: {}", auto_camel_case);
    eprintln!("  error_type_fields: {:?}", error_type_fields);
    eprintln!("  result.status: {}", result.status);
    eprintln!("  result.message: {:?}", result.message);
    eprintln!(
        "  result.entity: {}",
        if result.entity.is_some() {
            "Some(...)"
        } else {
            "None"
        }
    );
    eprintln!("╚══════════════════════════════════════════════════════════════╝\n");

    let mut obj = Map::new();

    // Add __typename (always included, special GraphQL field)
    obj.insert("__typename".to_string(), json!(error_type));

    // Check if field selection filtering is active
    let should_filter = error_type_fields.is_some();
    let empty_vec = Vec::new();
    let selected_fields = error_type_fields.unwrap_or(&empty_vec);

    eprintln!("  ├─ should_filter: {}", should_filter);
    eprintln!("  └─ selected_fields: {:?}", selected_fields);

    // Helper function to check if field is selected
    let is_selected = |field_name: &str| -> bool {
        let result = !should_filter || selected_fields.contains(&field_name.to_string());
        eprintln!("    is_selected(\"{}\"): {}", field_name, result);
        result
    };

    // Add REST-like code field (always included for compatibility)
    // The code field is required by mutation response spec
    // Even if not explicitly selected in GraphQL query, we must include it
    let code = result.status.application_code();
    obj.insert("code".to_string(), json!(code));
    eprintln!("    ✓ Added 'code': {}", code);

    // Add status if selected
    if is_selected("status") {
        obj.insert("status".to_string(), json!(result.status.to_string()));
        eprintln!("    ✓ Added 'status': {}", result.status);
    } else {
        eprintln!("    ✗ Skipped 'status' (not selected)");
    }

    // Add message if selected
    if is_selected("message") {
        obj.insert("message".to_string(), json!(result.message));
        eprintln!("    ✓ Added 'message': {:?}", result.message);
    } else {
        eprintln!("    ✗ Skipped 'message' (not selected)");
    }

    // Add errors array if selected
    if is_selected("errors") {
        let errors = generate_errors_array(result, result.status.application_code())?;
        obj.insert("errors".to_string(), errors);
    }

    // Extract entity fields from wrapper (same pattern as Success types)
    // For Error types, copy all fields from entity wrapper to root level
    // This enables patterns like: conflict_machine, current_user, etc.
    if let Some(Value::Object(entity_map)) = &result.entity {
        // Copy all fields from wrapper (excluding special fields)
        for (key, value) in entity_map {
            if key != "entity" && key != "cascade" {
                // Don't copy nested "entity" or CASCADE
                // CASCADE must only appear at error type level, never in entity
                let field_key = if auto_camel_case {
                    to_camel_case(key)
                } else {
                    key.clone()
                };
                // Only add if not already present AND field is selected
                if !obj.contains_key(&field_key) && is_selected(&field_key) {
                    let mut transformed_value = transform_value(value, auto_camel_case);

                    // Apply entity field filtering if selections provided (GitHub issue #525)
                    // Check if this field might be an entity object (has selections defined)
                    if let Some(selections_json) = entity_selections {
                        if let Ok(selections_obj) = serde_json::from_str::<Value>(selections_json) {
                            // Check if there are selections for this specific field
                            if let Some(selections) = selections_obj.as_object() {
                                if selections.contains_key(key) {
                                    // This field has specific selections - apply filtering
                                    if let Some(field_selections) = selections.get(key) {
                                        transformed_value = filter_entity_fields(
                                            &transformed_value,
                                            field_selections,
                                        );
                                    }
                                }
                            }
                        }
                    }

                    obj.insert(field_key, transformed_value);
                }
            }
        }
    }

    // Add cascade if present AND requested in selection
    add_cascade_if_selected(&mut obj, result, cascade_selections, auto_camel_case)?;

    Ok(Value::Object(obj))
}

/// Generate errors array for error responses
///
/// Priority order:
/// 1. Use explicit errors from metadata.errors if present
/// 2. Auto-generate single error from status string
pub fn generate_errors_array(result: &MutationResult, code: i32) -> Result<Value, String> {
    // Check if explicit errors provided in metadata.errors
    if let Some(metadata) = &result.metadata {
        if let Some(explicit_errors) = metadata.get("errors") {
            // Use explicit errors from database
            return Ok(explicit_errors.clone());
        }
    }

    // Auto-generate single error from status string
    let identifier = extract_identifier_from_status(&result.status);
    Ok(json!([{
        "code": code,
        "identifier": identifier,
        "message": result.message,
        "details": null
    }]))
}

/// Extract error identifier from mutation status
///
/// Examples:
/// - "noop:already_exists" -> "already_exists"
/// - "validation:invalid_input" -> "invalid_input"
/// - "not_found:user_missing" -> "user_missing"
/// - "failed" -> "general_error"
pub fn extract_identifier_from_status(status: &MutationStatus) -> String {
    match status {
        MutationStatus::Noop(reason) => {
            // Extract part after colon: "noop:already_exists" -> "already_exists"
            if let Some((_prefix, identifier)) = reason.split_once(':') {
                identifier.to_string()
            } else {
                "general_error".to_string()
            }
        },
        MutationStatus::Error(reason) => {
            // Extract part after colon: "validation:invalid_input" -> "invalid_input"
            if let Some((_prefix, identifier)) = reason.split_once(':') {
                identifier.to_string()
            } else {
                "general_error".to_string()
            }
        },
        MutationStatus::Success(_) => {
            // Should never reach here (only errors call this function)
            "unexpected_success".to_string()
        },
    }
}

/// Transform entity: add __typename and convert keys to camelCase
fn transform_entity(entity: &Value, entity_type: &str, auto_camel_case: bool) -> Value {
    match entity {
        Value::Object(map) => {
            let mut result = Map::with_capacity(map.len() + 1);

            // Add __typename first
            result.insert("__typename".to_string(), json!(entity_type));

            // Transform each field to camelCase
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
        Value::Array(arr) => Value::Array(
            arr.iter().map(|v| transform_entity(v, entity_type, auto_camel_case)).collect(),
        ),
        other => other.clone(),
    }
}

/// Transform value: convert keys to camelCase (no __typename)
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
            Value::Array(arr.iter().map(|v| transform_value(v, auto_camel_case)).collect())
        },
        other => other.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mutation::MutationResult;

    #[test]
    fn test_build_success_simple() {
        let result = MutationResult {
            status:           MutationStatus::Success("success".to_string()),
            message:          "Success".to_string(),
            entity_id:        Some("123".to_string()),
            entity_type:      Some("User".to_string()),
            entity:           Some(json!({"id": "123", "name": "John"})),
            updated_fields:   None,
            cascade:          None,
            metadata:         None,
            is_simple_format: false,
        };

        let response =
            build_success_response(&result, "CreateUserSuccess", Some("user"), true, None, None)
                .unwrap();
        let obj = response.as_object().unwrap();

        assert_eq!(obj["__typename"], "CreateUserSuccess");
        assert_eq!(obj["id"], "123");
        assert_eq!(obj["message"], "Success");
        assert!(obj.contains_key("user"));
        assert_eq!(obj["user"]["__typename"], "User");
        assert_eq!(obj["user"]["id"], "123");
        assert_eq!(obj["user"]["name"], "John");
    }

    #[test]
    fn test_build_success_with_cascade() {
        let result = MutationResult {
            status:           MutationStatus::Success("created".to_string()),
            message:          "User created".to_string(),
            entity_id:        None,
            entity_type:      Some("User".to_string()),
            entity:           Some(json!({"id": "123", "name": "John"})),
            updated_fields:   None,
            cascade:          Some(json!({"updated": []})),
            metadata:         None,
            is_simple_format: false,
        };

        let response =
            build_success_response(&result, "CreateUserSuccess", Some("user"), true, None, None)
                .unwrap();
        let obj = response.as_object().unwrap();

        // CASCADE at success level
        assert!(obj.contains_key("cascade"));
        assert_eq!(obj["cascade"]["__typename"], "Cascade");
        assert!(obj["cascade"]["updated"].is_array());

        // NOT in entity
        assert!(!obj["user"].as_object().unwrap().contains_key("cascade"));
    }

    #[test]
    fn test_wrapper_fields_promoted() {
        let result = MutationResult {
            status:           MutationStatus::Success("success".to_string()),
            message:          "Success".to_string(),
            entity_id:        None,
            entity_type:      Some("Post".to_string()),
            entity:           Some(
                json!({"post": {"id": "456", "title": "Hello"}, "message": "Created"}),
            ),
            updated_fields:   None,
            cascade:          None,
            metadata:         None,
            is_simple_format: false,
        };

        let response =
            build_success_response(&result, "CreateUserSuccess", Some("user"), true, None, None)
                .unwrap();
        let obj = response.as_object().unwrap();

        // Entity extracted and has __typename
        assert_eq!(obj["post"]["__typename"], "Post");
        assert_eq!(obj["post"]["id"], "456");
        assert_eq!(obj["post"]["title"], "Hello");

        // Wrapper field promoted to success level
        assert_eq!(obj["message"], "Created");
    }

    #[test]
    fn test_build_error() {
        let result = MutationResult {
            status:           MutationStatus::Error("validation:invalid_email".to_string()),
            message:          "Validation failed".to_string(),
            entity_id:        None,
            entity_type:      None,
            entity:           None,
            updated_fields:   None,
            cascade:          None,
            metadata:         Some(
                json!({"errors": [{"field": "email", "code": "invalid", "message": "Invalid email"}]}),
            ),
            is_simple_format: false,
        };

        let response =
            build_error_response_with_code(&result, "CreateUserError", true, None, None).unwrap();
        let obj = response.as_object().unwrap();

        assert_eq!(obj["__typename"], "CreateUserError");
        assert_eq!(obj["message"], "Validation failed");
        assert_eq!(obj["status"], "validation:invalid_email");
        assert_eq!(obj["code"], 422); // HTTP code for validation error

        let errors = obj["errors"].as_array().unwrap();
        assert_eq!(errors.len(), 1);
        assert_eq!(errors[0]["field"], "email");
        assert_eq!(errors[0]["code"], "invalid");
    }

    #[test]
    fn test_error_code_extraction() {
        let result = MutationResult {
            status:           MutationStatus::Error("validation:invalid_input".to_string()),
            message:          "Validation failed".to_string(),
            entity_id:        None,
            entity_type:      None,
            entity:           None,
            updated_fields:   None,
            cascade:          None,
            metadata:         None, // No errors in metadata
            is_simple_format: false,
        };

        let response =
            build_error_response_with_code(&result, "CreateUserError", true, None, None).unwrap();
        let obj = response.as_object().unwrap();

        // Auto-generated error with extracted code
        let errors = obj["errors"].as_array().unwrap();
        assert_eq!(errors.len(), 1);
        assert_eq!(errors[0]["code"], "invalid_input");
        assert_eq!(errors[0]["message"], "Validation failed");
    }

    #[test]
    fn test_http_code_mapping() {
        // Test semantic prefixes map to correct HTTP codes
        let test_cases = vec![
            ("not_found:user_missing", 404),
            ("validation:invalid_input", 422),
            ("unauthorized:token_expired", 401),
            ("forbidden:insufficient_permissions", 403),
            ("conflict:duplicate_email", 409),
            ("timeout:database_timeout", 408),
            ("failed:database_error", 500),
        ];

        for (status_str, expected_code) in test_cases {
            let result = MutationResult {
                status:           MutationStatus::Error(status_str.to_string()),
                message:          "Error".to_string(),
                entity_id:        None,
                entity_type:      None,
                entity:           None,
                updated_fields:   None,
                cascade:          None,
                metadata:         None,
                is_simple_format: false,
            };

            let response =
                build_error_response_with_code(&result, "TestError", true, None, None).unwrap();
            let obj = response.as_object().unwrap();
            assert_eq!(
                obj["code"], expected_code,
                "Status '{}' should map to HTTP code {}",
                status_str, expected_code
            );
        }
    }

    #[test]
    fn test_error_response_with_code_field_injection() {
        // Test that code field is correctly injected into error responses
        let result = MutationResult {
            status:           MutationStatus::Error("validation:invalid_input".to_string()),
            message:          "Validation failed".to_string(),
            entity_id:        None,
            entity_type:      None,
            entity:           None,
            updated_fields:   None,
            cascade:          None,
            metadata:         None,
            is_simple_format: false,
        };

        // Test with field selection that includes 'code'
        let response = build_error_response_with_code(
            &result,
            "CreatePostError",
            true,
            Some(&vec!["code".to_string(), "message".to_string()]),
            None,
        )
        .unwrap();

        let obj = response.as_object().unwrap();

        // Verify code field is present and correct
        assert!(obj.contains_key("code"), "Error response must have 'code' field");
        assert_eq!(obj["code"], 422, "Validation error should map to 422");
        assert_eq!(obj["message"], "Validation failed");
        assert_eq!(obj["__typename"], "CreatePostError");
    }

    #[test]
    fn test_not_found_maps_to_404() {
        // Specific test for not_found: semantic prefix
        let result = MutationResult {
            status:           MutationStatus::Error("not_found:author_missing".to_string()),
            message:          "Author not found".to_string(),
            entity_id:        None,
            entity_type:      None,
            entity:           None,
            updated_fields:   None,
            cascade:          None,
            metadata:         None,
            is_simple_format: false,
        };

        let response = build_error_response_with_code(
            &result,
            "CreatePostError",
            true,
            Some(&vec!["code".to_string(), "message".to_string()]),
            None,
        )
        .unwrap();

        let obj = response.as_object().unwrap();

        assert_eq!(obj["code"], 404, "not_found: should map to 404");
    }
}
