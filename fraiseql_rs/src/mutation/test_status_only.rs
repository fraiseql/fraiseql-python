//! Tests for status taxonomy only

use super::*;

// ============================================================================
// COMPREHENSIVE STATUS TAXONOMY TESTS (RED PHASE)
// ============================================================================

#[cfg(test)]
mod test_status_taxonomy {
    use super::*;

    // SUCCESS KEYWORDS (no colon) - should all be Success variants
    #[test]
    fn test_success_keywords_success() {
        let status = MutationStatus::from_str("success");
        assert!(status.is_success(), "success should be Success");
        assert!(!status.is_error(), "success should not be Error");
        assert!(!status.is_noop(), "success should not be Noop");
    }

    #[test]
    fn test_success_keywords_created() {
        let status = MutationStatus::from_str("created");
        assert!(status.is_success(), "created should be Success");
        assert!(!status.is_error(), "created should not be Error");
        assert!(!status.is_noop(), "created should not be Noop");
    }

    #[test]
    fn test_success_keywords_updated() {
        let status = MutationStatus::from_str("updated");
        assert!(status.is_success(), "updated should be Success");
        assert!(!status.is_error(), "updated should not be Error");
        assert!(!status.is_noop(), "updated should not be Noop");
    }

    #[test]
    fn test_success_keywords_deleted() {
        let status = MutationStatus::from_str("deleted");
        assert!(status.is_success(), "deleted should be Success");
        assert!(!status.is_error(), "deleted should not be Error");
        assert!(!status.is_noop(), "deleted should not be Noop");
    }

    #[test]
    fn test_success_keywords_new() {
        let status = MutationStatus::from_str("new");
        assert!(status.is_success(), "new should be Success");
        assert!(!status.is_error(), "new should not be Error");
        assert!(!status.is_noop(), "new should not be Noop");
    }

    #[test]
    fn test_success_keywords_completed() {
        let status = MutationStatus::from_str("completed");
        assert!(status.is_success(), "completed should be Success");
        assert!(!status.is_error(), "completed should not be Error");
        assert!(!status.is_noop(), "completed should not be Noop");
    }

    #[test]
    fn test_success_keywords_ok() {
        let status = MutationStatus::from_str("ok");
        assert!(status.is_success(), "ok should be Success");
        assert!(!status.is_error(), "ok should not be Error");
        assert!(!status.is_noop(), "ok should not be Noop");
    }

    // ERROR PREFIXES (colon-separated) - should all be Error variants
    #[test]
    fn test_error_prefixes_failed() {
        let status = MutationStatus::from_str("failed:validation");
        assert!(status.is_error(), "failed:validation should be Error");
        assert!(!status.is_success(), "failed:validation should not be Success");
        assert!(!status.is_noop(), "failed:validation should not be Noop");
    }

    #[test]
    fn test_error_prefixes_unauthorized() {
        let status = MutationStatus::from_str("unauthorized:token");
        assert!(status.is_error(), "unauthorized:token should be Error");
        assert!(!status.is_success(), "unauthorized:token should not be Success");
        assert!(!status.is_noop(), "unauthorized:token should not be Noop");
    }

    #[test]
    fn test_error_prefixes_forbidden() {
        let status = MutationStatus::from_str("forbidden:access");
        assert!(status.is_error(), "forbidden:access should be Error");
        assert!(!status.is_success(), "forbidden:access should not be Success");
        assert!(!status.is_noop(), "forbidden:access should not be Noop");
    }

    #[test]
    fn test_error_prefixes_not_found() {
        let status = MutationStatus::from_str("not_found:resource");
        assert!(status.is_error(), "not_found:resource should be Error");
        assert!(!status.is_success(), "not_found:resource should not be Success");
        assert!(!status.is_noop(), "not_found:resource should not be Noop");
    }

    #[test]
    fn test_error_prefixes_conflict() {
        let status = MutationStatus::from_str("conflict:duplicate");
        assert!(status.is_error(), "conflict:duplicate should be Error");
        assert!(!status.is_success(), "conflict:duplicate should not be Success");
        assert!(!status.is_noop(), "conflict:duplicate should not be Noop");
    }

    #[test]
    fn test_error_prefixes_timeout() {
        let status = MutationStatus::from_str("timeout:expired");
        assert!(status.is_error(), "timeout:expired should be Error");
        assert!(!status.is_success(), "timeout:expired should not be Success");
        assert!(!status.is_noop(), "timeout:expired should not be Noop");
    }

    // NOOP PREFIX (validation/business rule error) - should be Noop variant AND Error type
    #[test]
    fn test_noop_prefix_unchanged() {
        let status = MutationStatus::from_str("noop:unchanged");
        assert!(status.is_noop(), "noop:unchanged should be Noop");
        assert!(!status.is_success(), "noop:unchanged should not be Success");
        assert!(status.is_error(), "noop:unchanged should be Error (v1.8.0)"); // NEW
    }

    #[test]
    fn test_noop_prefix_no_changes() {
        let status = MutationStatus::from_str("noop:no_changes");
        assert!(status.is_noop(), "noop:no_changes should be Noop");
        assert!(!status.is_success(), "noop:no_changes should not be Success");
        assert!(status.is_error(), "noop:no_changes should be Error (v1.8.0)"); // NEW
    }

    // CASE INSENSITIVITY - should handle mixed case
    #[test]
    fn test_case_insensitivity_failed_uppercase() {
        let status = MutationStatus::from_str("FAILED:validation");
        assert!(status.is_error(), "FAILED:validation should be Error");
        assert!(!status.is_success(), "FAILED:validation should not be Success");
        assert!(!status.is_noop(), "FAILED:validation should not be Noop");
    }

