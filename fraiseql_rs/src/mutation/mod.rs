//! Mutation result transformation module
//!
//! Transforms PostgreSQL mutation_response JSON into GraphQL responses.

mod entity_filter;
mod entity_processor;
mod parser;
mod postgres_composite;
mod response_builder;
mod types;

pub use entity_filter::filter_entity_fields;
pub use entity_processor::{
    ProcessedEntity, add_typename_to_entity, process_cascade, process_entity,
    process_entity_with_typename,
};
pub use parser::parse_mutation_response;
pub use postgres_composite::PostgresMutationResponse;
pub use response_builder::{build_graphql_response, build_success_response};
pub use types::{FullResponse, MutationResponse, SimpleResponse, StatusKind};

pub use crate::cascade::{CascadeSelections, filter_cascade_by_selections};

#[cfg(test)]
mod test_status_only;
#[cfg(test)]
mod tests;

use serde_json::Value;

/// Build complete GraphQL mutation response
///
/// This is the main entry point. It takes PostgreSQL JSON and returns
/// HTTP-ready bytes with proper GraphQL structure.
///
/// Supports TWO formats:
/// 1. **Simple format**: Just entity JSONB (no status field) - auto-detected
/// 2. **Full format**: Complete mutation_response with status, message, etc.
///
/// # Arguments
/// * `mutation_json` - Raw JSON from PostgreSQL (simple or full format)
/// * `field_name` - GraphQL field name (e.g., "createUser")
/// * `success_type` - Success type name (e.g., "CreateUserSuccess")
/// * `error_type` - Error type name (e.g., "CreateUserError")
/// * `entity_field_name` - Field name for entity (e.g., "user")
/// * `entity_type` - Entity type for __typename (e.g., "User") - REQUIRED for simple format
/// * `cascade_selections` - Optional cascade field selections JSON
/// * `auto_camel_case` - Whether to convert field names and JSON keys to camelCase
/// * `success_type_fields` - Optional list of expected fields in success type for validation
/// * `error_type_fields` - Optional list of expected fields in error type for field selection
/// * `entity_selections` - Optional JSON string of entity field selections (GitHub issue #525)
#[allow(clippy::too_many_arguments)]
pub fn build_mutation_response(
    mutation_json: &str,
    field_name: &str,
    success_type: &str,
    error_type: &str,
    entity_field_name: Option<&str>,
    entity_type: Option<&str>,
    cascade_selections: Option<&str>,
    auto_camel_case: bool,
    success_type_fields: Option<Vec<String>>,
    error_type_fields: Option<Vec<String>>,
    entity_selections: Option<&str>,
) -> Result<Vec<u8>, String> {
    // Step 1: Try parsing as PostgreSQL 8-field mutation_response FIRST
    let result = match postgres_composite::PostgresMutationResponse::from_json(mutation_json) {
        Ok(pg_response) => {
            // SUCCESS: Valid 8-field composite type
            // CASCADE from Position 7 will be placed at success wrapper level
            pg_response.to_mutation_result(entity_type)
        },
        Err(_parse_error) => {
            // FALLBACK: Try simple format (backward compatibility)
            // This handles users with simple entity responses
            MutationResult::from_json(mutation_json, entity_type)?
        },
    };

    // Step 2: Build GraphQL response using response_builder
    let graphql_response = response_builder::build_graphql_response(
        &result,
        field_name,
        success_type,
        error_type,
        entity_field_name,
        entity_type,
        auto_camel_case,
        success_type_fields.as_ref(),
        error_type_fields.as_ref(),
        cascade_selections,
        entity_selections,
    )?;

    // Step 3: Serialize to bytes
    serde_json::to_vec(&graphql_response).map_err(|e| format!("Failed to serialize: {}", e))
}

#[cfg(test)]
mod integration_tests {
    use super::*;

    #[test]
    fn test_end_to_end_simple() {
        let json = r#"{"id": "123", "name": "John"}"#;
        let result = build_mutation_response(
            json,
            "createUser",
            "CreateUserSuccess",
            "CreateUserError",
            Some("user"),
            Some("User"),
            None,
            true,
            None,
            None,
            None, // entity_selections
        )
        .unwrap();

        let response: serde_json::Value = serde_json::from_slice(&result).unwrap();
        assert_eq!(response["data"]["createUser"]["__typename"], "CreateUserSuccess");
        assert_eq!(response["data"]["createUser"]["user"]["__typename"], "User");
    }

    #[test]
    fn test_end_to_end_cascade() {
        let json = r#"{
            "status": "created",
            "message": "Success",
            "entity_type": "User",
            "entity": {"id": "123"},
            "cascade": {"updated": []}
        }"#;

        let result = build_mutation_response(
            json,
            "createUser",
            "CreateUserSuccess",
            "CreateUserError",
            Some("user"),
            Some("User"),
            None,
            true,
            None,
            None,
            None, // entity_selections
        )
        .unwrap();

