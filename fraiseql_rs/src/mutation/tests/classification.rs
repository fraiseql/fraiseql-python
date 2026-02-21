//! Classification Tests - Stage 2: Status taxonomy
//!
//! Tests for status string parsing and classification:
//! - Status string parsing (new, updated, deleted, noop, failed, etc.)
//! - Status code mapping (201, 200, 204, 422, 400, 404, 409)
//! - Success/Error/Noop classification
//! - Status taxonomy correctness and edge cases

use super::*;

// SUCCESS KEYWORDS (no colon)
#[test]
fn test_success_keywords() {
    assert!(MutationStatus::from_str("success").is_success());
    assert!(MutationStatus::from_str("created").is_success());
    assert!(MutationStatus::from_str("updated").is_success());
    assert!(MutationStatus::from_str("deleted").is_success());
}

// ERROR PREFIXES (colon-separated)
#[test]
fn test_failed_prefix() {
    let status = MutationStatus::from_str("failed:validation");
    assert!(status.is_error());
    match status {
        MutationStatus::Error(full_status) => assert_eq!(full_status, "failed:validation"),
        _ => panic!("Expected Error variant"),
    }
}

#[test]
fn test_unauthorized_prefix() {
    let status = MutationStatus::from_str("unauthorized:token_expired");
    assert!(status.is_error());
}

#[test]
fn test_forbidden_prefix() {
    let status = MutationStatus::from_str("forbidden:insufficient_permissions");
    assert!(status.is_error());
}

#[test]
fn test_not_found_prefix() {
    let status = MutationStatus::from_str("not_found:user_missing");
    assert!(status.is_error());
}

#[test]
fn test_conflict_prefix() {
    let status = MutationStatus::from_str("conflict:duplicate_email");
    assert!(status.is_error());
}

#[test]
fn test_timeout_prefix() {
    let status = MutationStatus::from_str("timeout:database_query");
    assert!(status.is_error());
}

// NOOP PREFIX (success with no changes)
#[test]
fn test_noop_prefix() {
    let status = MutationStatus::from_str("noop:unchanged");
    assert!(status.is_noop());
    assert!(status.is_error()); // v1.8.0: noop is error type
    match status {
        MutationStatus::Noop(reason) => assert_eq!(reason, "unchanged"),
        _ => panic!("Expected Noop variant"),
    }
}

#[test]
fn test_noop_duplicate() {
    let status = MutationStatus::from_str("noop:duplicate");
    assert!(status.is_noop());
}

// CASE INSENSITIVITY
#[test]
fn test_case_insensitive_error_prefix() {
    assert!(MutationStatus::from_str("FAILED:validation").is_error());
    assert!(MutationStatus::from_str("Unauthorized:token").is_error());
    assert!(MutationStatus::from_str("Conflict:DUPLICATE").is_error());
}

#[test]
fn test_case_insensitive_success() {
    assert!(MutationStatus::from_str("SUCCESS").is_success());
    assert!(MutationStatus::from_str("Created").is_success());
}

// EDGE CASES
#[test]
fn test_status_with_multiple_colons() {
    let status = MutationStatus::from_str("failed:validation:email_invalid");
    assert!(status.is_error());
    match status {
        MutationStatus::Error(full_status) => {
            assert_eq!(full_status, "failed:validation:email_invalid")
        },
        _ => panic!("Expected Error with full status"),
    }
}

#[test]
fn test_error_prefix_without_reason() {
    let status = MutationStatus::from_str("failed:");
    assert!(status.is_error());
    match status {
        MutationStatus::Error(full_status) => assert_eq!(full_status, "failed:"),
        _ => panic!("Expected Error with empty status"),
    }
}

#[test]
fn test_unknown_status_becomes_success() {
    // Unknown statuses default to success for backward compatibility
    let status = MutationStatus::from_str("unknown_status");
    assert!(status.is_success());
}

#[test]
fn test_empty_status() {
    let status = MutationStatus::from_str("");
    assert!(status.is_success());
}

// ============================================================================
// Tests for STATUS TAXONOMY INTEGRATION (Phase 3: REFACTOR)
// ============================================================================
