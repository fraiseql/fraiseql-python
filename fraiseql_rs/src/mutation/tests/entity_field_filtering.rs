// ! Entity Field Filtering Tests
//! Tests for filtering nested entity fields based on GraphQL query selections.
//! Related to GitHub issue #525 - mutations should respect field selection for nested entities.

use serde_json::json;

use super::*;

#[test]
fn test_filter_entity_simple_fields() {
    /// Test filtering entity with simple field selection
    ///
    /// Given: Entity with many fields
    /// When: Only requesting ["id", "name"]
    /// Then: Return only id and name
    let entity = json!({
        "id": "loc-123",
        "name": "Warehouse A",
        "level": "floor-1",
        "has_elevator": true,
        "lat": 48.8606,
        "lng": 2.3376,
        "available_depth_mm": 1000,
    });

    let selections = json!({
        "fields": ["id", "name"]
    });

    let filtered = filter_entity_fields(&entity, &selections);

    // Should have only requested fields
    assert_eq!(filtered["id"], "loc-123");
    assert_eq!(filtered["name"], "Warehouse A");

    // Should NOT have unrequested fields
    assert!(filtered.get("level").is_none());
    assert!(filtered.get("has_elevator").is_none());
    assert!(filtered.get("lat").is_none());
    assert!(filtered.get("lng").is_none());
    assert!(filtered.get("available_depth_mm").is_none());
}

#[test]
fn test_filter_entity_nested_fields() {
    /// Test filtering entity with nested field selections
    ///
    /// Given: Entity with nested address object
    /// When: Selecting location.address.id and location.address.city
    /// Then: Return only selected nested fields
    let entity = json!({
        "id": "loc-123",
        "name": "Warehouse A",
        "address": {
            "id": "addr-456",
            "formatted": "123 Main St",
            "city": "Paris",
            "postal_code": "75001",
            "country": "France",
            "latitude": 48.8606,
            "longitude": 2.3376,
        }
    });

    let selections = json!({
        "fields": ["id", "name", "address"],
        "address": {
            "fields": ["id", "city"]
        }
    });

    let filtered = filter_entity_fields(&entity, &selections);

    // Top-level fields
    assert_eq!(filtered["id"], "loc-123");
    assert_eq!(filtered["name"], "Warehouse A");

    // Nested address should be filtered
    let address = &filtered["address"];
    assert_eq!(address["id"], "addr-456");
    assert_eq!(address["city"], "Paris");

    // Unrequested nested fields should not be present
    assert!(address.get("formatted").is_none());
    assert!(address.get("postal_code").is_none());
    assert!(address.get("country").is_none());
    assert!(address.get("latitude").is_none());
    assert!(address.get("longitude").is_none());
}

#[test]
fn test_filter_entity_deeply_nested() {
    /// Test filtering deeply nested structures (3+ levels)
    ///
    /// location -> contract -> customer
    let entity = json!({
        "id": "loc-123",
        "name": "Warehouse A",
        "contract": {
            "id": "contract-1",
            "name": "Service Agreement",
            "start_date": "2025-01-01",
            "customer": {
                "id": "customer-1",
                "name": "Acme Corp",
                "email": "contact@acme.com",
                "phone": "123-456-7890",
            }
        }
    });

    let selections = json!({
        "fields": ["id", "contract"],
        "contract": {
            "fields": ["id", "customer"],
            "customer": {
                "fields": ["id", "name"]
            }
        }
    });

    let filtered = filter_entity_fields(&entity, &selections);

    // Level 1: location
    assert_eq!(filtered["id"], "loc-123");
    assert!(filtered.get("name").is_none()); // Not requested

    // Level 2: contract
    let contract = &filtered["contract"];
    assert_eq!(contract["id"], "contract-1");
    assert!(contract.get("name").is_none()); // Not requested
    assert!(contract.get("start_date").is_none()); // Not requested

    // Level 3: customer
    let customer = &contract["customer"];
    assert_eq!(customer["id"], "customer-1");
    assert_eq!(customer["name"], "Acme Corp");
    assert!(customer.get("email").is_none()); // Not requested
    assert!(customer.get("phone").is_none()); // Not requested
}

