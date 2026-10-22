//! Mutation result transformation module
//!
//! Transforms PostgreSQL mutation_response JSON into GraphQL responses.

mod entity_filter;
mod entity_processor;
mod parser;
mod postgres_composite;
mod response_builder;
mod types;

pub use entity_filter::{filter_entity_fields, project_selection};
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
    let result = parse_result(mutation_json, entity_type)?;

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

/// The format of the selection document `build_mutation_response_selected` reads.
///
/// Exported to Python as `MUTATION_SELECTION_FORMAT`: the Python side checks it
/// before calling, and the PyO3 entry point rejects any other document, so a Python
/// package and an extension from different versions fail loudly instead of
/// filtering responses by a format the other side doesn't write.
pub const SELECTION_FORMAT: i64 = 2;

/// Parse a mutation result: the 8-field mutation_response first, then the simple
/// format (an entity alone).
fn parse_result(mutation_json: &str, entity_type: Option<&str>) -> Result<MutationResult, String> {
    match postgres_composite::PostgresMutationResponse::from_json(mutation_json) {
        // CASCADE from position 7 is placed at the success wrapper level
        Ok(pg_response) => Ok(pg_response.to_mutation_result(entity_type)),
        Err(_parse_error) => MutationResult::from_json(mutation_json, entity_type),
    }
}

/// Parse a selection document and check its format.
///
/// The document is `{"format": 2, "success": Selection | null, "error": Selection | null}`;
/// see `project_selection` for a Selection, and `null` means unfiltered.
pub fn parse_selection_document(document: Option<&str>) -> Result<Value, String> {
    let mismatch = |found: &str| {
        format!(
            "build_mutation_response needs a selection document of format {SELECTION_FORMAT}, \
             got {found}. The fraiseql Python package and its Rust extension are from \
             different versions: reinstall fraiseql, or rebuild the extension."
        )
    };
    let Some(document) = document else {
        return Err(mismatch("none"));
    };
    let parsed: Value = serde_json::from_str(document)
        .map_err(|e| format!("Invalid selection document JSON: {e}"))?;
    match parsed.get("format").and_then(Value::as_i64) {
        Some(SELECTION_FORMAT) => Ok(parsed),
        Some(other) => Err(mismatch(&format!("format {other}"))),
        None => Err(mismatch("a document without a format")),
    }
}

/// Build a GraphQL mutation response holding only what the query selected.
///
/// The success or error object is built in full (as `build_graphql_response` builds
/// it without field lists), then projected onto the document's `success` or `error`
/// selection (`project_selection`): selected fields only, under their response keys,
/// lists filtered element by element. The response is keyed by `field_name`, which
/// the caller sets to the field's response key.
#[allow(clippy::too_many_arguments)]
pub fn build_mutation_response_selected(
    mutation_json: &str,
    field_name: &str,
    success_type: &str,
    error_type: &str,
    entity_field_name: Option<&str>,
    entity_type: Option<&str>,
    cascade_selections: Option<&str>,
    auto_camel_case: bool,
    document: &Value,
) -> Result<Vec<u8>, String> {
    let result = parse_result(mutation_json, entity_type)?;
    let full = if result.status.is_success() {
        response_builder::build_success_response(
            &result,
            success_type,
            entity_field_name,
            auto_camel_case,
            None,
            cascade_selections,
            None,
        )?
    } else {
        response_builder::build_error_response_with_code(
            &result,
            error_type,
            auto_camel_case,
            None,
            cascade_selections,
            None,
        )?
    };
    let selection = &document[if result.status.is_success() {
        "success"
    } else {
        "error"
    }];
    let projected = if selection.is_null() {
        full
    } else {
        project_selection(full, selection)
    };
    serde_json::to_vec(&serde_json::json!({ "data": { field_name: projected } }))
        .map_err(|e| format!("Failed to serialize: {}", e))
}

#[cfg(test)]
mod integration_tests {
    use super::*;

    #[test]
    fn test_selection_document_needs_format_2() {
        assert!(parse_selection_document(Some(r#"{"format": 2, "success": null}"#)).is_ok());
        for document in [
            None,
            Some(r#"{"fields": ["id"]}"#),
            Some(r#"{"format": 3}"#),
        ] {
            let error = parse_selection_document(document).unwrap_err();
            assert!(error.contains("selection document of format 2"), "{error}");
        }
    }

    #[test]
    fn test_selected_response_is_keyed_and_projected() {
        let result = r#"{"status": "success", "message": "ok", "entity_id": "1",
            "entity_type": "User", "entity": {"id": "1", "first_name": "A"},
            "updated_fields": null, "cascade": null, "metadata": null}"#;
        let document = serde_json::json!({"format": 2, "error": null, "success": {"fields": [
            {"name": "user", "alias": "u", "selections": {"fields": [
                {"name": "firstName", "alias": "firstName"}]}}]}});

        let bytes = build_mutation_response_selected(
            result,
            "m",
            "CreateUserSuccess",
            "CreateUserError",
            Some("user"),
            None,
            None,
            true,
            &document,
        )
        .unwrap();

        let response: Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(
            response,
            serde_json::json!({"data": {"m": {"__typename": "CreateUserSuccess",
                "u": {"__typename": "User", "firstName": "A"}}}})
        );
    }

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
            Some(r#"{"fields": ["updated"]}"#),
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
                // "failed:<reason>", what the trinity helpers return
                // (failed:validation, failed:not_found, failed:duplicate), is read
                // like "<reason>:"; any other "failed:" status is a server error
                let (category, failed) = match reason_lower.strip_prefix("failed:") {
                    Some(rest) => (rest.split(':').next().unwrap_or(""), true),
                    None => (reason_lower.split(':').next().unwrap_or(""), false),
                };
                // Map error reasons to HTTP-like codes
                match category {
                    "not_found" => 404,
                    "validation" => 422,
                    "unauthorized" => 401,
                    "forbidden" => 403,
                    "conflict" => 409,
                    "duplicate" if failed => 409,
                    "timeout" => 408,
                    _ => 500,
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
    pub status: MutationStatus,
    pub message: String,
    pub entity_id: Option<String>,
    pub entity_type: Option<String>,
    pub entity: Option<Value>,
    pub updated_fields: Option<Vec<String>>,
    pub cascade: Option<Value>,
    pub metadata: Option<Value>,
    /// True if this was parsed from simple JSONB format (no status field)
    pub is_simple_format: bool,
}

/// Valid mutation status prefixes/values for format detection: the success keywords
/// of the status taxonomy (including "new", which mutation_created() returns) and the
/// prefixes MutationStatus::from_str classifies
const VALID_STATUS_PREFIXES: &[&str] = &[
    // Success keywords (no colon)
    "success",
    "new",
    "created",
    "updated",
    "deleted",
    "completed",
    "ok",
    // Error prefixes
    "failed:",
    "validation:",
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
