//! GraphQL Schema Registry for Rust
//!
//! This module provides a thread-safe registry for storing GraphQL schema metadata
//! that enables type resolution and transformation at runtime.
//!
//! The registry is initialized once at application startup with schema data from Python
//! and then used for all subsequent query transformations.

use std::{collections::HashMap, sync::Arc};

use arc_swap::ArcSwap;
use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};

/// Empty registry constant for efficient atomic operations
/// This avoids allocating new Arc instances during compare_and_swap
static EMPTY_REGISTRY: Lazy<Arc<SchemaRegistry>> = Lazy::new(|| Arc::new(SchemaRegistry::empty()));

/// Global schema registry using lock-free atomic access
/// Instead of RwLock<Option<T>>, we use ArcSwap<T> directly
static REGISTRY: Lazy<ArcSwap<SchemaRegistry>> =
    Lazy::new(|| ArcSwap::from(EMPTY_REGISTRY.clone()));

/// Field metadata describing a GraphQL field's type information
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct FieldInfo {
    /// The GraphQL type name (e.g., "String", "Equipment", "User")
    pub type_name: String,

    /// Whether this field is a nested object (true) or scalar (false)
    pub is_nested_object: bool,

    /// Whether this field is a list type (e.g., [User])
    pub is_list: bool,

    /// Extension fields for future compatibility
    /// Fields added in future versions will be stored here without breaking deserialization
    #[serde(flatten)]
    pub extensions: HashMap<String, serde_json::Value>,
}

impl FieldInfo {
    /// Get the type name of this field
    pub fn type_name(&self) -> &str {
        &self.type_name
    }

    /// Check if this is a nested object type
    pub fn is_nested_object(&self) -> bool {
        self.is_nested_object
    }

    /// Check if this is a list type
    pub fn is_list(&self) -> bool {
        self.is_list
    }
}

/// Type metadata describing a GraphQL object type's fields
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct TypeInfo {
    /// Map of field names to their metadata
    pub fields: HashMap<String, FieldInfo>,
}

/// GraphQL Schema Registry
///
/// Stores type metadata from the GraphQL schema for use in runtime type resolution.
/// Initialized once at application startup and then accessed read-only from all threads.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SchemaRegistry {
    /// Schema IR version (for forward compatibility)
    pub version: String,

    /// Feature flags (capabilities supported by this schema)
    pub features: Vec<String>,

    /// Map of type names to their metadata
    pub types: HashMap<String, TypeInfo>,
}

impl SchemaRegistry {
    /// Create an empty SchemaRegistry
    ///
    /// Used internally for initializing the global registry before it's populated.
    pub fn empty() -> Self {
        Self {
            version:  String::new(),
            features: Vec::new(),
            types:    HashMap::new(),
        }
    }

    /// Create a new SchemaRegistry from JSON schema IR
    ///
    /// # Arguments
    /// * `json` - JSON string containing the schema IR from Python
    ///
    /// # Returns
    /// * `Ok(SchemaRegistry)` - Successfully parsed schema
    /// * `Err(String)` - Parse error with description
    ///
    /// # Example
    /// ```ignore
    /// let schema_json = r#"{"version": "1.0", "features": [], "types": {}}"#;
    /// let registry = SchemaRegistry::from_json(schema_json)?;
    /// ```
    pub fn from_json(json: &str) -> Result<Self, String> {
        serde_json::from_str(json).map_err(|e| format!("Failed to parse schema JSON: {}", e))
    }

    /// Get the schema IR version
    pub fn version(&self) -> &str {
        &self.version
    }

    /// Check if a feature is enabled in this schema
    pub fn has_feature(&self, feature: &str) -> bool {
        self.features.contains(&feature.to_string())
    }

    /// Look up field type information
    ///
    /// # Arguments
    /// * `type_name` - The parent type name (e.g., "Assignment")
    /// * `field_name` - The field name (e.g., "equipment" or "network_config")
    ///
    /// # Returns
    /// * `Some(&FieldInfo)` - Field information if found
    /// * `None` - Type or field not found
    ///
    /// # Performance
    /// This is an O(1) HashMap lookup (or 2 lookups if camelCase fallback is needed)
    ///
    /// # Note
    /// Field names can be in snake_case (from database) or camelCase (from GraphQL).
    /// This method tries both formats to find the field:
    /// 1. First tries the original field name
    /// 2. If not found, tries camelCase version (for snake_case inputs)
    pub fn get_field_type(&self, type_name: &str, field_name: &str) -> Option<&FieldInfo> {
        let type_info = self.types.get(type_name)?;

        // Try original field name first
        if let Some(field_info) = type_info.fields.get(field_name) {
            return Some(field_info);
        }

        // If not found, try camelCase version (GraphQL schema uses camelCase)
        // This handles case where field_name is snake_case (e.g., "network_config")
        // but schema has camelCase (e.g., "networkConfig")
        let camel_field_name = crate::camel_case::to_camel_case(field_name);
        type_info.fields.get(&camel_field_name)
    }

    /// Get the number of types in the registry
    pub fn type_count(&self) -> usize {
        self.types.len()
    }
}

