/// Tests for multiple entity fields in Success/Error types
///
/// This pattern is used in PrintOptim for conflict scenarios, before/after states,
/// and related entities in mutation responses.
use super::*;

#[test]
fn test_success_with_multiple_entities() {
    // TEST: Success response with multiple entity fields at root level
    // Use case: Update operation showing before and after states
    //
    // PostgreSQL returns wrapper with multiple entities:
    // entity: {
    //     "machine": {...},
    //     "previous_location": {...},
    //     "new_location": {...}
    // }
    let json = r#"{
        "status": "updated",
        "message": "Machine location updated",
        "entity_type": "Machine",
        "entity": {
            "machine": {
                "id": "123",
                "name": "Printer-01"
            },
            "previous_location": {
                "id": "old-loc-456",
                "name": "Warehouse A"
            },
            "new_location": {
                "id": "new-loc-789",
                "name": "Warehouse B"
            }
        }
    }"#;

    let result = build_mutation_response(
        json,
        "updateMachine",
        "UpdateMachineSuccess",
        "UpdateMachineError",
        Some("machine"), // Primary entity field
        Some("Machine"),
        None,
        true,
        None,
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();
    let success = &response["data"]["updateMachine"];

    // Auto-injected fields at root
    assert_eq!(success["__typename"], "UpdateMachineSuccess");
    assert_eq!(success["status"], "updated");
    assert_eq!(success["message"], "Machine location updated");

    // Primary entity (extracted from wrapper)
    assert!(success["machine"].is_object(), "machine entity should exist");
    assert_eq!(success["machine"]["id"], "123");
    assert_eq!(success["machine"]["name"], "Printer-01");

    // Additional entities (copied from wrapper)
    // NOTE: Currently Rust extracts ONE entity and copies other wrapper fields
    // We expect previous_location and new_location to be copied from the wrapper
    assert!(
        success["previousLocation"].is_object(),
        "previousLocation should be copied from wrapper"
    );
    assert_eq!(success["previousLocation"]["id"], "old-loc-456");
    assert_eq!(success["previousLocation"]["name"], "Warehouse A");

    assert!(success["newLocation"].is_object(), "newLocation should be copied from wrapper");
    assert_eq!(success["newLocation"]["id"], "new-loc-789");
    assert_eq!(success["newLocation"]["name"], "Warehouse B");
}

#[test]
fn test_error_with_conflict_entity() {
    // TEST: Error response with conflict entity
    // Use case: Create operation failed due to existing entity
    //
    // PostgreSQL returns wrapper with conflict entity:
    // entity: {
    //     "conflict_machine": {...}
    // }
    let json = r#"{
        "status": "failed:conflict",
        "message": "Machine with this serial number already exists",
        "entity_type": "Machine",
        "entity": {
            "conflict_machine": {
                "id": "existing-123",
                "name": "Existing Printer",
                "serial_number": "ABC123"
            }
        }
    }"#;

    let result = build_mutation_response(
        json,
        "createMachine",
        "CreateMachineSuccess",
        "CreateMachineError",
        Some("machine"), // Would be used for success, ignored for error
        Some("Machine"),
        None,
        true,
        None,
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();
    let error = &response["data"]["createMachine"];

    // Auto-injected fields at root
    assert_eq!(error["__typename"], "CreateMachineError");
    assert_eq!(error["status"], "failed:conflict");
    assert_eq!(error["message"], "Machine with this serial number already exists");
    assert_eq!(error["code"], 409); // Conflict

    // Conflict entity should be extracted from wrapper
    // NOTE: For errors, entity handling works differently
    // We need to verify the actual behavior
    assert!(
        error["conflictMachine"].is_object() || error["entity"].is_object(),
        "conflict_machine should be accessible (either directly or via entity)"
    );
}

#[test]
fn test_multiple_entities_field_selection() {
    // TEST: Field selection should work independently for each entity
    // Use case: Client only requests specific fields from specific entities
    let json = r#"{
        "status": "updated",
        "message": "Machine location updated",
        "entity_type": "Machine",
        "entity": {
            "machine": {
                "id": "123",
                "name": "Printer-01",
                "serial_number": "XYZ789"
            },
            "previous_location": {
                "id": "old-loc-456",
                "name": "Warehouse A"
            },
            "new_location": {
                "id": "new-loc-789",
                "name": "Warehouse B"
            }
        }
    }"#;

    // Simulate field selection: only status, message, machine.id, newLocation
    let selected_fields = vec![
        "status".to_string(),
        "message".to_string(),
        "machine".to_string(),
        "newLocation".to_string(),
    ];

    let result = build_mutation_response(
        json,
        "updateMachine",
        "UpdateMachineSuccess",
        "UpdateMachineError",
        Some("machine"),
        Some("Machine"),
        None,
        true,
        Some(selected_fields),
        None,
    )
    .unwrap();

    let response: serde_json::Value = serde_json::from_slice(&result).unwrap();
    let success = &response["data"]["updateMachine"];

    // Selected fields should be present
    assert_eq!(success["status"], "updated");
    assert_eq!(success["message"], "Machine location updated");
    assert!(success["machine"].is_object());
    assert!(success["newLocation"].is_object());

    // Non-selected fields should NOT be present
    assert!(
        success["previousLocation"].is_null(),
        "previousLocation should not be included (not selected)"
    );
}
