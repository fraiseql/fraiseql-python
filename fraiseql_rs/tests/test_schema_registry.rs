/// Tests for SchemaRegistry module
///
/// These tests verify the Rust-side schema registry that stores GraphQL type metadata
/// for use in type resolution and JSON transformation.
use fraiseql_rs::schema_registry::SchemaRegistry;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_schema_registry_from_json() {
        // Sample schema JSON (from Python SchemaSerializer)
        let schema_json = r#"{
            "version": "1.0",
            "features": ["type_resolution", "aliases"],
            "types": {
                "User": {
                    "fields": {
                        "id": {
                            "type_name": "ID",
                            "is_nested_object": false,
                            "is_list": false
                        },
                        "name": {
                            "type_name": "String",
                            "is_nested_object": false,
                            "is_list": false
                        }
                    }
                },
                "Assignment": {
                    "fields": {
                        "id": {
                            "type_name": "ID",
                            "is_nested_object": false,
                            "is_list": false
                        },
                        "equipment": {
                            "type_name": "Equipment",
                            "is_nested_object": true,
                            "is_list": false
                        }
                    }
                }
            }
        }"#;

        let registry = SchemaRegistry::from_json(schema_json).expect("Failed to parse schema");

        // Verify version and features
        assert_eq!(registry.version(), "1.0");
        assert!(registry.has_feature("type_resolution"));
        assert!(registry.has_feature("aliases"));

        // Verify User type
        let user_id_field = registry.get_field_type("User", "id");
        assert!(user_id_field.is_some());
        let user_id = user_id_field.unwrap();
        assert_eq!(user_id.type_name(), "ID");
        assert!(!user_id.is_nested_object());
        assert!(!user_id.is_list());

        // Verify nested object field
        let equipment_field = registry.get_field_type("Assignment", "equipment");
        assert!(equipment_field.is_some());
        let equipment = equipment_field.unwrap();
        assert_eq!(equipment.type_name(), "Equipment");
        assert!(equipment.is_nested_object());
        assert!(!equipment.is_list());
    }

    #[test]
    fn test_schema_registry_missing_type() {
        // Test graceful handling of missing types
        let schema_json = r#"{"version": "1.0", "features": [], "types": {}}"#;
        let registry = SchemaRegistry::from_json(schema_json).unwrap();

        // Should return None for non-existent type
        let result = registry.get_field_type("NonExistent", "field");
        assert!(result.is_none());
    }

    #[test]
    fn test_schema_registry_version_check() {
        // Future version should work (for forward compatibility)
        let schema_json = r#"{"version": "2.0", "features": [], "types": {}}"#;
        let registry = SchemaRegistry::from_json(schema_json);
        assert!(registry.is_ok(), "Should handle newer versions gracefully");

        // Missing version should fail
        let schema_json_no_version = r#"{"features": [], "types": {}}"#;
        let result = SchemaRegistry::from_json(schema_json_no_version);
        assert!(result.is_err(), "Should fail without version field");
    }

    #[test]
    fn test_schema_registry_list_types() {
        // Test list type handling
        let schema_json = r#"{
            "version": "1.0",
            "features": [],
            "types": {
                "Post": {
                    "fields": {
                        "tags": {
                            "type_name": "Tag",
                            "is_nested_object": true,
                            "is_list": true
                        }
                    }
                }
            }
        }"#;
        let registry = SchemaRegistry::from_json(schema_json).unwrap();

        let tags_field = registry.get_field_type("Post", "tags").unwrap();
        assert_eq!(tags_field.type_name(), "Tag");
        assert!(tags_field.is_list());
        assert!(tags_field.is_nested_object());
    }

    #[test]
    fn test_schema_registry_performance() {
        // Test that field lookups are O(1) and fast
        use std::time::Instant;

        let schema_json = r#"{
            "version": "1.0",
            "features": [],
            "types": {
                "User": {
                    "fields": {
                        "id": {"type_name": "ID", "is_nested_object": false, "is_list": false}
                    }
                }
            }
        }"#;
        let registry = SchemaRegistry::from_json(schema_json).unwrap();

        // Perform 10000 lookups
        let start = Instant::now();
        for _ in 0..10000 {
            let _ = registry.get_field_type("User", "id");
        }
        let duration = start.elapsed();

        // Should complete in < 100ms in debug mode (10000 lookups)
        // In release mode this will be much faster (< 1ms)
        assert!(duration.as_millis() < 100, "Field lookups too slow: {:?}", duration);
    }
}
