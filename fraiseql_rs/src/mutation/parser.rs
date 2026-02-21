// fraiseql_rs/src/mutation/parser.rs

use serde_json::Value;

use crate::mutation::types::*;

/// Parse JSONB string into MutationResponse
///
/// Automatically detects format:
/// - Full: Has valid status field
/// - Simple: No status field OR invalid status value
pub fn parse_mutation_response(
    json_str: &str,
    default_entity_type: Option<&str>,
) -> Result<MutationResponse, crate::mutation::types::MutationError> {
    // Parse JSON
    let value: Value =
        serde_json::from_str(json_str).map_err(|e| MutationError::InvalidJson(e.to_string()))?;

    // Detect format
    if is_full_format(&value) {
        parse_full(value, default_entity_type).map(MutationResponse::Full)
    } else {
        parse_simple(value).map(MutationResponse::Simple)
    }
}

/// Check if value is full format (has valid status field)
fn is_full_format(value: &Value) -> bool {
    if let Some(status) = value.get("status").and_then(|s| s.as_str()) {
        is_valid_mutation_status(status)
    } else {
        false
    }
}

/// Check if status string is a valid mutation status
fn is_valid_mutation_status(status: &str) -> bool {
    const VALID_PREFIXES: &[&str] = &[
        "success",
        "created",
        "updated",
        "deleted",
        "completed",
        "ok",
        "new",
        "failed:",
        "unauthorized:",
        "forbidden:",
        "not_found:",
        "conflict:",
        "timeout:",
        "noop:",
    ];

    let status_lower = status.to_lowercase();
    VALID_PREFIXES
        .iter()
        .any(|prefix| status_lower == *prefix || status_lower.starts_with(prefix))
}

/// Parse simple format (entity only)
fn parse_simple(value: Value) -> Result<SimpleResponse, crate::mutation::types::MutationError> {
    Ok(SimpleResponse { entity: value })
}

/// Parse full mutation response format
fn parse_full(
    value: Value,
    default_entity_type: Option<&str>,
) -> Result<FullResponse, crate::mutation::types::MutationError> {
    // Required fields
    let status = value
        .get("status")
        .and_then(|s| s.as_str())
        .ok_or_else(|| MutationError::MissingField("status".to_string()))?
        .to_string();

    let message = value.get("message").and_then(|m| m.as_str()).unwrap_or("").to_string();

    // Optional fields
    let entity_type = value
        .get("entity_type")
        .and_then(|t| t.as_str())
        .map(String::from)
        .or_else(|| default_entity_type.map(String::from));

    let entity = value.get("entity").filter(|e| !e.is_null()).cloned();

    let updated_fields = value
        .get("updated_fields")
        .and_then(|f| f.as_array())
        .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect());

    // CASCADE: support both "cascade" and "_cascade" (backward compat)
    let cascade = value
        .get("cascade")
        .or_else(|| value.get("_cascade"))
        .filter(|c| !c.is_null())
        .cloned();

    let metadata = value.get("metadata").filter(|m| !m.is_null()).cloned();

    Ok(FullResponse {
        status,
        message,
        entity_type,
        entity,
        updated_fields,
        cascade,
        metadata,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detect_simple_format() {
        let json = r#"{"id": "123", "name": "Test"}"#;
        let response = parse_mutation_response(json, None).unwrap();
        assert!(matches!(response, MutationResponse::Simple(_)));
    }

    #[test]
    fn test_detect_full_format() {
        let json = r#"{"status": "success", "message": "OK"}"#;
        let response = parse_mutation_response(json, None).unwrap();
        assert!(matches!(response, MutationResponse::Full(_)));
    }

    #[test]
    fn test_parse_simple() {
        let json = r#"{"id": "123", "name": "Test"}"#;
        let response = parse_mutation_response(json, None).unwrap();

        match response {
            MutationResponse::Simple(simple) => {
                assert_eq!(simple.entity.get("id").unwrap(), "123");
            },
            _ => panic!("Expected Simple format"),
        }
    }

    #[test]
    fn test_parse_full_with_cascade() {
        let json = r#"{
            "status": "created",
            "message": "Success",
            "entity_type": "User",
            "entity": {"id": "123", "name": "John"},
            "cascade": {"updated": []}
        }"#;

        let response = parse_mutation_response(json, None).unwrap();

        match response {
            MutationResponse::Full(full) => {
                assert_eq!(full.status, "created");
                assert_eq!(full.entity_type, Some("User".to_string()));
                assert!(full.cascade.is_some());
            },
            _ => panic!("Expected Full format"),
        }
    }

    #[test]
    fn test_cascade_underscore_backward_compat() {
        let json = r#"{
            "status": "success",
            "message": "OK",
            "_cascade": {"updated": []}
        }"#;

        let response = parse_mutation_response(json, None).unwrap();

        match response {
            MutationResponse::Full(full) => {
                assert!(full.cascade.is_some());
            },
            _ => panic!("Expected Full format"),
        }
    }

    #[test]
    fn test_invalid_status_treated_as_simple() {
        // status field exists but value is not a valid mutation status
        let json = r#"{"status": "some_random_field", "data": "value"}"#;
        let response = parse_mutation_response(json, None).unwrap();
        assert!(matches!(response, MutationResponse::Simple(_)));
    }
}
