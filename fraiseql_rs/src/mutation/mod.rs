//! Mutation result transformation module
//!
//! Transforms `PostgreSQL` `mutation_response` JSON into GraphQL responses.

mod entity_processor;
mod field_filter;
mod parser;
mod postgres_composite;
mod response_builder;
mod types;

pub use crate::cascade::{filter_cascade_by_selections, CascadeSelections};
pub use types::MutationConfig;

#[cfg(test)]
mod test_status_only;
#[cfg(test)]
mod tests;

use serde_json::Value;

/// Build complete GraphQL mutation response
///
/// This is the main entry point. It takes `PostgreSQL` JSON and returns
/// HTTP-ready bytes with proper GraphQL structure.
///
/// Supports TWO formats:
/// 1. **Simple format**: Just entity JSONB (no status field) - auto-detected
/// 2. **Full format**: Complete `mutation_response` with status, message, etc.
///
/// # Arguments
/// * `mutation_json` - Raw JSON from `PostgreSQL` (simple or full format)
/// * `config` - `MutationConfig` with all mutation response building parameters
///
/// # Errors
///
/// Returns an error if:
/// - JSON parsing fails for mutation response
/// - GraphQL response building fails
/// - Response serialization to bytes fails
pub fn build_mutation_response(
    mutation_json: &str,
    config: &MutationConfig,
) -> Result<Vec<u8>, String> {
    // Step 1: Try parsing as PostgreSQL 8-field mutation_response FIRST
    let result = match postgres_composite::PostgresMutationResponse::from_json(mutation_json) {
        Ok(pg_response) => {
            // SUCCESS: Valid 8-field composite type
            // CASCADE from Position 7 will be placed at success wrapper level
            pg_response.to_mutation_result(config.entity_type)
        }
        Err(_parse_error) => {
            // FALLBACK: Try simple format (backward compatibility)
            // This handles users with simple entity responses
            MutationResult::from_json(mutation_json, config.entity_type)?
        }
    };

    // Step 2: Build GraphQL response using response_builder
    let graphql_response = response_builder::build_graphql_response(&result, config)?;

    // Step 3: Serialize to bytes
    serde_json::to_vec(&graphql_response).map_err(|e| format!("Failed to serialize: {e}"))
}

#[cfg(test)]
mod integration_tests {
    use super::*;

    #[test]
    fn test_end_to_end_simple() {
        let json = r#"{"id": "123", "name": "John"}"#;
        let config = MutationConfig::new("createUser", "CreateUserSuccess", "CreateUserError")
            .with_entity("user", "User");

        let result = build_mutation_response(json, &config).unwrap();

        let response: serde_json::Value = serde_json::from_slice(&result).unwrap();
        assert_eq!(
            response["data"]["createUser"]["__typename"],
            "CreateUserSuccess"
        );
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

        let config = MutationConfig::new("createUser", "CreateUserSuccess", "CreateUserError")
            .with_entity("user", "User");

        let result = build_mutation_response(json, &config).unwrap();

        let response: serde_json::Value = serde_json::from_slice(&result).unwrap();
        let mutation_result = &response["data"]["createUser"];

        // CASCADE at success level
        assert!(mutation_result["cascade"].is_object());
        // NOT in entity
        assert!(mutation_result["user"]["cascade"].is_null());
    }
}

/// Mutation result status classification
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MutationStatus {
    /// Successful mutation (success, new, updated, deleted)
    Success(String),
    /// No operation performed with reason (noop:reason)
    Noop(String),
    /// Mutation failed with error reason (failed:reason)
    Error(String),
}

