//! Parsing Tests - Stage 1: JSON → MutationResult
//!
//! Tests for parsing JSON responses into MutationResult structures:
//! - Simple format (entity JSONB only, no status)
//! - Full format (mutation_response with status field)
//! - Format detection and error handling
//! - CASCADE integration in parsing
//! - PostgreSQL composite type parsing

use super::*;

// ============================================================================
// Tests for SIMPLE format (just entity JSONB, no status field)
// ============================================================================

#[test]
fn test_parse_simple_format() {
    // Simple format: just entity data, no status/message wrapper
    let json = r#"{"id": "123", "first_name": "John", "email": "john@example.com"}"#;

    let result = MutationResult::from_json(json, Some("User")).unwrap();

    // Should be detected as simple format and treated as success
    assert!(result.status.is_success());
    assert!(result.is_simple_format);
    assert!(result.entity.is_some());

    // Entity should be the whole JSON
    let entity = result.entity.as_ref().unwrap();
    assert_eq!(entity["id"], "123");
    assert_eq!(entity["first_name"], "John");
}

#[test]
fn test_parse_simple_format_array() {
    // Simple format can also be an array of entities
    let json = r#"[{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]"#;

    let result = MutationResult::from_json(json, Some("User")).unwrap();

    assert!(result.is_simple_format);
    assert!(result.entity.is_some());
}

// ============================================================================
// Tests for FULL format (mutation_response with status field)
// ============================================================================

#[test]
fn test_parse_full_success_result() {
    let json = r#"{
        "status": "new",
        "message": "User created",
        "entity_id": "550e8400-e29b-41d4-a716-446655440000",
        "entity_type": "User",
        "entity": {"id": "123", "first_name": "John"},
        "updated_fields": null,
        "cascade": null,
        "metadata": null
    }"#;

    let result = MutationResult::from_json(json, Some("User")).unwrap();

    assert!(!result.is_simple_format); // Not simple - has status
    assert!(result.status.is_success());
    assert_eq!(result.message, "User created");
    assert_eq!(result.entity_type, Some("User".to_string()));
    assert!(result.entity.is_some());
}

#[test]
fn test_parse_full_error_result() {
    let json = r#"{
        "status": "failed:validation",
        "message": "Email already exists",
        "entity_id": null,
        "entity_type": null,
        "entity": null,
        "updated_fields": null,
        "cascade": null,
        "metadata": {"errors": [{"field": "email", "code": "duplicate"}]}
    }"#;

    let result = MutationResult::from_json(json, None).unwrap();

    assert!(!result.is_simple_format);
    assert!(result.status.is_error());
    assert_eq!(result.message, "Email already exists");
    assert!(result.errors().is_some());
}

#[test]
fn test_parse_full_with_updated_fields() {
    let json = r#"{
        "status": "updated",
        "message": "User updated",
        "entity_id": "123",
        "entity_type": "User",
        "entity": {"id": "123"},
        "updated_fields": ["name", "email"],
        "cascade": null,
        "metadata": null
    }"#;

    let result = MutationResult::from_json(json, None).unwrap();

    assert!(result.status.is_success());
    assert_eq!(result.updated_fields, Some(vec!["name".to_string(), "email".to_string()]));
}

// ============================================================================
// Format detection tests
// ============================================================================

#[test]
fn test_format_detection_simple_vs_full() {
    // Full format: has "status" field
    let full = r#"{"status": "new", "entity": {"id": "1"}}"#;
    let result = MutationResult::from_json(full, None).unwrap();
    assert!(!result.is_simple_format);

    // Simple format: no "status" field, just entity data
    let simple = r#"{"id": "1", "name": "test"}"#;
    let result = MutationResult::from_json(simple, None).unwrap();
    assert!(result.is_simple_format);
}

// ============================================================================
// Error handling tests
// ============================================================================

#[test]
fn test_parse_missing_status_fails() {
    // Empty JSON should fail
    let json = r#"{}"#;
    let result = MutationResult::from_json(json, None);
    assert!(result.is_err());
}

#[test]
fn test_parse_invalid_json_fails() {
    let json = r#"not valid json"#;
    let result = MutationResult::from_json(json, None);
    assert!(result.is_err());
}

// ============================================================================
// CASCADE integration tests
// ============================================================================

#[test]
fn test_parse_simple_format_with_cascade() {
    // Simple format with CASCADE selections - CASCADE data goes in top-level
    let json = r#"{
        "id": "123",
        "first_name": "John",
        "posts": [{"id": "1", "title": "Hello"}]
    }"#;

    let result = MutationResult::from_json(json, Some("User")).unwrap();

    assert!(result.is_simple_format);
    assert!(result.entity.is_some());
    // CASCADE relationships should be in entity
    let entity = result.entity.as_ref().unwrap();
    assert!(entity.get("posts").is_some());
}

// ============================================================================
// PostgreSQL Composite Type Tests
// ============================================================================

use crate::mutation::PostgresMutationResponse;

#[test]
fn test_parse_8field_mutation_response() {
    // Test parsing of 8-field mutation response format
    let json = r#"{
        "status": "created",
        "message": "Allocation created successfully",
        "entity_id": "4d16b78b-7d9b-495f-9094-a65b57b33916",
        "entity_type": "Allocation",
        "entity": {"id": "4d16b78b-7d9b-495f-9094-a65b57b33916", "identifier": "test"},
        "updated_fields": ["location_id", "machine_id"],
        "cascade": {
            "updated": [{"id": "some-id", "operation": "UPDATED"}],
            "deleted": [],
            "invalidations": [{"queryName": "allocations", "strategy": "INVALIDATE"}]
        },
        "metadata": {"extra": "data"}
    }"#;

    // Try to parse as 8-field format
    // Test parsing of 8-field composite type
    let result = PostgresMutationResponse::from_json(json).unwrap();

    assert_eq!(result.status, "created");
    assert_eq!(result.entity_type, Some("Allocation".to_string()));
    assert!(result.cascade.is_some());

    let cascade = result.cascade.as_ref().unwrap();
    assert!(cascade.get("updated").is_some());
}

#[test]
fn test_cascade_extraction_from_position_7() {
    let json = r#"{
        "status": "created",
        "message": "Success",
        "entity_id": "uuid",
        "entity_type": "Allocation",
        "entity": {},
        "updated_fields": [],
        "cascade": {"updated": [{"id": "1"}]},
        "metadata": {}
    }"#;

    let pg_response = PostgresMutationResponse::from_json(json).unwrap();
    let result = pg_response.to_mutation_result(None);

    // CASCADE should come from Position 7, not metadata
    assert!(result.cascade.is_some());
    assert_eq!(result.cascade.unwrap().get("updated").unwrap()[0]["id"], "1");
}
