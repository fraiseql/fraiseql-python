//! PostgreSQL composite type parser for app.mutation_response (8-field format)
//!
//! Parses the PostgreSQL mutation_response composite type which has:
//! - Position 1: status (TEXT)
//! - Position 2: message (TEXT)
//! - Position 3: entity_id (TEXT)
//! - Position 4: entity_type (TEXT)
//! - Position 5: entity (JSONB)
//! - Position 6: updated_fields (TEXT[])
//! - Position 7: cascade (JSONB) - Contains cascade operation data
//! - Position 8: metadata (JSONB)

use serde_json::Value;

use super::{MutationResult, MutationStatus};

/// PostgreSQL app.mutation_response composite type structure (8 fields)
///
/// This structure represents the 8-field PostgreSQL composite type.
/// The CASCADE field at Position 7 contains cascade operation data.
#[derive(Debug, Clone, serde::Deserialize)]
#[serde(deny_unknown_fields)] // Fail if structure doesn't match
pub struct PostgresMutationResponse {
    /// Position 1: Status code (created, updated, failed:*, noop:*)
    pub status: String,

    /// Position 2: Human-readable message
    pub message: String,

    /// Position 3: Entity UUID (as TEXT, not UUID type)
    #[serde(default)]
    pub entity_id: Option<String>,

    /// Position 4: Entity type name (e.g., "Allocation", "Machine")
    /// Enables proper __typename mapping without extraction
    #[serde(default)]
    pub entity_type: Option<String>,

    /// Position 5: Entity data (the actual object)
    pub entity: Value,

    /// Position 6: Changed field names
    #[serde(default)]
    pub updated_fields: Option<Vec<String>>,

    /// Position 7: CASCADE data (updated, deleted, invalidations)
    /// Contains cascade operation data for related entities.
    #[serde(default)]
    pub cascade: Option<Value>,

    /// Position 8: Extra metadata (errors, context, etc.)
    #[serde(default)]
    pub metadata: Option<Value>,
}

impl PostgresMutationResponse {
    /// Parse from JSON string (PostgreSQL composite type serialization)
    ///
    /// # Arguments
    /// * `json_str` - JSON representation of the composite type from PostgreSQL
    ///
    /// # Returns
    /// * `Ok(PostgresMutationResponse)` - Successfully parsed
    /// * `Err(String)` - Parse error with descriptive message
    ///
    /// # Example
    /// ```rust
    /// let json = r#"{"status": "created", "message": "OK", ...}"#;
    /// let response = PostgresMutationResponse::from_json(json)?;
    /// ```
    pub fn from_json(json_str: &str) -> Result<Self, String> {
        serde_json::from_str(json_str).map_err(|e| {
            format!(
                "Failed to parse PostgreSQL mutation_response composite type (8 fields): {}. \
                 Expected fields: status, message, entity_id, entity_type, entity, \
                 updated_fields, cascade, metadata",
                e
            )
        })
    }

    /// Convert to internal MutationResult format
    ///
    /// Maps the 8-field composite type to FraiseQL's internal representation.
    /// The CASCADE field from Position 7 will be placed at the GraphQL success
    /// wrapper level (not nested in the entity).
    ///
    /// # Arguments
    /// * `_entity_type_fallback` - Unused (kept for API compatibility) In 8-field format,
    ///   entity_type always comes from Position 4
    ///
    /// # Returns
    /// Internal `MutationResult` ready for GraphQL response building
    pub fn to_mutation_result(self, _entity_type_fallback: Option<&str>) -> MutationResult {
        // CASCADE is already at Position 7 - just filter out nulls
        let cascade = self.cascade.filter(|c| !c.is_null());

        // entity_type comes from Position 4 (always available in 8-field format)
        let entity_type = self.entity_type;

        MutationResult {
            status: MutationStatus::from_str(&self.status),
            message: self.message,
            entity_id: self.entity_id,
            entity_type,               // From Position 4
            entity: Some(self.entity), // From Position 5
            updated_fields: self.updated_fields,
            cascade, // From Position 7
            metadata: self.metadata,
            is_simple_format: false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_parsing() {
        let json = r#"{
            "status": "created",
            "message": "Test",
            "entity_id": "123",
            "entity_type": "User",
            "entity": {"id": "123"},
            "updated_fields": ["name"],
            "cascade": {"updated": []},
            "metadata": {}
        }"#;

        let result = PostgresMutationResponse::from_json(json);
        assert!(result.is_ok());

        let pg_response = result.unwrap();
        assert_eq!(pg_response.status, "created");
        assert_eq!(pg_response.entity_type, Some("User".to_string()));
    }

    #[test]
    fn test_null_cascade_filtered() {
        let json = r#"{
            "status": "created",
            "message": "Test",
            "entity_id": null,
            "entity_type": null,
            "entity": {},
            "updated_fields": null,
            "cascade": null,
            "metadata": null
        }"#;

        let pg_response = PostgresMutationResponse::from_json(json).unwrap();
        let result = pg_response.to_mutation_result(None);

        // Null cascade should be filtered out
        assert!(result.cascade.is_none());
    }

    #[test]
    fn test_missing_optional_fields() {
        // Only required fields: status, message, entity
        let json = r#"{
            "status": "success",
            "message": "OK",
            "entity": {}
        }"#;

        let result = PostgresMutationResponse::from_json(json);
        assert!(result.is_ok());
    }
}
