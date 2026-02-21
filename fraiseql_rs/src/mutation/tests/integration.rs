//! Integration Tests - Stage 4: End-to-end
//!
//! Comprehensive integration tests covering:
//! - Full mutation response flow (parse → build → validate)
//! - CASCADE placement and structure
//! - __typename correctness for success/error types
//! - Format detection (simple vs full)
//! - Null handling edge cases
//! - Array entity handling
//! - Deep nesting scenarios
//! - Special characters in field names
//! - Error array generation and explicit errors

use super::*;

#[test]
fn test_build_error_response_validation() {
    let mutation_json = r#"{
        "status": "failed:validation_error",
        "message": "Invalid email format",
        "entity_id": null,
        "entity_type": null,
        "entity": null,
        "updated_fields": null,
        "cascade": null,
        "metadata": null
    }"#;

    let result = build_mutation_response(
        mutation_json,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        Some("user"),
        Some("User"),
        None,
        true,
        None,
        None,
    );

    assert!(result.is_ok());
    let response_bytes = result.unwrap();
    let response_str = String::from_utf8(response_bytes).unwrap();

    // Parse JSON to verify structure
    let response: serde_json::Value = serde_json::from_str(&response_str).unwrap();

    // Should be error type
    assert_eq!(response["data"]["createUser"]["__typename"], "CreateUserError");
    assert_eq!(response["data"]["createUser"]["message"], "Invalid email format");
}

#[test]
fn test_build_error_response_conflict() {
    let mutation_json = r#"{
        "status": "conflict:duplicate_email",
        "message": "Email already exists",
        "entity_id": null,
        "entity_type": null,
        "entity": null,
        "updated_fields": null,
        "cascade": null,
        "metadata": null
    }"#;

    let result = build_mutation_response(
        mutation_json,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        Some("user"),
        Some("User"),
        None,
        true,
        None,
        None,
    );

    assert!(result.is_ok());
    let response_bytes = result.unwrap();
    let response_str = String::from_utf8(response_bytes).unwrap();
    let response: serde_json::Value = serde_json::from_str(&response_str).unwrap();

    // Should be error type with conflict status
    assert_eq!(response["data"]["createUser"]["__typename"], "CreateUserError");
    assert!(
        response["data"]["createUser"]["status"]
            .as_str()
            .unwrap()
            .starts_with("conflict:")
    );
}

#[test]
fn test_build_noop_response() {
    let mutation_json = r#"{
        "status": "noop:duplicate",
        "message": "Already exists",
        "entity_id": "123",
        "entity_type": "User",
        "entity": {"id": "123", "email": "test@example.com"},
        "updated_fields": null,
        "cascade": null,
        "metadata": null
    }"#;

    let result = build_mutation_response(
        mutation_json,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        Some("user"),
        Some("User"),
        None,
        true,
        None,
        None,
    );

    assert!(result.is_ok());
    let response_bytes = result.unwrap();
    let response_str = String::from_utf8(response_bytes).unwrap();
    let response: serde_json::Value = serde_json::from_str(&response_str).unwrap();

    // v1.8.0: Noop now returns ERROR type with code 422
    assert_eq!(response["data"]["createUser"]["__typename"], "CreateUserError");
    assert_eq!(response["data"]["createUser"]["code"], 422);
    assert_eq!(response["data"]["createUser"]["status"], "noop:duplicate");
    assert_eq!(response["data"]["createUser"]["message"], "Already exists");
}

#[test]
fn test_build_success_response() {
    let mutation_json = r#"{
        "status": "created",
        "message": "User created successfully",
        "entity_id": "456",
        "entity_type": "User",
        "entity": {"id": "456", "email": "new@example.com", "name": "Test User"},
        "updated_fields": ["email", "name"],
        "cascade": null,
        "metadata": null
    }"#;

    let result = build_mutation_response(
        mutation_json,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        Some("user"),
        Some("User"),
        None,
        true,
        None,
        None,
    );

    assert!(result.is_ok());
    let response_bytes = result.unwrap();
    let response_str = String::from_utf8(response_bytes).unwrap();
    let response: serde_json::Value = serde_json::from_str(&response_str).unwrap();

    // Should be success type
    assert_eq!(response["data"]["createUser"]["__typename"], "CreateUserSuccess");
    assert!(response["data"]["createUser"]["user"].is_object());
    assert_eq!(response["data"]["createUser"]["user"]["id"], "456");
}

