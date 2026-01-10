//! Security Profiles - v1.9.6 enforcement levels
//!
//! This module implements the v1.9.6 security profile system:
//! - **STANDARD**: Basic security (rate limiting, audit logging)
//! - **REGULATED**: Full compliance (HIPAA/SOC2 level with field masking, error redaction)
//!
//! ## Profile Levels
//!
//! ### STANDARD Profile
//! - Rate limiting enabled
//! - Audit logging of queries
//! - Basic error messages visible
//! - No field masking
//! - Large responses allowed
//!
//! ### REGULATED Profile
//! - All STANDARD features +
//! - Detailed field-level audit logging
//! - Sensitive field masking (PII, secrets)
//! - Error detail reduction (no internal details)
//! - Query logging for compliance audit trails
//! - Response size limits (prevent data exfiltration)
//! - Strict field filtering (only requested fields)
//!
//! ## Usage
//!
//! ```ignore
//! use fraiseql_rs::security::profiles::{SecurityProfile, ProfileConfig};
//!
//! // Create a profile configuration
//! let config = ProfileConfig::standard();
//! let profile = SecurityProfile::from_config(config);
//!
//! // Use in request validation
//! profile.validate_request(&request).await?;
//!
//! // Use in response transformation
//! profile.transform_response(&mut response)?;
//! ```

use serde::{Deserialize, Serialize};
use std::fmt;

/// Security profile configuration
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
pub enum SecurityProfile {
    /// STANDARD: Basic security (rate limit + audit)
    #[default]
    Standard,

    /// REGULATED: Full security with compliance features (HIPAA/SOC2)
    Regulated,
}

impl SecurityProfile {
    /// Create STANDARD profile
    #[must_use]
    pub const fn standard() -> Self {
        Self::Standard
    }

    /// Create REGULATED profile
    #[must_use]
    pub const fn regulated() -> Self {
        Self::Regulated
    }

    /// Check if this is STANDARD profile
    #[must_use]
    pub const fn is_standard(&self) -> bool {
        matches!(self, Self::Standard)
    }

    /// Check if this is REGULATED profile
    #[must_use]
    pub const fn is_regulated(&self) -> bool {
        matches!(self, Self::Regulated)
    }

    /// Get profile name
    #[must_use]
    pub const fn name(&self) -> &'static str {
        match self {
            Self::Standard => "STANDARD",
            Self::Regulated => "REGULATED",
        }
    }

    /// Check if rate limiting is enabled for this profile
    #[must_use]
    pub const fn rate_limit_enabled(&self) -> bool {
        true
    }

    /// Check if audit logging is enabled for this profile
    #[must_use]
    pub const fn audit_logging_enabled(&self) -> bool {
        true
    }

    /// Check if field-level audit is enabled (REGULATED only)
    #[must_use]
    pub const fn audit_field_access(&self) -> bool {
        matches!(self, Self::Regulated)
    }

    /// Check if sensitive field masking is enabled (REGULATED only)
    #[must_use]
    pub const fn sensitive_field_masking(&self) -> bool {
        matches!(self, Self::Regulated)
    }

    /// Check if error detail reduction is enabled (REGULATED only)
    #[must_use]
    pub const fn error_detail_reduction(&self) -> bool {
        matches!(self, Self::Regulated)
    }

    /// Check if query logging for compliance is enabled (REGULATED only)
    #[must_use]
    pub const fn query_logging_for_compliance(&self) -> bool {
        matches!(self, Self::Regulated)
    }

    /// Check if response size limits are enforced (REGULATED only)
    #[must_use]
    pub const fn response_size_limits(&self) -> bool {
        matches!(self, Self::Regulated)
    }

    /// Check if strict field filtering is enabled (REGULATED only)
    #[must_use]
    pub const fn field_filtering_strict(&self) -> bool {
        matches!(self, Self::Regulated)
    }

    /// Get maximum response size for this profile (bytes)
    #[must_use]
    pub const fn max_response_size_bytes(&self) -> usize {
        match self {
            Self::Standard => usize::MAX, // No limit
            Self::Regulated => 1_000_000, // 1MB for REGULATED
        }
    }

    /// Get maximum query complexity for this profile
    #[must_use]
    pub const fn max_query_complexity(&self) -> usize {
        match self {
            Self::Standard => 100_000,
            Self::Regulated => 50_000, // Stricter for REGULATED
        }
    }

    /// Get maximum query depth for this profile
    #[must_use]
    pub const fn max_query_depth(&self) -> usize {
        match self {
            Self::Standard => 20,
            Self::Regulated => 10, // Stricter for REGULATED
        }
    }

    /// Get rate limit - requests per second per user
    #[must_use]
    pub const fn rate_limit_rps(&self) -> u32 {
        match self {
            Self::Standard => 100,
            Self::Regulated => 10, // Stricter for REGULATED
        }
    }

    /// Get enforcement level description
    #[must_use]
    pub const fn description(&self) -> &'static str {
        match self {
            Self::Standard => "Basic security with rate limiting and audit logging",
            Self::Regulated => {
                "Full compliance with field masking, error redaction, and strict limits"
            }
        }
    }

    /// Get all enforced features for this profile
    #[must_use]
    pub fn enforced_features(&self) -> Vec<&'static str> {
        let mut features = vec!["Rate Limiting", "Audit Logging"];

        if self.is_regulated() {
            features.extend(vec![
                "Field-Level Audit",
                "Sensitive Field Masking",
                "Error Detail Reduction",
                "Query Logging for Compliance",
                "Response Size Limits",
                "Strict Field Filtering",
            ]);
        }

        features
    }
}

