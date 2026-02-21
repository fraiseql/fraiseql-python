//! Tests for mutation module
//!
//! This module contains comprehensive tests for mutation parsing, validation,
//! and response building. Tests are organized by category for easy navigation.

use serde_json::{Value, json};

use super::*;

// Test modules - organized by pipeline stage
mod classification; // Stage 2: Status taxonomy
mod entity_field_filtering; // Entity field filtering (GitHub issue #525)
mod integration; // Stage 4: End-to-end
mod parsing; // Stage 1: JSON → MutationResult
mod properties; // Property-based tests
mod response_building; // Stage 3: MutationResult → JSON
mod test_multiple_entities; // Multiple entity fields pattern (PrintOptim)