        let response: serde_json::Value = serde_json::from_slice(&result).unwrap();
        let mutation_result = &response["data"]["createUser"];

        // CASCADE at success level
        assert!(mutation_result["cascade"].is_object());
        // NOT in entity
        assert!(mutation_result["user"]["cascade"].is_null());
    }
}

/// Mutation result status classification
#[derive(Debug, Clone, PartialEq)]
pub enum MutationStatus {
    Success(String), // "success", "new", "updated", "deleted"
    Noop(String),    // "noop:reason" - no changes made
    Error(String),   // "failed:reason" - actual error
}

impl std::fmt::Display for MutationStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            MutationStatus::Success(s) => write!(f, "{}", s),
            MutationStatus::Noop(s) => write!(f, "{}", s),
            MutationStatus::Error(s) => write!(f, "{}", s),
        }
    }
}

impl MutationStatus {
    /// Parse status string into enum with minimal taxonomy
    ///
    /// # Status Categories
    ///
    /// ## Success (no colon)
    /// - "success", "created", "updated", "deleted"
    ///
    /// ## Error (colon-separated)
    /// - "failed:", "unauthorized:", "forbidden:", "not_found:", "conflict:", "timeout:"
    ///
    /// ## Noop (colon-separated, success with no changes)
    /// - "noop:"
    ///
    /// # Case Insensitivity
    /// All status strings are matched case-insensitively.
    ///
    /// # Examples
    /// ```
    /// assert!(MutationStatus::from_str("success").is_success());
    /// assert!(MutationStatus::from_str("validation:invalid_input").is_error());
    /// assert!(MutationStatus::from_str("noop:unchanged").is_noop());
    /// assert!(MutationStatus::from_str("CONFLICT:duplicate").is_error());
    /// ```
    #[allow(clippy::should_implement_trait)]
    pub fn from_str(status: &str) -> Self {
        let status_lower = status.to_lowercase();

        // ERROR PREFIXES - Return Error type with full status string
        if status_lower.starts_with("failed:")
            || status_lower.starts_with("validation:")
            || status_lower.starts_with("unauthorized:")
            || status_lower.starts_with("forbidden:")
            || status_lower.starts_with("not_found:")
            || status_lower.starts_with("conflict:")
            || status_lower.starts_with("timeout:")
        {
            MutationStatus::Error(status.to_string())
        }
        // NOOP PREFIX - Return Noop with full status string
        else if status_lower.starts_with("noop:") {
            MutationStatus::Noop(status.to_string())
        }
        // SUCCESS KEYWORDS - Return Success with full status string
        else if matches!(status_lower.as_str(), "success" | "created" | "updated" | "deleted") {
            MutationStatus::Success(status.to_string())
        }
        // DEFAULT - Unknown statuses become Success (backward compatibility)
        else {
            // Note: In production, this should log a warning
            MutationStatus::Success(status.to_string())
        }
    }

    pub fn is_success(&self) -> bool {
        matches!(self, MutationStatus::Success(_))
    }

    pub fn is_noop(&self) -> bool {
        matches!(self, MutationStatus::Noop(_))
    }

    /// Returns true if this status should return Error type
    ///
    /// Both Noop and Error return Error type
    pub fn is_error(&self) -> bool {
        matches!(self, MutationStatus::Error(_) | MutationStatus::Noop(_))
    }

    /// Returns true if this status should return Success type
    ///
    /// Only Success(_) returns Success type
    pub fn is_graphql_success(&self) -> bool {
        matches!(self, MutationStatus::Success(_))
    }

    /// Map status to HTTP code (ALWAYS 200 for GraphQL)
    ///
    /// GraphQL always returns HTTP 200 OK.
    /// Use application_code() for REST-like categorization.
    pub fn http_code(&self) -> i32 {
        200 // Always 200 OK for GraphQL
    }

    /// Map status to application-level code (for DX and categorization)
    ///
    /// This is NOT an HTTP status code. It's an application-level field
    /// that mirrors REST semantics for better developer experience.
    pub fn application_code(&self) -> i32 {
        match self {
            MutationStatus::Success(_) => 200,
            MutationStatus::Noop(_) => 422, // Validation/business rule
            MutationStatus::Error(reason) => {
                let reason_lower = reason.to_lowercase();
                // Map error reasons to HTTP-like codes
                if reason_lower.starts_with("not_found:") {
                    404
                } else if reason_lower.starts_with("validation:") {
                    422
                } else if reason_lower.starts_with("unauthorized:") {
                    401
                } else if reason_lower.starts_with("forbidden:") {
                    403
                } else if reason_lower.starts_with("conflict:") {
                    409
                } else if reason_lower.starts_with("timeout:") {
                    408
                } else {
                    500
                }
            },
        }
    }
}