impl fmt::Display for SecurityProfile {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.name())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ========================================================================
    // Test Suite 1: Profile Creation and Basic Properties
    // ========================================================================

    #[test]
    fn test_create_standard_profile() {
        let profile = SecurityProfile::standard();
        assert!(profile.is_standard());
        assert!(!profile.is_regulated());
        assert_eq!(profile.name(), "STANDARD");
    }

    #[test]
    fn test_create_regulated_profile() {
        let profile = SecurityProfile::regulated();
        assert!(!profile.is_standard());
        assert!(profile.is_regulated());
        assert_eq!(profile.name(), "REGULATED");
    }

    #[test]
    fn test_default_profile_is_standard() {
        let profile = SecurityProfile::default();
        assert!(profile.is_standard());
    }

    #[test]
    fn test_profile_display() {
        assert_eq!(SecurityProfile::Standard.to_string(), "STANDARD");
        assert_eq!(SecurityProfile::Regulated.to_string(), "REGULATED");
    }

    // ========================================================================
    // Test Suite 2: Common Features (Both Profiles)
    // ========================================================================

    #[test]
    fn test_standard_has_rate_limiting() {
        let profile = SecurityProfile::standard();
        assert!(profile.rate_limit_enabled());
    }

    #[test]
    fn test_regulated_has_rate_limiting() {
        let profile = SecurityProfile::regulated();
        assert!(profile.rate_limit_enabled());
    }

    #[test]
    fn test_standard_has_audit_logging() {
        let profile = SecurityProfile::standard();
        assert!(profile.audit_logging_enabled());
    }

    #[test]
    fn test_regulated_has_audit_logging() {
        let profile = SecurityProfile::regulated();
        assert!(profile.audit_logging_enabled());
    }

    // ========================================================================
    // Test Suite 3: STANDARD Profile Features
    // ========================================================================

    #[test]
    fn test_standard_no_field_audit() {
        let profile = SecurityProfile::standard();
        assert!(!profile.audit_field_access());
    }

    #[test]
    fn test_standard_no_field_masking() {
        let profile = SecurityProfile::standard();
        assert!(!profile.sensitive_field_masking());
    }

    #[test]
    fn test_standard_no_error_redaction() {
        let profile = SecurityProfile::standard();
        assert!(!profile.error_detail_reduction());
    }

    #[test]
    fn test_standard_no_query_logging_compliance() {
        let profile = SecurityProfile::standard();
        assert!(!profile.query_logging_for_compliance());
    }

    #[test]
    fn test_standard_no_response_limits() {
        let profile = SecurityProfile::standard();
        assert!(!profile.response_size_limits());
    }

    #[test]
    fn test_standard_no_strict_filtering() {
        let profile = SecurityProfile::standard();
        assert!(!profile.field_filtering_strict());
    }

    #[test]
    fn test_standard_unlimited_response_size() {
        let profile = SecurityProfile::standard();
        assert_eq!(profile.max_response_size_bytes(), usize::MAX);
    }

    #[test]
    fn test_standard_rate_limit_rps() {
        let profile = SecurityProfile::standard();
        assert_eq!(profile.rate_limit_rps(), 100);
    }

    // ========================================================================
    // Test Suite 4: REGULATED Profile Features
    // ========================================================================

    #[test]
    fn test_regulated_has_field_audit() {
        let profile = SecurityProfile::regulated();
        assert!(profile.audit_field_access());
    }

    #[test]
    fn test_regulated_has_field_masking() {
        let profile = SecurityProfile::regulated();
        assert!(profile.sensitive_field_masking());
    }

    #[test]
    fn test_regulated_has_error_redaction() {
        let profile = SecurityProfile::regulated();
        assert!(profile.error_detail_reduction());
    }

    #[test]
    fn test_regulated_has_query_logging_compliance() {
        let profile = SecurityProfile::regulated();
        assert!(profile.query_logging_for_compliance());
    }

    #[test]
    fn test_regulated_has_response_limits() {
        let profile = SecurityProfile::regulated();
        assert!(profile.response_size_limits());
    }

    #[test]
    fn test_regulated_has_strict_filtering() {
        let profile = SecurityProfile::regulated();
        assert!(profile.field_filtering_strict());
    }

    #[test]
    fn test_regulated_response_size_limit() {
        let profile = SecurityProfile::regulated();
        assert_eq!(profile.max_response_size_bytes(), 1_000_000);
    }

    #[test]
    fn test_regulated_rate_limit_stricter() {
        let standard = SecurityProfile::standard();
        let regulated = SecurityProfile::regulated();
        assert!(regulated.rate_limit_rps() < standard.rate_limit_rps());
    }

    #[test]
    fn test_regulated_query_complexity_stricter() {
        let standard = SecurityProfile::standard();
        let regulated = SecurityProfile::regulated();
        assert!(regulated.max_query_complexity() < standard.max_query_complexity());
    }

    #[test]
    fn test_regulated_query_depth_stricter() {
        let standard = SecurityProfile::standard();
        let regulated = SecurityProfile::regulated();
        assert!(regulated.max_query_depth() < standard.max_query_depth());
    }

    // ========================================================================
    // Test Suite 5: Limits and Thresholds
    // ========================================================================

    #[test]
    fn test_standard_query_limits() {
        let profile = SecurityProfile::standard();
        assert!(profile.max_query_complexity() > 0);
        assert!(profile.max_query_depth() > 0);
    }

    #[test]
    fn test_regulated_query_limits() {
        let profile = SecurityProfile::regulated();
        assert!(profile.max_query_complexity() > 0);
        assert!(profile.max_query_depth() > 0);
    }

    #[test]
    fn test_response_size_reasonable() {
        let profile = SecurityProfile::regulated();
        assert!(profile.max_response_size_bytes() > 100_000); // At least 100KB
        assert!(profile.max_response_size_bytes() < 100_000_000); // Less than 100MB
    }

    // ========================================================================
    // Test Suite 6: Feature Descriptions
    // ========================================================================

    #[test]
    fn test_standard_description() {
        let profile = SecurityProfile::standard();
        let desc = profile.description();
        assert!(!desc.is_empty());
        assert!(desc.contains("rate limiting"));
    }

    #[test]
    fn test_regulated_description() {
        let profile = SecurityProfile::regulated();
        let desc = profile.description();
        assert!(!desc.is_empty());
        assert!(desc.contains("compliance"));
    }

    #[test]
    fn test_standard_enforced_features() {
        let profile = SecurityProfile::standard();
        let features = profile.enforced_features();
        assert!(features.contains(&"Rate Limiting"));
        assert!(features.contains(&"Audit Logging"));
        assert_eq!(features.len(), 2);
    }

    #[test]
    fn test_regulated_enforced_features() {
        let profile = SecurityProfile::regulated();
        let features = profile.enforced_features();
        assert!(features.len() > 2);
        assert!(features.contains(&"Rate Limiting"));
        assert!(features.contains(&"Audit Logging"));
        assert!(features.contains(&"Sensitive Field Masking"));
        assert!(features.contains(&"Error Detail Reduction"));
    }

    // ========================================================================
    // Test Suite 7: Profile Comparison
    // ========================================================================

    #[test]
    fn test_profile_equality() {
        let standard1 = SecurityProfile::standard();
        let standard2 = SecurityProfile::standard();
        let regulated = SecurityProfile::regulated();

        assert_eq!(standard1, standard2);
        assert_ne!(standard1, regulated);
    }

    #[test]
    fn test_profile_clone() {
        let original = SecurityProfile::regulated();
        let cloned = original;
        assert_eq!(original, cloned);
    }

    // ========================================================================
    // Test Suite 8: Edge Cases
    // ========================================================================

    #[test]
    fn test_profile_features_are_superset() {
        // REGULATED should have everything STANDARD has, plus more
        let standard = SecurityProfile::standard();
        let regulated = SecurityProfile::regulated();

        assert_eq!(
            standard.rate_limit_enabled(),
            regulated.rate_limit_enabled()
        );
        assert_eq!(
            standard.audit_logging_enabled(),
            regulated.audit_logging_enabled()
        );
        // But REGULATED should have additional features
        assert!(regulated.audit_field_access() || !standard.audit_field_access());
    }

    #[test]
    fn test_all_features_documented() {
        let profile = SecurityProfile::standard();
        assert!(!profile.name().is_empty());
        assert!(!profile.description().is_empty());

        let profile = SecurityProfile::regulated();
        assert!(!profile.name().is_empty());
        assert!(!profile.description().is_empty());
    }

    #[test]
    fn test_rate_limits_are_positive() {
        for profile in &[SecurityProfile::Standard, SecurityProfile::Regulated] {
            assert!(
                profile.rate_limit_rps() > 0,
                "Profile {profile} should have positive rate limit"
            );
        }
    }
}
