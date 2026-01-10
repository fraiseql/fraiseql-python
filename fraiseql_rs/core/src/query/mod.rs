//! SQL query building and manipulation (Phase 5.5b - Foundation)
//!
//! This module provides core query building and manipulation utilities:
//! - Case conversion (camelCase ↔ snake_case)
//! - Operator registry and matching
//! - SQL prepared statement building with parameter binding

pub mod casing;
pub mod operators;
pub mod prepared_statement;

// Deferred modules (Phase 5.5c):
//   - field_analyzer    // Field type detection (depends on casing, operators, prepared_statement)
//   - where_builder     // WHERE clause building
//   - composer          // SQL composition
//   - where_normalization // WHERE clause normalization
//
// Deferred modules (Phase 5.5d - PyO3 dependent):
//   - schema.rs        // Has #[pyclass] decorators
//   - mod.rs           // Has #[pyfunction] exports

// Re-export key types for convenience
pub use casing::{to_camel_case, to_snake_case};
pub use operators::{OperatorCategory, OperatorInfo, get_operator_info, is_operator, get_operators_by_category};
pub use prepared_statement::PreparedStatement;