#[test]
fn test_unauthorized_error() {
    let mutation_json = r#"{
        "status": "unauthorized:token_expired",
        "message": "Authentication token has expired",
        "entity_id": null,
        "entity_type": null,
        "entity": null,
        "updated_fields": null,
        "cascade": null,
        "metadata": null
    }"#;

    let result = build_mutation_response(
        mutation_json,
        "updateProfile",
        "UpdateProfileSuccess",
        "UpdateProfileError",
        None,
        None,
        None,
        true,
        None,
        None,
    );

    assert!(result.is_ok());
    let response_bytes = result.unwrap();
    let response_str = String::from_utf8(response_bytes).unwrap();
    let response: serde_json::Value = serde_json::from_str(&response_str).unwrap();

    assert_eq!(response["data"]["updateProfile"]["__typename"], "UpdateProfileError");
}

#[test]
fn test_timeout_error() {
    let mutation_json = r#"{
        "status": "timeout:database_query",
        "message": "Database query exceeded 30 second timeout",
        "entity_id": null,
        "entity_type": null,
        "entity": null,
        "updated_fields": null,
        "cascade": null,
        "metadata": null
    }"#;

    let result = build_mutation_response(
        mutation_json,
        "processLargeDataset",
        "ProcessSuccess",
        "ProcessError",
        None,
        None,
        None,
        true,
        None,
        None,
    );

    assert!(result.is_ok());
    let response_bytes = result.unwrap();
    let response_str = String::from_utf8(response_bytes).unwrap();
    let response: serde_json::Value = serde_json::from_str(&response_str).unwrap();

    assert_eq!(response["data"]["processLargeDataset"]["__typename"], "ProcessError");
    assert!(
        response["data"]["processLargeDataset"]["status"]
            .as_str()
            .unwrap()
            .starts_with("timeout:")
    );
}

// ============================================================================
// ERROR ARRAY GENERATION TESTS (WP-034)
// ============================================================================

