//! SQL query building and manipulation (Phase 5.5b + Phase 6.1 - Foundation & Schema Extraction)
//!
//! This module provides core query building and manipulation utilities:
//! - Case conversion (camelCase ↔ snake_case)
//! - Operator registry and matching
//! - SQL prepared statement building with parameter binding
//! - Schema metadata types (Phase 6.1 - pure Rust, no PyO3)

pub mod casing;
pub mod operators;
pub mod prepared_statement;
pub mod schema; // Phase 6.1: Pure Rust schema types (moved from src/query/schema.rs)

// Deferred modules (blocked by schema.rs PyO3 dependency):
//   - field_analyzer    // Depends on schema.SchemaMetadata (#[pyclass])
//   - where_builder     // Depends on schema.SchemaMetadata (#[pyclass])
//   - composer          // Depends on where_builder → schema
//   - where_normalization // Depends on schema.SchemaMetadata (#[pyclass])

// Re-export key types for convenience
pub use casing::{to_camel_case, to_snake_case};
pub use operators::{
    get_operator_info, get_operators_by_category, is_operator, OperatorCategory, OperatorInfo,
};
pub use prepared_statement::PreparedStatement;
pub use schema::{FieldType, SchemaMetadata, TableSchema, TypeDefinition};