/// Get a reference-counted handle to the current schema registry
///
/// # Returns
/// An `Arc<SchemaRegistry>` that keeps the registry alive while in use.
/// This is a lock-free atomic load operation.
///
/// # Performance
/// O(1) and wait-free - no locks or syscalls.
///
/// # Example
/// ```
/// let registry = get_registry();
/// let field = registry.get_field_type("User", "name");
/// // Arc is dropped here, registry may be freed if no other references
/// ```
pub fn get_registry() -> Arc<SchemaRegistry> {
    REGISTRY.load_full()
}

/// Convenience function for single registry operations
/// Use this when you only need to read once
///
/// # Example
/// ```
/// let field_type = with_registry(|registry| {
///     registry.get_field_type("User", "name").cloned()
/// });
/// ```
pub fn with_registry<T, F: FnOnce(&SchemaRegistry) -> T>(f: F) -> T {
    let registry = REGISTRY.load();
    f(&registry)
}

/// Initialize the global schema registry
/// This should be called once at application startup
///
/// # Arguments
/// * `registry` - The SchemaRegistry to install
///
/// # Returns
/// * `true` - Registry was initialized (was previously empty)
/// * `false` - Registry was already initialized (no change made)
///
/// # Thread Safety
/// Safe to call from multiple threads. Only the first call will succeed.
pub fn initialize_registry(registry: SchemaRegistry) -> bool {
    let new_arc = Arc::new(registry);
    let old = REGISTRY.compare_and_swap(&*EMPTY_REGISTRY, new_arc);

    // If old was the empty registry, we successfully initialized
    Arc::ptr_eq(&old, &*EMPTY_REGISTRY)
}

/// Set/replace the schema registry (for hot-reload scenarios)
/// WARNING: Existing Arc references will continue to work with the old registry.
/// Do not cache raw references across calls to this function.
///
/// # Safety Note
/// This is safe, but callers must not cache &SchemaRegistry references
/// across calls to this function.
pub fn set_registry(registry: SchemaRegistry) {
    REGISTRY.store(Arc::new(registry));
}

/// Reset the schema registry to empty state (for testing)
/// This is safe to call at any time. Existing Arc references
/// will continue to work with the old registry until dropped.
///
/// # Thread Safety
/// This is an atomic operation. No locks are held.
pub fn reset_for_testing() {
    REGISTRY.store(EMPTY_REGISTRY.clone());
}

/// Check if the schema registry has been initialized
/// Returns true if the registry contains a real schema (not empty)
pub fn is_initialized() -> bool {
    !Arc::ptr_eq(&REGISTRY.load(), &EMPTY_REGISTRY)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_field_info_deserialization() {
        let json = r#"{
            "type_name": "String",
            "is_nested_object": false,
            "is_list": false
        }"#;

        let field_info: FieldInfo = serde_json::from_str(json).unwrap();
        assert_eq!(field_info.type_name(), "String");
        assert!(!field_info.is_nested_object());
        assert!(!field_info.is_list());
    }

    #[test]
    fn test_field_info_with_extensions() {
        // Future schema might include additional fields
        let json = r#"{
            "type_name": "String",
            "is_nested_object": false,
            "is_list": false,
            "future_field": "ignored",
            "another_field": 123
        }"#;

        // Should deserialize without error (unknown fields in extensions)
        let field_info: FieldInfo = serde_json::from_str(json).unwrap();
        assert_eq!(field_info.type_name(), "String");
        assert_eq!(field_info.extensions.len(), 2);
    }

    #[test]
    fn test_schema_registry_basic() {
        let json = r#"{
            "version": "1.0",
            "features": ["type_resolution"],
            "types": {
                "User": {
                    "fields": {
                        "id": {
                            "type_name": "ID",
                            "is_nested_object": false,
                            "is_list": false
                        }
                    }
                }
            }
        }"#;

        let registry = SchemaRegistry::from_json(json).unwrap();
        assert_eq!(registry.version(), "1.0");
        assert!(registry.has_feature("type_resolution"));
        assert_eq!(registry.type_count(), 1);

        let field = registry.get_field_type("User", "id").unwrap();
        assert_eq!(field.type_name(), "ID");
    }

    #[test]
    fn test_multiple_resets_no_deadlock() {
        // This test would deadlock with the old implementation
        for _i in 0..100 {
            // Reset
            reset_for_testing();

            // Initialize with new schema
            let schema = SchemaRegistry {
                version:  "1.0".to_string(),
                features: vec![],
                types:    HashMap::new(),
            };
            initialize_registry(schema);

            // Access multiple times (simulates test operations)
            for _ in 0..10 {
                let _registry = get_registry();
                assert!(is_initialized());
            }
        }

        // Final reset should work instantly (no deadlock!)
        reset_for_testing();
        assert!(!is_initialized());
    }

    #[test]
    fn test_concurrent_access_and_reset() {
        use std::thread;

        // Spawn 10 threads that read and reset concurrently
        let handles: Vec<_> = (0..10)
            .map(|_| {
                thread::spawn(|| {
                    for _ in 0..100 {
                        // Concurrent reads
                        let _registry = get_registry();

                        // Concurrent resets (safe with arc-swap!)
                        reset_for_testing();
                    }
                })
            })
            .collect();

        // Wait for all threads to complete
        for h in handles {
            h.join().unwrap();
        }
    }
}