#[test]
fn test_generate_errors_array_auto_generation() {
    let result = MutationResult {
        status:           MutationStatus::Error("failed:validation".to_string()),
        message:          "Email format invalid".to_string(),
        entity_id:        None,
        entity_type:      None,
        entity:           None,
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    let errors = super::response_builder::generate_errors_array(&result, 422).unwrap();
    let errors_array = errors.as_array().unwrap();

    assert_eq!(errors_array.len(), 1);
    let error = &errors_array[0];
    assert_eq!(error["code"], 422);
    assert_eq!(error["identifier"], "validation");
    assert_eq!(error["message"], "Email format invalid");
    assert!(error["details"].is_null());
}

#[test]
fn test_generate_errors_array_explicit_errors() {
    let explicit_errors = json!([
        {"code": 422, "identifier": "email_invalid", "message": "Email format invalid", "details": {"field": "email"}},
        {"code": 422, "identifier": "name_required", "message": "Name is required", "details": {"field": "name"}}
    ]);

    let result = MutationResult {
        status:           MutationStatus::Error("failed:validation".to_string()),
        message:          "Multiple validation errors".to_string(),
        entity_id:        None,
        entity_type:      None,
        entity:           None,
        updated_fields:   None,
        cascade:          None,
        metadata:         Some(json!({"errors": explicit_errors})),
        is_simple_format: false,
    };

    let errors = super::response_builder::generate_errors_array(&result, 422).unwrap();
    let errors_array = errors.as_array().unwrap();

    // Should use explicit errors, not auto-generate
    assert_eq!(errors_array.len(), 2);
    assert_eq!(errors_array[0]["identifier"], "email_invalid");
    assert_eq!(errors_array[1]["identifier"], "name_required");
}

#[test]
fn test_extract_identifier_from_status_error() {
    assert_eq!(
        super::response_builder::extract_identifier_from_status(&MutationStatus::Error(
            "failed:validation".to_string()
        )),
        "validation"
    );
    assert_eq!(
        super::response_builder::extract_identifier_from_status(&MutationStatus::Error(
            "not_found:user".to_string()
        )),
        "user"
    );
    assert_eq!(
        super::response_builder::extract_identifier_from_status(&MutationStatus::Error(
            "failed:".to_string()
        )),
        "general_error"
    );
    assert_eq!(
        super::response_builder::extract_identifier_from_status(&MutationStatus::Error(
            "failed".to_string()
        )),
        "general_error"
    );
}

#[test]
fn test_extract_identifier_from_status_noop() {
    assert_eq!(
        super::response_builder::extract_identifier_from_status(&MutationStatus::Noop(
            "noop:not_found".to_string()
        )),
        "not_found"
    );
    assert_eq!(
        super::response_builder::extract_identifier_from_status(&MutationStatus::Noop(
            "noop:duplicate".to_string()
        )),
        "duplicate"
    );
    assert_eq!(
        super::response_builder::extract_identifier_from_status(&MutationStatus::Noop(
            "noop".to_string()
        )),
        "general_error"
    );
}

#[test]
fn test_extract_identifier_from_status_success() {
    // Should not happen in practice, but handle gracefully
    assert_eq!(
        super::response_builder::extract_identifier_from_status(&MutationStatus::Success(
            "created".to_string()
        )),
        "unexpected_success"
    );
}

#[test]
fn test_error_response_includes_errors_array() {
    let mutation_json = r#"{
        "status": "failed:validation",
        "message": "Email already exists",
        "entity_id": null,
        "entity_type": null,
        "entity": null,
        "updated_fields": null,
        "cascade": null,
        "metadata": null
    }"#;

    let result = build_mutation_response(
        mutation_json,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        Some("user"),
        Some("User"),
        None,
        true,
        None,
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();
    let error_response = &response["data"]["createUser"];

    assert_eq!(error_response["__typename"], "CreateUserError");
    assert_eq!(error_response["code"], 422);
    assert_eq!(error_response["status"], "failed:validation");
    assert_eq!(error_response["message"], "Email already exists");

    // NEW: errors array should be present
    let errors = error_response["errors"].as_array().unwrap();
    assert_eq!(errors.len(), 1);
    assert_eq!(errors[0]["code"], 422);
    assert_eq!(errors[0]["identifier"], "validation");
    assert_eq!(errors[0]["message"], "Email already exists");
    assert!(errors[0]["details"].is_null());
}

#[test]
fn test_error_response_with_explicit_errors() {
    let mutation_json = r#"{
        "status": "failed:validation",
        "message": "Multiple validation errors",
        "entity_id": null,
        "entity_type": null,
        "entity": null,
        "updated_fields": null,
        "cascade": null,
        "metadata": {
            "errors": [
                {"code": 422, "identifier": "email_invalid", "message": "Invalid email format", "details": {"field": "email"}},
                {"code": 422, "identifier": "name_required", "message": "Name is required", "details": {"field": "name"}}
            ]
        }
    }"#;

    let result = build_mutation_response(
        mutation_json,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        Some("user"),
        Some("User"),
        None,
        true,
        None,
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();
    let error_response = &response["data"]["createUser"];

    // Should use explicit errors from metadata
    let errors = error_response["errors"].as_array().unwrap();
    assert_eq!(errors.len(), 2);
    assert_eq!(errors[0]["identifier"], "email_invalid");
    assert_eq!(errors[1]["identifier"], "name_required");
}

// ============================================================================
// COMPREHENSIVE EDGE CASE TESTS (Phase 5)
// ============================================================================
