//! Response Building Tests - Stage 3: MutationResult → JSON
//!
//! Tests for building GraphQL responses from MutationResult structures:
//! - Simple format response building
//! - Full format response building
//! - Auto-populated fields (status, errors, etc.)
//! - Error array generation
//! - Response routing (v1.8.0 validation as error type)
//! - CASCADE placement and handling
//! - __typename correctness
//! - Format detection edge cases
//! - Null entity handling
//! - Array entities
//! - Deep nesting
//! - Special characters

use super::*;

// ============================================================================
// Simple Format Response Building
// ============================================================================

#[test]
fn test_build_simple_format_response() {
    let result = MutationResult {
        status:           MutationStatus::Success("created".to_string()),
        message:          "User created".to_string(),
        entity_id:        None,
        entity_type:      Some("User".to_string()),
        entity:           Some(json!({"id": "123", "first_name": "John"})),
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: true,
    };

    let response = build_graphql_response(
        &result,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        Some("user"),
        Some("User"),
        true,
        None,
        None,
        None,
    )
    .unwrap();

    let data = &response["data"]["createUser"];
    assert_eq!(data["__typename"], "CreateUserSuccess");
    assert_eq!(data["user"]["id"], "123");
    assert_eq!(data["user"]["firstName"], "John");
}

#[test]
fn test_build_simple_format_with_status_data_field() {
    // When simple format has "status" in entity, it should be renamed to "statusData"
    let result = MutationResult {
        status:           MutationStatus::Success("created".to_string()),
        message:          "Task created".to_string(),
        entity_id:        None,
        entity_type:      Some("Task".to_string()),
        entity:           Some(json!({"id": "1", "status": "pending"})),
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: true,
    };

    let response = build_graphql_response(
        &result,
        "createTask",
        "CreateTaskSuccess",
        "CreateTaskError",
        Some("task"),
        Some("Task"),
        true,
        None,
        None,
        None,
    )
    .unwrap();

    let data = &response["data"]["createTask"];
    assert_eq!(data["task"]["statusData"], "pending");
}

#[test]
fn test_build_simple_format_array_response() {
    let result = MutationResult {
        status:           MutationStatus::Success("created".to_string()),
        message:          "Users created".to_string(),
        entity_id:        None,
        entity_type:      Some("User".to_string()),
        entity:           Some(json!([
            {"id": "1", "name": "Alice"},
            {"id": "2", "name": "Bob"}
        ])),
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: true,
    };

    let response = build_graphql_response(
        &result,
        "createUsers",
        "CreateUsersSuccess",
        "CreateUsersError",
        Some("users"),
        Some("User"),
        true,
        None,
        None,
        None,
    )
    .unwrap();

    let data = &response["data"]["createUsers"];
    assert_eq!(data["users"][0]["id"], "1");
    assert_eq!(data["users"][1]["id"], "2");
}