impl std::fmt::Display for MutationStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Success(s) | Self::Noop(s) | Self::Error(s) => write!(f, "{s}"),
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
    /// - "failed:", "unauthorized:", "forbidden:", "`not_found`:", "conflict:", "timeout:"
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
    #[must_use]
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
            Self::Error(status.to_string())
        }
        // NOOP PREFIX - Return Noop with full status string
        else if status_lower.starts_with("noop:") {
            Self::Noop(status.to_string())
        }
        // SUCCESS KEYWORDS - Return Success with full status string
        else if matches!(
            status_lower.as_str(),
            "success" | "created" | "updated" | "deleted"
        ) {
            Self::Success(status.to_string())
        }
        // DEFAULT - Unknown statuses become Success (backward compatibility)
        else {
            // Note: In production, this should log a warning
            Self::Success(status.to_string())
        }
    }

    /// Check if this status is a success variant
    #[must_use]
    pub const fn is_success(&self) -> bool {
        matches!(self, Self::Success(_))
    }

    /// Check if this status is a noop variant
    #[must_use]
    pub const fn is_noop(&self) -> bool {
        matches!(self, Self::Noop(_))
    }

    /// Returns true if this status should return Error type
    ///
    /// Both Noop and Error return Error type
    #[must_use]
    pub const fn is_error(&self) -> bool {
        matches!(self, Self::Error(_) | Self::Noop(_))
    }

    /// Returns true if this status should return Success type
    ///
    /// Only Success(_) returns Success type
    #[must_use]
    pub const fn is_graphql_success(&self) -> bool {
        matches!(self, Self::Success(_))
    }

    /// Map status to HTTP code (ALWAYS 200 for GraphQL)
    ///
    /// GraphQL always returns HTTP 200 OK.
    /// Use `application_code()` for REST-like categorization.
    #[must_use]
    pub const fn http_code(&self) -> i32 {
        200 // Always 200 OK for GraphQL
    }

    /// Map status to application-level code (for DX and categorization)
    ///
    /// This is NOT an HTTP status code. It's an application-level field
    /// that mirrors REST semantics for better developer experience.
    #[must_use]
    pub fn application_code(&self) -> i32 {
        match self {
            Self::Success(_) => 200,
            Self::Noop(_) => 422, // Validation/business rule
            Self::Error(reason) => {
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
            }
        }
    }
}

/// Parsed mutation result from `PostgreSQL`
///
/// Supports TWO formats:
/// 1. Simple: Just entity JSONB (detected by absence of "status" field)
/// 2. Full: Complete `mutation_response` with status, message, entity, etc.
#[derive(Debug, Clone)]
pub struct MutationResult {
    /// Mutation status classification
    pub status: MutationStatus,
    /// Human-readable message
    pub message: String,
    /// Entity identifier
    pub entity_id: Option<String>,
    /// Entity type name
    pub entity_type: Option<String>,
    /// Entity data
    pub entity: Option<Value>,
    /// List of updated fields
    pub updated_fields: Option<Vec<String>>,
    /// Cascade data
    pub cascade: Option<Value>,
    /// Additional metadata
    pub metadata: Option<Value>,
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
    #[must_use]
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
        v.get("status")
            .and_then(|s| s.as_str())
            .is_none_or(|status| !Self::is_valid_mutation_status(status))
    }

    /// Parse from `PostgreSQL` JSON string with smart format detection
    ///
    /// # Arguments
    /// * `json_str` - Raw JSON from `PostgreSQL`
    /// * `default_entity_type` - Entity type to use for simple format (e.g., "User")
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - JSON string is not valid JSON syntax
    /// - JSON value parsing fails
    pub fn from_json(json_str: &str, default_entity_type: Option<&str>) -> Result<Self, String> {
        let v: Value = serde_json::from_str(json_str).map_err(|e| format!("Invalid JSON: {e}"))?;

        Self::from_value(&v, default_entity_type)
    }

    /// Parse from `serde_json` Value with smart format detection
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - JSON value structure is invalid or unexpected
    /// - Required fields are missing in full format
    /// - Status value is invalid
    pub fn from_value(v: &Value, default_entity_type: Option<&str>) -> Result<Self, String> {
        // SMART DETECTION: Check if this is simple format
        let is_simple = v
            .get("status")
            .and_then(|s| s.as_str())
            .is_none_or(|status| !Self::is_valid_mutation_status(status));

        if is_simple || v.is_array() {
            // SIMPLE FORMAT: Treat entire JSON as entity, assume success
            // Extract '_cascade' field from simple format (note underscore prefix)
            let cascade = v.get("_cascade").filter(|c| !c.is_null()).cloned();

            return Ok(Self {
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
        let status_str = v
            .get("status")
            .and_then(|s| s.as_str())
            .ok_or("Missing 'status' field")?;

        let message = v
            .get("message")
            .and_then(|m| m.as_str())
            .unwrap_or("")
            .to_string();

        let entity_id = v
            .get("entity_id")
            .and_then(|id| id.as_str())
            .map(String::from);

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
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            });

        let cascade = v.get("cascade").filter(|c| !c.is_null()).cloned();
        let metadata = v.get("metadata").filter(|m| !m.is_null()).cloned();

        Ok(Self {
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
    #[must_use]
    pub fn errors(&self) -> Option<&Vec<Value>> {
        self.metadata
            .as_ref()
            .and_then(|m| m.get("errors"))
            .and_then(|e| e.as_array())
    }
}