    #[test]
    fn test_case_insensitivity_unauthorized_mixed() {
        let status = MutationStatus::from_str("Unauthorized:token");
        assert!(status.is_error(), "Unauthorized:token should be Error");
        assert!(!status.is_success(), "Unauthorized:token should not be Success");
        assert!(!status.is_noop(), "Unauthorized:token should not be Noop");
    }

    #[test]
    fn test_case_insensitivity_conflict_uppercase() {
        let status = MutationStatus::from_str("Conflict:DUPLICATE");
        assert!(status.is_error(), "Conflict:DUPLICATE should be Error");
        assert!(!status.is_success(), "Conflict:DUPLICATE should not be Success");
        assert!(!status.is_noop(), "Conflict:DUPLICATE should not be Noop");
    }

    #[test]
    fn test_case_insensitivity_noop_mixed() {
        let status = MutationStatus::from_str("Noop:Unchanged");
        assert!(status.is_noop(), "Noop:Unchanged should be Noop");
        assert!(!status.is_success(), "Noop:Unchanged should not be Success");
        assert!(status.is_error(), "Noop:Unchanged should be Error (v1.8.0)"); // NEW
    }

    // EDGE CASES
    #[test]
    fn test_edge_cases_multiple_colons() {
        let status = MutationStatus::from_str("failed:validation:extra:colons");
        assert!(status.is_error(), "failed:validation:extra:colons should be Error");
        assert!(!status.is_success(), "failed:validation:extra:colons should not be Success");
        assert!(!status.is_noop(), "failed:validation:extra:colons should not be Noop");
    }

    #[test]
    fn test_edge_cases_empty_reason() {
        let status = MutationStatus::from_str("failed:");
        assert!(status.is_error(), "failed: should be Error");
        assert!(!status.is_success(), "failed: should not be Success");
        assert!(!status.is_noop(), "failed: should not be Noop");
    }

    #[test]
    fn test_edge_cases_unknown_status_defaults_to_success() {
        let status = MutationStatus::from_str("unknown_status");
        assert!(status.is_success(), "unknown_status should default to Success");
        assert!(!status.is_error(), "unknown_status should not be Error");
        assert!(!status.is_noop(), "unknown_status should not be Noop");
    }

    #[test]
    fn test_edge_cases_random_string() {
        let status = MutationStatus::from_str("some_random_string");
        assert!(status.is_success(), "some_random_string should default to Success");
        assert!(!status.is_error(), "some_random_string should not be Error");
        assert!(!status.is_noop(), "some_random_string should not be Noop");
    }

    #[test]
    fn test_edge_cases_empty_string() {
        let status = MutationStatus::from_str("");
        assert!(status.is_success(), "empty string should default to Success");
        assert!(!status.is_error(), "empty string should not be Error");
        assert!(!status.is_noop(), "empty string should not be Noop");
    }

    // ADDITIONAL EDGE CASES
    #[test]
    fn test_edge_cases_noop_empty_reason() {
        let status = MutationStatus::from_str("noop:");
        assert!(status.is_noop(), "noop: should be Noop");
        assert!(!status.is_success(), "noop: should not be Success");
        assert!(status.is_error(), "noop: should be Error (v1.8.0)"); // NEW
    }

    #[test]
    fn test_edge_cases_noop_uppercase() {
        let status = MutationStatus::from_str("NOOP:UNCHANGED");
        assert!(status.is_noop(), "NOOP:UNCHANGED should be Noop");
        assert!(!status.is_success(), "NOOP:UNCHANGED should not be Success");
        assert!(status.is_error(), "NOOP:UNCHANGED should be Error (v1.8.0)"); // NEW
    }

    // ============================================================================
    // v1.8.0 VALIDATION AS ERROR TYPE - NEW STATUS METHOD TESTS
    // ============================================================================

    #[test]
    fn test_noop_is_error_v1_8() {
        let status = MutationStatus::from_str("noop:unchanged");
        assert!(status.is_noop());
        assert!(status.is_error()); // ✅ v1.8.0: noop is error
        assert!(!status.is_success());
        assert_eq!(status.application_code(), 422);
        assert_eq!(status.http_code(), 200); // Still HTTP 200
    }

    #[test]
    fn test_not_found_is_error() {
        let status = MutationStatus::from_str("not_found:user");
        assert!(!status.is_noop());
        assert!(status.is_error());
        assert!(!status.is_success());
        assert_eq!(status.application_code(), 404);
        assert_eq!(status.http_code(), 200);
    }

    #[test]
    fn test_conflict_is_error() {
        let status = MutationStatus::from_str("conflict:duplicate");
        assert!(status.is_error());
        assert_eq!(status.application_code(), 409);
    }

    #[test]
    fn test_success_is_not_error() {
        let status = MutationStatus::from_str("created");
        assert!(status.is_success());
        assert!(!status.is_error());
        assert!(!status.is_noop());
        assert_eq!(status.application_code(), 200);
    }

    #[test]
    fn test_is_graphql_success_method() {
        // Only true success returns true for is_graphql_success
        assert!(MutationStatus::from_str("created").is_graphql_success());
        assert!(MutationStatus::from_str("success").is_graphql_success());
        assert!(!MutationStatus::from_str("noop:unchanged").is_graphql_success());
        assert!(!MutationStatus::from_str("failed:validation").is_graphql_success());
    }
}