/// Parsed mutation result from PostgreSQL
///
/// Supports TWO formats:
/// 1. Simple: Just entity JSONB (detected by absence of "status" field)
/// 2. Full: Complete mutation_response with status, message, entity, etc.
#[derive(Debug, Clone)]
pub struct MutationResult {
    pub status:           MutationStatus,
    pub message:          String,
    pub entity_id:        Option<String>,
    pub entity_type:      Option<String>,
    pub entity:           Option<Value>,
    pub updated_fields:   Option<Vec<String>>,
    pub cascade:          Option<Value>,
    pub metadata:         Option<Value>,
    /// True if this was parsed from simple JSONB format (no status field)
    pub is_simple_format: bool,
}

/// Valid mutation status prefixes/values for format detection
const VALID_STATUS_PREFIXES: &[&str] = &[
    // Success keywords (no colon)
    "success",
    "created",
    "updated",
    "deleted",
    // Error prefixes
    "failed:",
    "unauthorized:",
    "forbidden:",
    "not_found:",
    "conflict:",
    "timeout:",
    // Noop prefix
    "noop:",
];

impl MutationResult {
    /// Check if a status string is a valid mutation status
    /// (vs. a data field that happens to be named "status")
    fn is_valid_mutation_status(status: &str) -> bool {
        VALID_STATUS_PREFIXES
            .iter()
            .any(|prefix| status == *prefix || status.starts_with(prefix))
    }

    /// Check if JSON is simple format (entity only, no mutation status)
    pub fn is_simple_format_json(json_str: &str) -> bool {
        let v: Value = match serde_json::from_str(json_str) {
            Ok(v) => v,
            Err(_) => return false,
        };

        // Arrays are always simple format
        if v.is_array() {
            return true;
        }

        // Check if has a valid mutation status field
        match v.get("status").and_then(|s| s.as_str()) {
            Some(status) => !Self::is_valid_mutation_status(status),
            None => true, // No status field = simple format
        }
    }

    /// Parse from PostgreSQL JSON string with smart format detection
    ///
    /// # Arguments
    /// * `json_str` - Raw JSON from PostgreSQL
    /// * `default_entity_type` - Entity type to use for simple format (e.g., "User")
    pub fn from_json(json_str: &str, default_entity_type: Option<&str>) -> Result<Self, String> {
        let v: Value =
            serde_json::from_str(json_str).map_err(|e| format!("Invalid JSON: {}", e))?;

        Self::from_value(&v, default_entity_type)
    }

    /// Parse from serde_json Value with smart format detection
    pub fn from_value(v: &Value, default_entity_type: Option<&str>) -> Result<Self, String> {
        // SMART DETECTION: Check if this is simple format
        let is_simple = match v.get("status").and_then(|s| s.as_str()) {
            Some(status) => !Self::is_valid_mutation_status(status),
            None => true, // No status = simple format
        };

        if is_simple || v.is_array() {
            // SIMPLE FORMAT: Treat entire JSON as entity, assume success
            // Extract '_cascade' field from simple format (note underscore prefix)
            let cascade = v.get("_cascade").filter(|c| !c.is_null()).cloned();

            return Ok(MutationResult {
                status: MutationStatus::Success("success".to_string()),
                message: "Success".to_string(),
                entity_id: v.get("id").and_then(|id| id.as_str()).map(String::from),
                entity_type: default_entity_type.map(String::from),
                entity: Some(v.clone()),
                updated_fields: None,
                cascade,
                metadata: None,
                is_simple_format: true,
            });
        }

        // FULL FORMAT: Parse all fields
        let status_str =
            v.get("status").and_then(|s| s.as_str()).ok_or("Missing 'status' field")?;

        let message = v.get("message").and_then(|m| m.as_str()).unwrap_or("").to_string();

        let entity_id = v.get("entity_id").and_then(|id| id.as_str()).map(String::from);

        // Use entity_type from JSON, fall back to default
        let entity_type = v
            .get("entity_type")
            .and_then(|t| t.as_str())
            .map(String::from)
            .or_else(|| default_entity_type.map(String::from));

        let entity = v.get("entity").filter(|e| !e.is_null()).cloned();

        let updated_fields = v
            .get("updated_fields")
            .and_then(|f| f.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect());

        let cascade = v.get("cascade").filter(|c| !c.is_null()).cloned();
        let metadata = v.get("metadata").filter(|m| !m.is_null()).cloned();

        Ok(MutationResult {
            status: MutationStatus::from_str(status_str),
            message,
            entity_id,
            entity_type,
            entity,
            updated_fields,
            cascade,
            metadata,
            is_simple_format: false,
        })
    }

    /// Get errors array from metadata
    pub fn errors(&self) -> Option<&Vec<Value>> {
        self.metadata.as_ref().and_then(|m| m.get("errors")).and_then(|e| e.as_array())
    }
}
