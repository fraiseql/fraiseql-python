//! GraphQL parsing and validation.
//!
//! This module provides:
//! - Query parsing
//! - Schema validation
//! - Type checking
//! - Fragment resolution
//! - Directive evaluation

// ============================================================================
// Module declarations
// ============================================================================

/// GraphQL AST types for query representation.
pub mod types;

// Submodules will be added:
// mod parser;
// mod validation;
// mod fragments;
// mod directives;

// ============================================================================
// Re-exports for convenient access
// ============================================================================

pub use types::{
    Directive, FieldSelection, FragmentDefinition, GraphQLArgument, GraphQLType, ParsedQuery,
    VariableDefinition,
};
