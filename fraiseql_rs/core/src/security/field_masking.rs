//! Sensitive field masking for compliance profiles
//!
//! This module handles masking sensitive data in GraphQL responses for REGULATED profiles.
//! Field sensitivity is determined by field name patterns and explicit marking.
//!
//! ## Field Sensitivity Levels
//!
//! - **Public**: No masking (e.g., id, name, title)
//! - **Sensitive**: Partial masking - show first char + *** (e.g., email, phone)
//! - **PII**: Heavy masking - type + **** (e.g., `ssn`, `credit_card`)
//! - **Secret**: Always masked - **** (e.g., `password`, `api_key`)
//!
//! ## Pattern Matching
//!
//! Fields are classified based on name patterns:
//! - `password*`, `secret*`, `token*`, `key*` → Secret
//! - `ssn`, `credit_card`, `cvv`, `pin` → PII
//! - `email`, `phone`, `mobile`, `telephone` → Sensitive
//! - Everything else → Public
//!
//! ## Usage
//!
//! ```ignore
//! use fraiseql_rs::security::field_masking::{FieldMasker, FieldSensitivity};
//!
//! let masker = FieldMasker::new();
//! let sensitivity = masker.detect_sensitivity("email");
//! // Result: FieldSensitivity::Sensitive
//!
//! let masked = masker.mask_value("user@example.com", sensitivity);
//! // Result: "u***"
//! ```

use crate::security::SecurityProfile;
use std::fmt;

/// Field sensitivity classification
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum FieldSensitivity {
    /// Public field - no masking
    Public,
    /// Sensitive field - partial masking
    Sensitive,
    /// Personally Identifiable Information - heavy masking
    PII,
    /// Secret field - always masked
    Secret,
}

impl fmt::Display for FieldSensitivity {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Public => write!(f, "public"),
            Self::Sensitive => write!(f, "sensitive"),
            Self::PII => write!(f, "pii"),
            Self::Secret => write!(f, "secret"),
        }
    }
}

/// Field masking rules and patterns
#[derive(Debug)]
pub struct FieldMasker;

impl FieldMasker {
    /// Detect field sensitivity based on name patterns
    #[must_use]
    pub fn detect_sensitivity(field_name: &str) -> FieldSensitivity {
        let lower = field_name.to_lowercase();

        // Secret fields
        if lower.starts_with("password")
            || lower.starts_with("secret")
            || lower.starts_with("token")
            || lower.starts_with("key")
            || lower.starts_with("api_key")
            || lower.starts_with("auth")
            || lower == "hash"
            || lower == "signature"
        {
            return FieldSensitivity::Secret;
        }

        // PII fields
        if lower == "ssn"
            || lower == "social_security_number"
            || lower.contains("credit_card")
            || lower.contains("card_number")
            || lower == "cvv"
            || lower == "cvc"
            || lower.contains("bank_account")
            || lower == "pin"
            || lower.contains("driver_license")
            || lower.contains("passport")
        {
            return FieldSensitivity::PII;
        }

        // Sensitive fields
        if lower == "email"
            || lower.starts_with("email_")
            || lower.ends_with("_email")
            || lower == "phone"
            || lower == "phone_number"
            || lower.starts_with("phone_")
            || lower == "mobile"
            || lower.starts_with("mobile_")
            || lower == "telephone"
            || lower == "fax"
            || lower.contains("ip_address")
            || lower.contains("ipaddress")
            || lower == "mac_address"
            || lower == "macaddress"
        {
            return FieldSensitivity::Sensitive;
        }

        // Default: public
        FieldSensitivity::Public
    }

    /// Mask a string value based on sensitivity level
    #[must_use]
    pub fn mask_value(value: &str, sensitivity: FieldSensitivity) -> String {
        match sensitivity {
            FieldSensitivity::Public => value.to_string(),
            FieldSensitivity::Sensitive => Self::mask_sensitive(value),
            FieldSensitivity::PII => Self::mask_pii(value),
            FieldSensitivity::Secret => Self::mask_secret(value),
        }
    }

    /// Mask sensitive value - show first char + ***
    fn mask_sensitive(value: &str) -> String {
        if value.is_empty() {
            "***".to_string()
        } else {
            let first_char = value.chars().next().unwrap_or('*');
            format!("{first_char}***")
        }
    }

    /// Mask PII - show only type + ****
    fn mask_pii(_value: &str) -> String {
        "[PII]".to_string()
    }

