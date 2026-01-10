//! ID Policy validation for GraphQL ID scalar type
//!
//! This module provides validation for ID fields based on the configured ID policy.
//!
//! **Design Pattern**: `FraiseQL` supports two ID policies:
//! 1. **UUID**: IDs must be valid UUIDs (`FraiseQL`'s opinionated default)
//! 2. **OPAQUE**: IDs accept any string (GraphQL spec-compliant)
//!
//! This module enforces UUID format validation when `IDPolicy::UUID` is configured.
//!
//! # Example
//!
//! ```ignore
//! use fraiseql_rs::validation::id_policy::{IDPolicy, validate_id};
//!
//! // UUID policy: strict UUID validation
//! let policy = IDPolicy::UUID;
//! assert!(validate_id("550e8400-e29b-41d4-a716-446655440000", policy).is_ok());
//! assert!(validate_id("not-a-uuid", policy).is_err());
//!
//! // OPAQUE policy: any string accepted
//! let policy = IDPolicy::OPAQUE;
//! assert!(validate_id("not-a-uuid", policy).is_ok());
//! assert!(validate_id("any-arbitrary-string", policy).is_ok());
//! ```

use serde::{Deserialize, Serialize};

/// ID Policy determines how GraphQL ID scalar type behaves
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum IDPolicy {
    /// IDs must be valid UUIDs (`FraiseQL`'s opinionated default)
    #[serde(rename = "uuid")]
    #[default]
    UUID,

    /// IDs accept any string (GraphQL specification compliant)
    #[serde(rename = "opaque")]
    OPAQUE,
}

impl IDPolicy {
    /// Check if this policy enforces UUID format for IDs
    #[must_use]
    pub fn enforces_uuid(self) -> bool {
        self == Self::UUID
    }

    /// Get the policy name as a string
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::UUID => "uuid",
            Self::OPAQUE => "opaque",
        }
    }
}