#[test]
fn test_build_simple_format_response_with_cascade() {
    let result = MutationResult {
        status:           MutationStatus::Success("updated".to_string()),
        message:          "Post updated".to_string(),
        entity_id:        None,
        entity_type:      Some("Post".to_string()),
        entity:           Some(json!({
            "id": "post-123",
            "title": "Updated",
            "comments": [{"id": "1", "text": "Nice"}]
        })),
        updated_fields:   Some(vec!["title".to_string()]),
        cascade:          Some(json!({
            "updated": [
                {"entity_id": "user-1", "entity_type": "User", "fields": ["post_count"]}
            ],
            "deleted": [],
            "invalidations": ["User:post-123"],
            "metadata": {"operation": "create"}
        })),
        metadata:         None,
        is_simple_format: true,
    };

    let response = build_graphql_response(
        &result,
        "updatePost",
        "UpdatePostSuccess",
        "UpdatePostError",
        Some("post"),
        Some("Post"),
        true,
        None,                         // success_type_fields
        None,                         // error_type_fields
        Some(r#"{"cascade": true}"#), // cascade_selections
    )
    .unwrap();

    let data = &response["data"]["updatePost"];
    assert_eq!(data["post"]["id"], "post-123");
    assert_eq!(data["post"]["title"], "Updated");

    // Verify CASCADE structure
    let cascade = &data["cascade"];
    assert!(cascade.is_object());

    let updated = cascade["updated"].as_array().unwrap();
    assert_eq!(updated.len(), 1);
    assert_eq!(updated[0]["entityId"], "user-1");
    assert_eq!(updated[0]["entityType"], "User");
    assert_eq!(updated[0]["fields"][0], "postCount");
    assert_eq!(updated[0]["post_count"], 5);

    let deleted = cascade["deleted"].as_array().unwrap();
    assert_eq!(deleted.len(), 0);

    let invalidations = cascade["invalidations"].as_array().unwrap();
    assert_eq!(invalidations.len(), 1);
    assert_eq!(invalidations[0], "User:post-123");

    let metadata = &cascade["metadata"];
    assert_eq!(metadata["operation"], "create");
}

// ============================================================================
// Full Format Response Building
// ============================================================================

#[test]
fn test_build_full_success_response() {
    let result = MutationResult {
        status:           MutationStatus::Success("created".to_string()),
        message:          "User created".to_string(),
        entity_id:        Some("550e8400-e29b-41d4-a716-446655440000".to_string()),
        entity_type:      Some("User".to_string()),
        entity:           Some(json!({"id": "123", "first_name": "John"})),
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    let response = build_graphql_response(
        &result,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        Some("user"),
        Some("User"),
        true,
        None,
        None,
        None,
    )
    .unwrap();

    let data = &response["data"]["createUser"];
    assert_eq!(data["__typename"], "CreateUserSuccess");
    assert_eq!(data["code"], 201); // New
    assert_eq!(data["message"], "User created");
    assert_eq!(data["user"]["id"], "123");
}

#[test]
fn test_build_full_error_response() {
    let result = MutationResult {
        status:           MutationStatus::Error("failed:validation".to_string()),
        message:          "Email already exists".to_string(),
        entity_id:        None,
        entity_type:      None,
        entity:           None,
        updated_fields:   None,
        cascade:          None,
        metadata:         Some(json!({"errors": [{"field": "email"}]})),
        is_simple_format: false,
    };

    let response = build_graphql_response(
        &result,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        None,
        None,
        true,
        None,
        None,
        None,
    )
    .unwrap();

    let data = &response["data"]["createUser"];
    assert_eq!(data["__typename"], "CreateUserError");
    assert_eq!(data["code"], 400); // Failed
    assert_eq!(data["message"], "Email already exists");
}

// ============================================================================
// Auto-Populated Fields Tests
// ============================================================================

use crate::mutation::response_builder::build_success_response;

#[test]
fn test_success_response_has_status_field() {
    // Setup
    let result = MutationResult {
        status:           MutationStatus::Success("success".to_string()),
        message:          "Operation completed".to_string(),
        entity_id:        Some("123e4567-e89b-12d3-a456-426614174000".to_string()),
        entity_type:      Some("User".to_string()),
        entity:           Some(json!({"id": "123", "name": "Test User"})),
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    // Execute
    let response = build_success_response(
        &result,
        "CreateUserSuccess",
        Some("user"),
        true, // auto_camel_case
        None, // success_type_fields
        None, // cascade_selections
    )
    .expect("Failed to build response");

    // Verify
    let obj = response.as_object().expect("Response should be object");

    // Check status field exists
    assert!(obj.contains_key("status"), "Response missing 'status' field");

    // Check status value
    let status = obj.get("status").expect("status field should exist");
    assert_eq!(status.as_str(), Some("success"), "status should be 'success'");
}

#[test]
fn test_success_response_has_errors_field() {
    // Setup
    let result = MutationResult {
        status:           MutationStatus::Success("success".to_string()),
        message:          "Operation completed".to_string(),
        entity_id:        Some("123e4567-e89b-12d3-a456-426614174000".to_string()),
        entity_type:      Some("User".to_string()),
        entity:           Some(json!({"id": "123", "name": "Test User"})),
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    // Execute
    let response =
        build_success_response(&result, "CreateUserSuccess", Some("user"), true, None, None)
            .expect("Failed to build response");

    // Verify
    let obj = response.as_object().expect("Response should be object");

    // Check errors field exists
    assert!(obj.contains_key("errors"), "Response missing 'errors' field");

    // Check errors is empty array
    let errors = obj.get("errors").expect("errors field should exist");
    let errors_array = errors.as_array().expect("errors should be array");
    assert_eq!(errors_array.len(), 0, "errors array should be empty for success");
}

#[test]
fn test_success_response_all_standard_fields() {
    // Setup
    let result = MutationResult {
        status:           MutationStatus::Success("success:created".to_string()),
        message:          "User created successfully".to_string(),
        entity_id:        Some("123e4567-e89b-12d3-a456-426614174000".to_string()),
        entity_type:      Some("User".to_string()),
        entity:           Some(json!({"id": "123", "email": "test@example.com"})),
        updated_fields:   Some(vec!["email".to_string(), "name".to_string()]),
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    // Execute
    let response =
        build_success_response(&result, "CreateUserSuccess", Some("user"), true, None, None)
            .expect("Failed to build response");

    // Verify all standard fields present
    let obj = response.as_object().expect("Response should be object");

    assert!(obj.contains_key("__typename"), "Missing __typename");
    assert!(obj.contains_key("id"), "Missing id");
    assert!(obj.contains_key("message"), "Missing message");
    assert!(obj.contains_key("status"), "Missing status");
    assert!(obj.contains_key("errors"), "Missing errors");
    assert!(obj.contains_key("user"), "Missing user entity");
    assert!(obj.contains_key("updatedFields"), "Missing updatedFields");

    // Verify values
    assert_eq!(obj.get("__typename").unwrap().as_str(), Some("CreateUserSuccess"));
    assert_eq!(obj.get("status").unwrap().as_str(), Some("success:created"));
    assert_eq!(obj.get("message").unwrap().as_str(), Some("User created successfully"));

    let errors = obj.get("errors").unwrap().as_array().unwrap();
    assert_eq!(errors.len(), 0, "Success should have empty errors array");
}

#[test]
fn test_success_status_preserves_detail() {
    // Test that status detail is preserved (e.g., "success:created")
    let result = MutationResult {
        status:           MutationStatus::Success("success:updated".to_string()),
        message:          "Updated".to_string(),
        entity_id:        Some("abc-123".to_string()),
        entity_type:      Some("Post".to_string()),
        entity:           Some(json!({"id": "abc-123"})),
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    let response =
        build_success_response(&result, "UpdatePostSuccess", Some("post"), true, None, None)
            .expect("Failed to build response");

    let obj = response.as_object().unwrap();
    let status = obj.get("status").unwrap().as_str().unwrap();

    assert_eq!(status, "success:updated", "Status detail should be preserved");
}

#[test]
fn test_success_fields_order() {
    // Verify fields appear in expected order for consistent API
    let result = MutationResult {
        status:           MutationStatus::Success("success".to_string()),
        message:          "OK".to_string(),
        entity_id:        Some("123".to_string()),
        entity_type:      Some("User".to_string()),
        entity:           Some(json!({"id": "123"})),
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    let response =
        build_success_response(&result, "CreateUserSuccess", Some("user"), true, None, None)
            .expect("Failed to build response");

    let obj = response.as_object().unwrap();
    let keys: Vec<&String> = obj.keys().collect();

    // Check that standard fields come before entity field
    let typename_idx = keys.iter().position(|&k| k == "__typename").unwrap();
    let id_idx = keys.iter().position(|&k| k == "id").unwrap();
    let message_idx = keys.iter().position(|&k| k == "message").unwrap();
    let status_idx = keys.iter().position(|&k| k == "status").unwrap();
    let errors_idx = keys.iter().position(|&k| k == "errors").unwrap();
    let user_idx = keys.iter().position(|&k| k == "user").unwrap();

    // Verify ordering
    assert!(typename_idx < id_idx, "__typename should come before id");
    assert!(id_idx < message_idx, "id should come before message");
    assert!(message_idx < status_idx, "message should come before status");
    assert!(status_idx < errors_idx, "status should come before errors");
    assert!(errors_idx < user_idx, "errors should come before entity");
}

// ============================================================================
// Error Array Generation Tests
// ============================================================================

use crate::mutation::response_builder::{extract_identifier_from_status, generate_errors_array};

#[test]
fn test_extract_identifier_from_failed_with_colon() {
    // Status: "failed:validation" -> identifier: "validation"
    let status = MutationStatus::Error("failed:validation".to_string());
    let identifier = extract_identifier_from_status(&status);
    assert_eq!(identifier, "validation");
}

#[test]
fn test_extract_identifier_from_noop_with_colon() {
    // Status: "noop:not_found" -> identifier: "not_found"
    let status = MutationStatus::Noop("not_found".to_string());
    let identifier = extract_identifier_from_status(&status);
    assert_eq!(identifier, "not_found");
}

#[test]
fn test_extract_identifier_from_failed_without_colon() {
    // Status: "failed" (no colon) -> identifier: "general_error"
    let status = MutationStatus::Error("failed".to_string());
    let identifier = extract_identifier_from_status(&status);
    assert_eq!(identifier, "general_error");
}

#[test]
fn test_extract_identifier_multiple_colons() {
    // Only split on first colon: "failed:validation:email" -> "validation:email"
    let status = MutationStatus::Error("failed:validation:email".to_string());
    let identifier = extract_identifier_from_status(&status);
    assert_eq!(identifier, "validation:email");
}

#[test]
fn test_generate_errors_array_auto() {
    // Test auto-generation from status string
    let result = MutationResult {
        status:           MutationStatus::Error("failed:validation".to_string()),
        message:          "Validation failed".to_string(),
        entity:           None,
        entity_type:      Some("User".to_string()),
        entity_id:        None,
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    let errors = generate_errors_array(&result, 400).unwrap();
    let errors_array = errors.as_array().unwrap();

    assert_eq!(errors_array.len(), 1);
    assert_eq!(errors_array[0]["code"], 400);
    assert_eq!(errors_array[0]["identifier"], "validation");
    assert_eq!(errors_array[0]["message"], "Validation failed");
    assert_eq!(errors_array[0]["details"], Value::Null);
}

#[test]
fn test_generate_errors_array_explicit_override() {
    // Test that explicit errors in metadata override auto-generation
    let explicit_errors = json!([
        {
            "code": 400,
            "identifier": "email_invalid",
            "message": "Email format is invalid",
            "details": {"field": "email"}
        }
    ]);

    let result = MutationResult {
        status:           MutationStatus::Error("failed:validation".to_string()),
        message:          "Multiple validation errors".to_string(),
        entity:           None,
        entity_type:      Some("User".to_string()),
        entity_id:        None,
        updated_fields:   None,
        cascade:          None,
        metadata:         Some(json!({"errors": explicit_errors})),
        is_simple_format: false,
    };

    let errors = generate_errors_array(&result, 400).unwrap();
    let errors_array = errors.as_array().unwrap();

    // Should use explicit errors, NOT auto-generated
    assert_eq!(errors_array.len(), 1);
    assert_eq!(errors_array[0]["identifier"], "email_invalid");
    assert_eq!(errors_array[0]["message"], "Email format is invalid");
    assert_eq!(errors_array[0]["details"]["field"], "email");
}

#[test]
fn test_generate_errors_array_noop_status() {
    // Test error generation from noop status (e.g., not_found)
    let result = MutationResult {
        status:           MutationStatus::Noop("not_found".to_string()),
        message:          "User not found".to_string(),
        entity:           None,
        entity_type:      Some("User".to_string()),
        entity_id:        None,
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    let errors = generate_errors_array(&result, 404).unwrap();
    let errors_array = errors.as_array().unwrap();

    assert_eq!(errors_array.len(), 1);
    assert_eq!(errors_array[0]["code"], 404);
    assert_eq!(errors_array[0]["identifier"], "not_found");
    assert_eq!(errors_array[0]["message"], "User not found");
}

// ============================================================================
// Response Routing Tests (v1.8.0 validation as error type)
// ============================================================================

#[test]
fn test_noop_returns_error_type_v1_8() {
    let result = MutationResult {
        status:           MutationStatus::Noop("noop:invalid_contract_id".to_string()),
        message:          "Contract not found".to_string(),
        entity_id:        None,
        entity_type:      None,
        entity:           None,
        updated_fields:   None,
        cascade:          Some(json!({"status": "noop:invalid_contract_id"})),
        metadata:         None,
        is_simple_format: false,
    };

    let response = build_graphql_response(
        &result,
        "createMachine",
        "CreateMachineSuccess",
        "CreateMachineError",
        Some("machine"),
        Some("Machine"),
        true,
        None,
        None,
        Some(r#"{"status": true}"#),
    )
    .unwrap();

    let data = &response["data"]["createMachine"];
    assert_eq!(data["__typename"], "CreateMachineError");
    assert_eq!(data["code"], 422);
    assert_eq!(data["status"], "noop:invalid_contract_id");
    assert_eq!(data["message"], "Contract not found");
    assert!(data["cascade"].is_object());
}

#[test]
fn test_not_found_returns_error_type_with_404() {
    let result = MutationResult {
        status:           MutationStatus::Error("not_found:machine".to_string()),
        message:          "Machine not found".to_string(),
        entity_id:        None,
        entity_type:      None,
        entity:           None,
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    let response = build_graphql_response(
        &result,
        "deleteMachine",
        "DeleteMachineSuccess",
        "DeleteMachineError",
        None,
        None,
        true,
        None,
        None,
        None,
    )
    .unwrap();
    let data = &response["data"]["deleteMachine"];

    assert_eq!(data["__typename"], "DeleteMachineError");
    assert_eq!(data["code"], 404);
    assert_eq!(data["status"], "not_found:machine");
}

#[test]
fn test_conflict_returns_error_type_with_409() {
    let result = MutationResult {
        status:           MutationStatus::Error("conflict:duplicate_serial".to_string()),
        message:          "Serial number already exists".to_string(),
        entity_id:        None,
        entity_type:      None,
        entity:           None,
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    let response = build_graphql_response(
        &result,
        "createMachine",
        "CreateMachineSuccess",
        "CreateMachineError",
        None,
        None,
        true,
        None,
        None,
        None,
    )
    .unwrap();
    let data = &response["data"]["createMachine"];

    assert_eq!(data["__typename"], "CreateMachineError");
    assert_eq!(data["code"], 409);
    assert_eq!(data["status"], "conflict:duplicate_serial");
}

#[test]
fn test_success_with_null_entity_returns_error() {
    // v1.8.0: Success type with null entity should return error
    let result = MutationResult {
        status:           MutationStatus::Success("created".to_string()),
        message:          "Created".to_string(),
        entity_id:        None,
        entity_type:      None,
        entity:           None, // ❌ Null entity with Success status
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    let response = build_graphql_response(
        &result,
        "createMachine",
        "CreateMachineSuccess",
        "CreateMachineError",
        Some("machine"),
        None,
        true,
        None,
        None,
        None,
    );
    assert!(response.is_err());
    let error_msg = response.unwrap_err();
    assert!(error_msg.contains("Success type"));
    assert!(error_msg.contains("requires non-null entity"));
}

#[test]
fn test_success_always_has_entity() {
    let result = MutationResult {
        status:           MutationStatus::Success("created".to_string()),
        message:          "Machine created".to_string(),
        entity_id:        None,
        entity_type:      None,
        entity:           Some(json!({"id": "123", "name": "Test"})),
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    let response = build_graphql_response(
        &result,
        "createMachine",
        "CreateMachineSuccess",
        "CreateMachineError",
        Some("machine"),
        None,
        true,
        None,
        None,
        None,
    )
    .unwrap();
    let data = &response["data"]["createMachine"];

    assert_eq!(data["__typename"], "CreateMachineSuccess");
    assert!(data["machine"].is_object());
    assert_eq!(data["machine"]["id"], "123");
}

#[test]
fn test_error_response_includes_cascade() {
    let result = MutationResult {
        status:           MutationStatus::Noop("noop:validation_failed".to_string()),
        message:          "Validation failed".to_string(),
        entity_id:        None,
        entity_type:      None,
        entity:           None,
        updated_fields:   None,
        cascade:          Some(
            json!({"status": "noop:validation_failed", "reason": "invalid_input"}),
        ),
        metadata:         None,
        is_simple_format: false,
    };

    let response = build_graphql_response(
        &result,
        "createMachine",
        "CreateMachineSuccess",
        "CreateMachineError",
        None,
        None,
        true,
        None,
        None,
        Some(r#"{"status": true, "reason": true}"#),
    )
    .unwrap();
    let data = &response["data"]["createMachine"];

    assert_eq!(data["__typename"], "CreateMachineError");
    assert_eq!(data["code"], 422);
    assert!(data["cascade"].is_object());
    assert_eq!(data["cascade"]["status"], "noop:validation_failed");
    assert_eq!(data["cascade"]["reason"], "invalid_input");
}

// ============================================================================
// CASCADE Placement and Handling Tests
// ============================================================================

#[test]
fn test_cascade_never_nested_in_entity() {
    let json = r#"{
        "status": "created",
        "entity_type": "Post",
        "entity": {"id": "123", "title": "Test"},
        "cascade": {"updated": []}
    }"#;

    let result = build_mutation_response(
        json,
        "createPost",
        "CreatePostSuccess",
        "CreatePostError",
        Some("post"),
        Some("Post"),
        None,
        true,
        None,
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();
    let success = &response["data"]["createPost"];

    // CASCADE at success level
    assert!(success["cascade"].is_object());
    // NOT in entity
    assert!(success["post"]["cascade"].is_null());
}

#[test]
fn test_cascade_never_copied_from_entity_wrapper() {
    // TEST: When entity is a wrapper containing both the entity field
    // AND cascade data, CASCADE should NOT be copied from the wrapper
    // into the entity object.
    //
    // This tests the case where PostgreSQL returns:
    // entity: {"allocation": {...}, "cascade": {...}, "message": "..."}
    let json = r#"{
        "status": "created",
        "entity_type": "Allocation",
        "entity": {
            "allocation": {
                "id": "d8c7c0b3-6b21-44c7-9195-504ca1c63e47",
                "identifier": "test-allocation"
            },
            "cascade": {
                "updated": [
                    {
                        "__typename": "Allocation",
                        "id": "d8c7c0b3-6b21-44c7-9195-504ca1c63e47",
                        "operation": "CREATED"
                    }
                ],
                "deleted": [],
                "invalidations": [
                    {
                        "queryName": "allocations",
                        "scope": "PREFIX",
                        "strategy": "INVALIDATE"
                    }
                ]
            },
            "message": "New allocation created"
        },
        "cascade": {
            "updated": [
                {
                    "__typename": "Allocation",
                    "id": "d8c7c0b3-6b21-44c7-9195-504ca1c63e47",
                    "operation": "CREATED"
                }
            ],
            "deleted": [],
            "invalidations": [
                {
                    "queryName": "allocations",
                    "scope": "PREFIX",
                    "strategy": "INVALIDATE"
                }
            ]
        }
    }"#;

    let result = build_mutation_response(
        json,
        "createAllocation",
        "CreateAllocationSuccess",
        "CreateAllocationError",
        Some("allocation"),
        Some("Allocation"),
        None,
        true,
        None,
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();
    let success = &response["data"]["createAllocation"];

    // CASCADE must be at success level
    assert!(success["cascade"].is_object(), "CASCADE missing at success level");
    assert!(success["cascade"]["updated"].is_array(), "CASCADE.updated should be array");

    // CASCADE must NEVER be in the entity object
    assert!(
        success["allocation"]["cascade"].is_null(),
        "BUG: CASCADE should NOT be copied from entity wrapper into allocation object"
    );

    // Message from wrapper should be copied (this is correct behavior)
    assert_eq!(success["message"], "New allocation created");

    // Verify entity has correct fields
    assert_eq!(success["allocation"]["id"], "d8c7c0b3-6b21-44c7-9195-504ca1c63e47");
    assert_eq!(success["allocation"]["identifier"], "test-allocation");
}

// ============================================================================
// __typename Correctness Tests
// ============================================================================

#[test]
fn test_typename_always_present() {
    let json = r#"{"id": "123"}"#;
    let result = build_mutation_response(
        json,
        "test",
        "TestSuccess",
        "TestError",
        Some("entity"),
        Some("Entity"),
        None,
        true,
        None,
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();

    // Success type has __typename
    assert_eq!(response["data"]["test"]["__typename"], "TestSuccess");
    // Entity has __typename
    assert_eq!(response["data"]["test"]["entity"]["__typename"], "Entity");
}

#[test]
fn test_typename_matches_entity_type() {
    let json = r#"{
        "status": "success",
        "entity_type": "CustomType",
        "entity": {"id": "123"}
    }"#;

    let result = build_mutation_response(
        json,
        "test",
        "TestSuccess",
        "TestError",
        Some("entity"),
        Some("CustomType"),
        None,
        true,
        None,
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();

    // __typename must match entity_type from JSON
    assert_eq!(response["data"]["test"]["entity"]["__typename"], "CustomType");
}

// ============================================================================
// Format Detection Edge Cases
// ============================================================================

#[test]
fn test_ambiguous_status_treated_as_simple() {
    // Has "status" field but value is not a valid mutation status
    let json = r#"{"status": "active", "name": "User"}"#;
    let result = build_mutation_response(
        json,
        "test",
        "TestSuccess",
        "TestError",
        Some("entity"),
        Some("Entity"),
        None,
        true,
        None,
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();

    // Should be treated as simple format (entity only)
    // The entire object becomes the entity
    assert_eq!(response["data"]["test"]["entity"]["status"], "active");
}

// ============================================================================
// Null Entity Handling
// ============================================================================

#[test]
fn test_null_entity() {
    let json = r#"{
        "status": "success",
        "message": "OK",
        "entity": null
    }"#;

    let result = build_mutation_response(
        json,
        "test",
        "TestSuccess",
        "TestError",
        None,
        None,
        None,
        true,
        None,
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();

    // Should have message but no entity field
    assert_eq!(response["data"]["test"]["message"], "OK");
    assert!(response["data"]["test"].get("entity").is_none());
}

// ============================================================================
// Array Entities
// ============================================================================

#[test]
fn test_array_of_entities() {
    let json = r#"[
        {"id": "1", "name": "Alice"},
        {"id": "2", "name": "Bob"}
    ]"#;

    let result = build_mutation_response(
        json,
        "listUsers",
        "ListUsersSuccess",
        "ListUsersError",
        Some("users"),
        Some("User"),
        None,
        true,
        None,
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();

    // Each array element should have __typename
    let users = response["data"]["listUsers"]["users"].as_array().unwrap();
    assert_eq!(users[0]["__typename"], "User");
    assert_eq!(users[1]["__typename"], "User");
}

// ============================================================================
// Deep Nesting
// ============================================================================

#[test]
fn test_deeply_nested_objects() {
    let json = r#"{
        "id": "1",
        "level1": {
            "level2": {
                "level3": {
                    "value": "deep"
                }
            }
        }
    }"#;

    let result = build_mutation_response(
        json,
        "test",
        "TestSuccess",
        "TestError",
        Some("entity"),
        Some("Entity"),
        None,
        true,
        None,
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();

    // Should handle deep nesting
    assert_eq!(
        response["data"]["test"]["entity"]["level1"]["level2"]["level3"]["value"],
        "deep"
    );
}

// ============================================================================
// Special Characters
// ============================================================================

#[test]
fn test_special_characters_in_fields() {
    let json = r#"{
        "id": "123",
        "field_with_unicode": "Hello 世界",
        "field_with_quotes": "He said \"hello\""
    }"#;

    let result = build_mutation_response(
        json,
        "test",
        "TestSuccess",
        "TestError",
        Some("entity"),
        Some("Entity"),
        None,
        false,
        None, // No camelCase
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();

    // Should preserve special characters
    assert_eq!(response["data"]["test"]["entity"]["field_with_unicode"], "Hello 世界");
}

// ============================================================================
// Field Selection Filtering (GraphQL Spec Compliance)
// ============================================================================

#[test]
fn test_success_response_field_filtering_all_fields() {
    let result = MutationResult {
        status:           MutationStatus::Success("created".to_string()),
        message:          "User created".to_string(),
        entity_id:        Some("123".to_string()),
        entity_type:      Some("User".to_string()),
        entity:           Some(json!({"id": "123", "first_name": "John"})),
        updated_fields:   Some(vec!["first_name".to_string()]),
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    // Request ALL fields
    let selected_fields = vec![
        "id".to_string(),
        "status".to_string(),
        "message".to_string(),
        "errors".to_string(),
        "updatedFields".to_string(),
        "user".to_string(),
    ];

    let response = build_graphql_response(
        &result,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        Some("user"),
        Some("User"),
        true,
        Some(&selected_fields),
        None,
        None,
    )
    .unwrap();

    let data = &response["data"]["createUser"];
    assert_eq!(data["__typename"], "CreateUserSuccess");
    assert_eq!(data["id"], "123");
    assert_eq!(data["status"], "success");
    assert_eq!(data["message"], "User created");
    assert_eq!(data["errors"], json!([]));
    assert_eq!(data["updatedFields"], json!(["firstName"])); // camelCase
    assert_eq!(data["user"]["id"], "123");
}

#[test]
fn test_success_response_field_filtering_partial_fields() {
    let result = MutationResult {
        status:           MutationStatus::Success("created".to_string()),
        message:          "User created".to_string(),
        entity_id:        Some("123".to_string()),
        entity_type:      Some("User".to_string()),
        entity:           Some(json!({"id": "123", "first_name": "John"})),
        updated_fields:   Some(vec!["first_name".to_string()]),
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    // Request only status and user
    let selected_fields = vec!["status".to_string(), "user".to_string()];

    let response = build_graphql_response(
        &result,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        Some("user"),
        Some("User"),
        true,
        Some(&selected_fields),
        None,
        None,
    )
    .unwrap();

    let data = &response["data"]["createUser"];
    assert_eq!(data["__typename"], "CreateUserSuccess");
    assert_eq!(data["status"], "success");
    assert_eq!(data["user"]["id"], "123");

    // These should NOT be present (filtered out)
    assert!(!data.as_object().unwrap().contains_key("id"));
    assert!(!data.as_object().unwrap().contains_key("message"));
    assert!(!data.as_object().unwrap().contains_key("errors"));
    assert!(!data.as_object().unwrap().contains_key("updatedFields"));
}

#[test]
fn test_success_response_field_filtering_no_filtering() {
    let result = MutationResult {
        status:           MutationStatus::Success("created".to_string()),
        message:          "User created".to_string(),
        entity_id:        Some("123".to_string()),
        entity_type:      Some("User".to_string()),
        entity:           Some(json!({"id": "123", "first_name": "John"})),
        updated_fields:   Some(vec!["first_name".to_string()]),
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    // No field filtering (None)
    let response = build_graphql_response(
        &result,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        Some("user"),
        Some("User"),
        true,
        None, // No filtering
        None,
        None,
    )
    .unwrap();

    let data = &response["data"]["createUser"];
    assert_eq!(data["__typename"], "CreateUserSuccess");
    // All fields should be present when no filtering is applied
    assert_eq!(data["id"], "123");
    assert_eq!(data["status"], "success");
    assert_eq!(data["message"], "User created");
    assert_eq!(data["errors"], json!([]));
    assert_eq!(data["updatedFields"], json!(["firstName"]));
    assert_eq!(data["user"]["id"], "123");
}

#[test]
fn test_error_response_field_filtering() {
    let result = MutationResult {
        status:           MutationStatus::Error("failed:validation".to_string()),
        message:          "Invalid input".to_string(),
        entity_id:        None,
        entity_type:      None,
        entity:           None,
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    // Request only status and message
    let selected_fields = vec!["status".to_string(), "message".to_string()];

    let response = build_graphql_response(
        &result,
        "createUser",
        "CreateUserSuccess",
        "CreateUserError",
        None,
        None,
        true,
        Some(&selected_fields),
        None,
        None,
    )
    .unwrap();

    let data = &response["data"]["createUser"];
    assert_eq!(data["__typename"], "CreateUserError");
    assert_eq!(data["status"], "failed:validation");
    assert_eq!(data["message"], "Invalid input");

    // These should NOT be present (filtered out)
    assert!(!data.as_object().unwrap().contains_key("code"));
    assert!(!data.as_object().unwrap().contains_key("errors"));
}