#[test]
fn test_filter_entity_no_selections_returns_all() {
    /// Test that None selections returns all fields (backward compat)
    let entity = json!({
        "id": "loc-123",
        "name": "Warehouse A",
        "level": "floor-1",
    });

    // No selections provided - should return all
    let selections = serde_json::Value::Null;

    let filtered = filter_entity_fields(&entity, &selections);

    // All fields should be present
    assert_eq!(filtered["id"], "loc-123");
    assert_eq!(filtered["name"], "Warehouse A");
    assert_eq!(filtered["level"], "floor-1");
}

#[test]
fn test_filter_entity_empty_fields_returns_all() {
    /// Test that empty fields array returns all fields
    let entity = json!({
        "id": "loc-123",
        "name": "Warehouse A",
    });

    let selections = json!({
        "fields": []
    });

    let filtered = filter_entity_fields(&entity, &selections);

    // Empty selection should return all fields
    assert_eq!(filtered["id"], "loc-123");
    assert_eq!(filtered["name"], "Warehouse A");
}

#[test]
fn test_filter_entity_missing_field_ignored() {
    /// Test that requested fields not in entity are silently ignored
    let entity = json!({
        "id": "loc-123",
        "name": "Warehouse A",
    });

    let selections = json!({
        "fields": ["id", "name", "nonexistent_field"]
    });

    let filtered = filter_entity_fields(&entity, &selections);

    // Should have existing fields
    assert_eq!(filtered["id"], "loc-123");
    assert_eq!(filtered["name"], "Warehouse A");

    // Missing field should not cause error
    assert!(filtered.get("nonexistent_field").is_none());
}

#[test]
fn test_filter_entity_array_entities() {
    /// Test filtering when entity is an array
    ///
    /// Arrays should be passed through without field filtering
    /// (individual items filtering handled separately if needed)
    let entity = json!([
        {"id": "1", "name": "Item A", "description": "Desc A"},
        {"id": "2", "name": "Item B", "description": "Desc B"},
    ]);

    let selections = json!({
        "fields": ["id", "name"]
    });

    let filtered = filter_entity_fields(&entity, &selections);

    // Arrays should pass through unchanged for now
    // (Could enhance to filter array items in future)
    assert!(filtered.is_array());
    assert_eq!(filtered.as_array().unwrap().len(), 2);
}

#[test]
fn test_filter_entity_null_entity() {
    /// Test filtering when entity is null
    let entity = serde_json::Value::Null;
    let selections = json!({"fields": ["id"]});

    let filtered = filter_entity_fields(&entity, &selections);

    // Null should remain null
    assert!(filtered.is_null());
}

#[test]
fn test_filter_entity_preserves_types() {
    /// Test that field filtering preserves value types
    let entity = json!({
        "id": "loc-123",
        "count": 42,
        "is_active": true,
        "price": 99.99,
        "tags": ["a", "b", "c"],
        "metadata": {"key": "value"},
    });

    let selections = json!({
        "fields": ["id", "count", "is_active", "price", "tags", "metadata"]
    });

    let filtered = filter_entity_fields(&entity, &selections);

    // Verify types are preserved
    assert!(filtered["id"].is_string());
    assert!(filtered["count"].is_number());
    assert_eq!(filtered["count"], 42);
    assert!(filtered["is_active"].is_boolean());
    assert_eq!(filtered["is_active"], true);
    assert!(filtered["price"].is_number());
    assert!(filtered["tags"].is_array());
    assert!(filtered["metadata"].is_object());
}

#[test]
fn test_filter_entity_multiple_nested_objects() {
    /// Test filtering with multiple nested objects at same level
    let entity = json!({
        "id": "machine-123",
        "name": "Machine X",
        "location": {
            "id": "loc-1",
            "name": "Warehouse A",
            "city": "Paris",
        },
        "contract": {
            "id": "contract-1",
            "name": "Service Agreement",
            "expires": "2026-12-31",
        }
    });

    let selections = json!({
        "fields": ["id", "location", "contract"],
        "location": {
            "fields": ["id", "name"]
        },
        "contract": {
            "fields": ["id"]
        }
    });

    let filtered = filter_entity_fields(&entity, &selections);

    // Top level
    assert_eq!(filtered["id"], "machine-123");
    assert!(filtered.get("name").is_none());

    // Location filtered
    let location = &filtered["location"];
    assert_eq!(location["id"], "loc-1");
    assert_eq!(location["name"], "Warehouse A");
    assert!(location.get("city").is_none());

    // Contract filtered differently
    let contract = &filtered["contract"];
    assert_eq!(contract["id"], "contract-1");
    assert!(contract.get("name").is_none());
    assert!(contract.get("expires").is_none());
}