impl std::fmt::Display for IDPolicy {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// Error type for ID validation failures
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IDValidationError {
    /// The invalid ID value
    pub value: String,
    /// The policy that was violated
    pub policy: IDPolicy,
    /// Error message
    pub message: String,
}

impl std::fmt::Display for IDValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for IDValidationError {}

/// Validate an ID string against the configured ID policy
///
/// # Arguments
///
/// * `id` - The ID value to validate
/// * `policy` - The ID policy to enforce
///
/// # Returns
///
/// `Ok(())` if the ID is valid for the policy, `Err(IDValidationError)` otherwise
///
/// # Errors
///
/// Returns `IDValidationError` if the ID does not conform to the specified policy.
/// For `IDPolicy::UUID`, the ID must be a valid UUID. For `IDPolicy::OPAQUE`, any string is valid.
///
/// # Examples
///
/// ```ignore
/// // UUID policy enforces UUID format
/// assert!(validate_id("550e8400-e29b-41d4-a716-446655440000", IDPolicy::UUID).is_ok());
/// assert!(validate_id("not-uuid", IDPolicy::UUID).is_err());
///
/// // OPAQUE policy accepts any string
/// assert!(validate_id("anything", IDPolicy::OPAQUE).is_ok());
/// assert!(validate_id("", IDPolicy::OPAQUE).is_ok());
/// ```
pub fn validate_id(id: &str, policy: IDPolicy) -> Result<(), IDValidationError> {
    match policy {
        IDPolicy::UUID => validate_uuid_format(id),
        IDPolicy::OPAQUE => Ok(()), // Opaque IDs accept any string
    }
}

/// Validate that an ID is a valid UUID string
///
/// **Security Note**: This validation happens at the Rust layer for defense-in-depth.
/// Python layer validation via `IDPolicy` is the primary enforcement mechanism.
///
/// UUID format validation requires:
/// - 36 characters total
/// - 8-4-4-4-12 hexadecimal digits separated by hyphens
/// - Case-insensitive
///
/// # Arguments
///
/// * `id` - The ID string to validate
///
/// # Returns
///
/// `Ok(())` if valid UUID format, `Err(IDValidationError)` otherwise
fn validate_uuid_format(id: &str) -> Result<(), IDValidationError> {
    // UUID must be 36 characters: 8-4-4-4-12
    if id.len() != 36 {
        return Err(IDValidationError {
            value: id.to_string(),
            policy: IDPolicy::UUID,
            message: format!(
                "ID must be a valid UUID (36 characters), got {} characters",
                id.len()
            ),
        });
    }

    // Check overall structure: 8-4-4-4-12
    let parts: Vec<&str> = id.split('-').collect();
    if parts.len() != 5 {
        return Err(IDValidationError {
            value: id.to_string(),
            policy: IDPolicy::UUID,
            message: "ID must be a valid UUID with format XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
                .to_string(),
        });
    }

    // Validate segment lengths
    let expected_lengths = [8, 4, 4, 4, 12];
    for (i, (part, &expected_len)) in parts.iter().zip(&expected_lengths).enumerate() {
        if part.len() != expected_len {
            return Err(IDValidationError {
                value: id.to_string(),
                policy: IDPolicy::UUID,
                message: format!(
                    "UUID segment {} has invalid length: expected {}, got {}",
                    i,
                    expected_len,
                    part.len()
                ),
            });
        }
    }

    // Validate all characters are hexadecimal
    for (i, part) in parts.iter().enumerate() {
        if !part.chars().all(|c| c.is_ascii_hexdigit()) {
            return Err(IDValidationError {
                value: id.to_string(),
                policy: IDPolicy::UUID,
                message: format!("UUID segment {i} contains non-hexadecimal characters: '{part}'"),
            });
        }
    }

    Ok(())
}

/// Validate multiple IDs against a policy
///
/// # Arguments
///
/// * `ids` - Slice of ID strings to validate
/// * `policy` - The ID policy to enforce
///
/// # Returns
///
/// `Ok(())` if all IDs are valid, `Err(IDValidationError)` for the first invalid ID
///
/// # Examples
///
/// ```ignore
/// let ids = vec![
///     "550e8400-e29b-41d4-a716-446655440000",
///     "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
/// ];
/// assert!(validate_ids(&ids, IDPolicy::UUID).is_ok());
/// ```
///
/// # Errors
///
/// Returns `IDValidationError` if any ID fails validation.
#[allow(dead_code)]
pub fn validate_ids(ids: &[&str], policy: IDPolicy) -> Result<(), IDValidationError> {
    for id in ids {
        validate_id(id, policy)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    // ==================== UUID Format Tests ====================

    #[test]
    fn test_validate_valid_uuid() {
        // Standard UUID format
        let result = validate_id("550e8400-e29b-41d4-a716-446655440000", IDPolicy::UUID);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_valid_uuid_uppercase() {
        // UUIDs are case-insensitive
        let result = validate_id("550E8400-E29B-41D4-A716-446655440000", IDPolicy::UUID);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_valid_uuid_mixed_case() {
        let result = validate_id("550e8400-E29b-41d4-A716-446655440000", IDPolicy::UUID);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_nil_uuid() {
        // Nil UUID (all zeros) is valid
        let result = validate_id("00000000-0000-0000-0000-000000000000", IDPolicy::UUID);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_max_uuid() {
        // Max UUID (all Fs) is valid
        let result = validate_id("ffffffff-ffff-ffff-ffff-ffffffffffff", IDPolicy::UUID);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_uuid_wrong_length() {
        let result = validate_id("550e8400-e29b-41d4-a716", IDPolicy::UUID);
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert_eq!(err.policy, IDPolicy::UUID);
        assert!(err.message.contains("36 characters"));
    }

    #[test]
    fn test_validate_uuid_extra_chars() {
        let result = validate_id("550e8400-e29b-41d4-a716-446655440000x", IDPolicy::UUID);
        assert!(result.is_err());
    }

    #[test]
    fn test_validate_uuid_missing_hyphens() {
        // 36 chars without hyphens - all hex digits, same length as UUID but no separators
        let result = validate_id("550e8400e29b41d4a716446655440000", IDPolicy::UUID);
        assert!(result.is_err());
        let err = result.unwrap_err();
        // Fails length check since 32 chars != 36
        assert!(err.message.contains("36 characters"));
    }

    #[test]
    fn test_validate_uuid_wrong_segment_lengths() {
        // First segment too short (7 chars instead of 8)
        // Need 36 chars total, so pad the last segment: 550e840-e29b-41d4-a716-4466554400001
        let result = validate_id("550e840-e29b-41d4-a716-4466554400001", IDPolicy::UUID);
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.message.contains("segment"));
    }

    #[test]
    fn test_validate_uuid_non_hex_chars() {
        let result = validate_id("550e8400-e29b-41d4-a716-44665544000g", IDPolicy::UUID);
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.message.contains("non-hexadecimal"));
    }

    #[test]
    fn test_validate_uuid_special_chars() {
        let result = validate_id("550e8400-e29b-41d4-a716-4466554400@0", IDPolicy::UUID);
        assert!(result.is_err());
    }

    #[test]
    fn test_validate_uuid_empty_string() {
        let result = validate_id("", IDPolicy::UUID);
        assert!(result.is_err());
    }

    // ==================== OPAQUE Policy Tests ====================

    #[test]
    fn test_opaque_accepts_any_string() {
        assert!(validate_id("not-a-uuid", IDPolicy::OPAQUE).is_ok());
        assert!(validate_id("anything", IDPolicy::OPAQUE).is_ok());
        assert!(validate_id("12345", IDPolicy::OPAQUE).is_ok());
        assert!(validate_id("special@chars!#$%", IDPolicy::OPAQUE).is_ok());
    }

    #[test]
    fn test_opaque_accepts_empty_string() {
        assert!(validate_id("", IDPolicy::OPAQUE).is_ok());
    }

    #[test]
    fn test_opaque_accepts_uuid() {
        assert!(validate_id("550e8400-e29b-41d4-a716-446655440000", IDPolicy::OPAQUE).is_ok());
    }

    // ==================== Multiple IDs Tests ====================

    #[test]
    fn test_validate_multiple_valid_uuids() {
        let ids = vec![
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
        ];
        assert!(validate_ids(&ids, IDPolicy::UUID).is_ok());
    }

    #[test]
    fn test_validate_multiple_fails_on_first_invalid() {
        let ids = vec![
            "550e8400-e29b-41d4-a716-446655440000",
            "invalid-id",
            "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
        ];
        let result = validate_ids(&ids, IDPolicy::UUID);
        assert!(result.is_err());
        assert_eq!(result.unwrap_err().value, "invalid-id");
    }

    #[test]
    fn test_validate_multiple_opaque_all_pass() {
        let ids = vec!["anything", "goes", "here", "12345"];
        assert!(validate_ids(&ids, IDPolicy::OPAQUE).is_ok());
    }

    // ==================== Policy Behavior Tests ====================

    #[test]
    fn test_policy_enforces_uuid() {
        assert!(IDPolicy::UUID.enforces_uuid());
        assert!(!IDPolicy::OPAQUE.enforces_uuid());
    }

    #[test]
    fn test_policy_as_str() {
        assert_eq!(IDPolicy::UUID.as_str(), "uuid");
        assert_eq!(IDPolicy::OPAQUE.as_str(), "opaque");
    }

    #[test]
    fn test_policy_default() {
        assert_eq!(IDPolicy::default(), IDPolicy::UUID);
    }

    #[test]
    fn test_policy_display() {
        assert_eq!(format!("{}", IDPolicy::UUID), "uuid");
        assert_eq!(format!("{}", IDPolicy::OPAQUE), "opaque");
    }

    // ==================== Security Scenarios ====================

    #[test]
    fn test_security_prevent_sql_injection_via_uuid() {
        // UUID validation prevents malicious IDs with SQL injection
        let result = validate_id("'; DROP TABLE users; --", IDPolicy::UUID);
        assert!(result.is_err());
    }

    #[test]
    fn test_security_prevent_path_traversal_via_uuid() {
        let result = validate_id("../../etc/passwd", IDPolicy::UUID);
        assert!(result.is_err());
    }

    #[test]
    fn test_security_opaque_policy_accepts_any_format() {
        // OPAQUE policy explicitly accepts any string
        // Input validation and authorization must be done elsewhere
        assert!(validate_id("'; DROP TABLE users; --", IDPolicy::OPAQUE).is_ok());
        assert!(validate_id("../../etc/passwd", IDPolicy::OPAQUE).is_ok());
    }

    #[test]
    fn test_validation_error_contains_policy_info() {
        let err = validate_id("invalid", IDPolicy::UUID).unwrap_err();
        assert_eq!(err.policy, IDPolicy::UUID);
        assert_eq!(err.value, "invalid");
        assert!(!err.message.is_empty());
    }
}
