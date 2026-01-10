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

// ============================================================================
// GraphQL Feature Modules (Phase 5.3)
// ============================================================================

/// Query complexity analysis for security limits
pub mod complexity;

/// Fragment resolution and expansion
pub mod fragment_resolver;

/// Directive evaluation and handling
pub mod directive_evaluator;

/// Advanced field selection handling
pub mod advanced_selections;

/// Fragment definition management
pub mod fragments;

/// GraphQL query parsing wrapper
pub mod parser;

// Deferred modules:
// pub mod variables;  // Depends on crate::query::schema (Phase 5.4)

// ============================================================================
// Re-exports for convenient access
// ============================================================================

pub use types::{
    Directive, FieldSelection, FragmentDefinition, GraphQLArgument, GraphQLType, ParsedQuery,
    VariableDefinition,
};

pub use advanced_selections::SelectionError;
pub use complexity::{ComplexityAnalyzer, ComplexityConfig, ComplexityDetector, ComplexityResult};
pub use directive_evaluator::DirectiveEvaluator;
pub use fragment_resolver::FragmentResolver;
pub use parser::parse_query;
