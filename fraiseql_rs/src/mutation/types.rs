// fraiseql_rs/src/mutation/types.rs

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Mutation response format (auto-detected)
#[derive(Debug, Clone, PartialEq)]
pub enum MutationResponse {
    /// Simple format: entity-only response (no status field)
    Simple(SimpleResponse),
    /// Full format: mutation_response with status/message/entity
    Full(FullResponse),
}

/// Simple format: Just entity JSONB
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SimpleResponse {
    /// Entity data (entire JSONB)
    pub entity: Value,
}

/// Full mutation response format
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FullResponse {
    pub status:         String, // REQUIRED
    pub message:        String, // REQUIRED
    #[serde(skip_serializing_if = "Option::is_none")]
    pub entity_type:    Option<String>, // PascalCase type name
    #[serde(skip_serializing_if = "Option::is_none")]
    pub entity:         Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub updated_fields: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cascade:        Option<Value>, // Just another optional field
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata:       Option<Value>,
}

/// Status classification (parsed from status string)
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StatusKind {
    Success(String), // success, created, updated, deleted
    Noop(String),    // noop:reason
    Error(String),   // failed:reason, not_found:reason, etc.
}

impl StatusKind {
    /// Parse status string into classification
    #[allow(clippy::should_implement_trait)]
    pub fn from_str(status: &str) -> Self {
        let status_lower = status.to_lowercase();

        #[allow(clippy::if_same_then_else)]
        // Error prefixes
        if status_lower.starts_with("failed:")
            || status_lower.starts_with("unauthorized:")
            || status_lower.starts_with("forbidden:")
            || status_lower.starts_with("not_found:")
            || status_lower.starts_with("conflict:")
            || status_lower.starts_with("timeout:")
        {
            StatusKind::Error(status.to_string())
        }
        // Noop prefix
        else if status_lower.starts_with("noop:") {
            StatusKind::Noop(status.to_string())
        }
        // Success keywords
        else if matches!(
            status_lower.as_str(),
            "success" | "created" | "updated" | "deleted" | "completed" | "ok" | "new"
        ) {
            StatusKind::Success(status.to_string())
        }
        // Unknown - default to success (backward compat)
        else {
            StatusKind::Success(status.to_string())
        }
    }

    pub fn is_success(&self) -> bool {
        matches!(self, StatusKind::Success(_))
    }

    pub fn is_error(&self) -> bool {
        matches!(self, StatusKind::Error(_))
    }

    /// Map to HTTP status code
    pub fn http_code(&self) -> u16 {
        match self {
            StatusKind::Success(_) | StatusKind::Noop(_) => 200,
            StatusKind::Error(reason) => {
                let reason_lower = reason.to_lowercase();
                if reason_lower.contains("not_found") {
                    404
                } else if reason_lower.contains("unauthorized") {
                    401
                } else if reason_lower.contains("forbidden") {
                    403
                } else if reason_lower.contains("conflict") {
                    409
                } else if reason_lower.contains("validation") || reason_lower.contains("invalid") {
                    422
                } else if reason_lower.contains("timeout") {
                    408
                } else {
                    500
                }
            },
        }
    }
}

/// Error type for mutation processing
#[derive(Debug, Clone, thiserror::Error)]
pub enum MutationError {
    #[error("Invalid JSON: {0}")]
    InvalidJson(String),

    #[error("Missing required field: {0}")]
    MissingField(String),

    #[error("Entity type required when entity is present")]
    MissingEntityType,

    #[error("Entity type must be PascalCase, got: {0}")]
    InvalidEntityType(String),

    #[error("Schema validation failed: {0}")]
    SchemaValidation(String),

    #[error("Serialization failed: {0}")]
    SerializationFailed(String),
}

impl From<String> for MutationError {
    fn from(s: String) -> Self {
        MutationError::SerializationFailed(s)
    }
}

impl From<&str> for MutationError {
    fn from(s: &str) -> Self {
        MutationError::SerializationFailed(s.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_status_kind_success() {
        assert!(StatusKind::from_str("success").is_success());
        assert!(StatusKind::from_str("created").is_success());
        assert!(StatusKind::from_str("UPDATED").is_success());
    }

    #[test]
    fn test_status_kind_error() {
        let status = StatusKind::from_str("failed:validation");
        assert!(status.is_error());
        assert_eq!(status.http_code(), 422);
    }

    #[test]
    fn test_status_kind_http_codes() {
        assert_eq!(StatusKind::from_str("not_found:user").http_code(), 404);
        assert_eq!(StatusKind::from_str("unauthorized:token").http_code(), 401);
        assert_eq!(StatusKind::from_str("conflict:duplicate").http_code(), 409);
    }

    #[test]
    fn test_simple_response_serde() {
        use serde_json::json;

        let simple = SimpleResponse {
            entity: json!({"id": "123", "name": "Test"}),
        };

        let serialized = serde_json::to_string(&simple).unwrap();
        let deserialized: SimpleResponse = serde_json::from_str(&serialized).unwrap();

        assert_eq!(simple, deserialized);
    }
}