    /// Mask secret - always ****
    fn mask_secret(_value: &str) -> String {
        "****".to_string()
    }

    /// Determine if value should be masked for this profile
    #[must_use]
    pub fn should_mask(sensitivity: FieldSensitivity, profile: &SecurityProfile) -> bool {
        match profile {
            SecurityProfile::Standard => false,
            SecurityProfile::Regulated => sensitivity != FieldSensitivity::Public,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ========================================================================
    // Test Suite 1: Field Sensitivity Detection - Public Fields
    // ========================================================================

    #[test]
    fn test_id_is_public() {
        assert_eq!(
            FieldMasker::detect_sensitivity("id"),
            FieldSensitivity::Public
        );
    }

    #[test]
    fn test_name_is_public() {
        assert_eq!(
            FieldMasker::detect_sensitivity("name"),
            FieldSensitivity::Public
        );
    }

    #[test]
    fn test_title_is_public() {
        assert_eq!(
            FieldMasker::detect_sensitivity("title"),
            FieldSensitivity::Public
        );
    }

    #[test]
    fn test_description_is_public() {
        assert_eq!(
            FieldMasker::detect_sensitivity("description"),
            FieldSensitivity::Public
        );
    }

    #[test]
    fn test_created_at_is_public() {
        assert_eq!(
            FieldMasker::detect_sensitivity("created_at"),
            FieldSensitivity::Public
        );
    }

    // ========================================================================
    // Test Suite 2: Field Sensitivity Detection - Sensitive Fields
    // ========================================================================

    #[test]
    fn test_email_is_sensitive() {
        assert_eq!(
            FieldMasker::detect_sensitivity("email"),
            FieldSensitivity::Sensitive
        );
    }

    #[test]
    fn test_email_address_is_sensitive() {
        assert_eq!(
            FieldMasker::detect_sensitivity("email_address"),
            FieldSensitivity::Sensitive
        );
    }

    #[test]
    fn test_user_email_is_sensitive() {
        assert_eq!(
            FieldMasker::detect_sensitivity("user_email"),
            FieldSensitivity::Sensitive
        );
    }

    #[test]
    fn test_phone_is_sensitive() {
        assert_eq!(
            FieldMasker::detect_sensitivity("phone"),
            FieldSensitivity::Sensitive
        );
    }

    #[test]
    fn test_phone_number_is_sensitive() {
        assert_eq!(
            FieldMasker::detect_sensitivity("phone_number"),
            FieldSensitivity::Sensitive
        );
    }

    #[test]
    fn test_mobile_is_sensitive() {
        assert_eq!(
            FieldMasker::detect_sensitivity("mobile"),
            FieldSensitivity::Sensitive
        );
    }

    #[test]
    fn test_mobile_phone_is_sensitive() {
        assert_eq!(
            FieldMasker::detect_sensitivity("mobile_phone"),
            FieldSensitivity::Sensitive
        );
    }

    #[test]
    fn test_ip_address_is_sensitive() {
        assert_eq!(
            FieldMasker::detect_sensitivity("ip_address"),
            FieldSensitivity::Sensitive
        );
    }

    #[test]
    fn test_mac_address_is_sensitive() {
        assert_eq!(
            FieldMasker::detect_sensitivity("mac_address"),
            FieldSensitivity::Sensitive
        );
    }

    // ========================================================================
    // Test Suite 3: Field Sensitivity Detection - PII Fields
    // ========================================================================

    #[test]
    fn test_ssn_is_pii() {
        assert_eq!(
            FieldMasker::detect_sensitivity("ssn"),
            FieldSensitivity::PII
        );
    }

    #[test]
    fn test_social_security_is_pii() {
        assert_eq!(
            FieldMasker::detect_sensitivity("social_security_number"),
            FieldSensitivity::PII
        );
    }

    #[test]
    fn test_credit_card_is_pii() {
        assert_eq!(
            FieldMasker::detect_sensitivity("credit_card"),
            FieldSensitivity::PII
        );
    }

    #[test]
    fn test_card_number_is_pii() {
        assert_eq!(
            FieldMasker::detect_sensitivity("card_number"),
            FieldSensitivity::PII
        );
    }

    #[test]
    fn test_cvv_is_pii() {
        assert_eq!(
            FieldMasker::detect_sensitivity("cvv"),
            FieldSensitivity::PII
        );
    }

    #[test]
    fn test_cvc_is_pii() {
        assert_eq!(
            FieldMasker::detect_sensitivity("cvc"),
            FieldSensitivity::PII
        );
    }

    #[test]
    fn test_bank_account_is_pii() {
        assert_eq!(
            FieldMasker::detect_sensitivity("bank_account"),
            FieldSensitivity::PII
        );
    }

    #[test]
    fn test_pin_is_pii() {
        assert_eq!(
            FieldMasker::detect_sensitivity("pin"),
            FieldSensitivity::PII
        );
    }

    #[test]
    fn test_driver_license_is_pii() {
        assert_eq!(
            FieldMasker::detect_sensitivity("driver_license"),
            FieldSensitivity::PII
        );
    }

    #[test]
    fn test_passport_is_pii() {
        assert_eq!(
            FieldMasker::detect_sensitivity("passport"),
            FieldSensitivity::PII
        );
    }

    // ========================================================================
    // Test Suite 4: Field Sensitivity Detection - Secret Fields
    // ========================================================================

    #[test]
    fn test_password_is_secret() {
        assert_eq!(
            FieldMasker::detect_sensitivity("password"),
            FieldSensitivity::Secret
        );
    }

    #[test]
    fn test_password_hash_is_secret() {
        assert_eq!(
            FieldMasker::detect_sensitivity("password_hash"),
            FieldSensitivity::Secret
        );
    }

    #[test]
    fn test_secret_is_secret() {
        assert_eq!(
            FieldMasker::detect_sensitivity("secret"),
            FieldSensitivity::Secret
        );
    }

    #[test]
    fn test_secret_key_is_secret() {
        assert_eq!(
            FieldMasker::detect_sensitivity("secret_key"),
            FieldSensitivity::Secret
        );
    }

    #[test]
    fn test_token_is_secret() {
        assert_eq!(
            FieldMasker::detect_sensitivity("token"),
            FieldSensitivity::Secret
        );
    }

    #[test]
    fn test_refresh_token_is_secret() {
        assert_eq!(
            FieldMasker::detect_sensitivity("refresh_token"),
            FieldSensitivity::Secret
        );
    }

    #[test]
    fn test_api_key_is_secret() {
        assert_eq!(
            FieldMasker::detect_sensitivity("api_key"),
            FieldSensitivity::Secret
        );
    }

    #[test]
    fn test_auth_token_is_secret() {
        assert_eq!(
            FieldMasker::detect_sensitivity("auth_token"),
            FieldSensitivity::Secret
        );
    }

    #[test]
    fn test_hash_is_secret() {
        assert_eq!(
            FieldMasker::detect_sensitivity("hash"),
            FieldSensitivity::Secret
        );
    }

    #[test]
    fn test_signature_is_secret() {
        assert_eq!(
            FieldMasker::detect_sensitivity("signature"),
            FieldSensitivity::Secret
        );
    }

    // ========================================================================
    // Test Suite 5: Case Insensitivity
    // ========================================================================

    #[test]
    fn test_case_insensitive_email() {
        assert_eq!(
            FieldMasker::detect_sensitivity("EMAIL"),
            FieldSensitivity::Sensitive
        );
    }

    #[test]
    fn test_case_insensitive_password() {
        assert_eq!(
            FieldMasker::detect_sensitivity("PASSWORD"),
            FieldSensitivity::Secret
        );
    }

    #[test]
    fn test_mixed_case_ssn() {
        assert_eq!(
            FieldMasker::detect_sensitivity("SSN"),
            FieldSensitivity::PII
        );
    }

    // ========================================================================
    // Test Suite 6: Value Masking - Public
    // ========================================================================

    #[test]
    fn test_public_value_unmasked() {
        let result = FieldMasker::mask_value("value", FieldSensitivity::Public);
        assert_eq!(result, "value");
    }

    #[test]
    fn test_public_empty_string_unmasked() {
        let result = FieldMasker::mask_value("", FieldSensitivity::Public);
        assert_eq!(result, "");
    }

    // ========================================================================
    // Test Suite 7: Value Masking - Sensitive
    // ========================================================================

    #[test]
    fn test_sensitive_email_masked() {
        let result = FieldMasker::mask_value("user@example.com", FieldSensitivity::Sensitive);
        assert_eq!(result, "u***");
    }

    #[test]
    fn test_sensitive_phone_masked() {
        let result = FieldMasker::mask_value("555-1234", FieldSensitivity::Sensitive);
        assert_eq!(result, "5***");
    }

    #[test]
    fn test_sensitive_single_char_masked() {
        let result = FieldMasker::mask_value("a", FieldSensitivity::Sensitive);
        assert_eq!(result, "a***");
    }

    #[test]
    fn test_sensitive_empty_masked() {
        let result = FieldMasker::mask_value("", FieldSensitivity::Sensitive);
        assert_eq!(result, "***");
    }

    // ========================================================================
    // Test Suite 8: Value Masking - PII
    // ========================================================================

    #[test]
    fn test_pii_ssn_masked() {
        let result = FieldMasker::mask_value("123-45-6789", FieldSensitivity::PII);
        assert_eq!(result, "[PII]");
    }

    #[test]
    fn test_pii_credit_card_masked() {
        let result = FieldMasker::mask_value("4111-1111-1111-1111", FieldSensitivity::PII);
        assert_eq!(result, "[PII]");
    }

    #[test]
    fn test_pii_empty_masked() {
        let result = FieldMasker::mask_value("", FieldSensitivity::PII);
        assert_eq!(result, "[PII]");
    }

    // ========================================================================
    // Test Suite 9: Value Masking - Secret
    // ========================================================================

    #[test]
    fn test_secret_password_masked() {
        let result = FieldMasker::mask_value("mypassword123", FieldSensitivity::Secret);
        assert_eq!(result, "****");
    }

    #[test]
    fn test_secret_token_masked() {
        let result = FieldMasker::mask_value("token_abc123xyz", FieldSensitivity::Secret);
        assert_eq!(result, "****");
    }

    #[test]
    fn test_secret_empty_masked() {
        let result = FieldMasker::mask_value("", FieldSensitivity::Secret);
        assert_eq!(result, "****");
    }

    #[test]
    fn test_secret_any_value_masked() {
        let result = FieldMasker::mask_value("anything", FieldSensitivity::Secret);
        assert_eq!(result, "****");
    }

    // ========================================================================
    // Test Suite 10: Profile-Based Masking Decision
    // ========================================================================

    #[test]
    fn test_standard_profile_no_masking() {
        let standard = SecurityProfile::standard();
        assert!(!FieldMasker::should_mask(
            FieldSensitivity::Public,
            &standard
        ));
        assert!(!FieldMasker::should_mask(
            FieldSensitivity::Sensitive,
            &standard
        ));
        assert!(!FieldMasker::should_mask(FieldSensitivity::PII, &standard));
        assert!(!FieldMasker::should_mask(
            FieldSensitivity::Secret,
            &standard
        ));
    }

    #[test]
    fn test_regulated_profile_public_no_masking() {
        let regulated = SecurityProfile::regulated();
        assert!(!FieldMasker::should_mask(
            FieldSensitivity::Public,
            &regulated
        ));
    }

    #[test]
    fn test_regulated_profile_sensitive_masked() {
        let regulated = SecurityProfile::regulated();
        assert!(FieldMasker::should_mask(
            FieldSensitivity::Sensitive,
            &regulated
        ));
    }

    #[test]
    fn test_regulated_profile_pii_masked() {
        let regulated = SecurityProfile::regulated();
        assert!(FieldMasker::should_mask(FieldSensitivity::PII, &regulated));
    }

    #[test]
    fn test_regulated_profile_secret_masked() {
        let regulated = SecurityProfile::regulated();
        assert!(FieldMasker::should_mask(
            FieldSensitivity::Secret,
            &regulated
        ));
    }

    // ========================================================================
    // Test Suite 11: Edge Cases
    // ========================================================================

    #[test]
    fn test_very_long_email_masked() {
        let long_email = "a".repeat(1000) + "@example.com";
        let result = FieldMasker::mask_value(&long_email, FieldSensitivity::Sensitive);
        assert_eq!(result, "a***");
        assert!(result.len() < long_email.len());
    }

    #[test]
    fn test_unicode_email_masked() {
        let result = FieldMasker::mask_value("émail@example.com", FieldSensitivity::Sensitive);
        assert_eq!(result, "é***");
    }

    #[test]
    fn test_sensitivity_display() {
        assert_eq!(FieldSensitivity::Public.to_string(), "public");
        assert_eq!(FieldSensitivity::Sensitive.to_string(), "sensitive");
        assert_eq!(FieldSensitivity::PII.to_string(), "pii");
        assert_eq!(FieldSensitivity::Secret.to_string(), "secret");
    }
}