// ============================================================================
// Integration with build_graphql_response
// ============================================================================

#[test]
fn test_build_response_with_entity_field_filtering() {
    /// Test that build_graphql_response applies entity field filtering
    ///
    /// This is the end-to-end integration test
    let result = MutationResult {
        status:           MutationStatus::Success("created".to_string()),
        message:          "Location created".to_string(),
        entity_id:        Some("loc-123".to_string()),
        entity_type:      Some("Location".to_string()),
        entity:           Some(json!({
            "id": "loc-123",
            "name": "Warehouse A",
            "level": "floor-1",
            "has_elevator": true,
            "lat": 48.8606,
            "lng": 2.3376,
        })),
        updated_fields:   Some(vec!["name".to_string()]),
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    // Entity field selections: only id and name
    let entity_selections_json = r#"{"fields": ["id", "name"]}"#;

    let response = build_graphql_response_with_entity_filtering(
        &result,
        "createLocation",
        "CreateLocationSuccess",
        "CreateLocationError",
        Some("location"),
        Some("Location"),
        true,                                // auto_camel_case
        Some(&vec!["location".to_string()]), // success_type_fields
        None,                                // error_type_fields
        None,                                // cascade_selections
        Some(entity_selections_json),        // entity_selections
    )
    .unwrap();

    let data = &response["data"]["createLocation"];
    let location = &data["location"];

    // Should have only selected entity fields
    assert_eq!(location["id"], "loc-123");
    assert_eq!(location["name"], "Warehouse A");

    // Should NOT have unrequested fields
    assert!(location.get("level").is_none());
    assert!(location.get("hasElevator").is_none());
    assert!(location.get("lat").is_none());
    assert!(location.get("lng").is_none());
}

#[test]
fn test_build_response_without_entity_filtering_backward_compat() {
    /// Test that None entity_selections preserves all fields (backward compat)
    let result = MutationResult {
        status:           MutationStatus::Success("created".to_string()),
        message:          "Location created".to_string(),
        entity_id:        Some("loc-123".to_string()),
        entity_type:      Some("Location".to_string()),
        entity:           Some(json!({
            "id": "loc-123",
            "name": "Warehouse A",
            "level": "floor-1",
        })),
        updated_fields:   None,
        cascade:          None,
        metadata:         None,
        is_simple_format: false,
    };

    let response = build_graphql_response_with_entity_filtering(
        &result,
        "createLocation",
        "CreateLocationSuccess",
        "CreateLocationError",
        Some("location"),
        Some("Location"),
        true,
        None,
        None,
        None,
        None, // No entity filtering
    )
    .unwrap();

    let location = &response["data"]["createLocation"]["location"];

    // All fields should be present (backward compatible)
    assert_eq!(location["id"], "loc-123");
    assert_eq!(location["name"], "Warehouse A");
    assert_eq!(location["level"], "floor-1");
}

// ============================================================================
// Import actual implementation
// ============================================================================

use crate::mutation::filter_entity_fields;

/// Build GraphQL response with entity field filtering
///
/// Extended version of build_graphql_response that supports entity field filtering
fn build_graphql_response_with_entity_filtering(
    _result: &MutationResult,
    _field_name: &str,
    _success_type: &str,
    _error_type: &str,
    _entity_field_name: Option<&str>,
    _entity_type: Option<&str>,
    _auto_camel_case: bool,
    _success_type_fields: Option<&Vec<String>>,
    _error_type_fields: Option<&Vec<String>>,
    _cascade_selections: Option<&str>,
    _entity_selections: Option<&str>,
) -> Result<serde_json::Value, String> {
    // TODO: This will be implemented when we integrate with build_graphql_response
    // For now, skip these integration tests
    unimplemented!("Integration with build_graphql_response pending")
}
